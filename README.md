<div align="center">

<img src="docs/assets/agentkiln-logo.svg" alt="AgentKiln Memory" width="160"/>

# AgentKiln Memory

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?logo=postgresql&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-FTS5-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

![CI](https://github.com/agentkiln/agentkiln-memory/actions/workflows/ci.yml/badge.svg)
![Deploy](https://github.com/agentkiln/agentkiln-memory/actions/workflows/deploy-pandastack.yml/badge.svg)


[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

English | [简体中文](README.zh-CN.md)

**An evidence-only long-term memory service for AI agents.**

AgentKiln Memory persists agent conversations under strict user isolation, indexes them with hybrid lexical and vector retrieval, and returns verbatim source evidence without generating answers. Suitable for production agent pipelines.

[Quick Start](#quick-start) | [API Reference](#api) | [Architecture](#architecture) | [Configuration](#configuration) | [Deployment](#deployment) | [Contributing](#contributing) | [License](#license)

</div>

## Table of Contents

- [Why AgentKiln Memory](#why-agentkiln-memory)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [API](#api)
- [Retrieval Pipeline](#retrieval-pipeline)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Why AgentKiln Memory

Long-term memory is the backbone of capable AI agents. Most memory systems conflate retrieval with generation: they return synthesized answers, making it impossible to audit what the agent actually remembered or verify that no hallucination occurred. AgentKiln Memory takes a different path.

**Evidence-only retrieval.** Search never generates a final answer. It returns the original source messages, token-bounded and ranked by relevance, so the downstream agent sees exactly what the memory system retrieved. This separation makes the retrieval layer auditable, testable, and trustworthy.

**Hybrid retrieval.** Lexical search catches exact terms, names, dates, and code identifiers that vector-only systems often miss. Vector retrieval catches paraphrases and semantic matches that lexical search cannot bridge. Reciprocal rank fusion combines both channels, and adjacent-turn expansion restores conversation context that a single message cannot carry alone.

**Contract-level integrity.** Strict user isolation, idempotent writes, request conflict detection, token budgeting, and no answer generation are contract-level requirements, not optional features. The same guarantees apply in production.

**CJK-native.** Unicode normalization, Porter tokenization, and CJK n-gram support work out of the box. Chinese and English memory content receive equal treatment in lexical indexing and vector retrieval.

## Features

- **Synchronous Add/Search API** with FastAPI and Pydantic validation
- **Strict user isolation**: every memory, index entry, vector, and cache key is scoped to the exact `user_id`
- **Idempotent Add**: the same `request_id` with the same payload is safe to retry; a different payload with the same `request_id` returns HTTP 409
- **Hybrid retrieval**: SQLite FTS5 lexical search and vector cosine similarity, fused by reciprocal rank
- **Adjacent-turn expansion**: restores multi-message conversation windows around matched evidence
- **Temporal intent detection**: recognizes latest and earliest queries and re-ranks evidence by time
- **Token-bounded output**: evidence windows respect a configurable token budget, never exceeding `top_k`
- **PostgreSQL or SQLite**: PostgreSQL with Managed PostgreSQL in production, SQLite with FTS5 for local development
- **OpenAI-compatible embeddings**: any provider exposing `POST /v1/embeddings` works, including Jina, OpenRouter, NVIDIA NIM, and SiliconFlow
- **Production deployment**: Docker, Compose, Caddy HTTPS reverse proxy, health checks, and manual GitHub Actions deploy
- **Privacy-first**: no request body logging, no credential persistence, evaluation data deletion within 30 days

## Architecture

```text
                       +---------------------+
                       |   FastAPI Service   |
                       |  /add  /search /v1  |
                       +----------+----------+
                                  |
                    +-------------+-------------+
                    |                           |
              +-----v------+             +------v------+
              | MemoryLLM  |             | MemoryService|
              | embeddings |             |  isolation   |
              | annotation |             |  caching     |
              | query plan |             +------+------+
              +-----+------+                    |
                    |                           |
          +---------v----------+     +----------v-----------+
          | Embedding Provider |     |    MemoryDatabase    |
          | (OpenAI-compatible)|     | PostgreSQL / SQLite  |
          +--------------------+     +----------+-----------+
                                                |
                                     +----------v-----------+
                                     |   Retrieval Layer    |
                                     |  FTS5 lexical search |
                                     |  Vector similarity   |
                                     |  RRF fusion          |
                                     |  Window expansion    |
                                     |  Temporal ranking    |
                                     +----------------------+
```

The service exposes synchronous REST endpoints. Add writes are validated, annotated, embedded, and persisted in a single synchronous call, so the record is immediately searchable. Search queries are planned with LLM-assisted intent extraction, then routed through both lexical and vector channels, fused, expanded, ranked, and packed into token-bounded windows.

## Quick Start

### Run locally

```bash
git clone https://github.com/agentkiln/agentkiln-memory.git
cd agentkiln-memory

python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

AML_LLM_MODE=off uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The service starts on port 8000. Health checks at `GET /health` require no authentication.

### Add a memory

```bash
curl -X POST http://127.0.0.1:8000/add \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "run:conv:chunk-0",
    "messages": [
      {
        "role": "user",
        "timestamp": 1704067200000,
        "content": "My favorite drink is jasmine tea."
      }
    ],
    "user_id": "user-123",
    "session_id": "session-456"
  }'
```

### Search

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What drink do I prefer?",
    "options": ["coffee", "jasmine tea"],
    "user_id": "user-123",
    "top_k": 5
  }'
```

### Run tests

```bash
pytest -q
python scripts/privacy_scan.py --root .
```

Unit and integration tests cover API contract, user isolation, persistence, concurrency, temporal retrieval, model integration, and tooling.

## API

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health, version, LLM mode, and model readiness |
| `POST` | `/add` | Store messages with idempotency and conflict detection |
| `POST` | `/search` | Retrieve ranked evidence without generating answers |
| `POST` | `/v1/memory/add` | Alias for `/add` |
| `POST` | `/v1/memory/search` | Alias for `/search` |

### Add request

```json
{
  "request_id": "eval:run:conv:chunk-0",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "My favorite drink is jasmine tea."
    }
  ],
  "user_id": "eval:run:conv",
  "session_id": "eval:run:sample:0"
}
```

- `request_id`: unique identifier for deduplication and retry safety
- `messages`: 1 to 200 messages, each with `role`, `content`, and optional Unix-millisecond `timestamp` (years 1-9999)
- `user_id`: strict isolation boundary
- `session_id`: conversation grouping for adjacent-turn expansion

### Add response

```json
{
  "success": true,
  "request_id": "eval:run:conv:chunk-0",
  "user_id": "eval:run:conv",
  "session_id": "eval:run:sample:0"
}
```

### Search request

```json
{
  "query": "What drink do I prefer?",
  "options": ["coffee", "jasmine tea"],
  "user_id": "eval:run:conv",
  "top_k": 100
}
```

- `query`: search text, 1 to 8000 characters
- `options`: optional candidate options for option-match scoring
- `top_k`: 1 to 100, maximum evidence windows returned

### Search response

```json
{
  "data": [
    {
      "id": "mem_123",
      "content": "[mem_123 | user | 2024-01-01T00:00:00Z] My favorite drink is jasmine tea.",
      "score": 0.91,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

Each item contains source text wrapped in a session window header. When a single source exceeds the configured evidence budget, the returned text is truncated with `...`; the stored source remains complete. The system never summarizes or generates answers.

In `competition` mode, long Add messages are split only for model calls. The stored source remains whole, and a large Add request may require several upstream calls.

### Authentication

Add and Search support three authentication methods when `AML_API_KEY` is configured:

| Method | Header | Format |
|--------|--------|--------|
| Bearer | `Authorization` | `Bearer <key>` |
| Token | `Authorization` | `Token <key>` |
| API Key | `X-Api-Key` | `<key>` |

Health checks are unauthenticated. When `AML_API_KEY` is empty, Add and Search are open.

## Retrieval Pipeline

The search pipeline processes a query through five stages:

1. **Query analysis**: an LLM call extracts retrieval cues, facets, and temporal intent from the query. In `off` or `dev_mock` modes, lexical features alone drive retrieval.

2. **Lexical search**: SQLite FTS5 or PostgreSQL full-text search retrieves candidates using BM25 ranking, Unicode normalization, Porter tokenization, and CJK terms including single characters. SQLite also searches the scoped source text for single-character queries against records written with the older index format.

3. **Vector search**: the query is embedded and compared against stored vectors using cosine similarity. Only vectors from the same embedding model and dimension are considered. Embedding writes are split into batches of at most 10 texts for `text-embedding-v4` compatibility.

4. **Reciprocal rank fusion**: both candidate lists are merged using `1 / (60 + rank)` scoring, then filtered by a minimum similarity threshold.

5. **Window expansion and ranking**: matched candidates expand to include adjacent turns in the same session. Rule-based ranking combines term coverage, option matches, phrase bonuses, and temporal intent. For queries without temporal intent, configured reranker scores determine the final evidence order; `qwen3.7-text-rerank` receives at most 500 top rule-ranked candidates per call. Temporary failures fall back to rule-based ranking and are retried on the next Search. Earliest and latest queries retain time-aware rule ranking.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `AML_DATABASE_PATH` | `data/memory.db` | SQLite database path |
| `DATABASE_URL` | empty | PostgreSQL URL; when set, the PostgreSQL backend is used |
| `AML_PRODUCTION` | empty | Set to `1` to require competition mode, API-key auth, HTTPS model endpoints, and PostgreSQL `DATABASE_URL` |
| `AML_LLM_MODE` | `off` | `off`, `dev_mock`, or `competition` |
| `AML_API_KEY` | empty | Optional Add/Search authentication |
| `OPENAI_API_KEY` | empty | Runtime model credential |
| `OPENAI_MODEL` | `gpt-4o-mini` | Add/Search LLM model |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding model |
| `OPENAI_EMBEDDING_BASE_URL` | falls back to `OPENAI_BASE_URL` | Optional separate embedding endpoint |
| `OPENAI_EMBEDDING_API_KEY` | falls back to `OPENAI_API_KEY` | Optional separate embedding credential |
| `RERANK_MODEL` | empty | Optional reranker model; empty disables reranking |
| `RERANK_BASE_URL` | falls back to the embedding base URL | Reranker endpoint or base URL |
| `RERANK_API_KEY` | falls back to the embedding API key | Optional separate reranker credential |
| `AML_TIMEOUT_SECONDS` | `90` | Upstream timeout |
| `AML_CANDIDATE_LIMIT` | `300` | Candidate cap per retrieval channel before fusion |
| `AML_MAX_OUTPUT_TOKENS` | `8000` | Evidence token budget |
| `AML_MAX_OUTPUT_ITEMS` | `24` | Maximum returned evidence windows |
| `AML_VECTOR_MIN_SIMILARITY` | `0.35` | Minimum vector similarity for vector-only candidates |
| `AML_VECTOR_ONLY_MIN_SIMILARITY` | `0.65` | Stricter threshold when lexical retrieval has no candidates |
| `AML_SEARCH_CONCURRENCY` | `32` | Maximum in-process Search operations |
| `AML_ADD_CONCURRENCY` | `16` | Maximum in-process Add operations |

For `qwen3.7-text-rerank`, `RERANK_BASE_URL` may be the full DashScope endpoint ending in `/api/v1/services/rerank/text-rerank/text-rerank`. The service uses that native API's nested `input` request and `output.results` response format.

## Deployment

### Docker

```bash
docker build -t agentkiln-memory .
docker run -d --name agentkiln \
  -p 8000:8000 \
  -e AML_LLM_MODE=off \
  agentkiln-memory
```

### Docker Compose

```bash
docker compose up -d
```

### Production

See [deploy/PandaStack.md](deploy/PandaStack.md) for the full production deployment guide, including Managed PostgreSQL, HTTPS reverse proxy, environment variables, and manual deployment.

### Verification

Before deploying to production:

```bash
python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory
python scripts/release_check.py \
  --repository-url https://github.com/agentkiln/agentkiln-memory \
  --add-url https://your-domain.example/add \
  --search-url https://your-domain.example/search \
  --health-url https://your-domain.example/health
```

## Testing

```bash
pytest -q
```

Unit and integration tests cover:

- API contract and response schema validation
- Strict user isolation and cross-user access denial
- Idempotent Add and payload conflict detection
- Persistence across process restart
- Concurrent Add and Search operations
- Temporal intent retrieval (latest, earliest)
- Lexical normalization and CJK token support
- Privacy scan and release check tooling

## Project Structure

```text
agentkiln-memory/
├── app/
│   ├── main.py          # FastAPI entry point
│   ├── config.py        # Settings and environment configuration
│   ├── llm.py           # Embedding and LLM calls
│   ├── service.py       # Retrieval pipeline and business logic
│   ├── postgres_db.py   # PostgreSQL storage backend
│   ├── schemas.py       # Pydantic request/response models
│   └── text.py          # Lexical normalization and feature extraction
├── eval/
│   └── retrieval.py     # Offline retrieval evaluation
├── scripts/
│   ├── smoke.py         # Public smoke test
│   ├── local_verify.py  # Local end-to-end verification
│   ├── ops_contract.py  # Public contract check
│   ├── recovery_check.py # Container restart recovery check
│   └── release_check.py # Submission readiness check
├── tests/               # Unit and integration tests
├── deploy/              # Production deployment guides
├── docs/                # Project state and submission materials
├── .github/workflows/   # CI and deployment automation
├── compose.yaml         # Docker Compose configuration
├── Dockerfile           # Production image
└── pyproject.toml       # Project metadata and dependencies
```

## Contributing

Contributions are welcome. Before submitting a pull request:

1. Run the full test suite: `pytest -q`
2. Run the privacy scan: `python scripts/privacy_scan.py --root .`
3. Check `git status --short` to ensure no secrets, `.env`, databases, logs, or evaluation data are staged
4. Use the commit message format `type: short description` with types `feat`, `fix`, `test`, `docs`, `chore`, `security`, `perf`, `refactor`

See [AGENTS.md](AGENTS.md) for the full development rules and verification workflow.

## Security

- Do not commit `.env`, API keys, or system credentials
- Health is public; Add and Search can require Bearer, Token, or `X-Api-Key` authentication
- The service does not log request bodies or credentials
- Production requires HTTPS for chat, embedding, and rerank endpoints; model credentials are not forwarded on redirects
- Production requires a PostgreSQL `DATABASE_URL` and fails startup if it is missing
- Upstream error bodies are not returned in Add/Search error details
- All memories are retrieved only through the exact submitted `user_id`
- Delete the database or Docker volume after evaluation or testing runs complete

See [SECURITY.md](SECURITY.md) for the full security policy.

## License

MIT. See [LICENSE](LICENSE) for the full text.
