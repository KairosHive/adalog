"""DeviceAdapter ABC + adapter-facing types (spec §6.1, §6.6).

A device adapter owns acquisition for one device class. It DECLARES its output streams
(``StreamSpec`` from ``adalog.core``) and config (``adalog.schema`` Fields), and produces
data by calling ``ctx.emit(StreamPacket)``. It NEVER opens files or reads the wall clock —
the Core stamps + writes. Templates (``adalog.adapters.templates``) prefill the transport,
timing mode, and back-pressure regime so a concrete device is a few lines.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Optional

from ..core.spec import StreamSpec  # noqa: F401  (re-exported for adapter authors)
from ..schema.fields import ConfigSchema, bind

# AdapterStatus.state values
ST_STREAMING = "streaming"
ST_STALLED = "stalled"
ST_ERRORED_TRANSIENT = "errored_transient"
ST_ERRORED_FATAL = "errored_fatal"
ST_IDLE = "idle"
ST_PAUSED = "paused"


@dataclass
class AdapterInfo:
    id: str
    title: str
    category: str = ""
    multi: bool = False               # multiple instances allowed
    requires: Optional[str] = None    # e.g. "browser" (unavailable in goofi-mode)


@dataclass
class DiscoveredSource:
    id: str
    label: str
    detail: Optional[dict] = None


@dataclass
class AdapterStatus:
    state: str = ST_IDLE
    rate_est: Optional[float] = None      # observed samples/s (stall detection + dashboard)
    quality: Optional[dict] = None        # typed per-modality quality (e.g. {"hsi": [1,1,2,1]})
    last_error: Optional[str] = None


@dataclass
class ReconfigResult:
    applied: bool
    requires_segment: bool = False
    message: Optional[str] = None


class DeviceAdapter(ABC):
    """Base device-adapter contract. Subclass a template (preferred) or this directly."""

    info: AdapterInfo = AdapterInfo(id="base", title="Base adapter")
    version: str = "1.0.0"
    template_name: Optional[str] = None
    provenance: str = "host_arrival"   # clock provenance for this adapter's streams

    # ---- discovery (cheap, fast; lazy-import heavy libs INSIDE; never raises) ----
    @staticmethod
    def discover() -> list[DiscoveredSource]:
        return []

    # ---- declarative config (auto-generates UI) ----
    @staticmethod
    def config_schema() -> ConfigSchema:
        return {}

    # ---- output contract: static + runtime-resolved ----
    def declare_streams(self) -> list[StreamSpec]:
        return []

    def resolve_streams(self) -> list[StreamSpec]:
        """Called AFTER open(): fill in true channels/rates. Defaults to declare_streams()."""
        return self.declare_streams()

    # ---- lifecycle (run inside the supervised worker) ----
    def open(self, ctx) -> None:
        self.ctx = ctx
        self.cfg = bind(self.config_schema(), getattr(ctx, "config", {}) or {})

    def start(self) -> None:
        ...

    def pause(self) -> None:
        ...

    def resume(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def close(self) -> None:
        ...

    # ---- health / monitoring ----
    def status(self) -> AdapterStatus:
        return AdapterStatus(state=ST_STREAMING)

    # ---- hot-reconfigure ----
    def reconfigure(self, group: str, name: str, value) -> ReconfigResult:
        return ReconfigResult(applied=False, message="reconfigure not supported")
