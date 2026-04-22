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

import torch
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import CrossEncoder
from pinecone import Pinecone
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

PINECONE_API_KEY = os.getenv("api")
PINECONE_INDEX = "legal-cases"
MODEL_NAME = "law-ai/InLegalBERT"
RERANKER_NAME = "BAAI/bge-reranker-v2-m3"

TOP_K_INITIAL = 80
TOP_K_FINAL = 10
TEMPORAL_WEIGHT = 0.005
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
            first_text = chunks[0].get("text", "") if chunks and isinstance(chunks[0], dict) else ""
            conn.execute(
                "INSERT OR REPLACE INTO cases VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    case.get("id", ""),
                    case.get("title", ""),
                    case.get("citation", ""),
                    int(case.get("year", 0)),
                    case.get("outcome", ""),
                    case.get("judges", ""),
                    first_text[:1000],
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


# ─── Domain pre-filter patterns ──────────────────────────────────────────────
# Tuple: (query_signals, primary_patterns, and_patterns_optional)
# primary_patterns  — SQLite OR: text must match at least one
# and_patterns      — SQLite AND on top: text must also match at least one (compound)
# Order matters — first match wins. Put specific/compound before general.
_DOMAIN_PREFILTERS: list[tuple[list[str], list[str], list[str]]] = [
    # (query_signals, primary_patterns, and_patterns)
    # Order matters — first match wins. Put specific before general.

    # ── Criminal — compound bail filters (specific offence + bail) ─────────────
    (
        ["anticipatory bail", "section 438", "s.438", "s. 438"],
        ["section 438", "anticipatory bail"],
        [],
    ),
    # bail + murder: narrow to cases that mention both bail and 302/murder
    (
        ["bail", "section 439", "s.439", "bail rejected", "bail denied", "bail refused"],
        ["section 439", "bail application", "bail in"],
        # AND: only when query also mentions murder
        # Handled dynamically in _sqlite_domain_prefilter
        [],
    ),
    (
        ["ndps", "narcotic", "drug trafficking", "drug offence"],
        ["ndps act", "narcotic drugs", "section 37 of the ndps"],
    ),
    (
        ["pocso", "sexual offence against child", "child abuse"],
        ["pocso act", "protection of children from sexual offences"],
        [],
    ),
    (
        ["habeas corpus", "illegal detention", "preventive detention", "detained without trial",
         "unlawful detention"],
        ["habeas corpus", "preventive detention"],
        [],
    ),
    (
        ["contempt of court", "disobeyed court order", "violation of court order",
         "wilful disobedience"],
        ["contempt of court", "contempt of courts act"],
        [],
    ),

    # ── Service / Employment ───────────────────────────────────────────────────
    (
        ["fired", "sacked", "dismissed from service", "termination without notice",
         "terminated without reason", "removed from service", "retrench", "article 311",
         "reinstatement", "back wages", "wrongful termination", "service terminated",
         "employment terminated", "discharged from service"],
        ["article 311", "termination of service", "dismissed from service",
         "reinstatement", "back wages"],
        [],
    ),
    (
        ["promotion denied", "promotion blocked", "seniority dispute", "dpc",
         "departmental promotion", "service seniority", "superseded in promotion"],
        ["seniority list", "departmental promotion committee", "promotion"],
        [],
    ),
    (
        ["pension denied", "pension withheld", "gratuity not paid", "retiral benefits",
         "retirement benefits"],
        ["pension", "gratuity", "retiral benefits", "government servant"],
        [],
    ),

    # ── Property / Land ───────────────────────────────────────────────────────
    (
        ["sarfaesi", "auction under sarfaesi", "bank auction", "npa auction",
         "secured asset", "secured creditor", "enforcement of security interest"],
        ["sarfaesi", "securitisation", "secured creditor"],
        [],
    ),
    (
        ["land acquired", "land acquisition", "compulsory acquisition", "compensation for land",
         "collector award", "larr act", "right to fair compensation"],
        ["land acquisition act", "right to fair compensation", "collector"],
        [],
    ),
    (
        ["eviction", "tenant evicted", "rent control", "landlord eviction",
         "vacate premises", "eviction notice"],
        ["rent control act", "eviction of tenant", "landlord and tenant"],
        [],
    ),

    # ── Family / Personal Law ─────────────────────────────────────────────────
    (
        ["divorce", "matrimonial dispute", "cruelty by spouse", "section 13 hma",
         "dissolution of marriage", "judicial separation"],
        ["hindu marriage act", "divorce", "matrimonial"],
        [],
    ),
    (
        ["maintenance", "alimony", "section 125", "child support", "wife maintenance",
         "maintenance refused"],
        ["section 125", "maintenance", "hindu marriage act"],
        [],
    ),
    (
        ["child custody", "custody of child", "guardianship", "visitation rights"],
        ["custody", "guardianship and wards act", "best interest of the child"],
        [],
    ),

    # ── Finance / Tax ─────────────────────────────────────────────────────────
    (
        ["cheque bounce", "cheque dishonour", "section 138", "ni act", "bounced cheque",
         "dishonoured cheque"],
        ["section 138", "negotiable instruments act"],
        [],
    ),
    (
        ["income tax", "it assessment", "reassessment notice", "section 148",
         "income tax return", "tax demand", "income tax officer"],
        ["income tax act", "assessing officer", "income tax"],
        [],
    ),
    (
        ["gst demand", "gst notice", "input tax credit", "igst", "cgst"],
        ["goods and services tax", "cgst act", "input tax credit"],
        [],
    ),

    # ── Consumer / Motor ──────────────────────────────────────────────────────
    (
        ["consumer complaint", "deficiency of service", "insurance claim rejected",
         "product defect", "consumer forum", "ncdrc"],
        ["consumer protection act", "deficiency in service", "national consumer"],
        [],
    ),
    (
        ["road accident", "motor accident", "mact", "accident compensation",
         "hit by vehicle", "accident claim"],
        ["motor vehicles act", "motor accident claims tribunal", "mact"],
        [],
    ),

    # ── Commercial ────────────────────────────────────────────────────────────
    (
        ["arbitration award", "arbitral tribunal", "section 34 arbitration",
         "section 11 arbitration", "set aside award", "enforce award"],
        ["arbitration and conciliation act", "arbitral award", "section 34"],
        [],
    ),
    (
        ["insolvency", "ibc", "corporate insolvency", "nclt", "liquidation",
         "resolution plan", "moratorium"],
        ["insolvency and bankruptcy code", "corporate insolvency resolution",
         "national company law tribunal"],
        [],
    ),
]

# Compound AND modifiers: when query contains ALL signals in a set,
# narrow the primary pre-filter results further with an AND condition.
# (primary_signal, secondary_signals, and_sqlite_patterns)
_COMPOUND_NARROWERS: list[tuple[str, list[str], list[str]]] = [
    # bail + murder → only bail cases that also mention 302/murder
    ("bail", ["murder", "302", "homicide", "culpable homicide"],
     ["section 302", " 302 ", "murder", "homicide"]),
    # bail + ndps → only bail cases mentioning NDPS
    ("bail", ["ndps", "narcotic", "drug"],
     ["ndps act", "narcotic drugs", "section 37"]),
    # bail + pmla/ed → only bail cases mentioning PMLA/money laundering
    ("bail", ["pmla", "money laundering", "enforcement directorate", " ed "],
     ["prevention of money laundering", "pmla", "enforcement directorate"]),
    # bail + uapa/terror → only bail cases mentioning UAPA
    ("bail", ["uapa", "terror", "unlawful activities"],
     ["uapa", "unlawful activities", "terrorist"]),
]


def _sqlite_domain_prefilter(query: str) -> Optional[list[str]]:
    """
    Returns list of case_ids to restrict Pinecone search to, or None (no filter).
    Supports compound AND narrowing when query signals multiple domains.
    """
    ql = query.lower()
    matched_patterns: Optional[list[str]] = None
    matched_primary_signal: Optional[str] = None

    for entry in _DOMAIN_PREFILTERS:
        signals, patterns = entry[0], entry[1]
        if any(s in ql for s in signals):
            matched_patterns = patterns
            # record which broad signal matched (first word of first signal)
            matched_primary_signal = signals[0].split()[0]
            break

    if not matched_patterns:
        return None

    conn = _get_catalog_db()

    # Check if a compound narrower applies
    and_patterns: list[str] = []
    if matched_primary_signal:
        for primary, secondary_signals, narrower_patterns in _COMPOUND_NARROWERS:
            if primary in matched_primary_signal and any(s in ql for s in secondary_signals):
                and_patterns = narrower_patterns
                break

    # Build SQL: primary OR patterns + optional AND patterns
    primary_where = " OR ".join(["LOWER(text) LIKE ?" for _ in matched_patterns])
    params: list[str] = [f"%{p}%" for p in matched_patterns]

    if and_patterns:
        and_where = " OR ".join(["LOWER(text) LIKE ?" for _ in and_patterns])
        sql = f"SELECT id FROM cases WHERE ({primary_where}) AND ({and_where})"
        params += [f"%{p}%" for p in and_patterns]
        label = f"{matched_patterns[0]} AND {and_patterns[0]}"
    else:
        sql = f"SELECT id FROM cases WHERE {primary_where}"
        label = matched_patterns[0]

    rows = conn.execute(sql, params).fetchall()
    ids = [r[0] for r in rows]
    print(f"[*] Domain pre-filter: {len(ids)} cases match '{label}...'")
    return ids if ids else None


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


def _build_query_variants(query: str, use_queryfy: bool = True) -> list[str]:
    variants = [query.strip()]
    if not use_queryfy or _looks_like_named_case_query(query):
        return [v for v in variants if v]

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
    except Exception:
        pass

    seen = set()
    out = []
    for v in variants:
        key = v.lower()
        if v and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def setup(local_only: bool = True):
    if not PINECONE_API_KEY:
        raise ValueError("Pinecone API key not found in .env file (variable name: 'api')")

    if local_only:
        # Force Transformers/HF to use only local cache and fail fast if missing.
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=local_only)
    bi_model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=local_only).to(device)
    bi_model.eval()

    reranker = CrossEncoder(
        RERANKER_NAME,
        device=device,
        local_files_only=local_only,
    )

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX)

    return tokenizer, bi_model, device, index, reranker


def embed_query(text: str, tokenizer, model, device) -> list[float]:
    encoded = tokenizer(text, padding=True, truncation=True, max_length=512, return_tensors="pt")
    encoded = {k: v.to(device) for k, v in encoded.items()}
    with torch.no_grad():
        outputs = model(**encoded)
    mask = encoded["attention_mask"]
    token_embeds = outputs.last_hidden_state
    mask_exp = mask.unsqueeze(-1).expand(token_embeds.size()).float()
    sum_embeds = torch.sum(token_embeds * mask_exp, dim=1)
    sum_mask = torch.clamp(mask_exp.sum(dim=1), min=1e-9)
    return (sum_embeds / sum_mask).cpu().numpy().tolist()[0]


def search_pro_diverse(
    query: str,
    tokenizer,
    bi_model,
    device,
    index,
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

    # ── Domain pre-filter: restrict Pinecone to SQLite-confirmed domain cases ──
    domain_ids = _sqlite_domain_prefilter(query)
    if domain_ids:
        # Pinecone $in filter — only embed-search within confirmed domain
        filter_meta["case_id"] = {"$in": domain_ids}

    # OPT-4: Outcome-aware soft boost (substring match against stored description)
    outcome_intent = _detect_outcome_intent(query)
    if outcome_intent:
        print(f"[*] Outcome Boost: '{outcome_intent}' detected — will boost matching results")

    query_variants = _build_query_variants(query, use_queryfy=use_queryfy)
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

    all_vectors = [embed_query(qv, tokenizer, bi_model, device) for qv in query_variants]
    for i, qv in enumerate(query_variants):
        variant_results = index.query(
            vector=all_vectors[i],
            top_k=per_variant_k,
            include_metadata=True,
            filter=filter_meta if filter_meta else None,
            namespace=namespace,
        ).matches
        for m in variant_results:
            prev = merged_by_id.get(m.id)
            if prev is None or getattr(m, "score", float("-inf")) > getattr(prev, "score", float("-inf")):
                merged_by_id[m.id] = m

    initial_results = list(merged_by_id.values())

    if not initial_results and not citation_pinned:
        return []

    # Use the expansion (the high-quality legal headnote) for the final reranking stage
    expansion = query_variants[1] if len(query_variants) > 1 else query
    
    pairs = []
    for m in initial_results:
        # Build a high-information context string for the reranker
        context = (
            f"TITLE: {m.metadata.get('title', 'Unknown')}\n"
            f"CITATION: {m.metadata.get('citation', 'Unknown')}\n"
            f"TEXT: {m.metadata.get('text', '')}"
        )
        pairs.append([expansion, context])

    if pairs:
        rerank_scores = reranker.predict(pairs)
        required_aliases = _detect_statute_aliases(query)
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

    tokenizer, bi_model, device, index, reranker = setup(local_only=not args.allow_online)

    if args.query:
        query = " ".join(args.query)
        results = search_pro_diverse(
            query,
            tokenizer,
            bi_model,
            device,
            index,
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
                tokenizer,
                bi_model,
                device,
                index,
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
