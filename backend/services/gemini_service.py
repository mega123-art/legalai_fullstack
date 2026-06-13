"""
OpenRouter API calls for structured case breakdown.
Model: configurable via OPENROUTER_BREAKDOWN_MODEL env var.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, AsyncGenerator

from openai import AsyncOpenAI

from config import OPENROUTER_API_KEY

BREAKDOWN_MODEL = os.getenv("OPENROUTER_BREAKDOWN_MODEL", "google/gemini-2.0-flash-001")

_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

_BREAKDOWN_PROMPT = """You are an expert Indian Supreme Court legal analyst with deep knowledge of Indian constitutional, civil, and criminal law.
Analyze the following judgment thoroughly and return ONLY a valid JSON object — no markdown fences, no explanations, no preamble.

Required JSON shape:
{{
  "facts": "<string: 3-4 paragraph detailed factual background covering the dispute origin, parties, lower court history, and how the matter reached the Supreme Court>",
  "issues": ["<precise legal issue 1 as framed by the court>", "<legal issue 2>", "<add all issues the court actually addressed>"],
  "arguments_petitioner": [
    "<argument 1: specific legal submission with the statute/article/precedent relied upon>",
    "<argument 2>",
    "<argument 3>",
    "<include ALL major arguments — aim for 4-6 substantive points, not summaries>"
  ],
  "arguments_respondent": [
    "<argument 1: specific counter-submission with statute/precedent>",
    "<argument 2>",
    "<argument 3>",
    "<include ALL major counter-arguments — aim for 4-6 substantive points>"
  ],
  "judgment": "<string: precise holding — what the court decided on each issue, orders passed, reliefs granted or refused>",
  "ratio_decidendi": "<string: the core legal principle(s) the court laid down that will bind future courts — quote the court where possible>",
  "conclusion": "<string: 4-5 paragraph detailed conclusion covering: (a) final disposition and exact order passed, (b) full reasoning chain the court relied on, (c) how the court distinguished or applied prior precedents, (d) practical implications for the parties, (e) broader significance for Indian jurisprudence and future cases. Use formal legal prose.>",
  "acts_cited": ["<Act name, year + specific section/article cited>"],
  "cases_cited": ["<Full case name + citation e.g. (2012) 3 SCC 460>"]
}}

Case text:
{full_text}"""


def _extract_json(raw: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON — handles common Gemini output quirks."""
    # Strip markdown fences
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Try direct parse first
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Extract outermost JSON object
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if not m:
        return None
    candidate = m.group(0)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Fix trailing commas before } or ] (common Gemini quirk)
    fixed = re.sub(r",\s*([\}\]])", r"\1", candidate)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Fix unescaped newlines inside string values
    fixed2 = re.sub(r'(?<!\\)\n', r'\\n', fixed)
    try:
        return json.loads(fixed2)
    except json.JSONDecodeError:
        pass

    return None


async def get_breakdown(full_text: str) -> dict:
    """Call OpenRouter for structured case breakdown. Returns parsed dict."""
    prompt = _BREAKDOWN_PROMPT.format(full_text=full_text[:20000])
    try:
        resp = await _client.chat.completions.create(
            model=BREAKDOWN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=8192,
        )
        raw_text = resp.choices[0].message.content or ""
        data = _extract_json(raw_text)
        if data:
            return _normalise(data)
        raise ValueError(f"Unparseable OpenRouter response: {raw_text[:200]}")
    except Exception as e:
        print(f"[breakdown_service] OpenRouter failed ({e})")
        return {
            "facts": "Error generating breakdown.",
            "issues": [],
            "arguments_petitioner": [],
            "arguments_respondent": [],
            "judgment": str(e),
            "ratio_decidendi": "",
            "conclusion": "Please check OPENROUTER_API_KEY and model availability.",
            "acts_cited": [],
            "cases_cited": [],
        }


async def stream_breakdown(full_text: str) -> AsyncGenerator[str, None]:
    """Stream raw text tokens from OpenRouter for the streaming SSE route."""
    prompt = _BREAKDOWN_PROMPT.format(full_text=full_text[:20000])
    stream = await _client.chat.completions.create(
        model=BREAKDOWN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=8192,
        stream=True,
    )
    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token


def _normalise(data: dict) -> dict:
    """Ensure all expected keys exist with correct types."""
    def _list(v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [v] if v else []
        return []

    return {
        "facts":                   data.get("facts", ""),
        "issues":                  _list(data.get("issues")),
        "arguments_petitioner":    _list(data.get("arguments_petitioner")),
        "arguments_respondent":    _list(data.get("arguments_respondent")),
        "judgment":                data.get("judgment", ""),
        "ratio_decidendi":         data.get("ratio_decidendi", ""),
        "conclusion":              data.get("conclusion", ""),
        "acts_cited":              _list(data.get("acts_cited")),
        "cases_cited":             _list(data.get("cases_cited")),
    }
