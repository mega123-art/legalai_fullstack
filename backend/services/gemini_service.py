"""
Groq API calls for structured case breakdown.
Model: llama-3.3-70b-versatile (configurable via GROQ_MODEL env var).
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, AsyncGenerator

from groq import AsyncGroq

from config import GROQ_API_KEY

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = AsyncGroq(api_key=GROQ_API_KEY)

_BREAKDOWN_PROMPT = """You are an expert Indian Supreme Court legal analyst.
Analyze the following judgment and return ONLY a valid JSON object — no markdown fences,
no explanations, no preamble.

Required JSON shape:
{{
  "facts": "<string: 2-3 paragraph factual background>",
  "issues": ["<legal issue 1>", "<legal issue 2>"],
  "arguments_petitioner": ["<argument 1>", "<argument 2>"],
  "arguments_respondent": ["<argument 1>", "<argument 2>"],
  "judgment": "<string: what the court decided and the order passed>",
  "ratio_decidendi": "<string: the legal principle/ratio that binds future courts>",
  "conclusion": "<string: 3-4 paragraph detailed conclusion covering: (a) final disposition and order passed, (b) reasoning the court relied on, (c) practical implications for the parties, (d) broader significance for future cases and legal practice. Use formal legal prose.>",
  "acts_cited": ["<Act name + section>"],
  "cases_cited": ["<Case name + citation>"]
}}

Case text:
{full_text}"""


def _extract_json(raw: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON."""
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


async def get_breakdown(full_text: str) -> dict:
    """Call Groq for structured case breakdown. Returns parsed dict."""
    prompt = _BREAKDOWN_PROMPT.format(full_text=full_text[:20000])
    try:
        resp = await _client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw_text = resp.choices[0].message.content or ""
        data = _extract_json(raw_text)
        if data:
            return _normalise(data)
        raise ValueError(f"Unparseable Groq response: {raw_text[:200]}")
    except Exception as e:
        print(f"[breakdown_service] Groq failed ({e})")
        return {
            "facts": "Error generating breakdown.",
            "issues": [],
            "arguments_petitioner": [],
            "arguments_respondent": [],
            "judgment": str(e),
            "ratio_decidendi": "",
            "conclusion": "Please check GROQ_API_KEY and model availability.",
            "acts_cited": [],
            "cases_cited": [],
        }


async def stream_breakdown(full_text: str) -> AsyncGenerator[str, None]:
    """Stream raw text tokens from Groq for the streaming SSE route."""
    prompt = _BREAKDOWN_PROMPT.format(full_text=full_text[:20000])
    stream = await _client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
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
