import os
import json
import re
import hashlib
import httpx
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EXPANSION_MODEL = os.getenv("OPENROUTER_EXPANSION_MODEL", "google/gemini-2.0-flash-001")

SYSTEM_PROMPT = """You are a Senior Registrar of the Supreme Court of India specialising in SCR Headnotes.
Given a 'Citizen Situation', produce a JSON object with four fields.

Rules:
1. PRIORITIZE the specific statute that governs the situation:
   - Tenancy/Property → Transfer of Property Act s.106, Rent Control Act
   - Employment → Article 311, service rules, reinstatement
   - Banking/Auction → SARFAESI Act Rules 8 and 9
   - Criminal procedure → IPC / CrPC sections
   - Tax → Income Tax Act / GST
2. Only add constitutional principles (Article 14, Natural Justice, Audi Alteram Partem) if NO specific statute applies, or if constitutional validity is directly in question.
3. filter_terms: 4–6 short phrases that would LITERALLY appear word-for-word in the body text of relevant judgments.
   - Use OPERATIONAL language that appears in actual headnotes and judgment text — not pure legal doctrine labels
   - NEVER use terms that match thousands of unrelated cases (e.g. "eviction", "bail", "termination", "rent control act" alone)
   - Each term must be discriminating: specific to this exact factual and legal situation
   - EMPLOYMENT HOUSING: use "official quarters", "service quarters", "allotment of quarters", "occupying quarters", "vacate quarters" — prefer BOTH the common phrase ("service quarters") AND the administrative term ("official quarters") to cover vocabulary variation across judgments
   - PMLA/ED: use "section 45 pmla", "twin conditions", "money laundering proceeds"
   - SERVICE LAW: use "regularisation of service", "compassionate appointment", "back wages reinstatement"
   - Good: "official quarters", "allotment of quarters", "section 45 pmla", "twin conditions", "regularisation of service"
   - Bad: "service tenancy", "licensee not tenant", "Rent Control Act", "eviction", "Transfer of Property Act"

Output ONLY valid JSON — no markdown, no preamble:
{
  "original_situation": "...",
  "legal_keywords": "comma-separated key legal terms",
  "hypothetical_headnote": "clinical SCR-style headnote paragraph",
  "filter_terms": ["exact phrase 1", "exact phrase 2", "exact phrase 3", "exact phrase 4"]
}"""

# In-memory expansion cache — keyed on md5(query), max 500 entries
_expansion_cache: dict[str, dict] = {}


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


def queryfy(situation: str):
    """Transforms a raw situation into a legal headnote + filter terms using OpenRouter."""
    key = _cache_key(situation)
    if key in _expansion_cache:
        print(f"[*] Query expansion cache hit")
        return _expansion_cache[key]

    text = ""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": EXPANSION_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Citizen Situation: {situation}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 400,
                },
            )
            resp.raise_for_status()
            text = resp.json()['choices'][0]['message']['content'].strip()

        clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        result = json.loads(clean, strict=False)

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
        except Exception:
            pass
        return {"error": str(e), "raw_response": text if text else None}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_situation = " ".join(sys.argv[1:])
    else:
        test_situation = "My building was demolished by the city council without any prior notice in the middle of the night."

    print(f"\n[QUERYFYING VIA OPENROUTER ({EXPANSION_MODEL})]: {test_situation}\n")
    result = queryfy(test_situation)
    print(json.dumps(result, indent=2))
