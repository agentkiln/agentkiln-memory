from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .db import MemoryRow
from .text import estimate_tokens


@dataclass(frozen=True)
class PackedWindow:
    source_id: str
    score: float
    content: str
    source_ids: tuple[str, ...]


def render_line(row: MemoryRow) -> str:
    if row.occurred_at is not None:
        timestamp = datetime.fromtimestamp(row.occurred_at / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return f"[{row.id} | {row.role} | {timestamp}] {row.content}"
    return f"[{row.id} | {row.role}] {row.content}"


def truncate_line(line: str, max_tokens: int) -> str:
    max_characters = max_tokens * 4
    if len(line) <= max_characters:
        return line
    return line[: max(0, max_characters - 3)].rstrip() + "..."


def pack_windows(
    ranked: list[tuple[float, MemoryRow, list[MemoryRow]]],
    top_k: int,
    max_tokens: int,
    max_items: int,
) -> list[PackedWindow]:
    output: list[PackedWindow] = []
    seen: set[str] = set()
    used = 0
    for score, anchor, context in ranked:
        if len(output) >= min(top_k, max_items):
            break
        lines: list[str] = []
        ids: list[str] = []
        ordered = sorted(context or [anchor], key=MemoryRow.source_order)
        for row in ordered:
            if row.id in seen:
                continue
            line = render_line(row)
            candidate = "\n".join(lines + [line])
            if used + estimate_tokens(candidate) > max_tokens:
                if not lines:
                    line = truncate_line(line, max(1, max_tokens - used))
                    if line and used + estimate_tokens(line) <= max_tokens:
                        lines.append(line)
                        ids.append(row.id)
                break
            lines.append(line)
            ids.append(row.id)
        if not lines:
            continue
        content = "\n".join(lines)
        used += estimate_tokens(content)
        output.append(PackedWindow(anchor.id, score, content, tuple(ids)))
        seen.update(ids)
    return output
