from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

from .db import MemoryRow
from .schemas import AddRequest
from .text import lexical_terms


QUOTED_TERM_RE = re.compile(r'"((?:[^"]|"")*)"')


def to_tsquery(query: str) -> str:
    """Convert an FTS5-style quoted OR query into a safe PostgreSQL tsquery."""
    terms: list[str] = []
    for match in QUOTED_TERM_RE.finditer(query):
        term = match.group(1).replace('""', '"').strip()
        cleaned = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", "", term)
        if not cleaned:
            continue
        if cleaned.isascii():
            terms.append(f"{cleaned}:*")
        else:
            terms.append(cleaned)
    if not terms:
        return ""
    return " | ".join(terms[:200])


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


class PostgresMemoryDatabase:
    backend_name = "postgres"

    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError(
                "psycopg is required for PostgreSQL deployment; install psycopg[binary]"
            ) from exc
        return psycopg.connect(self.database_url)

    def initialize(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA_SQL)

    def request_status(self, request: AddRequest) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT session_id, payload_hash FROM requests "
                    "WHERE user_id = %s AND request_id = %s",
                    (request.user_id, request.request_id),
                )
                existing = cursor.fetchone()
        if existing is None:
            return "new"
        if existing[0] != request.session_id or existing[1] != request.payload_hash():
            return "conflict"
        return "existing"

    def add(
        self,
        request: AddRequest,
        annotations: list[str],
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(annotations) != len(request.messages) or len(embeddings) != len(request.messages):
            raise ValueError("annotations and embeddings must match message count")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT session_id, payload_hash FROM requests "
                    "WHERE user_id = %s AND request_id = %s FOR UPDATE",
                    (request.user_id, request.request_id),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if existing[0] != request.session_id or existing[1] != request.payload_hash():
                        raise ValueError("request_id was already used with a different payload")
                    return
                cursor.execute(
                    "INSERT INTO requests (user_id, request_id, session_id, payload_hash, created_at) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, request_id) DO NOTHING",
                    (
                        request.user_id,
                        request.request_id,
                        request.session_id,
                        request.payload_hash(),
                        created_at,
                    ),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "SELECT session_id, payload_hash FROM requests "
                        "WHERE user_id = %s AND request_id = %s",
                        (request.user_id, request.request_id),
                    )
                    concurrent = cursor.fetchone()
                    if concurrent is None:
                        raise RuntimeError("request row disappeared during concurrent add")
                    if (
                        concurrent[0] != request.session_id
                        or concurrent[1] != request.payload_hash()
                    ):
                        raise ValueError("request_id was already used with a different payload")
                    return
                for ordinal, message in enumerate(request.messages):
                    vector = embeddings[ordinal]
                    if not vector or not all(math.isfinite(value) for value in vector):
                        raise ValueError("embedding vectors must be finite and non-empty")
                    digest = hashlib.sha256(
                        f"{request.user_id}:{request.request_id}:{ordinal}".encode("utf-8")
                    ).hexdigest()[:24]
                    memory_id = f"mem_{digest}"
                    search_text = " ".join(
                        lexical_terms(f"{message.content}\n{annotations[ordinal]}", limit=384)
                    )
                    cursor.execute(
                        """
                        INSERT INTO memories (
                            id, user_id, session_id, request_id, ordinal, role, content,
                            occurred_at, created_at, search_text
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            memory_id,
                            request.user_id,
                            request.session_id,
                            request.request_id,
                            ordinal,
                            message.role,
                            message.content,
                            message.timestamp,
                            created_at,
                            search_text,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO embeddings (memory_id, user_id, model, dimensions, vector_json) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            memory_id,
                            request.user_id,
                            embedding_model,
                            len(vector),
                            json.dumps(vector, separators=(",", ":")),
                        ),
                    )
                cursor.execute(
                    "INSERT INTO user_revisions (user_id, revision) VALUES (%s, 1) "
                    "ON CONFLICT (user_id) DO UPDATE "
                    "SET revision = user_revisions.revision + 1",
                    (request.user_id,),
                )

    @staticmethod
    def _memory_row(raw: tuple) -> MemoryRow:
        return MemoryRow(
            id=raw[0],
            row_id=int(raw[1]),
            user_id=raw[2],
            session_id=raw[3],
            request_id=raw[4],
            ordinal=int(raw[5]),
            role=raw[6],
            content=raw[7],
            occurred_at=raw[8],
            created_at=raw[9],
            search_text=raw[10],
            fts_rank=float(raw[11]) if raw[11] is not None else 1_000.0,
        )

    def lexical_search(self, user_id: str, query: str, limit: int) -> list[MemoryRow]:
        tsquery = to_tsquery(query)
        if not tsquery:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.id, m.user_id, m.session_id, m.request_id, m.ordinal,
                           m.role, m.content, m.occurred_at, m.created_at, m.search_text,
                           ts_rank(
                               to_tsvector('simple', coalesce(m.content, '') || ' ' || coalesce(m.search_text, '')),
                               to_tsquery('simple', %s)
                           ) AS rank
                    FROM memories AS m
                    WHERE m.user_id = %s
                      AND to_tsvector('simple', coalesce(m.content, '') || ' ' || coalesce(m.search_text, ''))
                          @@ to_tsquery('simple', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (tsquery, user_id, tsquery, limit),
                )
                rows = cursor.fetchall()
        return [
            self._memory_row((row[0], 0, row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10]))
            for row in rows
        ]

    def vector_search(
        self,
        user_id: str,
        query_vector: list[float],
        limit: int,
        model: str,
        minimum_similarity: float = 0.0,
    ) -> list[MemoryRow]:
        if not query_vector:
            return []
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.id, m.user_id, m.session_id, m.request_id, m.ordinal,
                           m.role, m.content, m.occurred_at, m.created_at, m.search_text,
                           e.vector_json
                    FROM embeddings AS e
                    JOIN memories AS m ON m.id = e.memory_id
                    WHERE e.user_id = %s AND e.model = %s AND e.dimensions = %s
                    """,
                    (user_id, model, len(query_vector)),
                )
                rows = cursor.fetchall()
        scored: list[tuple[float, MemoryRow]] = []
        for row in rows:
            vector = json.loads(row[10])
            denominator = query_norm * math.sqrt(sum(value * value for value in vector))
            if denominator == 0:
                continue
            similarity = sum(left * right for left, right in zip(query_vector, vector)) / denominator
            if similarity < minimum_similarity:
                continue
            memory = MemoryRow(
                id=row[0],
                row_id=0,
                user_id=row[1],
                session_id=row[2],
                request_id=row[3],
                ordinal=int(row[4]),
                role=row[5],
                content=row[6],
                occurred_at=row[7],
                created_at=row[8],
                search_text=row[9],
                fts_rank=1_000.0,
            )
            scored.append((similarity, memory))
        scored.sort(key=lambda item: (item[0], item[1].occurred_at or 0), reverse=True)
        return [row for _score, row in scored[:limit]]

    def neighbors(self, user_id: str, seed_ids: list[str], radius: int = 1) -> list[tuple[MemoryRow, int, int]]:
        if not seed_ids or radius < 1:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT session_id FROM memories WHERE user_id = %s AND id = ANY(%s)",
                    (user_id, list(seed_ids)),
                )
                session_ids = sorted(row[0] for row in cursor.fetchall())
                if not session_ids:
                    return []
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, request_id, ordinal, role,
                           content, occurred_at, created_at, search_text
                    FROM memories
                    WHERE user_id = %s AND session_id = ANY(%s)
                    ORDER BY session_id, occurred_at NULLS FIRST, ordinal, id
                    """,
                    (user_id, session_ids),
                )
                rows = cursor.fetchall()
        by_session: dict[str, list[MemoryRow]] = {}
        for row in rows:
            memory = MemoryRow(
                id=row[0],
                row_id=0,
                user_id=row[1],
                session_id=row[2],
                request_id=row[3],
                ordinal=int(row[4]),
                role=row[5],
                content=row[6],
                occurred_at=row[7],
                created_at=row[8],
                search_text=row[9],
                fts_rank=1_000.0,
            )
            by_session.setdefault(memory.session_id, []).append(memory)
        positions = {
            row.id: (session_id, index)
            for session_id, session_rows in by_session.items()
            for index, row in enumerate(session_rows)
        }
        output: dict[str, tuple[MemoryRow, int, int]] = {}
        for seed_rank, seed_id in enumerate(seed_ids):
            location = positions.get(seed_id)
            if not location:
                continue
            session_id, seed_index = location
            session_rows = by_session[session_id]
            start = max(0, seed_index - radius)
            stop = min(len(session_rows), seed_index + radius + 1)
            for index in range(start, stop):
                distance = abs(index - seed_index)
                row = session_rows[index]
                current = output.get(row.id)
                candidate = (row, distance, seed_rank)
                if current is None or (distance, seed_rank) < (current[1], current[2]):
                    output[row.id] = candidate
        return list(output.values())

    def revision(self, user_id: str) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision FROM user_revisions WHERE user_id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
        return int(row[0]) if row else 0
