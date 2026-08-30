"""Typed numeric non-conclusions."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from arbogast.cert import FrozenMap, freeze_mapping
from arbogast.core import CanonicalEncodingError, CanonicalJSON, canonical_data

from ._schema import (
    MAX_CANONICAL_DEPTH,
    MAX_CANONICAL_NODES,
    MAX_TEXT_LENGTH,
    NumericSemanticObject,
    ensure_canonical_bounds,
)
from .errors import NumericError, NumericVerificationError


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NumericError(f"{name} must be a non-blank string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if len(normalized) > MAX_TEXT_LENGTH:
        raise NumericError(f"{name} exceeds the portable text-length bound")
    return normalized


def _requested_nodes(value: object, name: str = "requested", *, depth: int = 0) -> int:
    if depth > MAX_CANONICAL_DEPTH:
        raise NumericError(f"{name} exceeds the portable nesting-depth bound")
    if value is None or type(value) in {bool, int}:
        return 1
    if type(value) is str:
        text = value
        if len(text) > MAX_TEXT_LENGTH:
            raise NumericError(f"{name} contains oversized text")
        return 1
    if type(value) is list:
        count = 1 + sum(
            _requested_nodes(item, f"{name}[{index}]", depth=depth + 1)
            for index, item in enumerate(cast(list[object], value))
        )
        if count > MAX_CANONICAL_NODES:
            raise NumericError("requested data exceeds the portable node bound")
        return count
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        dangerous = ("backend", "handle", "session", "transcript", "raw_output")
        for key in mapping:
            normalized = key.casefold().replace("-", "_")
            if any(token in normalized for token in dangerous):
                raise NumericError("backend-local requested data cannot cross the proof boundary")
            if len(key) > MAX_TEXT_LENGTH:
                raise NumericError(f"{name} contains an oversized key")
        count = 1 + sum(
            _requested_nodes(item, f"{name}.{key}", depth=depth + 1)
            for key, item in mapping.items()
        )
        if count > MAX_CANONICAL_NODES:
            raise NumericError("requested data exceeds the portable node bound")
        return count
    raise NumericError(f"{name} contains noncanonical data")


def _strict_equal(value: object, canonical: object) -> bool:
    if type(canonical) is dict:
        if type(value) is not dict:
            return False
        left = cast(dict[object, object], value)
        right = cast(dict[object, object], canonical)
        return left.keys() == right.keys() and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if type(canonical) is list:
        if type(value) is not list:
            return False
        left_items = cast(list[object], value)
        right_items = cast(list[object], canonical)
        return len(left_items) == len(right_items) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left_items, right_items, strict=True)
        )
    return type(value) is type(canonical) and value == canonical


def _requested(value: Mapping[str, object] | None) -> FrozenMap:
    raw = dict(value or {})
    try:
        ensure_canonical_bounds(raw, "requested data")
    except NumericVerificationError as exc:
        raise NumericError(str(exc)) from exc
    try:
        normalized = canonical_data(raw)
    except CanonicalEncodingError as exc:
        raise NumericError(f"requested data is not exact canonical JSON: {exc}") from exc
    if not isinstance(normalized, dict) or not _strict_equal(raw, normalized):
        raise NumericError("requested data must already equal strict canonical JSON")
    _requested_nodes(normalized)
    return freeze_mapping(normalized)


@dataclass(frozen=True, slots=True, init=False)
class NumericUnknown(NumericSemanticObject):
    """A bounded computation that establishes no positive or negative conclusion."""

    operation: str
    reason: str
    requested: FrozenMap

    schema_version = "arbogast.numeric.unknown/v1"

    def __init__(
        self,
        operation: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None = None,
    ) -> None:
        object.__setattr__(self, "operation", _label(operation, "operation"))
        object.__setattr__(self, "reason", _label(reason, "reason"))
        object.__setattr__(self, "requested", _requested(requested))

    def verify(self) -> bool:
        if (
            NumericUnknown(
                self.operation,
                self.reason,
                requested=self.requested.to_dict(),
            )
            != self
        ):
            raise NumericVerificationError("unknown result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "operation": self.operation,
            "reason": self.reason,
            "requested": canonical_data(self.requested.to_dict()),
            "type": "arbogast.numeric.unknown",
        }


@dataclass(frozen=True, slots=True, init=False)
class UnsupportedNumeric(NumericSemanticObject):
    """A typed refusal for an operation outside the certified numeric slice."""

    operation: str
    reason: str
    requested: FrozenMap
    supported: tuple[str, ...]

    schema_version = "arbogast.numeric.unsupported/v1"

    def __init__(
        self,
        operation: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None = None,
        supported: Sequence[str] = (),
    ) -> None:
        capabilities = tuple(sorted(_label(item, "supported capability") for item in supported))
        if len(set(capabilities)) != len(capabilities):
            raise NumericError("supported capabilities contain duplicates")
        object.__setattr__(self, "operation", _label(operation, "operation"))
        object.__setattr__(self, "reason", _label(reason, "reason"))
        object.__setattr__(self, "requested", _requested(requested))
        object.__setattr__(self, "supported", capabilities)

    def verify(self) -> bool:
        if (
            UnsupportedNumeric(
                self.operation,
                self.reason,
                requested=self.requested.to_dict(),
                supported=self.supported,
            )
            != self
        ):
            raise NumericVerificationError("unsupported result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "operation": self.operation,
            "reason": self.reason,
            "requested": canonical_data(self.requested.to_dict()),
            "supported": list(self.supported),
            "type": "arbogast.numeric.unsupported",
        }


__all__ = ["NumericUnknown", "UnsupportedNumeric"]
