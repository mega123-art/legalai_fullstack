import os
import sys
import time
import argparse
import re
import json
import sqlite3
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from sentence_transformers import CrossEncoder
from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Filter, FieldCondition, Range, MatchAny,
    Prefetch, FusionQuery, Fusion, SparseVector,
    NamedVector, NamedSparseVector,
)
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

QDRANT_URL      = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME = "legal-cases"
BGE_MODEL_NAME  = "BAAI/bge-m3"
RERANKER_NAME   = "BAAI/bge-reranker-v2-m3"

TOP_K_INITIAL = 100
TOP_K_FINAL = 12
TEMPORAL_WEIGHT = 0.002
BASELINE_YEAR = 2011
OUTCOME_BOOST = 0.40   # Soft score bonus when outcome substring matches detected intent
DOMAIN_PENALTY = 0.35  # Subtracted when query names a statute the candidate doesn't mention
BASE_DIR = Path(os.getenv("LEGAL_DATA_PATH", "/Users/parthagrawal99/legal-data"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DATA_PATH", str(BASE_DIR / "processed")))
CATALOG_DB = Path(os.getenv("CATALOG_DB_PATH", str(PROCESSED_DIR / "catalog.db")))

# ─── Outcome intent keywords → normalized outcome value ───
OUTCOME_KEYWORDS: dict[str, str] = {
    "dismissed":  "dismissed",
    "dismiss":    "dismissed",
    "acquitted":  "acquitted",
    "acquittal":  "acquitted",
    "allowed":    "allowed",
    "allow":      "allowed",
    "granted":    "allowed",
    "convicted":  "convicted",
    "conviction": "convicted",
}

# ─── Legal citation regex (Indian SC formats) ───
_CITATION_RE = re.compile(
    r'(?:'
    r'\[\d{4}\]\s+\d+\s+S\.?C\.?R\.?\s+\d+'   # [2012] 3 S.C.R. 460
    r'|\(\d{4}\)\s+\d+\s+SCC\s+\d+'             # (2012) 3 SCC 460
    r'|AIR\s+\d{4}\s+SC\s+\d+'                  # AIR 2012 SC 460
    r'|\d{4}\s+\(\d+\)\s+SCC\s+\d+'             # 2012 (3) SCC 460
    r'|\d{4}\s+SCR\s+\d+'                        # 2012 SCR 460
    r')',
    re.IGNORECASE,
)


CASE_STOPWORDS = {
    "and", "ors", "or", "anr", "anrs", "the", "of", "in", "for", "to", "on",
    "india", "union", "state", "govt", "government",
}


def _normalize_legal_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _content_tokens(text: str) -> set[str]:
    toks = _normalize_legal_text(text).split()
    return {t for t in toks if len(t) > 2 and t not in CASE_STOPWORDS}


def _case_name_bonus(query: str, title: str, citation: str) -> float:
    """
    Boost exact/near-exact case-name intent.
    Keeps semantic reranking as base but nudges named-case lookups to the right judgment.
    """
    q_norm = _normalize_legal_text(query)
    t_norm = _normalize_legal_text(title)
    c_norm = _normalize_legal_text(citation)
    if not q_norm or not t_norm:
        return 0.0

    query_looks_named_case = any(p in q_norm for p in [" versus ", " vs ", " v "]) or len(q_norm.split()) <= 7

    q_tokens = _content_tokens(query)
    t_tokens = _content_tokens(title)
    overlap = (len(q_tokens & t_tokens) / max(1, len(q_tokens))) if q_tokens else 0.0
    ratio = SequenceMatcher(None, q_norm, t_norm).ratio()

    bonus = 0.0
    if query_looks_named_case:
        if overlap >= 0.7:
            bonus += 0.60
        elif overlap >= 0.5:
            bonus += 0.35
        elif overlap >= 0.3:
            bonus += 0.15

        if ratio >= 0.75:
            bonus += 0.35
        elif ratio >= 0.60:
            bonus += 0.20

        if q_norm in t_norm or t_norm in q_norm:
            bonus += 0.25

    if c_norm and c_norm in q_norm:
        bonus += 0.20

    return min(1.0, bonus)


# ─── Statute / domain alias map ───
# Map canonical key → list of alias substrings. If query contains any alias,
# candidate metadata must also contain at least one alias, else penalise.
_STATUTE_ALIASES: dict[str, list[str]] = {
    "sarfaesi": ["sarfaesi", "securitisation", "securitization",
                 "secured creditor", "secured asset", "security interest"],
    "ipc": ["ipc", "indian penal code", "penal code"],
    "crpc": ["crpc", "code of criminal procedure", "cr.p.c", "cr p c"],
    "cpc": ["cpc", "code of civil procedure", "c.p.c"],
    "pmla": ["pmla", "prevention of money laundering", "money laundering"],
    "gst": ["gst", "goods and services tax", "cgst", "sgst", "igst"],
    "income_tax": ["income tax act", "income-tax act", "it act, 1961"],
    "it_act": ["information technology act", "it act, 2000"],
    "nia": ["uapa", "unlawful activities", "nia act"],
    "ndps": ["ndps", "narcotic drugs", "psychotropic substances"],
    "arbitration": ["arbitration and conciliation", "arbitration act"],
    "companies": ["companies act", "ibc", "insolvency and bankruptcy"],
    "consumer": ["consumer protection"],
    "negotiable": ["negotiable instruments", "section 138", "ni act"],
    "motor_vehicles": ["motor vehicles act"],
    "domestic_violence": ["domestic violence", "pwdva"],
    "pocso": ["pocso", "protection of children from sexual offences"],
    "electricity": ["electricity act, 2003"],
    "evidence": ["evidence act", "bharatiya sakshya"],
    "contract": ["contract act, 1872", "indian contract act"],
    "tp_act": ["transfer of property act"],
    "specific_relief": ["specific relief act"],
    "limitation": ["limitation act"],
}


def _detect_statute_aliases(query: str) -> list[str]:
    """Return all statute aliases present in the query (flattened list)."""
    ql = (query or "").lower()
    hits: list[str] = []
    for aliases in _STATUTE_ALIASES.values():
        if any(a in ql for a in aliases):
            hits.extend(aliases)
    return hits


def _domain_penalty(required_aliases: list[str], meta: dict) -> float:
    """Return -DOMAIN_PENALTY when none of the required aliases appears in the
    candidate's title, citation, or snippet text. 0.0 when match or no requirement."""
    if not required_aliases:
        return 0.0
    haystack = " ".join([
        str(meta.get("title", "")),
        str(meta.get("citation", "")),
        str(meta.get("text", "")),
    ]).lower()
    if any(a in haystack for a in required_aliases):
        return 0.0
    return -DOMAIN_PENALTY


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_STATUTE_CONTEXT_RE = re.compile(
    r"(act|code|rules|amendment|regulation|ordinance|policy)\s*,?\s*$",
    re.IGNORECASE,
)


def _extract_year_from_query(query: str) -> Optional[int]:
    """Detect a standalone year in the query (e.g. '2012 rape cases').
    Skips years that are part of statute names like 'POCSO Act, 2012'."""
    if not query:
        return None
    for m in _YEAR_RE.finditer(query):
        start = m.start()
        prefix = query[max(0, start - 20):start]
        if _STATUTE_CONTEXT_RE.search(prefix):
            continue
        return int(m.group(0))
    return None


def _looks_like_named_case_query(query: str) -> bool:
    q = _normalize_legal_text(query)
    return (" versus " in q) or (" vs " in q) or (" v " in q)


# ─────────────────────────────────────────────────────────────
# OPTIMIZATION 3 — SQLite Local Catalog
# Replaces per-year JSON scanning with a single indexed DB.
# Delete catalog.db to force a rebuild after adding new cases.
# ─────────────────────────────────────────────────────────────

_catalog_db_conn: Optional[sqlite3.Connection] = None


def _build_sqlite_catalog() -> None:
    """Scan all processed JSON files and write them into catalog.db."""
    print("[*] Building SQLite catalog — this runs once...")
    conn = sqlite3.connect(str(CATALOG_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id       TEXT PRIMARY KEY,
            title    TEXT,
            citation TEXT,
            year     INTEGER,
            outcome  TEXT,
            judges   TEXT,
            text     TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_year     ON cases(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation ON cases(citation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome  ON cases(outcome)")

    for year_dir in sorted(PROCESSED_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for p in sorted(year_dir.glob("*.json")):
            try:
                with p.open(encoding="utf-8") as f:
                    case = json.load(f)
            except Exception:
                continue
            chunks = case.get("chunks", []) or []
            headnotes = case.get("headnotes", "") or ""
            chunk_texts = " ".join(
                c.get("text", "") for c in chunks[:3] if isinstance(c, dict)
            )
            rich_text = f"{headnotes} {chunk_texts}".strip()[:2000]
            conn.execute(
                "INSERT OR REPLACE INTO cases VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    case.get("id", ""),
                    case.get("title", ""),
                    case.get("citation", ""),
                    int(case.get("year", 0)),
                    case.get("outcome", ""),
                    case.get("judges", ""),
                    rich_text,
                ),
            )
    conn.commit()
    conn.close()
    print("[*] SQLite catalog built successfully.")


def _get_catalog_db() -> sqlite3.Connection:
    global _catalog_db_conn
    if _catalog_db_conn is None:
        if not CATALOG_DB.exists():
            _build_sqlite_catalog()
        _catalog_db_conn = sqlite3.connect(str(CATALOG_DB), check_same_thread=False)
    return _catalog_db_conn


# ─── LLM-driven domain pre-filter ────────────────────────────────────────────
# filter_terms come from the queryfier LLM response — no manual rules needed.

def _llm_domain_prefilter(filter_terms: list[str]) -> Optional[list[str]]:
    """
    Uses LLM-generated filter_terms to restrict Pinecone search to domain-relevant cases.
    Drops terms that match too many cases (not discriminating enough).
    """
    terms = [t.lower().strip() for t in filter_terms if len(t.strip()) >= 5]
    if not terms:
        return None

    conn = _get_catalog_db()

    # Drop terms that match >400 cases — too broad to be useful as domain filters
    discriminating = []
    for t in terms:
        count = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE LOWER(text) LIKE ?", (f"%{t}%",)
        ).fetchone()[0]
        if count <= 400:
            discriminating.append(t)
        else:
            print(f"[*] Dropped broad filter term '{t}' ({count} matches)")

    if not discriminating:
        print(f"[*] All filter terms too broad — no domain restriction applied")
        return None

    where = " OR ".join(["LOWER(text) LIKE ?" for _ in discriminating])
    params = [f"%{t}%" for t in discriminating]
    rows = conn.execute(f"SELECT id FROM cases WHERE {where}", params).fetchall()
    ids = [r[0] for r in rows]
    print(f"[*] LLM domain pre-filter ({len(ids)} cases) terms: {discriminating[:3]}...")
    # Too few matches = catalog text too shallow to find this doctrine — skip filter,
    # let semantic search + reranker handle it unrestricted
    if len(ids) < 1:
        print(f"[*] No catalog matches — skipping domain restriction")
        return None
    return ids


def _rows_to_cases(rows) -> list[dict]:
    return [
        {"id": r[0], "title": r[1], "citation": r[2], "year": r[3],
         "outcome": r[4], "judges": r[5], "text": r[6]}
        for r in rows
    ]


def _load_case_catalog_for_year(year: int) -> list[dict]:
    """Return all cases for a given year from the SQLite catalog."""
    conn = _get_catalog_db()
    rows = conn.execute(
        "SELECT id, title, citation, year, outcome, judges, text FROM cases WHERE year = ?",
        (year,),
    ).fetchall()
    return _rows_to_cases(rows)


def _resolve_named_case_from_local(query: str, filter_year: Optional[int]) -> Optional[dict]:
    if not _looks_like_named_case_query(query):
        return None
    if not filter_year:
        return None

    catalog = _load_case_catalog_for_year(int(filter_year))
    if not catalog:
        return None

    q_norm = _normalize_legal_text(query)
    q_tokens = _content_tokens(query)

    best = None
    best_score = -1.0
    for c in catalog:
        t_norm = _normalize_legal_text(c.get("title", ""))
        if not t_norm:
            continue
        t_tokens = _content_tokens(c.get("title", ""))
        overlap = (len(q_tokens & t_tokens) / max(1, len(q_tokens))) if q_tokens else 0.0
        ratio = SequenceMatcher(None, q_norm, t_norm).ratio()
        contains = 1.0 if (q_norm in t_norm or t_norm in q_norm) else 0.0
        score = 0.55 * overlap + 0.35 * ratio + 0.10 * contains
        if score > best_score:
            best_score = score
            best = c

    # High-confidence gate avoids pinning wrong cases.
    if best and best_score >= 0.52:
        return best
    return None


# ─────────────────────────────────────────────────────────────
# OPTIMIZATION 1 — Citation Extractor + Pinning
# ─────────────────────────────────────────────────────────────

def _extract_citation_from_query(query: str) -> Optional[str]:
    """Return the first legal citation found in the query, or None."""
    m = _CITATION_RE.search(query)
    return re.sub(r'\s+', ' ', m.group(0)).strip() if m else None


def _resolve_case_by_citation(citation: str) -> Optional[dict]:
    """Exact/partial citation lookup in the SQLite catalog."""
    conn = _get_catalog_db()
    # Normalize whitespace for the LIKE search
    norm = re.sub(r'\s+', ' ', citation.strip())
    rows = conn.execute(
        "SELECT id, title, citation, year, outcome, judges, text FROM cases WHERE citation LIKE ?",
        (f"%{norm}%",),
    ).fetchall()
    return _rows_to_cases(rows)[0] if rows else None


# ─────────────────────────────────────────────────────────────
# OPTIMIZATION 4 — Outcome-Aware Retrieval
# ─────────────────────────────────────────────────────────────

def _detect_outcome_intent(query: str) -> Optional[str]:
    """Return a normalized outcome string if the query contains an outcome keyword."""
    q = query.lower()
    
    # SPECIAL CASE: 'dismissed' in Service/Labor law usually refers to the EMPLOYEE being fired.
    if any(x in q for x in ["dismissed", "dismiss"]):
        # If 'dismissed'/'dismiss' is preceded by employee context, it's likely SITUATIONAL.
        if any(x in q for x in ["employee", "worker", "officer", "service", "from service"]):
            # Continue to check OTHER keywords (like 'allowed') but keep 'dismissed' blocked.
            pass 
        elif any(x in q for x in ["appeal", "petition", "slp", "suit"]):
            return "dismissed"
        else:
            # Default to no boost if ambiguous
            pass

    for keyword, outcome in OUTCOME_KEYWORDS.items():
        # Block both 'dismissed' and 'dismiss' from the general loop if safety triggered
        if keyword in ["dismissed", "dismiss"] and any(x in q for x in ["employee", "worker", "officer", "service", "from service"]):
            continue
            
        if keyword in q:
            return outcome
    return None


# ─────────────────────────────────────────────────────────────
# OPTIMIZATION 2 — Best-Chunk-Per-Case Selection
# ─────────────────────────────────────────────────────────────

def _select_best_chunk_per_case(matches: list, top_k: int) -> list:
    """
    Group all retrieved chunks by case_id and keep only the highest-scored
    chunk per case.  This ensures the Preview shown is the most relevant
    passage for the user's specific question rather than whichever chunk
    happened to come first.
    """
    by_case: dict[str, list] = defaultdict(list)
    unkeyed: list = []
    for m in matches:
        case_id = (m.metadata or {}).get("case_id")
        if case_id:
            by_case[case_id].append(m)
        else:
            unkeyed.append(m)

    best_per_case = [
        max(chunks, key=lambda x: getattr(x, "final_score", float("-inf")))
        for chunks in by_case.values()
    ]
    best_per_case.extend(unkeyed)
    best_per_case.sort(key=lambda x: getattr(x, "final_score", float("-inf")), reverse=True)
    return best_per_case[:top_k]


def _build_query_variants(query: str, use_queryfy: bool = True) -> tuple[list[str], list[str]]:
    """Returns (query_variants, filter_terms). filter_terms power the LLM domain pre-filter."""
    variants = [query.strip()]
    filter_terms: list[str] = []

    if not use_queryfy or _looks_like_named_case_query(query):
        return [v for v in variants if v], filter_terms

    try:
        from legal_queryfier import queryfy
        payload = queryfy(query)
        if isinstance(payload, dict) and not payload.get("error"):
            parts = []
            for k in ("legal_keywords", "hypothetical_headnote", "original_situation"):
                val = payload.get(k, "")
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            expanded = " ".join(parts).strip()
            if expanded and expanded.lower() != query.strip().lower():
                variants.append(expanded[:2000])
            raw_terms = payload.get("filter_terms", [])
            if isinstance(raw_terms, list):
                filter_terms = [str(t).lower().strip() for t in raw_terms if t]
    except Exception:
        pass

    seen = set()
    out = []
    for v in variants:
        key = v.lower()
        if v and key not in seen:
            seen.add(key)
            out.append(v)
    return out, filter_terms


def setup(local_only: bool = True):
    import torch
    if local_only:
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")

    print(f"[setup] Loading BGE-M3...")
    bge_model = BGEM3FlagModel(BGE_MODEL_NAME, use_fp16=True)

    reranker = CrossEncoder(RERANKER_NAME, device=device, local_files_only=local_only)

    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY or None,
        timeout=60,
        check_compatibility=False,
    )
    print(f"[setup] Qdrant connected: {QDRANT_URL}")

    return bge_model, client, reranker


def _build_qdrant_filter(filter_meta: dict):
    if not filter_meta:
        return None
    must = []
    if "year" in filter_meta:
        yr = filter_meta["year"]
        must.append(FieldCondition(key="year", range=Range(
            gte=yr.get("$gte"), lte=yr.get("$lte")
        )))
    if "case_id" in filter_meta:
        ids = filter_meta["case_id"].get("$in", [])
        if ids:
            must.append(FieldCondition(key="case_id", match=MatchAny(any=ids)))
    return Filter(must=must) if must else None


def embed_query(text: str, model) -> list[float]:
    out = model.encode([text], return_dense=True, return_sparse=False, return_colbert_vecs=False)
    return out["dense_vecs"][0].tolist()


def search_pro_diverse(
    query: str,
    bge_model,
    client,
    reranker,
    filter_year=None,
    year_from=None,
    year_to=None,
    historical=False,
    namespace: str = "",
    use_queryfy: bool = True,
):
    # ── Famous case nickname check — early return ────────────
    try:
        from famous_cases import resolve_famous_case
        _famous = resolve_famous_case(query)
        if _famous:
            pinned = SimpleNamespace(
                id=f"{_famous['id']}_chunk_0",
                metadata={
                    "case_id": _famous["id"],
                    "citation": _famous["citation"],
                    "title":    _famous["title"],
                    "year":     _famous["year"],
                    "outcome":  _famous["outcome"],
                    "judges":   _famous["judges"],
                    "text":     _famous["text"],
                },
                final_score=20.0,
            )
            return [pinned], _famous["title"]
    except Exception as _e:
        print(f"[famous_cases] lookup failed: {_e}")

    # ── Infer year from query if no explicit year filter given ──
    if not filter_year and year_from is None and year_to is None:
        inferred_year = _extract_year_from_query(query)
        if inferred_year:
            filter_year = inferred_year
            print(f"[*] Year inferred from query: {inferred_year}")

    # ── Build metadata filter ────────────────────────────────────
    filter_meta: dict = {}
    if year_from is not None or year_to is not None:
        # Explicit range from UI — no fuzz needed
        yr_filter: dict = {}
        if year_from is not None:
            yr_filter["$gte"] = int(year_from)
        if year_to is not None:
            yr_filter["$lte"] = int(year_to)
        filter_meta["year"] = yr_filter
    elif filter_year:
        # Legacy single-year — ±1 fuzz for SCR reporting-year drift
        y = int(filter_year)
        filter_meta["year"] = {"$gte": y - 1, "$lte": y + 1}

    # OPT-4: Outcome-aware soft boost
    outcome_intent = _detect_outcome_intent(query)
    if outcome_intent:
        print(f"[*] Outcome Boost: '{outcome_intent}' detected — will boost matching results")

    # Build query variants + extract LLM filter terms in one queryfier call
    query_variants, filter_terms = _build_query_variants(query, use_queryfy=use_queryfy)

    # ── LLM-driven domain pre-filter ─────────────────────────────────────────
    domain_ids = _llm_domain_prefilter(filter_terms) if filter_terms else None
    if domain_ids:
        filter_meta["case_id"] = {"$in": domain_ids}

    per_variant_k = max(30, TOP_K_INITIAL // max(1, len(query_variants)))
    merged_by_id = {}

    # OPT-1: Citation surgical hit — skip semantic search if found in catalog
    detected_citation = _extract_citation_from_query(query)
    citation_pinned = None
    if detected_citation:
        print(f"[*] Citation detected: '{detected_citation}' — attempting surgical lookup")
        cited_case = _resolve_case_by_citation(detected_citation)
        if cited_case:
            citation_pinned = SimpleNamespace(
                id=f"{cited_case['id']}_chunk_0",
                metadata={
                    "case_id": cited_case["id"],
                    "citation": cited_case["citation"],
                    "title": cited_case["title"],
                    "year": cited_case["year"],
                    "outcome": cited_case["outcome"],
                    "judges": cited_case["judges"],
                    "text": cited_case["text"],
                },
                final_score=20.0,  # Hard-pin: citation is an exact user intent
            )
            print(f"[*] Citation pin: '{cited_case['title']}'")

    qdrant_filter = _build_qdrant_filter(filter_meta)
    for qv in query_variants:
        out = bge_model.encode([qv], return_dense=True, return_sparse=True, return_colbert_vecs=False)
        dense = out["dense_vecs"][0].tolist()
        sw = out["lexical_weights"][0]
        sparse = SparseVector(
            indices=[int(k) for k in sw.keys()],
            values=[float(v) for v in sw.values()],
        )
        res = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                Prefetch(query=dense, using="dense", limit=per_variant_k),
                Prefetch(query=NamedSparseVector(name="sparse", vector=sparse), using="sparse", limit=per_variant_k),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=per_variant_k,
            with_payload=True,
            query_filter=qdrant_filter,
        )
        for p in res.points:
            payload = p.payload or {}
            chunk_id = f"{payload.get('case_id','unknown')}_chunk_{payload.get('chunk_index',0)}"
            m = SimpleNamespace(id=chunk_id, metadata=payload, score=p.score)
            prev = merged_by_id.get(chunk_id)
            if prev is None or p.score > getattr(prev, "score", float("-inf")):
                merged_by_id[chunk_id] = m

    initial_results = list(merged_by_id.values())

    if not initial_results and not citation_pinned:
        return []

    expansion = query_variants[1] if len(query_variants) > 1 else query

    # Always rerank against original query — expansion is for vector retrieval only.
    # Using expansion for reranking caused constitutional-term bleed across domains.
    rerank_query = query

    pairs = []
    for m in initial_results:
        context = (
            f"TITLE: {m.metadata.get('title', 'Unknown')}\n"
            f"CITATION: {m.metadata.get('citation', 'Unknown')}\n"
            f"TEXT: {m.metadata.get('text', '')}"
        )
        pairs.append([rerank_query, context])

    required_aliases = _detect_statute_aliases(query)
    if pairs:
        rerank_scores = reranker.predict(pairs)
        if required_aliases:
            print(f"[*] Domain gate: query references statute — penalising non-matches.")
        for i, m in enumerate(initial_results):
            score = float(rerank_scores[i])
            meta = m.metadata or {}
            year = int(float(meta.get("year", BASELINE_YEAR)))
            age_bonus = (year - BASELINE_YEAR) * TEMPORAL_WEIGHT
            if historical:
                age_bonus = (2026 - year) * TEMPORAL_WEIGHT
            name_bonus = _case_name_bonus(
                query=query,
                title=meta.get("title", ""),
                citation=meta.get("citation", ""),
            )
            outcome_bonus = (
                OUTCOME_BOOST
                if outcome_intent and outcome_intent in (meta.get("outcome") or "").lower()
                else 0.0
            )
            domain_pen = _domain_penalty(required_aliases, meta)
            m.final_score = score + age_bonus + name_bonus + outcome_bonus + domain_pen

    # Fallback: domain restriction can be too narrow for sparse legal domains.
    # If all domain-restricted results score < 0.3, retry without domain restriction.
    if domain_ids and initial_results and not citation_pinned:
        max_score = max(getattr(m, "final_score", 0) for m in initial_results)
        if max_score < 0.3:
            print(f"[*] Domain-restricted results weak (max={max_score:.4f}) — retrying unrestricted")
            filter_meta_fallback = {k: v for k, v in filter_meta.items() if k != "case_id"}
            merged_fallback: dict = {}
            for i, qv in enumerate(query_variants):
                fb_results = index.query(
                    vector=all_vectors[i],
                    top_k=per_variant_k,
                    include_metadata=True,
                    filter=filter_meta_fallback if filter_meta_fallback else None,
                    namespace=namespace,
                ).matches
                for m in fb_results:
                    prev = merged_fallback.get(m.id)
                    if prev is None or getattr(m, "score", float("-inf")) > getattr(prev, "score", float("-inf")):
                        merged_fallback[m.id] = m
            fb_list = list(merged_fallback.values())
            fb_pairs = [
                [rerank_query, f"TITLE: {m.metadata.get('title','')}\nCITATION: {m.metadata.get('citation','')}\nTEXT: {m.metadata.get('text','')}"]
                for m in fb_list
            ]
            if fb_pairs:
                fb_scores = reranker.predict(fb_pairs)
                for i, m in enumerate(fb_list):
                    score = float(fb_scores[i])
                    meta = m.metadata or {}
                    year = int(float(meta.get("year", BASELINE_YEAR)))
                    age_bonus = (year - BASELINE_YEAR) * TEMPORAL_WEIGHT
                    if historical:
                        age_bonus = (2026 - year) * TEMPORAL_WEIGHT
                    m.final_score = score + age_bonus + _case_name_bonus(query, meta.get("title",""), meta.get("citation","")) + (OUTCOME_BOOST if outcome_intent and outcome_intent in (meta.get("outcome") or "").lower() else 0.0) + _domain_penalty(required_aliases, meta)
                initial_results = fb_list

    # Local named-case pin (title fuzzy match)
    local_case = _resolve_named_case_from_local(query, int(filter_year) if filter_year else None)
    if local_case:
        pinned = SimpleNamespace(
            id=f"{local_case.get('id', '')}_chunk_0",
            metadata={
                "case_id": local_case.get("id", ""),
                "citation": local_case.get("citation", ""),
                "title": local_case.get("title", ""),
                "year": local_case.get("year", filter_year or BASELINE_YEAR),
                "outcome": local_case.get("outcome", ""),
                "judges": local_case.get("judges", ""),
                "text": local_case.get("text", ""),
            },
            final_score=10.0,
        )
        initial_results.append(pinned)

    if citation_pinned:
        initial_results.append(citation_pinned)

    # Return results and the expansion used
    return _select_best_chunk_per_case(initial_results, TOP_K_FINAL), expansion


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="*", help="The legal query")
    parser.add_argument("--year", type=int, help="Filter by specific year (payload metadata)")
    parser.add_argument("--historical", action="store_true", help="Prioritize older cases")
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="Allow downloading model files if not present in local cache (default is local-only mode).",
    )
    parser.add_argument(
        "--namespace",
        default="",
        help="Pinecone namespace to query. Keep empty ('') for default namespace.",
    )
    parser.add_argument(
        "--no-queryfy",
        action="store_true",
        help="Disable adaptive queryfication expansion and use only raw query retrieval.",
    )
    args = parser.parse_args()

    bge_model, client, reranker = setup(local_only=not args.allow_online)

    if args.query:
        query = " ".join(args.query)
        results = search_pro_diverse(
            query,
            bge_model,
            client,
            reranker,
            filter_year=args.year,
            historical=args.historical,
            namespace=args.namespace,
            use_queryfy=not args.no_queryfy,
        )

        if not results:
            print("No cases found.")
        else:
            print(
                f"\n--- SEARCH RESULTS (Namespace: '{args.namespace or 'default'}' | "
                f"Boost: {'Historical' if args.historical else 'Recency'}) ---"
            )
            for i, m in enumerate(results, 1):
                meta = m.metadata
                print(f"\n# CASE {i} (Combined Score: {m.final_score:.3f})")
                print(f"   YEAR     : {meta.get('year')}")
                print(f"   CITATION : {meta.get('citation')}")
                print(f"   TITLE    : {meta.get('title')}")
                print(f"   OUTCOME  : {meta.get('outcome')}")
                print(f"   JUDGES   : {meta.get('judges')}")
                print(f"   PREVIEW  : {meta.get('text', '')[:300]}...")
        sys.exit(0)

    print("\n--- APP-READY LEGAL SEARCH (PAYLOAD FILTER MODE) ---")

    while True:
        try:
            query = input("\nEnter Legal Query (or 'q' to quit): ").strip()
            if not query or query.lower() == "q":
                break

            t0 = time.time()
            results = search_pro_diverse(
                query,
                bge_model,
                client,
                reranker,
                namespace=args.namespace,
                use_queryfy=not args.no_queryfy,
            )
            elapsed = time.time() - t0

            print(f"\nTime taken: {elapsed:.2f}s")
            print("=" * 80)

            if not results:
                print("No cases found.")
                continue

            for i, m in enumerate(results, 1):
                meta = m.metadata
                print(f"\nCASE #{i} (Score: {m.final_score:.3f})")
                print(f"   YEAR     : {meta.get('year')}")
                print(f"   CITATION : {meta.get('citation')}")
                print(f"   TITLE    : {meta.get('title')}")
                print(f"   OUTCOME  : {meta.get('outcome')}")
                print(f"   PREVIEW  : {meta.get('text', '')[:300]}...")

            print(f"\n{'=' * 80}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
