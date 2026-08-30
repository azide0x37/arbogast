"""Typed boundaries for the finite exact deformation slice."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from arbogast.cert import FrozenMap, freeze_mapping
from arbogast.core import (
    CanonicalEncodingError,
    CanonicalJSON,
    VerificationError,
    canonical_data,
)
from arbogast.formats import DEFORM_UNSUPPORTED_SCHEMA_V1

from ._schema import DeformationSemanticObject


class DeformationError(ValueError):
    """Base class for invalid finite deformation data."""


class DeformationVerificationError(DeformationError, VerificationError):
    """Raised when an independently replayed finite witness fails."""


class UnsupportedDeformationOperation(DeformationError, NotImplementedError):
    """Raised when a constructor is outside the bounded automatic slice."""


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeformationError(f"{name} must be a non-empty string")
    return unicodedata.normalize("NFC", value.strip())


def _strict_json_equal(value: object, canonical: object) -> bool:
    if type(canonical) is dict:
        if type(value) is not dict:
            return False
        source = cast(dict[object, object], value)
        target = cast(dict[object, object], canonical)
        return source.keys() == target.keys() and all(
            _strict_json_equal(source[key], target[key]) for key in source
        )
    if type(canonical) is list:
        if type(value) is not list:
            return False
        source_list = cast(list[object], value)
        target_list = cast(list[object], canonical)
        return len(source_list) == len(target_list) and all(
            _strict_json_equal(left, right)
            for left, right in zip(source_list, target_list, strict=True)
        )
    return type(value) is type(canonical) and value == canonical


def _canonical_requested(value: Mapping[str, object]) -> dict[str, object]:
    raw = dict(value)
    try:
        normalized = canonical_data(raw)
    except CanonicalEncodingError as exc:
        raise DeformationError(
            f"unsupported requested parameters are not strict core canonical data: {exc}"
        ) from exc
    if not isinstance(normalized, dict) or not _strict_json_equal(raw, normalized):
        raise DeformationError(
            "unsupported requested parameters must already equal strict core canonical data"
        )
    return cast(dict[str, object], normalized)


@dataclass(frozen=True, slots=True, init=False)
class UnsupportedDeformation(DeformationSemanticObject):
    """A serializable refusal that does not invent a mathematical result."""

    operation: str
    reason: str
    requested: FrozenMap
    supported: tuple[str, ...]

    schema_version = DEFORM_UNSUPPORTED_SCHEMA_V1

    def __init__(
        self,
        operation: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None = None,
        supported: Sequence[str] = (),
    ) -> None:
        canonical_requested = _canonical_requested(requested or {})
        normalized_supported = tuple(_label(item, "supported capability") for item in supported)
        if len(set(normalized_supported)) != len(normalized_supported):
            raise DeformationError("supported capabilities contain duplicates")
        object.__setattr__(self, "operation", _label(operation, "operation"))
        object.__setattr__(self, "reason", _label(reason, "reason"))
        object.__setattr__(self, "requested", freeze_mapping(canonical_requested))
        object.__setattr__(self, "supported", tuple(sorted(normalized_supported)))

    def verify(self) -> bool:
        replay = UnsupportedDeformation(
            self.operation,
            self.reason,
            requested=self.requested.to_dict(),
            supported=self.supported,
        )
        if replay != self:
            raise DeformationVerificationError("unsupported result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "operation": self.operation,
            "reason": self.reason,
            "requested": canonical_data(self.requested.to_dict()),
            "supported": list(self.supported),
            "type": "arbogast.deform.unsupported",
        }


__all__ = [
    "DeformationError",
    "DeformationVerificationError",
    "UnsupportedDeformation",
    "UnsupportedDeformationOperation",
]
