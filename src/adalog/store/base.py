"""Storage interfaces (spec §store): content-addressed BlobStore + queryable Index.

These ``typing.Protocol`` definitions are the contract every backend implements. The
local filesystem backend lives in :mod:`adalog.store.local`; Google Drive sync is
deferred to Spec 2. Blobs are keyed by their ``blake3`` content hash (the ``b3:`` form
used throughout the manifest); the index keeps a lightweight catalog for browsing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Protocol, Union, runtime_checkable

from adalog.core.manifest import Manifest

PathLike = Union[str, Path]


@runtime_checkable
class BlobStore(Protocol):
    """A content-addressed, write-once object store keyed by ``blake3`` hash."""

    def has(self, blake3: str) -> bool:
        """Return ``True`` if an object with this content hash is already stored."""
        ...

    def put(self, blake3: str, src_path: PathLike) -> None:
        """Store ``src_path`` under its content hash.

        Content-addressed and write-once: idempotent, so a second ``put`` of the
        same hash is a no-op. The caller asserts ``blake3`` is the hash of
        ``src_path``'s bytes.
        """
        ...

    def get(self, blake3: str, dest_path: PathLike) -> None:
        """Copy the stored object for ``blake3`` to ``dest_path``."""
        ...

    def iter_hashes(self) -> Iterable[str]:
        """Yield every content hash currently held by the store (``b3:`` form)."""
        ...


@runtime_checkable
class Index(Protocol):
    """A queryable catalog of session manifests."""

    def put_manifest(self, manifest: Manifest) -> None:
        """Insert or update the catalog row for ``manifest``."""
        ...

    def get(self, session_id: str) -> Optional[Manifest]:
        """Return the full manifest for ``session_id`` if present."""
        ...

    def query(
        self,
        *,
        user: Optional[str] = None,
        subject: Optional[str] = None,
        modality: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[dict]:
        """Return lightweight catalog rows matching every supplied filter.

        Each row has: ``session_id, user, subject, label, tags, modalities,
        duration_s, t0_utc_ns``.
        """
        ...

    def all_sessions(self) -> list[dict]:
        """Return every catalog row."""
        ...
