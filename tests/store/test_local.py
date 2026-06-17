"""Tests for the local filesystem store backend."""
from __future__ import annotations

from pathlib import Path

import pytest

from adalog.core.ids import blake3_file
from adalog.core.manifest import (
    AdapterRef,
    ClockAnchorModel,
    ClockBlock,
    FileEntry,
    Manifest,
    StreamEntry,
)
from adalog.store.base import BlobStore, Index
from adalog.store.local import LocalBlobStore, LocalIndex, LocalStore


def _make_session(session_dir: Path, *, session_id: str = "01TESTSESSION") -> Manifest:
    """Build a one-stream (jsonl) session on disk and return its manifest."""
    session_dir.mkdir(parents=True, exist_ok=True)
    stream_dir = session_dir / "streams" / "marker"
    stream_dir.mkdir(parents=True, exist_ok=True)
    data_path = stream_dir / "data.jsonl"
    data_path.write_text('{"label": "hello", "t": 0.0}\n{"label": "world", "t": 1.5}\n', encoding="utf-8")

    rel_path = "streams/marker/data.jsonl"
    file_entry = FileEntry(
        role="data",
        path=rel_path,
        encoding="jsonl",
        blake3=blake3_file(data_path),
        bytes=data_path.stat().st_size,
    )
    stream = StreamEntry(
        id="marker",
        modality="markers",
        adapter=AdapterRef(id="keyboard", version="1"),
        files=[file_entry],
    )
    manifest = Manifest(
        session_id=session_id,
        label="demo",
        tags=["test"],
        clock=ClockBlock(t0_anchor=ClockAnchorModel(t=0.0, mono_ns=1_000, utc_ns=1_750_000_000_000_000_000)),
        duration_s=1.5,
        streams=[stream],
    )
    (session_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def test_protocols_are_satisfied(tmp_path):
    store = LocalStore(tmp_path / "store")
    assert isinstance(store.blobs, BlobStore)
    assert isinstance(store.index, Index)


def test_blobstore_dedup_and_roundtrip(tmp_path):
    src = tmp_path / "blob.bin"
    src.write_bytes(b"some content")
    h = blake3_file(src)

    blobs = LocalBlobStore(tmp_path / "store")
    assert not blobs.has(h)
    blobs.put(h, src)
    assert blobs.has(h)

    # path uses stripped hash and 2-char shard
    bare = h[3:]
    assert (tmp_path / "store" / "objects" / "b3" / bare[:2] / bare).exists()

    # idempotent re-put is a no-op (no crash, still present)
    blobs.put(h, src)
    assert list(blobs.iter_hashes()) == [h]

    out = tmp_path / "out.bin"
    blobs.get(h, out)
    assert out.read_bytes() == b"some content"

    with pytest.raises(FileNotFoundError):
        blobs.get("b3:deadbeef", tmp_path / "missing.bin")


def test_index_put_query_get(tmp_path):
    sess = tmp_path / "sess"
    manifest = _make_session(sess)

    index = LocalIndex(tmp_path / "store")
    index.put_manifest(manifest)

    rows = index.query(modality="markers")
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == manifest.session_id
    assert row["modalities"] == ["markers"]
    assert row["t0_utc_ns"] == 1_750_000_000_000_000_000
    assert row["duration_s"] == 1.5

    assert index.query(modality="eeg") == []
    assert index.query(tag="test")
    assert index.query(tag="nope") == []
    assert index.query(user="u_local")
    assert len(index.all_sessions()) == 1

    # persisted to disk -> a fresh index reads it back
    again = LocalIndex(tmp_path / "store")
    got = again.get(manifest.session_id)
    assert got is not None
    assert got.session_id == manifest.session_id

    assert index.get("unknown") is None


def test_publish_dedup_and_materialize(tmp_path):
    sess = tmp_path / "sess"
    manifest = _make_session(sess)

    store = LocalStore(tmp_path / "store")
    store.publish_session(sess)

    hashes = list(store.blobs.iter_hashes())
    assert len(hashes) == 1

    # re-publishing the same session does not duplicate the blob
    store.publish_session(sess)
    assert list(store.blobs.iter_hashes()) == hashes

    # query finds it
    assert store.index.query(modality="markers")[0]["session_id"] == manifest.session_id

    # materialize into a new dir reproduces bytes + layout
    dest = tmp_path / "restored"
    store.materialize_session(manifest.session_id, dest)

    orig = (sess / "streams" / "marker" / "data.jsonl").read_bytes()
    restored = (dest / "streams" / "marker" / "data.jsonl").read_bytes()
    assert restored == orig
    assert (dest / "manifest.json").exists()
    assert Manifest.from_json((dest / "manifest.json").read_text()).session_id == manifest.session_id

    with pytest.raises(KeyError):
        store.materialize_session("does-not-exist", tmp_path / "x")
