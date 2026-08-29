"""Atomic content-addressed filesystem sink."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from arbogast.formats import loads

from .base import (
    SinkIntegrityError,
    SinkPredicate,
    SinkReceipt,
    SinkRecord,
    accepts,
    as_record,
)

_CONTENT_ID = re.compile(r"^sha256:([0-9a-f]{64})$")


class FilesystemSink:
    """Write immutable records atomically under their SHA-256 content IDs."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        predicate: SinkPredicate | None = None,
    ) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects" / "sha256"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.predicate = predicate

    def _path(self, content_id: str) -> Path:
        match = _CONTENT_ID.fullmatch(content_id)
        if match is None:
            raise SinkIntegrityError("content ID must be sha256:<64 lowercase hex>")
        digest = match.group(1)
        return self.objects / digest[:2] / f"{digest[2:]}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def write(
        self,
        value: SinkRecord | object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> SinkReceipt:
        record = as_record(value, kind=kind, metadata=metadata)
        path = self._path(record.content_id)
        if not accepts(self.predicate, record):
            return SinkReceipt(record.content_id, accepted=False, stored=False)
        if path.exists():
            existing = self.read(record.content_id)
            if existing != record:
                raise SinkIntegrityError("content-addressed filesystem collision")
            return SinkReceipt(
                record.content_id,
                accepted=True,
                stored=False,
                location=str(path),
            )
        self._atomic_write(path, record.to_json().encode("utf-8"))
        return SinkReceipt(
            record.content_id,
            accepted=True,
            stored=True,
            location=str(path),
        )

    emit = write

    def read(self, content_id: str) -> SinkRecord | None:
        path = self._path(content_id)
        try:
            value = loads(path.read_bytes())
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise SinkIntegrityError("filesystem sink record must be an object")
        record = SinkRecord.from_dict(value)
        if record.content_id != content_id:
            raise SinkIntegrityError("filesystem path/content identity mismatch")
        return record

    def contains(self, content_id: str) -> bool:
        return self.read(content_id) is not None

    def records(self) -> tuple[SinkRecord, ...]:
        result: list[SinkRecord] = []
        for path in sorted(self.objects.glob("*/*.json")):
            digest = f"{path.parent.name}{path.stem}"
            record = self.read(f"sha256:{digest}")
            if record is not None:
                result.append(record)
        return tuple(result)


AtomicFilesystemSink = FilesystemSink

__all__ = ["AtomicFilesystemSink", "FilesystemSink"]
