"""Generic schema-labelled interchange envelope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import FrozenMapping, JSONValue, canonical_dumps
from .schemas import validate_document


@dataclass(frozen=True, slots=True)
class Envelope:
    """An immutable schema-labelled JSON payload."""

    schema: str
    payload: FrozenMapping

    def __init__(self, schema: str, payload: Mapping[str, Any]) -> None:
        if not isinstance(schema, str) or not schema:
            raise ValueError("envelope schema must be a non-empty string")
        if "schema" in payload:
            raise ValueError("envelope payload cannot override its schema")
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "payload", FrozenMapping(payload))

    def to_dict(self) -> dict[str, JSONValue]:
        return {"schema": self.schema, **self.payload.to_dict()}

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, expected: str | None = None) -> Envelope:
        document = validate_document(value, expected)
        schema = document.pop("schema")
        assert isinstance(schema, str)
        return cls(schema, document)
