import os
import json
import re
import hashlib
import httpx
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_EXPANSION_MODEL", "llama-3.1-8b-instant")

SYSTEM_PROMPT = """You are a Senior Registrar of the Supreme Court of India. Your specialty is drafting 'Supreme Court Reports' (SCR) Headnotes.
When I give you a 'Citizen Situation,' transform it into a professional, CLINICAL SCR Hypothetical Headnote.

Guidelines:
1. Use SURGICAL legal terminology (e.g., 'Article 14', 'Article 311', 'Natural Justice', 'Prejudice Doctrine', 'Audi Alteram Partem').
2. STAY FOCUSED on the specific statutory violation. For Employment Dismissal, prioritize Article 14 and 311, NOT Article 19.
3. For procedural lapses, mention the 'Prejudice Doctrine'—the requirement to show that the lack of hearing caused actual damage.
4. If a Bank or Auction is involved, prioritize SARFAESI Rules 8 and 9.
5. Structure: KEYWORDS: [list] followed by HEADNOTE: [text].
6. Output ONLY a clean JSON object: { 'original_situation': '...', 'legal_keywords': '...', 'hypothetical_headnote': '...' }"""

# In-memory expansion cache — keyed on md5(query), max 500 entries
_expansion_cache: dict[str, dict] = {}


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


def queryfy(situation: str):
    """Transforms a raw situation into a legal headnote using Groq."""
    key = _cache_key(situation)
    if key in _expansion_cache:
        print(f"[*] Query expansion cache hit")
        return _expansion_cache[key]

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Citizen Situation: {situation}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 300,
                    "response_format": {"type": "json_object"}
                },
            )
            resp.raise_for_status()
            text = resp.json()['choices'][0]['message']['content'].strip()

        result = json.loads(text, strict=False)

        # Cache successful result
        if len(_expansion_cache) >= 500:
            for k in list(_expansion_cache)[:100]:
                del _expansion_cache[k]
        _expansion_cache[key] = result
        return result

    except Exception as e:
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(), strict=False)
        except:
            pass
        return {"error": str(e), "raw_response": text if 'text' in locals() else None}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_situation = " ".join(sys.argv[1:])
    else:
        test_situation = "My building was demolished by the city council without any prior notice in the middle of the night."

    print(f"\n[QUERYFYING VIA GROQ ({GROQ_MODEL})]: {test_situation}\n")
    result = queryfy(test_situation)
    print(json.dumps(result, indent=2))
