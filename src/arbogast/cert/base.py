"""Common certificate types and content-addressing contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol, cast, runtime_checkable

from .canonical import canonicalize, content_address, validate_content_address


class CertificateError(ValueError):
    """Base class for invalid certificate records."""


class CertificateLayer(StrEnum):
    """The three deliberately separate proof-carrying-computation layers."""

    DISCOVERY = "discovery"
    VERIFICATION = "verification"
    THEOREM = "theorem"


@runtime_checkable
class Certificate(Protocol):
    """Structural protocol shared by all certificate layers."""

    @property
    def layer(self) -> CertificateLayer:
        """Return the semantic certificate layer."""

    @property
    def certificate_id(self) -> str:
        """Return the deterministic content address."""

    def to_canonical(self) -> object:
        """Return the payload covered by ``certificate_id``."""

    def to_dict(self) -> dict[str, object]:
        """Return a transport representation including ``certificate_id``."""


@dataclass(frozen=True)
class CertificateRef:
    """Typed reference to a content-addressed certificate."""

    certificate_id: str
    layer: CertificateLayer
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.certificate_id, str):
            raise CertificateError("certificate_id must be a string")
        validate_content_address(self.certificate_id)
        if isinstance(self.layer, str):
            try:
                object.__setattr__(self, "layer", CertificateLayer(self.layer))
            except ValueError as exc:
                raise CertificateError(f"invalid certificate layer: {self.layer!r}") from exc
        elif not isinstance(self.layer, CertificateLayer):
            raise CertificateError("certificate layer must be a CertificateLayer")
        if self.schema_version is not None:
            if not isinstance(self.schema_version, str):
                raise CertificateError("schema_version must be a string or null")
            if not self.schema_version.strip():
                raise CertificateError("schema_version cannot be blank")

    @classmethod
    def from_certificate(cls, certificate: Certificate) -> CertificateRef:
        schema = getattr(certificate, "schema_version", None)
        return cls(certificate.certificate_id, certificate.layer, schema)

    def to_canonical(self) -> dict[str, object]:
        result: dict[str, object] = {
            "certificate_id": self.certificate_id,
            "layer": self.layer.value,
        }
        if self.schema_version is not None:
            result["schema_version"] = self.schema_version
        return result

    def to_dict(self) -> dict[str, object]:
        return self.to_canonical()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CertificateRef:
        """Decode a reference without coercing malformed transport values."""

        allowed = {"certificate_id", "layer", "schema_version"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise CertificateError(
                f"unexpected certificate reference fields: {', '.join(unexpected)}"
            )
        certificate_id = value.get("certificate_id")
        layer = value.get("layer")
        schema = value.get("schema_version")
        if not isinstance(certificate_id, str):
            raise CertificateError("certificate reference certificate_id must be a string")
        if not isinstance(layer, str):
            raise CertificateError("certificate reference layer must be a string")
        if schema is not None and not isinstance(schema, str):
            raise CertificateError("certificate reference schema_version must be a string or null")
        try:
            parsed_layer = CertificateLayer(layer)
        except ValueError as exc:
            raise CertificateError(f"invalid certificate layer: {layer!r}") from exc
        return cls(certificate_id, parsed_layer, schema)


class ContentAddressedCertificate:
    """Mixin implementing deterministic certificate identity and integrity checks."""

    layer: ClassVar[CertificateLayer]

    @property
    def certificate_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> object:
        raise NotImplementedError

    def to_dict(self) -> dict[str, object]:
        payload = self.to_canonical()
        if not isinstance(payload, dict):
            raise CertificateError("certificate canonical payload must be a mapping")
        plain = canonicalize({**payload, "certificate_id": self.certificate_id})
        if not isinstance(plain, dict):
            raise CertificateError("certificate canonical payload must be an object")
        return cast(dict[str, object], plain)

    def verify_integrity(self, expected_id: str | None = None) -> str:
        """Check structural content integrity, not the mathematical assertion."""

        address = expected_id or self.certificate_id
        return validate_content_address(address, self.to_canonical())


__all__ = [
    "Certificate",
    "CertificateError",
    "CertificateLayer",
    "CertificateRef",
    "ContentAddressedCertificate",
]
