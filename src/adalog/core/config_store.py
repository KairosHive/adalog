"""Persistent configuration (spec §8): app/session-default/per-device scopes + keyring secrets.

What persists across restarts: device configs, last-used device set, subject defaults, window
layout, sessions_root, theme. What does NOT: live session state, discovery results, status.
Secret fields are stored in the OS keyring (never plaintext in the JSON).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

try:
    import platformdirs
    _DEFAULT_DIR = Path(platformdirs.user_config_dir("adalog"))
except Exception:  # pragma: no cover
    _DEFAULT_DIR = Path.home() / ".config" / "adalog"

_SECRET_REF = "__keyring__"


class ConfigStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else (_DEFAULT_DIR / "config.json")
        self._data: dict[str, Any] = {"version": 1, "app": {}, "session_defaults": {}, "devices": {}}
        if self.path.exists():
            try:
                self._data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # ---- app scope ----
    def get_app(self, key: str, default=None):
        return self._data["app"].get(key, default)

    def set_app(self, key: str, value) -> None:
        self._data["app"][key] = value
        self._save()

    @property
    def sessions_root(self) -> Path:
        return Path(self._data["app"].get("sessions_root") or (Path.home() / "adalog-sessions"))

    # ---- session defaults ----
    def get_session_defaults(self) -> dict:
        return dict(self._data["session_defaults"])

    def set_session_defaults(self, **kw) -> None:
        self._data["session_defaults"].update(kw)
        self._save()

    # ---- per-device config (secrets routed to keyring) ----
    def get_device(self, adapter_id: str, instance_id: str = "0") -> dict:
        cfg = dict(self._data["devices"].get(f"{adapter_id}#{instance_id}", {}))
        for k, v in list(cfg.items()):
            if v == _SECRET_REF:
                cfg[k] = self._get_secret(adapter_id, k)
        return cfg

    def set_device(self, adapter_id: str, values: dict, *, instance_id: str = "0", secret_keys=()) -> None:
        stored = {}
        for k, v in values.items():
            if k in secret_keys:
                self._set_secret(adapter_id, k, v)
                stored[k] = _SECRET_REF
            else:
                stored[k] = v
        self._data["devices"][f"{adapter_id}#{instance_id}"] = stored
        self._save()

    def set_last_used_devices(self, device_ids: list[str]) -> None:
        self._data["app"]["last_used_devices"] = list(device_ids)
        self._save()

    def get_last_used_devices(self) -> list[str]:
        return list(self._data["app"].get("last_used_devices", []))

    # ---- secrets via keyring ----
    def _set_secret(self, adapter_id: str, key: str, value) -> None:
        try:
            import keyring
            keyring.set_password("adalog", f"{adapter_id}/{key}", str(value))
        except Exception:  # keyring unavailable -> treat as unset (never write plaintext)
            pass

    def _get_secret(self, adapter_id: str, key: str):
        try:
            import keyring
            return keyring.get_password("adalog", f"{adapter_id}/{key}")
        except Exception:
            return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
