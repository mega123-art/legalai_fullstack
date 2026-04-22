"""
Wraps the existing InLegalBERT + Pinecone + reranking pipeline.
Models are loaded once at app startup via init_search().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import PROCESSED_DATA_PATH, TOP_K_FINAL

# ── Lazy globals (populated by init_search) ───────────────────
_tokenizer = None
_bi_model = None
_device = None
_index = None
_reranker = None
_initialized = False


def init_search(local_only: bool = True) -> None:
    """Load models and Pinecone index. Call once at startup."""
    global _tokenizer, _bi_model, _device, _index, _reranker, _initialized
    if _initialized:
        return
    # Import here so the path manipulation in config.py is already done
    import search_pro_payload as base
    _tokenizer, _bi_model, _device, _index, _reranker = base.setup(local_only=local_only)
    _initialized = True
    print("[search_service] Models loaded.")


def run_search(
    query: str,
    filter_year: Optional[int] = None,
    historical: bool = False,
    outcome_filter: Optional[str] = None,
) -> list[dict]:
    """
    Run intelligent search and return serialisable case dicts.
    outcome_filter is not passed as a hard filter — the pipeline
    uses soft-boost internally when the keyword appears in the query.
    If the caller passes a distinct outcome_filter (from UI pills),
    we append it to the query so the pipeline's keyword detector fires.
    """
    if not _initialized:
        raise RuntimeError("Search not initialised. Call init_search() first.")

    import search_pro_payload as base

    matches, expansion = base.search_pro_diverse(
        query=query,
        tokenizer=_tokenizer,
        bi_model=_bi_model,
        device=_device,
        index=_index,
        reranker=_reranker,
        filter_year=filter_year,
        historical=historical,
    )

    SCORE_THRESHOLD = 0.55

    results = []
    for m in matches:
        score = round(float(getattr(m, "final_score", 0)), 4)
        if score < SCORE_THRESHOLD:
            continue
        meta = m.metadata or {}
        results.append({
            "case_id":        meta.get("case_id", ""),
            "citation":       meta.get("citation", ""),
            "title":          meta.get("title", ""),
            "petitioner":     meta.get("petitioner", ""),
            "respondent":     meta.get("respondent", ""),
            "court":          meta.get("court", "Supreme Court of India"),
            "year":           int(float(meta.get("year", 0))),
            "date":           meta.get("date", ""),
            "outcome":        meta.get("outcome", ""),
            "relevance_score": score,
            "preview":        (meta.get("text") or "")[:600],
            "chunk_type":     meta.get("chunk_type", "judgment"),
        })

    # Deduplicate — same-party cases (referral + final judgment) appear as separate SCR entries
    seen_parties: set[str] = set()
    deduped = []
    for r in results:
        party_key = r["title"][:35].lower().strip()
        if party_key not in seen_parties:
            seen_parties.add(party_key)
            deduped.append(r)
    results = deduped[:5]
    return results, expansion


def load_case_json(case_id: str, year: int) -> Optional[dict]:
    """
    Load a processed case JSON from disk.
    Tries PROCESSED_DATA_PATH/{year}/{case_id}.json
    """
    path = PROCESSED_DATA_PATH / str(year) / f"{case_id}.json"
    if not path.exists():
        # Fallback: scan year folder for matching id field
        year_dir = PROCESSED_DATA_PATH / str(year)
        if year_dir.exists():
            for p in year_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if data.get("id") == case_id:
                        return data
                except Exception:
                    continue
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_full_text(case_data: dict, max_chars: int = 20_000) -> str:
    """Return case text for LLM prompts. Prefers stored full_text field (complete,
    contiguous) over chunk reassembly so argument sections aren't truncated."""
    ft = case_data.get("full_text", "")
    if ft:
        return ft[:max_chars]
    # Fallback: reassemble from chunks
    chunks = case_data.get("chunks", []) or []
    parts = []
    total = 0
    for chunk in chunks:
        text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars]
