"""Strict canonical and semantic support for the bounded p-adic layer."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from functools import wraps
from importlib import import_module
from typing import ClassVar, cast

from arbogast.cert import VerificationCertificate, canonical_bytes
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import CanonicalJSON, CanonicalObject, canonical_data

# Generic canonical-envelope bounds.  These apply to runtime replay and to the
# receipt transport; domain modules may impose smaller algebraic bounds.
MAX_CANONICAL_NODES = 100_000
MAX_CANONICAL_DEPTH = 128
MAX_CANONICAL_INTEGER_BITS = 4096
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
MAX_TEXT_LENGTH = 16_384
MAX_RECEIPT_DEPENDENCIES = 256
MAX_ASSUMPTIONS = 256
MAX_PROOF_OBLIGATIONS = 256
MAX_CLAIM_DEPENDENCIES = 4096

# Shared portable algebraic bounds for the initial 0.5 vertical slice.
MAX_PRIME_BITS = 256
MAX_LOCAL_DEGREE = 64
MAX_PRECISION = 4096
MAX_DIMENSION = 64
MAX_MATRIX_CELLS = MAX_DIMENSION * MAX_DIMENSION
MAX_GROUP_ORDER = 1024
MAX_GROUP_TABLE_CELLS = MAX_GROUP_ORDER * MAX_GROUP_ORDER
MAX_PRECISION_WORK = 65_536
MAX_EXACT_REPLAY_WORK = 10_000_000
MAX_CHARTS = 1024
MAX_OVERLAPS = 8192
MAX_COMPONENTS = 4096
MAX_SPECIAL_FIBER_NODES = 8192
MAX_LIFTS = 4096

PADIC_PROOF_OBLIGATION_SCHEMA_V1 = "arbogast.padic.proof-obligation/v1"
PADIC_CERTIFIED_SCHEMA_V1 = "arbogast.padic.certified/v1"
PADIC_PARTIAL_SCHEMA_V1 = "arbogast.padic.partial/v1"
PADIC_UNKNOWN_SCHEMA_V1 = "arbogast.padic.unknown/v1"
PADIC_UNSUPPORTED_SCHEMA_V1 = "arbogast.padic.unsupported/v1"

_VERIFY_DEPTH: ContextVar[int] = ContextVar("padic_verify_depth", default=0)


def strict_int(value: object, name: str, *, minimum: int | None = None) -> int:
    """Return an exact integer, rejecting booleans and silent coercions."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def canonical_label(value: object, name: str) -> str:
    """Return strict trimmed NFC text without normalizing altered transport."""

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        not value
        or value.strip() != value
        or unicodedata.normalize("NFC", value) != value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError(f"{name} must be nonempty trimmed printable NFC text")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds the portable text-length bound")
    return value


def strict_canonical_equal(value: object, expected: object) -> bool:
    """Compare raw JSON shapes without tuple/list or scalar aliases."""

    if type(expected) is dict:
        if type(value) is not dict:
            return False
        left = cast(dict[object, object], value)
        right = cast(dict[object, object], expected)
        return left.keys() == right.keys() and all(
            strict_canonical_equal(left[key], right[key]) for key in left
        )
    if type(expected) is list:
        if type(value) is not list:
            return False
        left_items = cast(list[object], value)
        right_items = cast(list[object], expected)
        return len(left_items) == len(right_items) and all(
            strict_canonical_equal(left_item, right_item)
            for left_item, right_item in zip(left_items, right_items, strict=True)
        )
    return type(value) is type(expected) and value == expected


def ensure_canonical_bounds(
    value: object,
    name: str = "p-adic object",
    *,
    depth: int = 0,
) -> int:
    """Reject values outside strict canonical JSON or the portable envelope."""

    from .errors import PAdicResourceError, PAdicVerificationError

    if depth > MAX_CANONICAL_DEPTH:
        raise PAdicResourceError(f"{name} exceeds the portable nesting-depth bound")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if value.bit_length() > MAX_CANONICAL_INTEGER_BITS:
            raise PAdicResourceError(f"{name} contains an oversized integer")
        return 1
    if type(value) is str:
        text = value
        if text != unicodedata.normalize("NFC", text):
            raise PAdicVerificationError(f"{name} contains noncanonical Unicode text")
        if len(text) > MAX_TEXT_LENGTH:
            raise PAdicResourceError(f"{name} contains oversized text")
        return 1
    if type(value) is list:
        count = 1
        for index, item in enumerate(cast(list[object], value)):
            count += ensure_canonical_bounds(item, f"{name}[{index}]", depth=depth + 1)
            if count > MAX_CANONICAL_NODES:
                raise PAdicResourceError(f"{name} exceeds the portable node bound")
        return count
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise PAdicVerificationError(f"{name} contains a non-string mapping key")
        count = 1
        for key, item in mapping.items():
            text_key = cast(str, key)
            if text_key != unicodedata.normalize("NFC", text_key):
                raise PAdicVerificationError(f"{name} contains a noncanonical mapping key")
            if len(text_key) > MAX_TEXT_LENGTH:
                raise PAdicResourceError(f"{name} contains an oversized mapping key")
            count += ensure_canonical_bounds(
                item,
                f"{name}.{text_key}",
                depth=depth + 1,
            )
            if count > MAX_CANONICAL_NODES:
                raise PAdicResourceError(f"{name} exceeds the portable node bound")
        return count
    raise PAdicVerificationError(
        f"{name} contains noncanonical {type(value).__module__}.{type(value).__qualname__}"
    )


def ensure_canonical_envelope(value: object, name: str = "p-adic object") -> int:
    """Apply shape, aggregate-node, integer, text, depth, and byte bounds."""

    from .errors import PAdicResourceError, PAdicVerificationError

    count = ensure_canonical_bounds(value, name)
    try:
        encoded = canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"{name} is not canonical JSON: {exc}") from exc
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise PAdicResourceError(f"{name} exceeds the portable byte bound")
    return count


def strict_canonical_mapping(value: Mapping[str, object], name: str) -> dict[str, CanonicalJSON]:
    """Require a raw mapping already equal to its strict canonical JSON form."""

    from .errors import PAdicVerificationError

    raw = dict(value)
    normalized = canonical_data(raw)
    if not isinstance(normalized, dict) or not strict_canonical_equal(raw, normalized):
        raise PAdicVerificationError(f"{name} must already equal strict canonical JSON")
    ensure_canonical_envelope(normalized, name)
    return normalized


class PAdicSchemaObject(CanonicalObject):
    """Canonical p-adic object carrying one additive wire-schema ID."""

    schema_version: ClassVar[str]

    def verify(self) -> bool:
        """Replay this exact value; concrete schema objects must override."""

        raise NotImplementedError

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Apply the receipt envelope once to each top-level successful replay."""

        super().__init_subclass__(**kwargs)
        raw_verify = cls.__dict__.get("verify")
        if raw_verify is None or getattr(raw_verify, "_padic_bounds_wrapped", False):
            return
        verify = cast(Callable[..., object], raw_verify)

        @wraps(verify)
        def bounded_verify(self: PAdicSchemaObject, *args: object, **inner: object) -> object:
            depth = _VERIFY_DEPTH.get()
            token = _VERIFY_DEPTH.set(depth + 1)
            try:
                result = verify(self, *args, **inner)
                if result is True and depth == 0:
                    ensure_canonical_envelope(self.to_schema_document(), type(self).__qualname__)
                return result
            finally:
                _VERIFY_DEPTH.reset(token)

        bounded_verify.__dict__["_padic_bounds_wrapped"] = True
        type.__setattr__(cls, "verify", bounded_verify)

    def to_schema_document(self) -> dict[str, CanonicalJSON]:
        payload = self.to_canonical_data()
        if not isinstance(payload, dict):
            raise TypeError("p-adic schema objects must encode as canonical mappings")
        return {"schema": self.schema_version, **payload}


class PAdicSemanticObject(PAdicSchemaObject):
    """P-adic result exposing lazy central certificate and claim adapters."""

    @property
    def certificate(self) -> VerificationCertificate:
        semantic = import_module("arbogast.padic.semantic")
        return cast(
            VerificationCertificate,
            semantic.verification_certificate_for_result(self),
        )

    def claim(self) -> Claim:
        semantic = import_module("arbogast.padic.semantic")
        return cast(Claim, semantic.claim_for_result(self))

    def claim_graph(self) -> ClaimGraph:
        semantic = import_module("arbogast.padic.semantic")
        return cast(ClaimGraph, semantic.claim_graph_for_result(self))


__all__ = [
    "MAX_ASSUMPTIONS",
    "MAX_CANONICAL_BYTES",
    "MAX_CANONICAL_DEPTH",
    "MAX_CANONICAL_INTEGER_BITS",
    "MAX_CANONICAL_NODES",
    "MAX_CHARTS",
    "MAX_CLAIM_DEPENDENCIES",
    "MAX_COMPONENTS",
    "MAX_DIMENSION",
    "MAX_EXACT_REPLAY_WORK",
    "MAX_GROUP_ORDER",
    "MAX_GROUP_TABLE_CELLS",
    "MAX_LIFTS",
    "MAX_LOCAL_DEGREE",
    "MAX_MATRIX_CELLS",
    "MAX_OVERLAPS",
    "MAX_PRECISION",
    "MAX_PRECISION_WORK",
    "MAX_PRIME_BITS",
    "MAX_PROOF_OBLIGATIONS",
    "MAX_RECEIPT_DEPENDENCIES",
    "MAX_SPECIAL_FIBER_NODES",
    "MAX_TEXT_LENGTH",
    "PADIC_CERTIFIED_SCHEMA_V1",
    "PADIC_PARTIAL_SCHEMA_V1",
    "PADIC_PROOF_OBLIGATION_SCHEMA_V1",
    "PADIC_UNKNOWN_SCHEMA_V1",
    "PADIC_UNSUPPORTED_SCHEMA_V1",
    "PAdicSchemaObject",
    "PAdicSemanticObject",
    "canonical_label",
    "ensure_canonical_bounds",
    "ensure_canonical_envelope",
    "strict_canonical_equal",
    "strict_canonical_mapping",
    "strict_int",
]
