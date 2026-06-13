"""
OpenRouter API calls for summaries.
Model: configurable via OPENROUTER_SUMMARY_MODEL env var.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

from openai import AsyncOpenAI

from config import OPENROUTER_API_KEY

_SUMMARY_MODEL = os.getenv("OPENROUTER_SUMMARY_MODEL", "google/gemini-2.0-flash-001")
_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

_SUMMARY_PROMPT = (
    "Summarize this Supreme Court judgment in exactly 150 words. "
    "Focus on: (1) the core legal issue, (2) how the court decided, "
    "(3) the legal principle or precedent established. "
    "Write in plain English — no Latin, no jargon. "
    "Start directly with the substance — no preamble, no 'Here is a summary', no greeting.\n\n"
    "Case text:\n{combined}"
)


async def stream_summary(headnote: str, judgment_text: str) -> AsyncGenerator[str, None]:
    """Stream summary tokens as SSE data lines: 'data: <token>\\n\\n'"""
    combined = f"{headnote}\n\n{judgment_text}"[:3000]
    prompt = _SUMMARY_PROMPT.format(combined=combined)
    try:
        stream = await _client.chat.completions.create(
            model=_SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                safe = token.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        print(f"[llm_service] stream_summary failed: {e}")
        yield "data: Summary unavailable.\n\n"
        yield "data: [DONE]\n\n"
