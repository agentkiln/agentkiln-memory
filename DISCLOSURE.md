# Method and Integrity Disclosure

## Submission identity

- System: AgentKiln Memory
- Version: 1.0.0
- Track: Textual Memory
- Division: Open-source Methods
- Route: Participant-hosted Add/Search API

## Method summary

AgentKiln Memory was created for the 2026 Agent Memory Challenge. The service, tests, deployment files, evaluation contract checks, and documentation live together in this repository.

The implementation uses standard, publicly documented information-retrieval methods, including SQLite FTS5, BM25 ranking, Unicode normalization, Porter tokenization, CJK n-grams, cosine similarity, reciprocal rank fusion, source-order window expansion, temporal intent scoring, and token budgeting.

## Evaluation integrity

- Search returns source evidence, never generated final answers.
- The system contains no benchmark answers, dataset-specific answers, hard-coded question mappings, prompt injection, or human-in-the-loop answering path.
- All storage and retrieval is scoped to the exact `user_id` supplied by the evaluator.
- Add is synchronous and returns success only after persistence and indexing complete.
- Formal mode fails closed when required model credentials are absent.
- Runtime model use is explicit in environment configuration and never silently swaps models.

## AI-assisted development

OpenAI Codex was used as a software-engineering assistant to research the public interface contract, implement the repository, write tests, and prepare deployment documentation. Codex is not invoked during evaluation as a hidden human-in-the-loop participant.
