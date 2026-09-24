# Project State

Updated: 2026-09-24.

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
- `text-embedding-v4` calls split into batches of at most 10, with response indexes and dimensions checked before persistence.
- `qwen3.7-text-rerank` uses the native DashScope request and response format, with at most 500 rule-ranked documents per call; successful scores order non-temporal evidence, while earliest/latest queries retain time-aware ordering.
- Packed evidence IDs correspond to a source contained in the returned window.
- Long `text-embedding-v4` inputs and Add annotation requests are split into bounded model calls while source text stays complete in storage.
- PostgreSQL neighbor windows follow source chunk order, and legacy Chinese single-character fallback terms are preserved within the query bound.
- Oversized Chinese evidence is truncated to the configured output budget instead of being dropped.
- Deployment and operational checks are included.

## Verified locally

Command:

```bash
pytest -q
```

Result: the full local test suite passed using the existing Python environment.

Command:

```bash
python scripts/privacy_scan.py --root .
```

Result: privacy scan passed for all tracked files.

Command:

```bash
python scripts/local_verify.py --port 8123 --concurrency 24
```

Result: local end-to-end verification passed with 24 concurrent synchronous Add calls completing in about 0.34-0.38 seconds. Recent runs returned 12-13 evidence windows, with measured Search latency around 0.106-0.111 seconds in `dev_mock` mode.

## Verified on the prior PandaStack deployment

Public HTTPS deployment on PandaStack with Managed PostgreSQL has been verified:

- Health endpoint returns `status: ok`, `llm_mode: competition`, and `llm_ready: true`.
- Add successfully stores messages with real chat and embedding calls.
- Search successfully retrieves evidence with real embedding calls.
- Idempotent Add: identical `request_id` and payload return success without duplicate writes.
- Conflict detection: different payload with the same `request_id` returns HTTP 409.
- User isolation: cross-user queries return empty results.
- Invalid credentials return HTTP 401.
- Search latency with live embedding and rerank is approximately 4-6 seconds.

These checks predate the current code changes. The updated deployment has not been tested remotely.

## Not yet verified

- Platform-issued Eval Key and public Smoke.
- PandaStack deployment and remote verification of the current code changes.
- Docker image build and container restart verification on a machine with a running Docker daemon.
- Search latency and memory use against a PostgreSQL dataset at expected competition scale; the current vector path reads all of a user's vectors for similarity scoring.
- Official score.

Do not report planned model use or local tests as an official competition result.

## Next minimum task

Deploy the committed code, then apply for an evaluation key and run:

```bash
python scripts/ops_contract.py --base-url https://<app-id>.pandastack.ai --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url https://<app-id>.pandastack.ai --api-key "$AML_API_KEY" --container agentkiln-memory
```
