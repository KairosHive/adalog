import pytest
from pydantic import ValidationError

from adalog.core.manifest import (
    AdapterRef,
    ClockAnchorModel,
    ClockBlock,
    FileEntry,
    Manifest,
    StreamEntry,
    Timing,
    reconcile,
)


def _manifest(**over):
    base = dict(
        session_id="01TESTSESSION0000000000000",
        clock=ClockBlock(t0_anchor=ClockAnchorModel(t=0.0, mono_ns=1, utc_ns=2)),
    )
    base.update(over)
    return Manifest(**base)


def test_minimal_manifest_validates_and_roundtrips():
    m = _manifest(label="hi", tags=["eeg", "writing"])
    js = m.to_json()
    m2 = Manifest.from_json(js)
    assert m2.session_id == m.session_id
    assert m2.tags == ["eeg", "writing"]
    assert m2.manifest_version == "1.0"


def test_event_timing_mode_is_accepted():
    t = Timing(mode="event")
    assert t.mode == "event"


def test_invalid_timing_mode_rejected():
    with pytest.raises(ValidationError):
        Timing(mode="bogus")


def test_invalid_confidence_rejected():
    with pytest.raises(ValidationError):
        Timing(mode="anchored_irregular", confidence="totally-sure")


def test_schema_alias_roundtrips():
    s = StreamEntry(id="eeg", modality="eeg", adapter=AdapterRef(id="eeg_muse"))
    dumped = s.model_dump(by_alias=True)
    assert "schema" in dumped and "schema_" not in dumped
    s2 = StreamEntry.model_validate(dumped)
    assert s2.id == "eeg"


def test_reconcile_flags_mismatch_and_degrades():
    stream = StreamEntry(
        id="eeg", modality="eeg", adapter=AdapterRef(id="eeg_muse"),
        files=[FileEntry(role="data", path="streams/eeg/eeg.arrow", encoding="arrow_ipc_stream",
                         timing=Timing(mode="anchored_irregular", n_samples=1000))],
    )
    m = _manifest(streams=[stream])
    results = reconcile(m, {"eeg": {"produced": 1000, "persisted": 990}})
    assert results[0].ok is False
    assert m.stream("eeg").status == "degraded"

    m2 = _manifest(streams=[StreamEntry(
        id="eeg", modality="eeg", adapter=AdapterRef(id="eeg_muse"),
        files=[FileEntry(role="data", path="p", encoding="arrow_ipc_stream",
                         timing=Timing(mode="anchored_irregular", n_samples=1000))])])
    res2 = reconcile(m2, {"eeg": {"produced": 1000, "persisted": 1000}})
    assert res2[0].ok is True
    assert m2.stream("eeg").status == "complete"
