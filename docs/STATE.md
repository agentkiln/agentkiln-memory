# Project State

Updated: 2026-09-21.

## Current status

The repository has a runnable FastAPI service with synchronous Add/Search, SQLite persistence, FTS5 lexical retrieval, mock embeddings, optional formal model calls, RRF fusion, source-window packing, strict user isolation, idempotent Add, and API-key authentication.

The repository also includes Docker deployment files, a Caddy HTTPS example, public contract checks, a restart recovery check, and submission/disclosure documents.

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
- Deployment and operational checks are included.

## Verified locally

Command:

```bash
pytest -q
```

Result: 61 tests passed using the existing local Python environment.

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

The local dependency install for a new virtual environment was blocked by network permissions during this session. The project itself did not require network access for the passing tests.

## Not yet verified

- Formal `gpt-4o-mini` and `text-embedding-v4` API calls.
- Public HTTPS deployment.
- Platform-issued Eval Key and public Smoke.
- Official Full evaluation.
- Official score.

Do not report planned model use or local tests as an official competition result.

## Next minimum task

Provide a public host, a system credential, and a runtime model credential, then deploy the frozen `1.0.0` image and run:

```bash
python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory
```
