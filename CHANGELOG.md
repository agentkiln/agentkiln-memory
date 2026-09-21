# Changelog

## 1.1.0

- Added the optional reranker with `RERANK_MODEL`, `RERANK_BASE_URL`, and `RERANK_API_KEY`; rerank failures fall back to rule-based ranking.
- Added the PostgreSQL backend with GIN full-text indexes and CJK substring search.
- Added the PandaStack deployment guide with Managed PostgreSQL.
- Added the technical report, centered logo, English and Chinese README, CI and deployment badges.
- Removed the invalid job-level `secrets` condition from the deploy workflow.

## 1.0.0 - initial release

- Added the FastAPI Add/Search service.
- Added SQLite persistence, FTS5 retrieval, vector storage, RRF fusion, and source-window packing.
- Added strict user isolation, request idempotency, payload conflict detection, and API-key auth.
- Added Docker, Compose, Caddy, contract-check, smoke, and recovery deployment assets.
- Added public submission, disclosure, and security documents.
