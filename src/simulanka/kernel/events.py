from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from simulanka.layout.project import ProjectLayout

SEGMENT_MAX_BYTES = 1_048_576  # 1 MiB


class Event(BaseModel):
    id: str
    at: datetime
    actor: str
    kind: str
    base_graph_version: int
    graph_version: int
    note: str | None = None
    ops: list[dict[str, Any]]


def append_event(layout: ProjectLayout, event: Event) -> None:
    segment = _current_segment(layout)
    line = event.model_dump_json() + "\n"
    if segment.exists() and segment.stat().st_size + len(line.encode()) > SEGMENT_MAX_BYTES:
        segment = _next_segment(layout, segment)
    with segment.open("a", encoding="utf-8") as fh:
        fh.write(line)


def iter_events(layout: ProjectLayout) -> Iterator[Event]:
    for segment in sorted(layout.events_dir.glob("*.jsonl")):
        with segment.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    yield Event.model_validate_json(raw)


def _current_segment(layout: ProjectLayout) -> Path:
    segments = sorted(layout.events_dir.glob("*.jsonl"))
    return segments[-1] if segments else layout.events_dir / "0001.jsonl"


def _next_segment(layout: ProjectLayout, current: Path) -> Path:
    n = int(current.stem) + 1
    return layout.events_dir / f"{n:04d}.jsonl"
