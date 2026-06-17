"""Pen-trace writer (drawing strokes). Behaviourally NDJSON; distinct encoding label."""
from __future__ import annotations

from .jsonl import JsonlWriter
from .base import register_writer


@register_writer("pentrace")
class PentraceWriter(JsonlWriter):
    """t,x,y,pressure,stroke_id per_sample rows — identical persistence to jsonl."""
