"""Local filesystem backend for the store interfaces (spec §store).

* :class:`LocalBlobStore` — content-addressed objects under ``root/objects/b3/<aa>/<hash>``.
* :class:`LocalIndex` — a JSON catalog (``root/catalog.json``) of session rows + manifests.
* :class:`LocalStore` — wires the two together with ``publish_session`` /
  ``materialize_session`` helpers that move a whole session in and out of the store.

All writes are atomic (temp file + rename) so a crash never leaves a partial object or
a corrupt catalog. Blobs are write-once and deduplicated by content hash.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable, Optional, Union

from adalog.core.manifest import Manifest

PathLike = Union[str, Path]


def _strip_prefix(blake3: str) -> str:
    """Return the bare hex digest, dropping any leading ``b3:`` algorithm prefix."""
    return blake3[3:] if blake3.startswith("b3:") else blake3


def _atomic_copy(src: PathLike, dest: Path) -> None:
    """Copy ``src`` to ``dest`` atomically via a temp file in the destination dir."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def _atomic_write_text(dest: Path, text: str) -> None:
    """Write ``text`` to ``dest`` atomically."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


class LocalBlobStore:
    """Content-addressed object store on the local filesystem.

    Objects live at ``root/objects/b3/<first2hex>/<hash>``. ``put`` is idempotent and
    write-once: storing a hash that already exists is a no-op.
    """

    def __init__(self, root: PathLike):
        self.root = Path(root)
        self.objects_dir = self.root / "objects" / "b3"

    def _object_path(self, blake3: str) -> Path:
        h = _strip_prefix(blake3)
        return self.objects_dir / h[:2] / h

    def has(self, blake3: str) -> bool:
        return self._object_path(blake3).exists()

    def put(self, blake3: str, src_path: PathLike) -> None:
        dest = self._object_path(blake3)
        if dest.exists():  # write-once / idempotent
            return
        _atomic_copy(src_path, dest)

    def get(self, blake3: str, dest_path: PathLike) -> None:
        src = self._object_path(blake3)
        if not src.exists():
            raise FileNotFoundError(f"blob not found in store: {blake3}")
        _atomic_copy(src, Path(dest_path))

    def iter_hashes(self) -> Iterable[str]:
        if not self.objects_dir.exists():
            return
        for shard in sorted(self.objects_dir.iterdir()):
            if not shard.is_dir():
                continue
            for obj in sorted(shard.iterdir()):
                if obj.is_file():
                    yield "b3:" + obj.name


class LocalIndex:
    """A JSON-backed catalog of session manifests.

    The catalog (``root/catalog.json``) stores, per session, both a lightweight row for
    browsing/querying and the full manifest JSON for exact reconstruction.
    """

    def __init__(self, root: PathLike):
        self.root = Path(root)
        self.path = self.root / "catalog.json"
        self._sessions: dict[str, dict] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._sessions = data.get("sessions", {})
            except Exception:
                self._sessions = {}

    @staticmethod
    def _row(manifest: Manifest) -> dict:
        modalities = sorted({s.modality for s in manifest.streams})
        t0_utc_ns = None
        if manifest.clock and manifest.clock.t0_anchor:
            t0_utc_ns = manifest.clock.t0_anchor.utc_ns
        return {
            "session_id": manifest.session_id,
            "user": manifest.provenance.user_id,
            "subject": manifest.subject.id,
            "label": manifest.label,
            "tags": list(manifest.tags),
            "modalities": modalities,
            "duration_s": manifest.duration_s,
            "t0_utc_ns": t0_utc_ns,
        }

    def _save(self) -> None:
        _atomic_write_text(self.path, json.dumps({"version": 1, "sessions": self._sessions}, indent=2))

    def put_manifest(self, manifest: Manifest) -> None:
        self._sessions[manifest.session_id] = {
            "row": self._row(manifest),
            "manifest": json.loads(manifest.to_json()),
        }
        self._save()

    def get(self, session_id: str) -> Optional[Manifest]:
        entry = self._sessions.get(session_id)
        if not entry:
            return None
        return Manifest.model_validate(entry["manifest"])

    def query(
        self,
        *,
        user: Optional[str] = None,
        subject: Optional[str] = None,
        modality: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[dict]:
        rows = []
        for entry in self._sessions.values():
            row = entry["row"]
            if user is not None and row["user"] != user:
                continue
            if subject is not None and row["subject"] != subject:
                continue
            if modality is not None and modality not in row["modalities"]:
                continue
            if tag is not None and tag not in row["tags"]:
                continue
            rows.append(dict(row))
        return rows

    def all_sessions(self) -> list[dict]:
        return [dict(entry["row"]) for entry in self._sessions.values()]


class LocalStore:
    """Convenience facade wiring :class:`LocalBlobStore` + :class:`LocalIndex`.

    A session on disk is a directory containing ``manifest.json`` plus per-stream files
    under paths the manifest records. ``publish_session`` ingests one into the store;
    ``materialize_session`` reconstructs it elsewhere from the index + blobs.
    """

    def __init__(self, root: PathLike):
        self.root = Path(root)
        self.blobs = LocalBlobStore(self.root)
        self.index = LocalIndex(self.root)

    def publish_session(self, session_dir: PathLike) -> Manifest:
        """Read ``<session_dir>/manifest.json``, index it, and store every stream blob.

        Files without a ``blake3`` are skipped (nothing to content-address). Returns the
        parsed manifest.
        """
        session_dir = Path(session_dir)
        manifest = Manifest.from_json((session_dir / "manifest.json").read_text(encoding="utf-8"))
        self.index.put_manifest(manifest)
        for stream in manifest.streams:
            for f in stream.files:
                if not f.blake3:
                    continue
                self.blobs.put(f.blake3, session_dir / f.path)
        return manifest

    def materialize_session(self, session_id: str, dest_dir: PathLike) -> Manifest:
        """Pull a session's manifest + blobs back, recreating the on-disk layout.

        Writes ``<dest_dir>/manifest.json`` and each stream file at its manifest-recorded
        path. Returns the manifest. Raises ``KeyError`` if the session is unknown.
        """
        dest_dir = Path(dest_dir)
        manifest = self.index.get(session_id)
        if manifest is None:
            raise KeyError(f"session not in index: {session_id}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(dest_dir / "manifest.json", manifest.to_json())
        for stream in manifest.streams:
            for f in stream.files:
                if not f.blake3:
                    continue
                self.blobs.get(f.blake3, dest_dir / f.path)
        return manifest
