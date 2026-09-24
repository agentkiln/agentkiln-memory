# Evaluation Submission Draft

Complete the personal contact fields before submitting. Do not include secrets in this file.

## Recommended selections



- Participant division: Open-source Methods
- System name: AgentKiln Memory
- Version: 1.0.0
- GitHub repository: add the public repository URL after publishing
- License: MIT

## Short method description

AgentKiln Memory is an evidence-only long-term memory service. It persists source messages under a strict `user_id` boundary, indexes them with SQLite FTS5 and PostgreSQL GIN full-text search, adds a vector retrieval channel with configured embeddings, fuses candidates by reciprocal rank, expands adjacent source turns within the same session, and returns token-bounded source evidence windows. A source that exceeds the evidence budget is truncated in the response while its stored text stays complete. Temporal intent scoring supports latest and earliest questions without generating final answers. An optional external reranker can reorder candidates with automatic fallback to rule-based ranking. Add is synchronous and idempotent; Search never generates the final answer.

## Public endpoints

- Health: `GET https://your-domain.example/health`
- Add: `POST https://your-domain.example/add`
- Search: `POST https://your-domain.example/search`
- Authentication: Bearer token, `Token`, or `X-Api-Key`

## Deployment summary

- Managed PostgreSQL on PandaStack; the service creates its schema on startup.
- FastAPI with Uvicorn; SQLite WAL is used for local development only.
- Runtime model mode: `competition`
- LLM: `gpt-4o-mini` (via OpenAI-compatible endpoint)
- Embedding model: configured through `OPENAI_EMBEDDING_MODEL`
- Optional reranker: configured through `RERANK_MODEL`; falls back to rule-based ranking when unavailable
- Search evidence budget: approximately 32,000 tokens by default; at most 100 returned windows by default, subject to `top_k`.
- In-process concurrency limits: Add 16, Search 32.
- Add returns only after the request is durably stored and immediately searchable.
- Long Add messages are split for model calls while the original source is stored whole; larger requests may require multiple upstream calls.
- Long Search queries are accepted. Lexical retrieval selects terms across the full query and `text-embedding-v4` embeds every chunk; chat query analysis and reranking use a beginning-and-end excerpt of 16,000 characters by default, configurable with `AML_QUERY_MODEL_MAX_CHARS`.
- Production model endpoints require HTTPS, and malformed model vectors cannot be stored.

## Capacity declaration

Preliminary target for the public endpoint:

- Add concurrency: 16
- Search concurrency: 32
- Timeout: 90 seconds for upstream model calls
- Database: Managed PostgreSQL with auto-suspend; 4 GB instance (PandaStack clone-based resize)
- Container baseline: 8 vCPU burst, 4 GB RAM

Local tests and the `dev_mock` Add/Search contract pass; see `docs/STATE.md` for the latest local measurements. Replace this section with measured production results after running `scripts/ops_contract.py` and `scripts/recovery_check.py`.

## Required participant additions

- Full name
- Contact email
- Organization or team, or `Independent`
- Public repository URL
- Public display consent choices
- System credentials delivered through a controlled request flow
- Technical report: see `docs/TECHNICAL_REPORT.md`

## Compliance notes

- Search returns source evidence and never generates final answers.
- No benchmark answers or question-specific hard-coding are present.
- All memories are retrieved only through the exact submitted `user_id`.
- Evaluation data must be deleted after the run unless a longer retention period is agreed.
