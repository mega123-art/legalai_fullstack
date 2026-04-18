"""
Famous case nickname resolver.
Maps popular Indian SC case nicknames to SQLite title keyword tuples.
No dependency on search_pro_payload — safe to import from there.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

# Each value = list of keyword-tuples (OR between tuples, AND within tuple).
# A case title must contain ALL words in one tuple to match.
FAMOUS_CASE_ALIASES: dict[str, list[list[str]]] = {
    "nirbhaya":              [["mukesh", "nct"], ["mukesh", "delhi"]],
    "nirbhaya case":         [["mukesh", "nct"], ["mukesh", "delhi"]],
    "delhi gang rape":       [["mukesh", "nct"], ["mukesh", "delhi"]],
    "jessica lal":           [["manu sharma"], ["sidhartha vashisht"]],
    "jessica lal case":      [["manu sharma"], ["sidhartha vashisht"]],
    "shah bano":             [["shah bano"], ["mohd ahmed khan"]],
    "shah bano case":        [["shah bano"], ["mohd ahmed khan"]],
    "kesavananda":           [["kesavananda bharati"]],
    "kesavananda case":      [["kesavananda bharati"]],
    "basic structure":       [["kesavananda bharati"]],
    "vishaka":               [["vishaka", "rajasthan"]],
    "vishaka case":          [["vishaka", "rajasthan"]],
    "maneka gandhi":         [["maneka gandhi"]],
    "olga tellis":           [["olga tellis"]],
    "mc mehta":              [["m.c. mehta"], ["mc mehta"]],
    "aadhaar case":          [["puttaswamy"]],
    "privacy case":          [["puttaswamy"]],
    "puttaswamy":            [["puttaswamy"]],
    "navtej johar":          [["navtej johar"], ["navtej singh johar"]],
    "section 377 case":      [["navtej johar"]],
    "377 case":              [["navtej johar"]],
    "sabarimala":            [["indian young lawyers association"]],
    "sabarimala case":       [["indian young lawyers association"]],
    "triple talaq":          [["shayara bano"]],
    "triple talaq case":     [["shayara bano"]],
    "ayodhya":               [["m. siddiq"], ["ram lalla"], ["babri"]],
    "ayodhya case":          [["m. siddiq"], ["ram lalla"]],
    "ram janmabhoomi":       [["ram lalla"], ["m. siddiq"]],
    "babri masjid":          [["m. siddiq"], ["babri"]],
    "indra sawhney":         [["indra sawhney"]],
    "mandal case":           [["indra sawhney"]],
    "mandal commission":     [["indra sawhney"]],
    "best bakery":           [["best bakery"]],
    "priyadarshini":         [["priyadarshini mattoo"]],
    "aruna shanbaug":        [["aruna shanbaug"]],
    "naz foundation":        [["naz foundation"]],
    "electoral bonds":       [["association for democratic reforms"], ["electoral bond"]],
    "electoral bond case":   [["association for democratic reforms"]],
    "demonetisation":        [["demonetisation"], ["demonetization"]],
    "article 370":           [["article 370"], ["jammu and kashmir reorganisation"]],
    "370 case":              [["article 370"], ["jammu kashmir"]],
    "cab case":              [["citizenship amendment"]],
    "caa case":              [["citizenship amendment"]],
    "indira gandhi case":    [["indira nehru gandhi", "raj narain"]],
    "election case 1975":    [["indira nehru gandhi", "raj narain"]],
}


_db_conn: Optional[sqlite3.Connection] = None


def _get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        import os
        default = str(Path(__file__).parent / "processed" / "catalog.db")
        db_path = Path(os.getenv("CATALOG_DB_PATH", default))
        _db_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return _db_conn


def resolve_famous_case(query: str) -> Optional[dict]:
    """
    Check query for famous case nickname. If found, do SQLite LIKE title search.
    Returns case dict with keys: id, title, citation, year, outcome, judges, text.
    Returns None if no match.
    """
    ql = query.lower().strip()

    matched_keywords: Optional[list[list[str]]] = None
    for nickname, kw_tuples in FAMOUS_CASE_ALIASES.items():
        if nickname in ql:
            matched_keywords = kw_tuples
            print(f"[*] Famous case alias matched: '{nickname}'")
            break

    if not matched_keywords:
        return None

    conn = _get_db()
    for kw_tuple in matched_keywords:
        # Build AND query — all keywords in tuple must appear in title
        where = " AND ".join(["LOWER(title) LIKE ?" for _ in kw_tuple])
        params = [f"%{kw}%" for kw in kw_tuple]
        rows = conn.execute(
            f"SELECT id, title, citation, year, outcome, judges, text "
            f"FROM cases WHERE {where} ORDER BY year DESC LIMIT 1",
            params,
        ).fetchall()
        if rows:
            r = rows[0]
            case = {"id": r[0], "title": r[1], "citation": r[2], "year": r[3],
                    "outcome": r[4], "judges": r[5], "text": r[6]}
            print(f"[*] Famous case resolved: '{case['title']}' ({case['year']})")
            return case

    return None
