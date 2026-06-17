"""AdapterContext — the adapter's only handle to the host.

Exposes a thread-safe / callback-safe ``emit`` (must be callable from a realtime callback
thread), a monotonic clock read for stamping device time when an adapter has no native clock,
runtime ``register_stream`` for dynamic-schema adapters (OSC), config, and a logger. Adapters
never see disk, the manifest, or which host (standalone vs goofi) they run in.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..core.envelope import StreamPacket
from ..core.spec import StreamSpec


class AdapterContext:
    def __init__(self, *, emit_fn: Callable[[StreamPacket], None], now_mono_ns: Callable[[], int],
                 register_fn: Optional[Callable[[StreamSpec], None]] = None,
                 config: Optional[dict] = None, logger: Optional[logging.Logger] = None,
                 instance_id: str = "0"):
        self._emit_fn = emit_fn
        self._now = now_mono_ns
        self._register_fn = register_fn
        self.config = config or {}
        self.instance_id = instance_id
        self.log = logger or logging.getLogger(f"adalog.adapter.{instance_id}")

    def emit(self, packet: StreamPacket) -> None:
        """Hand a packet to the Core. Thread-safe; safe from realtime callback threads."""
        self._emit_fn(packet)

    def now_mono_ns(self) -> int:
        return self._now()

    def register_stream(self, spec: StreamSpec) -> None:
        """Register a stream discovered at runtime (dynamic-schema adapters, e.g. OSC)."""
        if self._register_fn is None:
            raise RuntimeError("dynamic register_stream not supported by this host")
        self._register_fn(spec)
