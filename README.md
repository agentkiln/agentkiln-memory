# AgentKiln Memory

Project development rules are in [AGENTS.md](AGENTS.md).

AgentKiln Memory is an evidence-only memory service for the textual retrieval track of the an open retrieval evaluation. It implements the public synchronous `Add` and `Search` contract and returns source evidence rather than generated final answers.

## What It Does

- Stores every source message under an exact `user_id` isolation boundary.
- Uses SQLite FTS5, lexical normalization, CJK token support, and vector retrieval.
- Fuses lexical and vector candidates with reciprocal rank fusion.
- Expands adjacent source turns within the same session.
- Ranks evidence with term coverage, option matches, phrase matches, and temporal intent.
- Returns token-bounded, source-deduplicated conversation windows.
- Keeps Add idempotent through `request_id` and payload hashes.
- Supports public deployment with Docker, a persistent volume, optional API-key auth, health checks, and an HTTPS reverse proxy example.

## API

Endpoints:

- `GET /health`
- `POST /add`
- `POST /search`
- `POST /v1/memory/add`
- `POST /v1/memory/search`

Add request:

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

Search request:

```json
{
  "query": "What drink do I prefer?",
  "options": ["coffee", "jasmine tea"],
  "user_id": "eval:run:conv",
  "top_k": 100
}
```

Search response:

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

## Run Locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
AML_LLM_MODE=off uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
python scripts/smoke.py
pytest
```

## Public Deployment

The competition requires participant-hosted Add and Search APIs. Deploy the service behind HTTPS and submit the live URLs:

- `POST https://your-domain.example/add`
- `POST https://your-domain.example/search`
- `GET https://your-domain.example/health`

Use a long random `AML_API_KEY`; configure the same value as the system credential in the evaluation application. Formal mode uses `gpt-4o-mini` for Add/Search model calls and `text-embedding-v4` for embeddings. Search never generates the final answer.

Before applying:

```bash
python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"
```

For a Docker restart check:

```bash
python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory
```

For an offline retrieval panel, provide a JSONL file whose records contain `memory` or `messages`, a `question` or `query`, and optional `evidence_ids`:

```bash
python -m eval.retrieval /path/to/public-panel.jsonl --top-k 100
```

Before freezing the submission version:

```bash
python scripts/release_check.py \
  --repository-url https://github.com/your-team/agentkiln-memory \
  --add-url https://your-domain.example/add \
  --search-url https://your-domain.example/search \
  --health-url https://your-domain.example/health
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AML_DATABASE_PATH` | `data/memory.db` | SQLite database path |
| `DATABASE_URL` | empty | PostgreSQL URL; when set, the PostgreSQL backend is used |
| `AML_PRODUCTION` | empty | Set to `1` to require competition mode and API-key auth |
| `AML_LLM_MODE` | `off` | `off`, `dev_mock`, or `competition` |
| `AML_API_KEY` | empty | Optional Add/Search authentication |
| `OPENAI_API_KEY` | empty | Runtime model credential |
| `OPENAI_MODEL` | `gpt-4o-mini` | Add/Search LLM model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding model |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `AML_TIMEOUT_SECONDS` | `90` | Upstream timeout |
| `AML_CANDIDATE_LIMIT` | `300` | Candidate cap before ranking |
| `AML_MAX_OUTPUT_TOKENS` | `8000` | Evidence token budget |
| `AML_MAX_OUTPUT_ITEMS` | `24` | Maximum returned evidence windows |
| `AML_VECTOR_MIN_SIMILARITY` | `0.35` | Minimum vector similarity for vector-only candidates |
| `AML_VECTOR_ONLY_MIN_SIMILARITY` | `0.65` | Stricter threshold when lexical retrieval has no candidates |
| `AML_SEARCH_CONCURRENCY` | `32` | Maximum in-process Search operations |
| `AML_ADD_CONCURRENCY` | `16` | Maximum in-process Add operations |

## Security

- Do not commit `.env`, API keys, system credentials, or system credentials.
- Health is public; Add and Search can require Bearer, Token, or `X-Api-Key` authentication.
- The service does not log request bodies or credentials.
- All memories are retrieved only through the exact submitted `user_id`.
- Delete the evaluation database or Docker volume within 30 days after the run unless written organizer permission says otherwise.

## PandaStack Deployment

See [deploy/PandaStack.md](deploy/PandaStack.md). The `PandaStack` branch runs FastAPI on PandaStack Apps with Managed PostgreSQL. Local development still uses SQLite when `DATABASE_URL` is not set.

## License

MIT
