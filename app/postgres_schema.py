from __future__ import annotations

import re


QUOTED_TERM_RE = re.compile(r'"((?:[^"]|"")*)"')
MAX_CJK_LIKE_TERMS = 12


def to_tsquery(query: str) -> str:
    """Convert an FTS5-style quoted OR query into a safe PostgreSQL tsquery."""
    terms: list[str] = []
    for match in QUOTED_TERM_RE.finditer(query):
        term = match.group(1).replace('""', '"').strip()
        cleaned = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", "", term)
        if not cleaned:
            continue
        terms.append(f"{cleaned}:*" if cleaned.isascii() else cleaned)
    if not terms:
        return ""
    return " | ".join(terms[:200])


def cjk_terms(query: str) -> list[str]:
    """Bound user-scoped LIKE fallbacks for CJK terms absent from older indexes."""
    terms: list[str] = []
    for match in QUOTED_TERM_RE.finditer(query):
        term = match.group(1).replace('""', '"').strip()
        cleaned = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", "", term)
        if cleaned and not cleaned.isascii() and cleaned not in terms:
            terms.append(cleaned)
    if not terms:
        return []

    multi_character = [term for term in terms if len(term) > 1]
    selected = [terms[0]] if len(terms[0]) == 1 else []
    selected.extend(term for term in multi_character if term not in selected)
    if not multi_character:
        selected.extend(term for term in terms if term not in selected)
    return selected[:MAX_CJK_LIKE_TERMS]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, request_id)
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    occurred_at BIGINT,
    created_at TEXT NOT NULL,
    search_text TEXT NOT NULL,
    UNIQUE (user_id, request_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_memories_user_time
    ON memories (user_id, occurred_at, ordinal);

CREATE INDEX IF NOT EXISTS idx_memories_fts
    ON memories USING GIN (
        to_tsvector('simple', coalesce(content, '') || ' ' || coalesce(search_text, ''))
    );

CREATE TABLE IF NOT EXISTS embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embeddings_user_model_dimensions
    ON embeddings (user_id, model, dimensions);

CREATE TABLE IF NOT EXISTS user_revisions (
    user_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL
);
"""
