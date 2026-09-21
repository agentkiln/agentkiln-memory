# Evaluation Submission Draft

Complete the personal contact fields before submitting. Do not include secrets in this file.

## Recommended selections

- Evaluation type: textual retrieval
- Participant division: Open-source Methods
- System name: AgentKiln Memory
- Version: 1.0.0
- GitHub repository: add the public repository URL after publishing
- License: MIT

## Short method description

AgentKiln Memory is an evidence-only long-term memory service. It persists source messages under a strict `user_id` boundary, indexes them with SQLite FTS5 and deterministic lexical features, adds a vector retrieval channel with mock or configured embeddings, fuses candidates by reciprocal rank, expands adjacent source turns within the same session, and returns token-bounded verbatim evidence windows. Temporal intent scoring supports current and earliest questions without generating final answers. Add is synchronous and idempotent; Search never generates the final answer.

## Public endpoints

- Health: `GET https://your-domain.example/health`
- Add: `POST https://your-domain.example/add`
- Search: `POST https://your-domain.example/search`
- Authentication: Bearer token or `X-Api-Key` with the submitted system credential

## Deployment summary

- Docker image: `agentkiln-memory:1.0.0`
- Persistent path: `/data/memory.db`
- One Uvicorn worker; SQLite WAL and a 60-second busy timeout handle concurrent requests.
- Runtime model mode: `competition`
- LLM: `gpt-4o-mini`
- Embedding model: `text-embedding-v4`
- Search evidence budget: 8,000 tokens by default; 24 returned windows by default.
- In-process concurrency limits: Add 16, Search 32.
- Add returns only after the request is durably stored and immediately searchable.

## Capacity declaration

Preliminary local target for the public endpoint:

- Add concurrency: 24
- Search concurrency: 32
- Timeout: 90 seconds for upstream model calls
- Persistent volume: at least 10 GB
- Container baseline: 2 vCPU, 2 GB RAM

Run `scripts/ops_contract.py` and `scripts/recovery_check.py` against the deployed service, then replace this section with the measured results before applying.

## Required participant additions

- Full name
- Contact email
- Organization or team, or `Independent`
- Public repository URL
- Public display consent choices
- system credential delivery through the organizer's controlled request flow

## Compliance notes

- Search returns source evidence and never generates final answers.
- No benchmark answers or question-specific hard-coding are present.
- All memories are retrieved only through the exact submitted `user_id`.
- Evaluation data must be deleted within 30 days after the run unless the organizer approves another retention period.
