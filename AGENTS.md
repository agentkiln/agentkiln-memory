# AGENTS.md

This file is the entry point for AI Agents working on AgentKiln Memory. README.md targets human readers with project purpose and quick start; this file defines constraints, command entry points, and the verification loop. Prefer code and docs under `docs/` for details; do not duplicate them here.

## Project Positioning

AgentKiln Memory targets the textual retrieval track of the an open retrieval evaluation and implements the participant-hosted synchronous `Add` and `Search` interfaces. Search returns memory evidence only; it never generates final answers.

Technology stack and structure:

- Python 3.10+, FastAPI, Pydantic, SQLite FTS5, PostgreSQL, Uvicorn.
- `app/`: interface models, configuration, storage backends, retrieval, evidence packing, and service entry point.
- `eval/`: offline retrieval metrics and JSONL evaluation entry.
- `scripts/`: local verification, public contract checks, recovery checks, release checks, and privacy scanning.
- `tests/`: interface contracts, isolation, persistence, concurrency, temporal retrieval, and tooling.
- `deploy/`: public HTTPS reverse proxy examples, PandaStack deployment guide, and deployment notes.
- `docs/`: build status, project state, technical report, and submission materials.

## Must Follow

- All memories, lexical indexes, vector candidates, neighbor windows, and caches must be isolated by the exact `user_id`.
- Add must complete persistence and indexing before returning success, so records are immediately searchable.
- The same `request_id` with the same payload must be idempotent; the same `request_id` with a different payload must return a conflict.
- Search `data` must be ordered by relevance and must not exceed `top_k`.
- Do not commit keys, `.env`, databases, evaluation private data, logs, or credential files to the repository.
- Production deployment uses `AML_PRODUCTION=1`, `AML_LLM_MODE=competition`, and a randomly generated `AML_API_KEY`.
- Runtime models follow the current competition contract; never silently degrade in `competition` mode when credentials are missing.
- Only real executed steps may be recorded as verification results; never imply an official ranking without one.
- Interface behavior changes must update tests, README examples, and submission materials together.
- After fixing a production issue, add a test that reproduces it before committing the fix.

## Commit Rules

- Git committer name is `chronicle`; email uses the project maintainer address; do not add other author information.
- Commit messages use `type: short description` with types limited to `feat`, `fix`, `test`, `docs`, `chore`, `security`, `perf`, `refactor`.
- Descriptions use lowercase English short sentences describing the behavior change; avoid empty descriptions such as `update code`.
- One commit handles one type of change. Do not mix bug fixes, features, documentation, and dependency updates in one commit.
- Bug fixes should add a failing test first, then the fix, then confirm tests pass.
- Before committing, run `pytest -q` and `python scripts/privacy_scan.py --root .`.
- Before committing, check `git status --short` to ensure no databases, logs, keys, `.env`, temporary data, or `del/` content is staged.
- After formal evaluation freezes, do not rewrite interface behavior for that version; new experiments use new commits with independent deployment verification.
- Security fixes use `security:` prefix; performance optimizations use `perf:` prefix.
- Split multi-purpose commits rather than mixing features, fixes, documentation, and dependency changes.

## Engineering Conventions

| Goal | Command |
|---|---|
| Unit tests | `python -m pytest -q` |
| Privacy scan | `python scripts/privacy_scan.py --root .` |
| Local end-to-end | `python scripts/local_verify.py --port 8123 --concurrency 24` |
| Public contract | `python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"` |
| Restart recovery | `python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory` |
| Release check | `python scripts/release_check.py --repository-url ... --add-url ... --search-url ... --health-url ...` |

## Verification Loop

After code changes, follow this order; do not stop at code editing.

1. Run the tests closest to the change first.
2. Run `python -m pytest -q` and `python scripts/privacy_scan.py --root .`.
3. For service startup or interface behavior changes, run `python scripts/local_verify.py`.
4. For public deployment changes, run `scripts/ops_contract.py` and `scripts/recovery_check.py`.
5. For commit or frozen-version changes, run `scripts/release_check.py`.

Rules that only live in documentation can be violated under pressure. Add script-checkable rules to `scripts/privacy_scan.py`, `scripts/release_check.py`, or `tests/`.

## Documentation Map

- `README.md`: interface examples, run instructions, configuration, and deployment entry.
- `README.zh-CN.md`: Chinese version of the README.
- `docs/BUILD_STATUS.md`: completed items, open items, and external blockers.
- `docs/STATE.md`: latest verification record and next task.
- `docs/TECHNICAL_REPORT.md`: design decisions, architecture, retrieval pipeline, integrity guarantees, and limitations.
- `SUBMISSION.md`: evaluation submission draft.
- `DISCLOSURE.md`: method and integrity disclosure.
- `SECURITY.md`: key handling and evaluation data deletion requirements.
- `deploy/README.md`: public deployment, HTTPS, and contract check steps.
- `deploy/PandaStack.md`: PandaStack Apps with Managed PostgreSQL deployment.

Retired project files move into `del/`; do not delete them directly. Real test temporary files are cleaned by the test framework.

## Rule Maintenance

AGENTS.md is not a write-once document. Each time an AI makes a mistake that affects interface behavior, isolation, security, or verification results, decide where the rule belongs:

- Hard rules whose violation produces incorrect code go into this file.
- Module-specific development details go into the corresponding `docs/` file or code comments.
- Script-checkable rules go directly into automated checks.
