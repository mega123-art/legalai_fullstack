#!/usr/bin/env python3
"""
Test CLI for the legal search + enrich pipeline.
Runs the full stack: InLegalBERT → Pinecone → reranker → Groq enrich.

Usage:
    python test_cli.py "bail rejected sessions court murder"
    python test_cli.py "nirbhaya case"
    python test_cli.py "SARFAESI auction Rule 8" --year 2020
    python test_cli.py "query here" --no-queryfy --no-enrich
    python test_cli.py "query here" --expand-only   # just show queryfy output
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

SCORE_THRESHOLD = 0.55


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def bold(t): return _color(t, "1")
def dim(t):  return _color(t, "2")
def green(t): return _color(t, "32")
def red(t):   return _color(t, "31")
def cyan(t):  return _color(t, "36")
def yellow(t): return _color(t, "33")


def show_expand(query: str) -> None:
    from legal_queryfier import queryfy
    print(bold(f"\n── Query expansion for: {query!r} ──"))
    result = queryfy(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def run_search(query: str, year: int | None, historical: bool, no_queryfy: bool):
    import search_pro_payload as base
    print(bold(f"\n── Loading models… ──"))
    tokenizer, bi_model, device, index, reranker = base.setup(local_only=True)
    print(dim(f"   Device: {device}"))
    print(bold(f"\n── Searching: {query!r} ──\n"))
    raw, expansion = base.search_pro_diverse(
        query,
        tokenizer, bi_model, device, index, reranker,
        filter_year=year,
        historical=historical,
        use_queryfy=not no_queryfy,
    )
    results = [m for m in raw if float(getattr(m, "final_score", 0)) >= SCORE_THRESHOLD][:5]
    if len(results) < len(raw):
        print(dim(f"   Filtered {len(raw) - len(results)} low-score results (threshold={SCORE_THRESHOLD})"))
    return results, expansion


async def enrich(query: str, cases: list[dict]) -> list[dict]:
    from services.gemini_service import enrich_cases
    return await enrich_cases(query, cases)


def cases_from_results(results) -> list[dict]:
    out = []
    for m in results:
        meta = m.metadata or {}
        out.append({
            "case_id":  meta.get("case_id", ""),
            "title":    meta.get("title", ""),
            "citation": meta.get("citation", ""),
            "year":     int(float(meta.get("year", 0))),
            "outcome":  meta.get("outcome", ""),
            "preview":  (meta.get("text") or "")[:600],
        })
    return out


def print_case(i: int, case: dict, enriched: dict | None, score: float) -> None:
    outcome = case.get("outcome", "")
    if "allow" in outcome.lower() or "grant" in outcome.lower():
        outcome_str = green(f"[{outcome}]")
    elif "dismiss" in outcome.lower() or "reject" in outcome.lower():
        outcome_str = red(f"[{outcome}]")
    else:
        outcome_str = dim(f"[{outcome or 'Disposed'}]")

    print(f"\n{'─'*70}")
    print(bold(f"  #{i}  {case.get('title', 'Unknown')}"))
    print(dim(f"       {case.get('citation', '')}  ·  {case.get('year', '')}  ·  score={score:.3f}  ·  {outcome_str}"))

    if enriched:
        if enriched.get("why_relevant"):
            print(f"\n  {cyan('WHY RELEVANT')}")
            print(textwrap.fill(enriched["why_relevant"], width=68, initial_indent="  ", subsequent_indent="  "))
        if enriched.get("key_issue"):
            print(f"\n  {cyan('KEY ISSUE')}")
            print(textwrap.fill(enriched["key_issue"], width=68, initial_indent="  ", subsequent_indent="  "))
        if enriched.get("decision"):
            print(f"\n  {cyan('DECISION')}")
            print(textwrap.fill(enriched["decision"], width=68, initial_indent="  ", subsequent_indent="  "))
    else:
        preview = case.get("preview", "")
        if preview:
            print(f"\n  {dim('PREVIEW')}")
            print(textwrap.fill(preview[:300], width=68, initial_indent="  ", subsequent_indent="  "))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test CLI — legal search + Groq card enrichment"
    )
    parser.add_argument("query", nargs="*", help="Search query")
    parser.add_argument("--year", type=int, help="Filter by year (±1 fuzz applied)")
    parser.add_argument("--historical", action="store_true", help="Boost older cases")
    parser.add_argument("--no-queryfy", action="store_true", help="Skip Groq query expansion")
    parser.add_argument("--no-enrich", action="store_true", help="Skip card enrichment")
    parser.add_argument("--expand-only", action="store_true", help="Only show queryfy output, no search")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Dump raw JSON results")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(0)

    query = " ".join(args.query)

    if args.expand_only:
        show_expand(query)
        return

    results, expansion = run_search(query, args.year, args.historical, args.no_queryfy)

    if not results:
        print(red("\nNo results found above score threshold."))
        return

    cases = cases_from_results(results)

    enriched_list: list[dict] = []
    if not args.no_enrich:
        print(bold(f"\n── Enriching {len(cases)} cards via Groq… ──"))
        try:
            enriched_list = asyncio.run(enrich(query, cases))
        except Exception as e:
            print(yellow(f"   Enrich failed: {e}"))

    if args.as_json:
        for i, (case, m) in enumerate(zip(cases, results)):
            case["score"] = round(float(getattr(m, "final_score", 0)), 4)
            if i < len(enriched_list):
                case.update(enriched_list[i])
        print(json.dumps(cases, indent=2, ensure_ascii=False))
        return

    print(bold(f"\n── Results ({len(results)})  |  understood as: {expansion[:80]!r} ──"))
    for i, (case, m) in enumerate(zip(cases, results), 1):
        enriched = enriched_list[i - 1] if i - 1 < len(enriched_list) else None
        print_case(i, case, enriched, float(getattr(m, "final_score", 0)))

    print(f"\n{'─'*70}\n")


if __name__ == "__main__":
    main()
