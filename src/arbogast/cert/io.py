"""Strict, extensible certificate transport loading."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from .base import Certificate, CertificateError, CertificateLayer
from .discovery import DiscoveryReceipt
from .theorem import TheoremCertificate
from .verification import VerificationCertificate

CertificateDecoder = Callable[[Mapping[str, object]], Certificate]


@dataclass(frozen=True)
class _Decoder:
    schema_version: str
    layer: CertificateLayer
    parser: CertificateDecoder


class CertificateDecoderRegistry:
    """Schema-to-parser registry with exact layer and identity checks."""

    def __init__(self) -> None:
        self._decoders: dict[str, _Decoder] = {}

    def register(
        self,
        schema_version: str,
        layer: CertificateLayer,
        parser: CertificateDecoder,
    ) -> None:
        if not schema_version.strip():
            raise CertificateError("certificate schema_version cannot be blank")
        candidate = _Decoder(schema_version, layer, parser)
        existing = self._decoders.get(schema_version)
        if existing is not None and existing != candidate:
            raise CertificateError(f"certificate decoder already registered: {schema_version}")
        self._decoders[schema_version] = candidate

    def schemas(self) -> tuple[str, ...]:
        return tuple(sorted(self._decoders))

    def decode(self, value: Mapping[str, object]) -> Certificate:
        if any(not isinstance(key, str) for key in value):
            raise CertificateError("certificate keys must be strings")
        raw_schema = value.get("schema_version")
        if not isinstance(raw_schema, str):
            raise CertificateError("certificate schema_version is required")
        decoder = self._decoders.get(raw_schema)
        if decoder is None:
            raise CertificateError(f"unsupported certificate schema: {raw_schema}")
        raw_layer = value.get("layer")
        if raw_layer != decoder.layer.value:
            raise CertificateError(
                f"certificate schema {raw_schema} requires layer {decoder.layer.value}, "
                f"got {raw_layer!r}"
            )
        certificate = decoder.parser(value)
        if certificate.layer is not decoder.layer:
            raise CertificateError("certificate decoder returned the wrong semantic layer")
        if getattr(certificate, "schema_version", None) != raw_schema:
            raise CertificateError("certificate decoder returned the wrong schema")
        integrity = getattr(certificate, "verify_integrity", None)
        if not callable(integrity):
            raise CertificateError("certificate decoder returned non-content-addressed evidence")
        integrity()
        expected = value.get("certificate_id")
        if expected is not None and certificate.certificate_id != expected:
            raise CertificateError(
                f"certificate content address mismatch: expected {expected}, "
                f"computed {certificate.certificate_id}"
            )
        return certificate


default_decoders = CertificateDecoderRegistry()
default_decoders.register(
    DiscoveryReceipt.schema_version,
    CertificateLayer.DISCOVERY,
    DiscoveryReceipt.from_dict,
)
default_decoders.register(
    VerificationCertificate.schema_version,
    CertificateLayer.VERIFICATION,
    VerificationCertificate.from_dict,
)
default_decoders.register(
    TheoremCertificate.schema_version,
    CertificateLayer.THEOREM,
    TheoremCertificate.from_dict,
)


def certificate_decoder(
    schema_version: str,
    *,
    layer: CertificateLayer,
    registry: CertificateDecoderRegistry = default_decoders,
) -> Callable[[CertificateDecoder], CertificateDecoder]:
    """Register a strict domain certificate parser."""

    def decorate(parser: CertificateDecoder) -> CertificateDecoder:
        registry.register(schema_version, layer, parser)
        return parser

    return decorate


def certificate_from_dict(
    value: Mapping[str, object],
    *,
    registry: CertificateDecoderRegistry = default_decoders,
) -> Certificate:
    """Decode a certificate through its exact registered schema."""

    return registry.decode(value)


def certificate_from_json(
    value: str | bytes,
    *,
    registry: CertificateDecoderRegistry = default_decoders,
) -> Certificate:
    """Decode a certificate from JSON, rejecting non-object top-level data."""

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except CertificateError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CertificateError(f"invalid certificate JSON: {exc}") from exc
    except ValueError as exc:
        raise CertificateError(f"invalid certificate JSON value: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise CertificateError("certificate JSON must contain an object")
    if any(not isinstance(key, str) for key in decoded):
        raise CertificateError("certificate keys must be strings")
    return certificate_from_dict(cast(Mapping[str, object], decoded), registry=registry)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON fields before Python can erase them."""

    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise CertificateError(f"duplicate JSON object key: {key!r}")
        result[key] = item
    return result


def _reject_float(value: str) -> float:
    raise CertificateError(
        f"bare floating-point JSON value {value!r} is not exact certificate evidence"
    )


__all__ = [
    "CertificateDecoder",
    "CertificateDecoderRegistry",
    "certificate_decoder",
    "certificate_from_dict",
    "certificate_from_json",
    "default_decoders",
]
