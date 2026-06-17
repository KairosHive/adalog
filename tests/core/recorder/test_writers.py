import json

import numpy as np
import pyarrow as pa
import pytest

from adalog.core.recorder.writers import get_writer
from adalog.core.recorder.writers.arrow_chunk import ArrowChunkWriter, _sidecar_path
from adalog.core.recorder.writers.jsonl import JsonlWriter
from adalog.core.recorder.writers.wav import WavWriter, _HEADER_SIZE
from adalog.core.spec import (
    TIMING_ANCHORED,
    TIMING_ANCHORED_IRREGULAR,
    TIMING_EVENT,
    TIMING_PER_SAMPLE,
    Channel,
    StreamSpec,
)


def test_registry_resolves_encodings():
    assert get_writer("arrow_ipc_stream") is ArrowChunkWriter
    assert get_writer("jsonl") is JsonlWriter
    assert get_writer("wav") is WavWriter
    with pytest.raises(KeyError):
        get_writer("nope")


def _eeg_spec():
    return StreamSpec(id="eeg", modality="eeg", encoding="arrow_ipc_stream",
                      timing_mode=TIMING_ANCHORED_IRREGULAR, sfreq_nominal=256.0,
                      channels=[Channel(c, "uV", "float32") for c in ("TP9", "AF7", "AF8", "TP10")])


def _read_arrow_rows(path):
    reader = pa.ipc.open_stream(str(path))
    tbl = reader.read_all()
    return tbl.num_rows, tbl.column_names


def test_arrow_roundtrip_and_timing(tmp_path):
    spec = _eeg_spec()
    p = tmp_path / "streams" / "eeg" / "eeg.arrow"
    w = ArrowChunkWriter(p, spec, provenance="device_lsl")
    w.open()
    # two batches @ ~256Hz with exact per-sample session times
    base = 0.5
    t_all = []
    for b in range(2):
        n = 4
        data = np.arange(n * 4, dtype=np.float32).reshape(n, 4) + b
        ts = [base + (b * n + i) / 256.0 for i in range(n)]
        t_all.extend(ts)
        w.write(data, ts, seq=b)
    files = w.close()
    rows, cols = _read_arrow_rows(p)
    assert rows == 8
    assert cols == ["TP9", "AF7", "AF8", "TP10"]
    data_entry = files[0]
    assert data_entry.timing.n_samples == 8
    assert data_entry.timing.index_to_t == "sidecar"
    assert data_entry.timing.clock_provenance == "device_lsl"
    assert abs(data_entry.timing.sfreq_effective - 256.0) < 1.0
    assert data_entry.blake3.startswith("b3:")
    # round-trip exactness: sidecar t == original within 1us
    sidecar = _sidecar_path(p)
    recon = []
    for line in sidecar.read_text().splitlines():
        recon.extend(json.loads(line)["t"])
    assert max(abs(a - b) for a, b in zip(recon, t_all)) <= 1e-6


def test_arrow_torn_tail_recovers(tmp_path):
    spec = _eeg_spec()
    p = tmp_path / "streams" / "eeg" / "eeg.arrow"
    w = ArrowChunkWriter(p, spec, provenance="device_lsl")
    w.open()
    for b in range(3):
        data = np.ones((4, 4), dtype=np.float32) * b
        ts = [0.1 + (b * 4 + i) / 256.0 for i in range(4)]
        w.write(data, ts, seq=b)
    # simulate kill -9: flush + close handles WITHOUT writing the EOS marker
    w._sink.flush()
    w._sink.close()
    w._sidecar.close()
    # corrupt the tail (cut into the 3rd batch)
    size = p.stat().st_size
    with open(p, "r+b") as fh:
        fh.truncate(size - 12)
    files = ArrowChunkWriter.recover(p, spec, provenance="device_lsl")
    rows, _ = _read_arrow_rows(p)
    assert rows in (8, 12)  # at least the first 2 complete batches salvaged
    assert files[0].timing.n_samples == rows
    # sidecar truncated to the salvaged batch count
    sidecar_lines = _sidecar_path(p).read_text().splitlines()
    assert len(sidecar_lines) == rows // 4


def test_jsonl_per_sample_roundtrip_and_recover(tmp_path):
    spec = StreamSpec(id="text", modality="text", encoding="jsonl", timing_mode=TIMING_PER_SAMPLE)
    p = tmp_path / "streams" / "text" / "text.ndjson"
    w = JsonlWriter(p, spec, provenance="browser")
    w.open()
    w.write({"word": "hello"}, [1.0], seq=0)
    w.write({"word": "world"}, [1.5], seq=1)
    files = w.close()
    assert files[0].timing.n_samples == 2
    assert files[0].timing.t_start == 1.0
    lines = p.read_text().splitlines()
    assert json.loads(lines[0]) == {"t": 1.0, "word": "hello"}
    # torn tail: append a partial line, recover truncates it
    with open(p, "ab") as fh:
        fh.write(b'{"t":2.0,"word":"par')
    rec = JsonlWriter.recover(p, spec, provenance="browser")
    assert rec[0].timing.n_samples == 2
    assert p.read_text().splitlines() == lines


def test_jsonl_event_mode(tmp_path):
    spec = StreamSpec(id="snap", modality="drawing", encoding="jsonl", timing_mode=TIMING_EVENT)
    p = tmp_path / "streams" / "snap" / "snap.ndjson"
    w = JsonlWriter(p, spec)
    w.open()
    w.write({"file": "a.png"}, [3.0], seq=0)
    files = w.close()
    assert files[0].timing.mode == "event"
    assert files[0].timing.n_samples == 1


def test_wav_roundtrip_and_recover(tmp_path):
    spec = StreamSpec(id="audio", modality="audio", encoding="wav",
                      timing_mode=TIMING_ANCHORED, sfreq_nominal=48000.0, channels=[Channel("mono")])
    p = tmp_path / "streams" / "audio" / "audio.wav"
    w = WavWriter(p, spec, provenance="device_portaudio")
    w.open()
    # 3 blocks of 1000 frames; block start times spaced by 1000/48000 s
    for b in range(3):
        block = (np.random.rand(1000).astype(np.float32) - 0.5)
        w.write(block, [b * 1000 / 48000.0], seq=b)
    files = w.close()
    assert files[0].timing.n_samples == 3000
    assert abs(files[0].timing.sfreq_effective - 48000.0) < 50.0
    # read frames back
    raw = p.read_bytes()[_HEADER_SIZE:]
    frames = np.frombuffer(raw, dtype="<f4")
    assert frames.shape[0] == 3000
    # torn tail mid-frame: append 2 stray bytes, recover truncates to whole frames
    with open(p, "ab") as fh:
        fh.write(b"\x01\x02")
    rec = WavWriter.recover(p, spec, provenance="device_portaudio")
    assert rec[0].timing.n_samples == 3000
