# Project State

Updated: 2026-09-25.

## Current status

The repository has a runnable FastAPI service with synchronous Add/Search, SQLite and PostgreSQL persistence, FTS5 and GIN lexical retrieval, configured embeddings, optional rerank with fallback, RRF fusion, source-window packing, strict user isolation, idempotent Add, and API-key authentication.

The repository also includes Docker deployment files, a Caddy HTTPS example, PandaStack deployment guide, public contract checks, a restart recovery check, and submission/disclosure documents.

## What is complete

- AgentKiln Memory is implemented in this repository.
- Public Add/Search contract implemented under both short paths and `/v1/memory/*` aliases.
- Health endpoint returns `status`, version, mode, and model readiness.
- Add validates required fields and rejects unsupported extra fields.
- Search caps `top_k` at 100 and returns a `data` array.
- Indexed `request_id` and `user_id` values are capped at 512 characters to limit PostgreSQL index key size. Add has no application-level `session_id` length or message-count maximum; Search accepts long queries and options without application-level length or count maximums.
- Long Search queries contribute terms from across the full text to lexical retrieval and use chunked `text-embedding-v4` embedding; chat analysis and reranking use a configurable beginning-and-end excerpt (16,000 characters by default).
- Explicit event-day questions also retrieve messages whose `timestamp` falls in that UTC day, using the existing per-user time index. Date-named entities, due dates, and deadlines do not trigger this lookup; if the day has no timestamped source, ordinary reranking remains available.
- Related newer corrections may suppress an older single fact; independent facts in an older source remain available when the query needs them.
- Explicit whole-history summaries may select similarly relevant evidence from different sessions while keeping the top result and relevance order. Search still returns source evidence rather than a final answer.
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
- PostgreSQL neighbor windows follow source chunk order, and legacy Chinese single-character fallback terms remain searchable in long queries.
- Oversized Chinese evidence is truncated to the configured output budget instead of being dropped.
- Deployment and operational checks are included.

## Current local verification

On 2026-09-25, the full `python -m pytest -q` suite and `python scripts/privacy_scan.py --root .` passed after the Search changes. `python scripts/local_verify.py --port 8123 --concurrency 24` passed in `dev_mock` mode: 24 Add calls completed in 0.289 seconds, Search returned 12 evidence windows in 0.110 seconds, and `/health` reported version 1.0.0. These measurements do not represent PandaStack or official evaluation performance.

## Earlier local verification

The measurements below predate the current Search changes and do not verify the updated implementation.

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
- A PandaStack deploy attempt failed during sandbox provisioning with `429 workspace resource quota exceeded`: 8 GiB committed of 10 GiB, with another 4 GiB requested. Free at least 2 GiB of committed memory before retrying; the App sandbox itself remains fixed at 4 GiB.
- Docker image build and container restart verification on a machine with a running Docker daemon.
- Search latency and memory use against a PostgreSQL dataset at expected competition scale; the current vector path reads all of a user's vectors for similarity scoring.
- Official score for the current revision.

Do not report planned model use or local tests as an official competition result.

## Next minimum task

Deploy the committed code, then apply for an evaluation key and run:

```bash
python scripts/ops_contract.py --base-url https://<app-id>.pandastack.ai --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url https://<app-id>.pandastack.ai --api-key "$AML_API_KEY" --container agentkiln-memory
```
