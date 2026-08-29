"""Content-addressed campaign sink protocol."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from arbogast.formats import (
    FrozenJSONValue,
    FrozenMapping,
    JSONValue,
    canonical_dumps,
    canonical_sha256,
    freeze_json,
    thaw_json,
)


class SinkError(RuntimeError):
    """Base class for sink failures."""


class SinkIntegrityError(SinkError, ValueError):
    """Raised when persisted content does not match its advertised ID."""


SinkPredicate = Callable[["SinkRecord"], bool]


@dataclass(frozen=True, slots=True, init=False)
class SinkRecord:
    """A strict canonical record shared by every sink implementation."""

    kind: str
    payload: FrozenJSONValue
    metadata: FrozenMapping

    def __init__(
        self,
        payload: object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise SinkIntegrityError("sink record kind must be a non-empty string")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "payload", freeze_json(payload))
        object.__setattr__(self, "metadata", FrozenMapping(metadata))

    @classmethod
    def create(
        cls,
        payload: object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> SinkRecord:
        return cls(payload, kind=kind, metadata=metadata)

    @property
    def content_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "kind": self.kind,
            "metadata": self.metadata.to_dict(),
            "payload": thaw_json(self.payload),
            "schema": "arbogast.sink.record.v1",
        }
        if include_id:
            payload["content_id"] = self.content_id
        return payload

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SinkRecord:
        required = {"content_id", "kind", "metadata", "payload", "schema"}
        if set(value) != required:
            raise SinkIntegrityError("sink record has missing or unknown fields")
        if value["schema"] != "arbogast.sink.record.v1":
            raise SinkIntegrityError("unsupported sink record schema")
        kind = value["kind"]
        metadata = value["metadata"]
        if not isinstance(kind, str):
            raise SinkIntegrityError("sink record kind must be a string")
        if not isinstance(metadata, Mapping) or any(not isinstance(key, str) for key in metadata):
            raise SinkIntegrityError("sink record metadata must be a string-keyed object")
        record = cls(value["payload"], kind=kind, metadata=metadata)
        supplied_id = value["content_id"]
        if not isinstance(supplied_id, str) or supplied_id != record.content_id:
            raise SinkIntegrityError("sink record content_id mismatch")
        return record


@dataclass(frozen=True, slots=True)
class SinkReceipt:
    """Idempotent sink-write result."""

    content_id: str
    accepted: bool
    stored: bool
    location: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "accepted": self.accepted,
            "content_id": self.content_id,
            "location": self.location,
            "stored": self.stored,
        }


def as_record(
    value: SinkRecord | object,
    *,
    kind: str,
    metadata: Mapping[str, object] | None,
) -> SinkRecord:
    if isinstance(value, SinkRecord):
        if kind != "record" or metadata is not None:
            raise SinkIntegrityError("kind/metadata cannot override an existing SinkRecord")
        return value
    return SinkRecord(value, kind=kind, metadata=metadata)


@runtime_checkable
class Sink(Protocol):
    """Minimal durable-output protocol."""

    def write(
        self,
        value: SinkRecord | object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> SinkReceipt: ...

    def emit(
        self,
        value: SinkRecord | object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> SinkReceipt: ...

    def read(self, content_id: str) -> SinkRecord | None: ...

    def contains(self, content_id: str) -> bool: ...

    def records(self) -> Iterable[SinkRecord]: ...


def accepts(predicate: SinkPredicate | None, record: SinkRecord) -> bool:
    if predicate is None:
        return True
    verdict = predicate(record)
    if not isinstance(verdict, bool):
        raise SinkError("sink predicate must return bool")
    return verdict


__all__ = [
    "Sink",
    "SinkError",
    "SinkIntegrityError",
    "SinkPredicate",
    "SinkReceipt",
    "SinkRecord",
    "accepts",
    "as_record",
]
