"""Adapter for explicitly injected custom sink functions."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .base import (
    SinkIntegrityError,
    SinkPredicate,
    SinkReceipt,
    SinkRecord,
    accepts,
    as_record,
)

CustomWriter = Callable[[SinkRecord], bool | None]
CustomReader = Callable[[str], SinkRecord | Mapping[str, object] | None]
CustomContains = Callable[[str], bool]


class CustomSink:
    """Use trusted local callbacks without ever serializing executable code."""

    def __init__(
        self,
        writer: CustomWriter,
        *,
        reader: CustomReader | None = None,
        contains: CustomContains | None = None,
        predicate: SinkPredicate | None = None,
        name: str = "custom",
    ) -> None:
        if not name.strip():
            raise SinkIntegrityError("custom sink name cannot be blank")
        self.writer = writer
        self.reader = reader
        self.contains_callback = contains
        self.predicate = predicate
        self.name = name
        self._seen: dict[str, SinkRecord] = {}

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
        if self.contains(record.content_id):
            return SinkReceipt(
                record.content_id,
                accepted=True,
                stored=False,
                location=f"custom:{self.name}:{record.content_id}",
            )
        verdict = self.writer(record)
        if verdict is not None and not isinstance(verdict, bool):
            raise SinkIntegrityError("custom sink writer must return bool or None")
        stored = verdict is not False
        if stored:
            self._seen[record.content_id] = record
        return SinkReceipt(
            record.content_id,
            accepted=True,
            stored=stored,
            location=f"custom:{self.name}:{record.content_id}" if stored else None,
        )

    emit = write

    def read(self, content_id: str) -> SinkRecord | None:
        local = self._seen.get(content_id)
        if local is not None:
            return local
        if self.reader is None:
            return None
        value = self.reader(content_id)
        if value is None:
            return None
        record = value if isinstance(value, SinkRecord) else SinkRecord.from_dict(value)
        if record.content_id != content_id:
            raise SinkIntegrityError("custom reader returned content under the wrong ID")
        self._seen[content_id] = record
        return record

    def contains(self, content_id: str) -> bool:
        if content_id in self._seen:
            return True
        if self.contains_callback is not None:
            verdict = self.contains_callback(content_id)
            if not isinstance(verdict, bool):
                raise SinkIntegrityError("custom contains callback must return bool")
            return verdict
        return self.read(content_id) is not None

    def records(self) -> tuple[SinkRecord, ...]:
        return tuple(self._seen[key] for key in sorted(self._seen))


__all__ = ["CustomContains", "CustomReader", "CustomSink", "CustomWriter"]
