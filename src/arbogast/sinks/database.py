"""Transactional SQLite campaign sink."""

from __future__ import annotations

import os
import sqlite3
import threading
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


class DatabaseSink:
    """Store canonical records idempotently in a small SQLite database."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        predicate: SinkPredicate | None = None,
    ) -> None:
        self.path = os.fspath(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.predicate = predicate
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    content_id TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL,
                    canonical_json TEXT NOT NULL
                )
                """
            )

    def write(
        self,
        value: SinkRecord | object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> SinkReceipt:
        record = as_record(value, kind=kind, metadata=metadata)
        if not accepts(self.predicate, record):
            return SinkReceipt(record.content_id, accepted=False, stored=False)
        payload = record.to_json()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO records(content_id, kind, canonical_json) VALUES (?, ?, ?)",
                (record.content_id, record.kind, payload),
            )
            stored = cursor.rowcount == 1
            if not stored:
                row = self._connection.execute(
                    "SELECT canonical_json FROM records WHERE content_id = ?",
                    (record.content_id,),
                ).fetchone()
                if row is None or row[0] != payload:
                    raise SinkIntegrityError("content-addressed database collision")
        return SinkReceipt(
            record.content_id,
            accepted=True,
            stored=stored,
            location=f"sqlite:{self.path}#{record.content_id}",
        )

    emit = write

    def read(self, content_id: str) -> SinkRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT canonical_json FROM records WHERE content_id = ?",
                (content_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row[0]
        if not isinstance(raw, str):
            raise SinkIntegrityError("database sink payload must be text")
        value = loads(raw)
        if not isinstance(value, dict):
            raise SinkIntegrityError("database sink record must be an object")
        record = SinkRecord.from_dict(value)
        if record.content_id != content_id:
            raise SinkIntegrityError("database key/content identity mismatch")
        return record

    def contains(self, content_id: str) -> bool:
        return self.read(content_id) is not None

    def records(self) -> tuple[SinkRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT content_id FROM records ORDER BY content_id"
            ).fetchall()
        result: list[SinkRecord] = []
        for row in rows:
            content_id = row[0]
            if not isinstance(content_id, str):
                raise SinkIntegrityError("database content ID must be text")
            record = self.read(content_id)
            if record is not None:
                result.append(record)
        return tuple(result)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> DatabaseSink:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


SQLiteSink = DatabaseSink

__all__ = ["DatabaseSink", "SQLiteSink"]
