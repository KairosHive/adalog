"""Regression gate for the legacy v0 -> v1 converter against the real pinned fixture."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from adalog.convert import convert_session
from adalog.core.manifest import Manifest
from adalog.core.reader import read_session

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "adalog-sessions"
    / "phil"
    / "2025-05-31T23-09-11-481969"
)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="pinned legacy fixture not present")
def test_convert_real_fixture(tmp_path):
    manifest = convert_session(_FIXTURE, tmp_path, user="phil", session_id="TESTSESSION")

    # manifest round-trips / validates
    out_manifest = tmp_path / "phil" / "TESTSESSION" / "manifest.json"
    assert out_manifest.exists()
    rt = Manifest.from_json(out_manifest.read_text(encoding="utf-8"))
    assert rt.session_id == "TESTSESSION"
    assert rt.status == "complete"
    assert rt.clock.t0_anchor.utc_ns > 0

    # tags
    assert "eeg" in rt.tags
    assert "writing" in rt.tags

    sess = read_session(out_manifest)

    # EEG stream
    eeg = sess.stream("eeg")
    assert eeg.array.shape == (161353, 4)
    assert eeg.channels == ["TP9", "AF7", "AF8", "TP10"]
    assert eeg.timing.confidence == "approximate"
    assert eeg.timing.clock_provenance == "reconstructed"
    assert eeg.t is not None and eeg.t.shape == (161353,)

    sfreq_eff = eeg.timing.sfreq_effective
    assert 200.0 < sfreq_eff < 256.0

    # text stream
    text = sess.stream("text")
    assert text.records, "text stream should have records"
    assert text.records[0]["word"] == "wir"

    # eeg2txt-style alignment for the first word
    tw = float(text.records[0]["t"])
    t_start = eeg.timing.t_start
    idx = round((tw - t_start) * sfreq_eff)
    assert 0 <= idx < eeg.array.shape[0]

    # manifest matches what the reader saw (sanity on the StreamEntry wiring)
    assert manifest.stream("eeg").data_file().timing.n_samples == 161353
