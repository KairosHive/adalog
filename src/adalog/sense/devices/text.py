"""Free-form text capture (browser UiSource): per-word onset times + a final-text dump.

Two streams reproduce the old Text panel: ``text`` is the lossless per-word onset log (what
EEG↔text alignment needs); ``text_full`` receives the complete editor contents once on stop,
the analog of the old ``text_final.txt`` dump."""
from __future__ import annotations

from ...adapters.base import AdapterInfo
from ...adapters.templates import UiSourceDevice
from ...core.spec import ENC_JSONL, TIMING_EVENT, TIMING_PER_SAMPLE, StreamSpec


class TextAdapter(UiSourceDevice):
    info = AdapterInfo(id="text", title="Text", category="human", requires="browser", multi=True)

    def declare_streams(self):
        return [StreamSpec(id="text", modality="text", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE),
                StreamSpec(id="text_full", modality="text", encoding=ENC_JSONL, timing_mode=TIMING_EVENT)]

    def handle_item(self, item: dict) -> int:
        kind = item.get("kind")
        if kind == "word":
            word = item.get("word")
            if not word:
                return 0
            return self.emit_record("text", {"word": word}, item.get("t_browser_ns"))
        if kind == "final":
            text = item.get("text")
            if not text:
                return 0
            return self.emit_record("text_full", {"text": text}, item.get("t_browser_ns"))
        return 0
