from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import MemoryRow
from .text import CJK_RE, estimate_tokens


@dataclass(frozen=True)
class PackedWindow:
    source_id: str
    score: float
    content: str
    source_ids: tuple[str, ...]


def render_line(row: MemoryRow) -> str:
    if row.occurred_at is not None:
        try:
            timestamp = (
                datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(milliseconds=row.occurred_at)
            ).isoformat().replace("+00:00", "Z")
        except OverflowError:
            timestamp = f"{row.occurred_at}ms"
        return f"[{row.id} | {row.role} | {timestamp}] {row.content}"
    return f"[{row.id} | {row.role}] {row.content}"


def truncate_line(line: str, max_tokens: int) -> str:
    if estimate_tokens(line) <= max_tokens:
        return line
    cjk_count = 0
    other_count = 0
    prefix_length = 0
    for character in line:
        if CJK_RE.fullmatch(character):
            cjk_count += 1
        else:
            other_count += 1
        if cjk_count + (other_count + 6) // 4 > max_tokens:
            break
        prefix_length += 1
    return line[:prefix_length].rstrip() + "..."


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
        source_id = anchor.id if anchor.id in ids else ids[0]
        output.append(PackedWindow(source_id, score, content, tuple(ids)))
        seen.update(ids)
    return output
