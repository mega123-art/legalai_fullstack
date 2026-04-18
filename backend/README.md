# Legal AI Backend

FastAPI backend for Indian Supreme Court case search and analysis.

## Architecture

```
Query → Groq expansion (llama-3.1-8b) → InLegalBERT embed → Pinecone ANN
      → BGE reranker → domain penalty → results
                                      → Groq breakdown (llama-3.3-70b)
                                      → Groq summary (llama-3.1-8b)
```

Famous case aliases (nirbhaya, ayodhya, etc.) short-circuit the pipeline via SQLite lookup.

## Prerequisites

- Python 3.10+
- PostgreSQL running locally
- `legal-data/` directory with processed files (SQLite catalog + InLegalBERT model)
- Pinecone index populated with case embeddings

## Setup

```bash
# 1. Create venv and install deps
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in API keys and correct LEGAL_DATA_PATH

# 3. Create database
createdb legalai_fresh

# 4. Run
uvicorn main:app --reload --port 8000
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PINECONE_API_KEY` | Pinecone API key |
| `GROQ_API_KEY` | Groq API key (get free at console.groq.com) |
| `GROQ_MODEL` | Main LLM — default `llama-3.3-70b-versatile` |
| `GROQ_SUMMARY_MODEL` | Summary/expansion LLM — default `llama-3.1-8b-instant` |
| `DATABASE_URL` | PostgreSQL async URL |
| `LEGAL_DATA_PATH` | Absolute path to `legal-data/` directory |
| `PROCESSED_DATA_PATH` | Path to `legal-data/processed/` |
| `CATALOG_DB_PATH` | Path to `catalog.db` SQLite file |
| `TOP_K_FINAL` | Number of results to return (default 5) |

## Key Files

| File | Purpose |
|------|---------|
| `search_pro_payload.py` | Core search pipeline (embed → Pinecone → rerank) |
| `legal_queryfier.py` | Query expansion via Groq |
| `famous_cases.py` | Famous case alias resolution (SQLite) |
| `services/gemini_service.py` | Case breakdown via Groq (streaming) |
| `services/llm_service.py` | Summaries via Groq (streaming) |
| `routers/search.py` | `/search` endpoint |
| `routers/breakdown.py` | `/breakdown` SSE endpoint |

## ML Models Used

| Model | Purpose | Source |
|-------|---------|--------|
| `law-ai/InLegalBERT` | Query/doc embedding | HuggingFace |
| `BAAI/bge-reranker-v2-m3` | Cross-encoder reranking | HuggingFace |
| `llama-3.3-70b-versatile` | Case breakdown (Groq) | Groq API |
| `llama-3.1-8b-instant` | Summaries + query expansion (Groq) | Groq API |

Models download automatically on first run (~2GB total). GPU not required but speeds up reranking.
