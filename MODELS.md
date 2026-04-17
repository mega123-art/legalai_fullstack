# Model Registry

All models used in the LegalAI pipeline, where they run, and what they do.

---

## Search Pipeline (local, Mac Mini)

| Model | Provider | Task | Config |
|-------|----------|------|--------|
| `law-ai/InLegalBERT` | HuggingFace (local) | Bi-encoder: embeds queries and case chunks into vectors for Pinecone ANN retrieval | `MODEL_NAME` in `search_pro_payload.py` |
| `BAAI/bge-reranker-v2-m3` | HuggingFace (local) | Cross-encoder reranker: rescores top-300 Pinecone hits against query expansion | `RERANKER_NAME` in `search_pro_payload.py` |

**Flow:** query → InLegalBERT embed → Pinecone ANN (top 300) → bge-reranker cross-encode → top 10 results

---

## Query Expansion (API)

| Model | Provider | Task | Config |
|-------|----------|------|--------|
| `gemini-2.0-flash` (or similar) | Google Gemini API | Transforms raw user query into a legal headnote-style expansion (acts, sections, legal doctrine) | `GEMINI_API_KEY` in `.env` |

Used in `legal_queryfier` / `_build_query_variants()` before retrieval.

---

## Case Breakdown (API)

| Model | Provider | Task | Config |
|-------|----------|------|--------|
| `llama-3.3-70b-versatile` | Groq API | Structured JSON extraction from full case text: facts, issues, arguments, judgment, ratio, conclusion, acts cited, cases cited | `GROQ_MODEL` in `.env`, `GROQ_API_KEY` in `.env` |

**Endpoint:** `POST /api/breakdown` and `POST /api/breakdown/stream`  
**Context:** up to 20,000 chars of case `full_text`  
**Output:** JSON with `response_format: json_object` — deterministic, no markdown wrapping

---

## Vector Store

| Store | Provider | Task |
|-------|----------|------|
| Pinecone (`legal-cases` index) | Pinecone cloud | Stores 768-dim InLegalBERT embeddings of all case chunks with metadata (year, outcome, citation, title, text snippet) |

---

## Summary (SSE streaming)

| Model | Provider | Task | Config |
|-------|----------|------|--------|
| `llama-3.1-8b-instant` | Groq API | 150-word plain English case summary, streamed via SSE | `GROQ_SUMMARY_MODEL` in `.env` |

**Note:** Uses faster/cheaper 8B model — summary is short output, quality sufficient. Breakdown uses 70B for complex structured extraction.

---

## Environment Variables

```env
# Groq — breakdown + summaries
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_SUMMARY_MODEL=llama-3.1-8b-instant

# Google Gemini — query expansion
GEMINI_API_KEY=AIza...

# Pinecone — vector store
PINECONE_API_KEY=pcsk_...

# Ollama — no longer used (kept in .env for legacy)
```

---

## Swapping Models

- **Breakdown model:** change `GROQ_MODEL` in `.env`. Any Groq model supporting `response_format: json_object` works (e.g. `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `meta-llama/llama-4-scout-17b-16e-instruct`).
- **Reranker:** change `RERANKER_NAME` in `search_pro_payload.py`, re-run `init_search()`.
- **Bi-encoder:** change `MODEL_NAME` in `search_pro_payload.py` — requires re-embedding all cases into Pinecone.
