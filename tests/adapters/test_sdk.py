import pytest

from adalog.adapters.base import AdapterInfo, DeviceAdapter
from adalog.adapters.context import AdapterContext
from adalog.adapters.registry import AdapterRegistry, entrypoint_adapters
from adalog.core.envelope import StreamPacket
from adalog.core.spec import StreamSpec
from adalog.schema.fields import (
    BoolField,
    EnumField,
    FloatField,
    IntField,
    SecretField,
    StrField,
    bind,
    secret_keys,
    to_jsonschema,
)


def test_fields_jsonschema_and_bind():
    schema = {
        "conn": {"port": StrField("/dev/ttyUSB0", doc="serial"),
                 "baud": IntField(256, min=110, max=2_000_000),
                 "gain": FloatField(1.0, min=0.0),
                 "invert": BoolField(False),
                 "mode": EnumField("raw", options=["raw", "filtered"]),
                 "token": SecretField()},
    }
    js = to_jsonschema(schema)
    assert js["groups"]["conn"]["baud"]["minimum"] == 110
    assert js["groups"]["conn"]["mode"]["enum"] == ["raw", "filtered"]
    assert js["groups"]["conn"]["token"]["secret"] is True
    assert secret_keys(schema) == {("conn", "token")}

    cfg = bind(schema, {"conn": {"baud": "512", "mode": "filtered"}})
    assert cfg.conn.baud == 512  # coerced to int
    assert cfg.conn.mode == "filtered"
    assert cfg.conn.port == "/dev/ttyUSB0"  # default
    assert cfg.conn.invert is False


def test_adapter_open_binds_cfg():
    class A(DeviceAdapter):
        info = AdapterInfo(id="a", title="A")

        @staticmethod
        def config_schema():
            return {"g": {"x": IntField(1)}}

    a = A()
    ctx = AdapterContext(emit_fn=lambda p: None, now_mono_ns=lambda: 0, config={"g": {"x": 7}})
    a.open(ctx)
    assert a.cfg.g.x == 7


def test_context_emit_and_register():
    emitted = []
    registered = []
    ctx = AdapterContext(emit_fn=emitted.append, now_mono_ns=lambda: 123,
                         register_fn=registered.append, config={})
    ctx.emit(StreamPacket(stream_id="s", seq=0, payload={"a": 1}))
    assert emitted[0].stream_id == "s"
    assert ctx.now_mono_ns() == 123
    spec = StreamSpec(id="dyn", modality="osc")
    ctx.register_stream(spec)
    assert registered[0] is spec


def test_registry_register_and_catalog():
    class A(DeviceAdapter):
        info = AdapterInfo(id="a", title="A", category="neuro")

        @staticmethod
        def config_schema():
            return {"g": {"x": IntField(1)}}

    reg = AdapterRegistry()
    reg.register(A)
    assert reg.ids() == ["a"]
    cat = reg.catalog()
    assert cat[0]["id"] == "a" and cat[0]["category"] == "neuro"
    assert "x" in cat[0]["config_schema"]["groups"]["g"]


def test_entrypoint_loader_skips_broken():
    class Good(DeviceAdapter):
        info = AdapterInfo(id="good", title="Good")

    class _EP:
        def __init__(self, name, loader):
            self.name = name
            self._loader = loader

        def load(self):
            return self._loader()

    def boom():
        raise ImportError("missing dep")

    def fake_eps(group=None):
        return [_EP("good", lambda: Good), _EP("bad", boom), _EP("notadapter", lambda: object)]

    loaded = entrypoint_adapters(entry_points_fn=fake_eps)
    assert loaded == [Good]  # broken + non-adapter skipped, never fatal
