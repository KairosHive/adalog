"""Free-form text capture (browser UiSource): per-word onset times."""
from __future__ import annotations

from ...adapters.base import AdapterInfo
from ...adapters.templates import UiSourceDevice
from ...core.spec import ENC_JSONL, TIMING_PER_SAMPLE, StreamSpec


class TextAdapter(UiSourceDevice):
    info = AdapterInfo(id="text", title="Text", category="human", requires="browser", multi=True)

    def declare_streams(self):
        return [StreamSpec(id="text", modality="text", encoding=ENC_JSONL, timing_mode=TIMING_PER_SAMPLE)]

    def handle_item(self, item: dict) -> int:
        if item.get("kind") == "word":
            word = item.get("word")
            if not word:
                return 0
            return self.emit_record("text", {"word": word}, item.get("t_browser_ns"))
        return 0
