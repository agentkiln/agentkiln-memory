from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator

from .schemas import AddRequest
from .text import lexical_terms


@dataclass(frozen=True)
class MemoryRow:
    id: str
    row_id: int
    user_id: str
    session_id: str
    request_id: str
    ordinal: int
    role: str
    content: str
    occurred_at: int | None
    created_at: str
    search_text: str
    fts_rank: float

    def source_order(self) -> tuple[int, int, int, int]:
        match = re.search(r"(?:^|[-_:])chunk[-_:]?(\d+)(?:$|[-_:])", self.request_id)
        chunk_index = int(match.group(1)) if match else 1_000_000_000
        timestamp = self.occurred_at if self.occurred_at is not None else 0
        return (timestamp, chunk_index, self.ordinal, self.row_id)


class MemoryDatabase:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

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
                    occurred_at INTEGER,
                    created_at TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    UNIQUE(user_id, request_id, ordinal)
                );

                CREATE INDEX IF NOT EXISTS idx_memories_user_time
                    ON memories(user_id, occurred_at, ordinal);

                CREATE TABLE IF NOT EXISTS embeddings (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memories(id)
                );

                CREATE INDEX IF NOT EXISTS idx_embeddings_user
                    ON embeddings(user_id);

                CREATE INDEX IF NOT EXISTS idx_embeddings_user_model_dimensions
                    ON embeddings(user_id, model, dimensions);

                CREATE TABLE IF NOT EXISTS user_revisions (
                    user_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id UNINDEXED,
                    user_id UNINDEXED,
                    content,
                    search_text,
                    tokenize='porter unicode61 remove_diacritics 2'
                );
                """
            )
            indexed = connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
            stored = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
            if indexed == 0 and stored:
                connection.execute(
                    "INSERT INTO memory_fts(id, user_id, content, search_text) "
                    "SELECT id, user_id, content, search_text FROM memories"
                )

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
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT session_id, payload_hash FROM requests WHERE user_id = ? AND request_id = ?",
                (request.user_id, request.request_id),
            ).fetchone()
            if existing:
                if (
                    existing["session_id"] != request.session_id
                    or existing["payload_hash"] != request.payload_hash()
                ):
                    raise ValueError("request_id was already used with a different payload")
                connection.execute("COMMIT")
                return
            connection.execute(
                "INSERT INTO requests(user_id, request_id, session_id, payload_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    request.user_id,
                    request.request_id,
                    request.session_id,
                    request.payload_hash(),
                    created_at,
                ),
            )
            for ordinal, message in enumerate(request.messages):
                digest = hashlib.sha256(
                    f"{request.user_id}:{request.request_id}:{ordinal}".encode("utf-8")
                ).hexdigest()[:24]
                memory_id = f"mem_{digest}"
                search_text = " ".join(
                    lexical_terms(f"{message.content}\n{annotations[ordinal]}", limit=384)
                )
                connection.execute(
                    """
                    INSERT INTO memories(
                        id, user_id, session_id, request_id, ordinal, role, content,
                        occurred_at, created_at, search_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                connection.execute(
                    "INSERT INTO memory_fts(id, user_id, content, search_text) VALUES (?, ?, ?, ?)",
                    (memory_id, request.user_id, message.content, search_text),
                )
                vector = embeddings[ordinal]
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise ValueError("embedding vectors must be finite and non-empty")
                connection.execute(
                    "INSERT INTO embeddings(memory_id, user_id, model, dimensions, vector_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        memory_id,
                        request.user_id,
                        embedding_model,
                        len(vector),
                        json.dumps(vector, separators=(",", ":")),
                    ),
                )
            connection.execute(
                "INSERT INTO user_revisions(user_id, revision) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1",
                (request.user_id,),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def request_status(self, request: AddRequest) -> str:
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT session_id, payload_hash FROM requests WHERE user_id = ? AND request_id = ?",
                (request.user_id, request.request_id),
            ).fetchone()
        if existing is None:
            return "new"
        if existing["session_id"] != request.session_id or existing["payload_hash"] != request.payload_hash():
            return "conflict"
        return "existing"

    def lexical_search(self, user_id: str, query: str, limit: int) -> list[MemoryRow]:
        if not query:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.rowid AS row_id, m.user_id, m.session_id, m.request_id,
                       m.ordinal, m.role, m.content, m.occurred_at, m.created_at,
                       m.search_text, bm25(memory_fts, 0.0, 0.0, 1.0, 2.0) AS fts_rank
                FROM memory_fts
                JOIN memories AS m ON m.id = memory_fts.id
                WHERE memory_fts MATCH ? AND memory_fts.user_id = ?
                ORDER BY fts_rank ASC
                LIMIT ?
                """,
                (query, user_id, limit),
            ).fetchall()
        return [MemoryRow(**dict(row)) for row in rows]

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
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.rowid AS row_id, m.user_id, m.session_id, m.request_id,
                       m.ordinal, m.role, m.content, m.occurred_at, m.created_at,
                       m.search_text, 1000.0 AS fts_rank, e.vector_json
                FROM embeddings AS e
                JOIN memories AS m ON m.id = e.memory_id
                WHERE e.user_id = ? AND e.model = ? AND e.dimensions = ?
                """,
                (user_id, model, len(query_vector)),
            ).fetchall()
        scored: list[tuple[float, MemoryRow]] = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            denominator = query_norm * math.sqrt(sum(value * value for value in vector))
            if denominator == 0:
                continue
            similarity = sum(left * right for left, right in zip(query_vector, vector)) / denominator
            if similarity < minimum_similarity:
                continue
            memory = MemoryRow(**{key: row[key] for key in row.keys() if key != "vector_json"})
            scored.append((similarity, memory))
        scored.sort(key=lambda item: (item[0], item[1].occurred_at or 0), reverse=True)
        return [row for _score, row in scored[:limit]]

    def recent(self, user_id: str, limit: int) -> list[MemoryRow]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, rowid AS row_id, user_id, session_id, request_id, ordinal, role,
                       content, occurred_at, created_at, search_text, 1000.0 AS fts_rank
                FROM memories
                WHERE user_id = ?
                ORDER BY COALESCE(occurred_at, 0) DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [MemoryRow(**dict(row)) for row in rows]

    def neighbors(self, user_id: str, seed_ids: list[str], radius: int = 1) -> list[tuple[MemoryRow, int, int]]:
        if not seed_ids or radius < 1:
            return []
        placeholders = ",".join("?" for _ in seed_ids)
        with self._connection() as connection:
            seeds = connection.execute(
                f"SELECT id, session_id FROM memories WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *seed_ids),
            ).fetchall()
            session_ids = sorted({row["session_id"] for row in seeds})
            if not session_ids:
                return []
            session_placeholders = ",".join("?" for _ in session_ids)
            rows = connection.execute(
                f"""
                SELECT id, rowid AS row_id, user_id, session_id, request_id, ordinal, role,
                       content, occurred_at, created_at, search_text, 1000.0 AS fts_rank
                FROM memories
                WHERE user_id = ? AND session_id IN ({session_placeholders})
                ORDER BY session_id, COALESCE(occurred_at, 0), ordinal, rowid
                """,
                (user_id, *session_ids),
            ).fetchall()
        by_session: dict[str, list[MemoryRow]] = {}
        for row in rows:
            memory = MemoryRow(**dict(row))
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
        with self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM user_revisions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["revision"]) if row else 0
