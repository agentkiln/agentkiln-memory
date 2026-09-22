# Project State

Updated: 2026-09-22.

## Current status

The repository has a runnable FastAPI service with synchronous Add/Search, SQLite and PostgreSQL persistence, FTS5 and GIN lexical retrieval, configured embeddings, optional rerank with fallback, RRF fusion, source-window packing, strict user isolation, idempotent Add, and API-key authentication.

The repository also includes Docker deployment files, a Caddy HTTPS example, PandaStack deployment guide, public contract checks, a restart recovery check, and submission/disclosure documents.

## What is complete

- AgentKiln Memory is implemented in this repository.
- Public Add/Search contract implemented under both short paths and `/v1/memory/*` aliases.
- Health endpoint returns `status`, version, mode, and model readiness.
- Add validates required fields and rejects unsupported extra fields.
- Search caps `top_k` at 100 and returns a `data` array.
- Source records are isolated by exact `user_id`.
- Memories persist across process restart.
- Request retries are idempotent; conflicting payloads return HTTP 409.
- Lexical retrieval works without external model credentials in `off` and `dev_mock` modes.
- Embeddings and optional model calls are explicit configuration, not hidden fallback behavior.
- Optional reranker with automatic fallback to rule-based ranking.
- Deployment and operational checks are included.

## Verified locally

Command:

```bash
pytest -q
```

Result: 76 tests passed using the existing local Python environment.

Command:

```bash
python scripts/privacy_scan.py --root .
```

Result: privacy scan passed for all tracked files.

Command:

```bash
python scripts/local_verify.py --port 8123 --concurrency 24
```

Result: local end-to-end verification passed with 24 concurrent synchronous Add calls completing in about 0.36 seconds, 13 returned evidence windows, and a measured Search latency of about 0.081 seconds in `dev_mock` mode.

## Verified on PandaStack deployment

Public HTTPS deployment on PandaStack with Managed PostgreSQL has been verified:

- Health endpoint returns `status: ok`, `llm_mode: competition`, and `llm_ready: true`.
- Add successfully stores messages with real chat and embedding calls.
- Search successfully retrieves evidence with real embedding calls.
- Idempotent Add: identical `request_id` and payload return success without duplicate writes.
- Conflict detection: different payload with the same `request_id` returns HTTP 409.
- User isolation: cross-user queries return empty results.
- Invalid credentials return HTTP 401.
- Search latency with live embedding and rerank is approximately 4-6 seconds.

## Not yet verified

- Platform-issued Eval Key and public Smoke.


- Official score.

Do not report planned model use or local tests as an official competition result.

## Next minimum task

Apply for an evaluation key, then run:

```bash
python scripts/ops_contract.py --base-url https://<app-id>.pandastack.ai --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url https://<app-id>.pandastack.ai --api-key "$AML_API_KEY" --container agentkiln-memory
```
