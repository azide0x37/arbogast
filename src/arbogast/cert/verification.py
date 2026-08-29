"""Independent finite verification certificates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from .base import CertificateError, CertificateLayer, CertificateRef, ContentAddressedCertificate
from .canonical import FrozenMap, freeze_mapping, validate_content_address


@dataclass(frozen=True)
class VerificationCertificate(ContentAddressedCertificate):
    """A compact witness checked independently of discovery."""

    subject: str
    verifier: str
    claim_id: str | None = None
    statement_hash: str | None = None
    witness: FrozenMap = field(default_factory=FrozenMap)
    checks: tuple[str, ...] = ()
    dependencies: tuple[CertificateRef, ...] = ()
    guarantees: tuple[str, ...] = ()

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION
    schema_version: ClassVar[str] = "arbogast.cert.verification/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str):
            raise CertificateError("verification subject must be a string")
        if not self.subject.strip():
            raise CertificateError("verification subject cannot be blank")
        if not isinstance(self.verifier, str):
            raise CertificateError("verifier name must be a string")
        if not self.verifier.strip():
            raise CertificateError("verifier name cannot be blank")
        if self.claim_id is not None and (
            not isinstance(self.claim_id, str) or not self.claim_id.strip()
        ):
            raise CertificateError("claim_id must be a non-blank string")
        if self.statement_hash is not None:
            validate_content_address(self.statement_hash)
        if (self.claim_id is None) != (self.statement_hash is None):
            raise CertificateError(
                "claim_id and statement_hash must be supplied together for bound evidence"
            )
        object.__setattr__(self, "witness", freeze_mapping(self.witness))
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "guarantees", tuple(self.guarantees))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        if any(not isinstance(check, str) or not check.strip() for check in self.checks):
            raise CertificateError("verification check names cannot be blank")
        if any(
            not isinstance(guarantee, str) or not guarantee.strip() for guarantee in self.guarantees
        ):
            raise CertificateError("verification guarantees cannot be blank")
        if any(not isinstance(ref, CertificateRef) for ref in self.dependencies):
            raise CertificateError("verification dependencies must be CertificateRef values")
        if any(ref.layer is not CertificateLayer.VERIFICATION for ref in self.dependencies):
            raise CertificateError(
                "verification certificates may depend only on verification-layer evidence"
            )
        dependency_ids = tuple(ref.certificate_id for ref in self.dependencies)
        if len(set(dependency_ids)) != len(dependency_ids):
            raise CertificateError("verification certificate dependencies must be unique")

    @classmethod
    def create(
        cls,
        subject: str,
        verifier: str,
        *,
        claim_id: str | None = None,
        statement_hash: str | None = None,
        witness: Mapping[str, object] | None = None,
        checks: Sequence[str] = (),
        dependencies: Sequence[CertificateRef] = (),
        guarantees: Sequence[str] = (),
    ) -> VerificationCertificate:
        return cls(
            subject=subject,
            verifier=verifier,
            claim_id=claim_id,
            statement_hash=statement_hash,
            witness=freeze_mapping(witness),
            checks=tuple(checks),
            dependencies=tuple(dependencies),
            guarantees=tuple(guarantees),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "subject": self.subject,
            "verifier": self.verifier,
            "claim_id": self.claim_id,
            "statement_hash": self.statement_hash,
            "witness": self.witness,
            "checks": self.checks,
            "dependencies": self.dependencies,
            "guarantees": self.guarantees,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> VerificationCertificate:
        from .discovery import _mapping, _require_fields, _required_string, _strings

        _require_fields(
            value,
            required={"schema_version", "layer", "subject", "verifier"},
            allowed={
                "schema_version",
                "layer",
                "subject",
                "verifier",
                "claim_id",
                "statement_hash",
                "witness",
                "checks",
                "dependencies",
                "guarantees",
                "certificate_id",
            },
            record="verification certificate",
        )
        if value.get("schema_version") != cls.schema_version:
            raise CertificateError("missing or unsupported verification certificate schema")
        if value.get("layer") != cls.layer.value:
            raise CertificateError("verification certificate has the wrong semantic layer")

        raw_dependencies = value.get("dependencies", ())
        if isinstance(raw_dependencies, str) or not isinstance(raw_dependencies, Sequence):
            raise CertificateError("dependencies must be a sequence")
        dependencies: list[CertificateRef] = []
        for raw in raw_dependencies:
            if not isinstance(raw, Mapping):
                raise CertificateError("certificate dependency must be a mapping")
            dependencies.append(CertificateRef.from_dict(raw))
        raw_claim_id = value.get("claim_id")
        raw_statement_hash = value.get("statement_hash")
        if raw_claim_id is not None and not isinstance(raw_claim_id, str):
            raise CertificateError("claim_id must be a string or null")
        if raw_statement_hash is not None and not isinstance(raw_statement_hash, str):
            raise CertificateError("statement_hash must be a string or null")
        certificate = cls.create(
            subject=_required_string(value, "subject"),
            verifier=_required_string(value, "verifier"),
            claim_id=raw_claim_id,
            statement_hash=raw_statement_hash,
            witness=_mapping(value.get("witness")),
            checks=_strings(value.get("checks")),
            dependencies=dependencies,
            guarantees=_strings(value.get("guarantees")),
        )
        expected = value.get("certificate_id")
        if expected is not None:
            if not isinstance(expected, str):
                raise CertificateError("certificate_id must be a string")
            certificate.verify_integrity(expected)
        return certificate


__all__ = ["VerificationCertificate"]
