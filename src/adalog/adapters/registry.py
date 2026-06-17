"""Adapter registry + entry-point discovery (spec §6.4).

Built-in device adapters live in the app layer (``adalog.sense.devices``); this generic
registry merges them with out-of-tree adapters advertised under the ``adalog.adapters``
entry-point group. A broken third-party entry-point is skipped (logged), never fatal.

Security stance (honest): out-of-tree adapters are trusted code running with the user's
privileges. ``config_schema()`` runs at catalog time. We surface a clear notice; capability
declarations are informational only — a subprocess is not a sandbox.
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable, Optional

from .base import DeviceAdapter

log = logging.getLogger("adalog.adapters.registry")

ENTRYPOINT_GROUP = "adalog.adapters"


def entrypoint_adapters(group: str = ENTRYPOINT_GROUP,
                        entry_points_fn: Optional[Callable[..., Iterable]] = None) -> list[type]:
    """Load adapter classes advertised under ``group``. Each load is isolated; failures skip."""
    if entry_points_fn is None:
        from importlib.metadata import entry_points as entry_points_fn  # py3.10+
    try:
        eps = entry_points_fn(group=group)
    except TypeError:  # pragma: no cover - older selection API
        eps = entry_points_fn().get(group, [])
    out: list[type] = []
    for ep in eps:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, DeviceAdapter):
                out.append(cls)
            else:
                log.warning("entry-point %r is not a DeviceAdapter subclass; skipping", getattr(ep, "name", ep))
        except Exception as exc:  # third-party breakage must never be fatal
            log.warning("failed to load adapter entry-point %r: %r", getattr(ep, "name", ep), exc)
    return out


class AdapterRegistry:
    """Holds adapter classes keyed by ``info.id``; supports catalog projection for the UI."""

    def __init__(self):
        self._by_id: dict[str, type] = {}

    def register(self, cls: type) -> None:
        if not (isinstance(cls, type) and issubclass(cls, DeviceAdapter)):
            raise TypeError(f"{cls!r} is not a DeviceAdapter subclass")
        self._by_id[cls.info.id] = cls

    def register_all(self, classes: Iterable[type]) -> None:
        for cls in classes:
            try:
                self.register(cls)
            except TypeError as exc:
                log.warning("skip %r: %r", cls, exc)

    def get(self, adapter_id: str) -> type:
        return self._by_id[adapter_id]

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def catalog(self) -> list[dict]:
        """Project adapters to JSON for the add-device palette (info + config schema)."""
        from ..schema.fields import to_jsonschema
        out = []
        for cls in self._by_id.values():
            out.append({
                "id": cls.info.id, "title": cls.info.title, "category": cls.info.category,
                "multi": cls.info.multi, "requires": cls.info.requires,
                "config_schema": to_jsonschema(cls.config_schema()),
            })
        return out

    @classmethod
    def build(cls, builtin: Iterable[type] = (), *, include_entrypoints: bool = True,
              entry_points_fn=None) -> "AdapterRegistry":
        reg = cls()
        reg.register_all(builtin)
        if include_entrypoints:
            reg.register_all(entrypoint_adapters(entry_points_fn=entry_points_fn))
        return reg
