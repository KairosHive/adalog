"""Declarative config Fields (spec §6.1) — the goofi-free analog of goofi's Param system.

A device adapter declares ``config_schema() -> {group: {name: Field}}``. The host turns it
into an auto-generated UI (via ``to_jsonschema``) and binds user values into ``self.cfg`` so
authors read ``self.cfg.<group>.<field>``. Secret fields are routed to the keyring by the
config store (never serialized in plaintext).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional


class Field:
    kind = "string"

    def __init__(self, default: Any = None, *, doc: str = ""):
        self.default = default
        self.doc = doc

    def to_jsonschema(self) -> dict:
        return {"type": self.kind, "default": self.default, "doc": self.doc}

    def coerce(self, value: Any) -> Any:
        return value


class StrField(Field):
    kind = "string"

    def coerce(self, value):
        return "" if value is None else str(value)


class IntField(Field):
    kind = "integer"

    def __init__(self, default=0, *, min: Optional[int] = None, max: Optional[int] = None, doc: str = ""):
        super().__init__(default, doc=doc)
        self.min, self.max = min, max

    def to_jsonschema(self):
        d = super().to_jsonschema()
        if self.min is not None:
            d["minimum"] = self.min
        if self.max is not None:
            d["maximum"] = self.max
        return d

    def coerce(self, value):
        return int(value)


class FloatField(Field):
    kind = "number"

    def __init__(self, default=0.0, *, min: Optional[float] = None, max: Optional[float] = None, doc: str = ""):
        super().__init__(default, doc=doc)
        self.min, self.max = min, max

    def to_jsonschema(self):
        d = super().to_jsonschema()
        if self.min is not None:
            d["minimum"] = self.min
        if self.max is not None:
            d["maximum"] = self.max
        return d

    def coerce(self, value):
        return float(value)


class BoolField(Field):
    kind = "boolean"

    def coerce(self, value):
        return bool(value)


class EnumField(Field):
    kind = "string"

    def __init__(self, default=None, *, options: list, doc: str = ""):
        super().__init__(default if default is not None else (options[0] if options else None), doc=doc)
        self.options = list(options)

    def to_jsonschema(self):
        d = super().to_jsonschema()
        d["enum"] = self.options
        return d


class SecretField(StrField):
    kind = "string"
    secret = True

    def to_jsonschema(self):
        d = super().to_jsonschema()
        d["secret"] = True
        d["default"] = ""  # never expose a secret default
        return d


ConfigSchema = dict  # {group: {name: Field}}


def to_jsonschema(schema: ConfigSchema) -> dict:
    return {
        "groups": {
            group: {name: field.to_jsonschema() for name, field in fields.items()}
            for group, fields in schema.items()
        }
    }


def secret_keys(schema: ConfigSchema) -> set:
    out = set()
    for group, fields in schema.items():
        for name, field in fields.items():
            if isinstance(field, SecretField):
                out.add((group, name))
    return out


def bind(schema: ConfigSchema, values: Optional[dict] = None) -> SimpleNamespace:
    """Bind user values onto defaults, returning ``cfg.<group>.<field>`` attribute access."""
    values = values or {}
    cfg = SimpleNamespace()
    for group, fields in schema.items():
        gv = values.get(group, {})
        ns = SimpleNamespace()
        for name, field in fields.items():
            raw = gv.get(name, field.default)
            try:
                val = field.coerce(raw) if raw is not None else field.default
            except (TypeError, ValueError):
                val = field.default
            setattr(ns, name, val)
        setattr(cfg, group, ns)
    return cfg
