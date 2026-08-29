"""Theorem-level certificates that bind verified evidence to a claim."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from .base import CertificateError, CertificateLayer, CertificateRef, ContentAddressedCertificate
from .canonical import FrozenMap, freeze_mapping, validate_content_address


@dataclass(frozen=True)
class TheoremCertificate(ContentAddressedCertificate):
    """Bind a formal statement and verified finite evidence to a theorem claim."""

    claim_id: str
    statement_hash: str
    verifier: str
    verification_certificates: tuple[CertificateRef, ...]
    dependencies: tuple[str, ...] = ()
    conclusion: FrozenMap = field(default_factory=FrozenMap)
    theorem_name: str | None = None

    layer: ClassVar[CertificateLayer] = CertificateLayer.THEOREM
    schema_version: ClassVar[str] = "arbogast.cert.theorem/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str):
            raise CertificateError("theorem claim_id must be a string")
        if not self.claim_id.strip():
            raise CertificateError("theorem claim_id cannot be blank")
        if not isinstance(self.verifier, str):
            raise CertificateError("theorem verifier must be a string")
        if not self.verifier.strip():
            raise CertificateError("theorem certificate requires an inference verifier")
        validate_content_address(self.statement_hash)
        refs = tuple(self.verification_certificates)
        if not refs:
            raise CertificateError("theorem certificate requires verified evidence")
        if any(not isinstance(ref, CertificateRef) for ref in refs):
            raise CertificateError("theorem evidence must contain CertificateRef values")
        if any(ref.layer is not CertificateLayer.VERIFICATION for ref in refs):
            raise CertificateError(
                "theorem certificates may be supported only by verification-layer evidence"
            )
        ref_ids = tuple(ref.certificate_id for ref in refs)
        if len(set(ref_ids)) != len(ref_ids):
            raise CertificateError("theorem verification certificates must be unique")
        object.__setattr__(self, "verification_certificates", refs)
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "conclusion", freeze_mapping(self.conclusion))
        if any(
            not isinstance(dependency, str) or not dependency.strip()
            for dependency in self.dependencies
        ):
            raise CertificateError("theorem dependency IDs cannot be blank")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise CertificateError("theorem dependency IDs must be unique")
        if self.theorem_name is not None and (
            not isinstance(self.theorem_name, str) or not self.theorem_name.strip()
        ):
            raise CertificateError("theorem_name must be a non-blank string")

    @classmethod
    def create(
        cls,
        claim_id: str,
        statement_hash: str,
        verification_certificates: Sequence[CertificateRef],
        *,
        verifier: str,
        dependencies: Sequence[str] = (),
        conclusion: Mapping[str, object] | None = None,
        theorem_name: str | None = None,
    ) -> TheoremCertificate:
        return cls(
            claim_id=claim_id,
            statement_hash=statement_hash,
            verifier=verifier,
            verification_certificates=tuple(verification_certificates),
            dependencies=tuple(dependencies),
            conclusion=freeze_mapping(conclusion),
            theorem_name=theorem_name,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "claim_id": self.claim_id,
            "statement_hash": self.statement_hash,
            "verifier": self.verifier,
            "verification_certificates": self.verification_certificates,
            "dependencies": self.dependencies,
            "conclusion": self.conclusion,
            "theorem_name": self.theorem_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TheoremCertificate:
        from .discovery import _mapping, _require_fields, _required_string, _strings

        _require_fields(
            value,
            required={
                "schema_version",
                "layer",
                "claim_id",
                "statement_hash",
                "verifier",
                "verification_certificates",
            },
            allowed={
                "schema_version",
                "layer",
                "claim_id",
                "statement_hash",
                "verifier",
                "verification_certificates",
                "dependencies",
                "conclusion",
                "theorem_name",
                "certificate_id",
            },
            record="theorem certificate",
        )
        if value.get("schema_version") != cls.schema_version:
            raise CertificateError("missing or unsupported theorem certificate schema")
        if value.get("layer") != cls.layer.value:
            raise CertificateError("theorem certificate has the wrong semantic layer")

        raw_refs = value.get("verification_certificates")
        if isinstance(raw_refs, str) or not isinstance(raw_refs, Sequence):
            raise CertificateError("verification_certificates must be a sequence")
        refs: list[CertificateRef] = []
        for raw in raw_refs:
            if not isinstance(raw, Mapping):
                raise CertificateError("certificate reference must be a mapping")
            refs.append(CertificateRef.from_dict(raw))
        theorem_name = value.get("theorem_name")
        if theorem_name is not None and not isinstance(theorem_name, str):
            raise CertificateError("theorem_name must be a string or null")
        theorem = cls.create(
            claim_id=_required_string(value, "claim_id"),
            statement_hash=_required_string(value, "statement_hash"),
            verifier=_required_string(value, "verifier"),
            verification_certificates=refs,
            dependencies=_strings(value.get("dependencies")),
            conclusion=_mapping(value.get("conclusion")),
            theorem_name=theorem_name,
        )
        expected = value.get("certificate_id")
        if expected is not None:
            if not isinstance(expected, str):
                raise CertificateError("certificate_id must be a string")
            theorem.verify_integrity(expected)
        return theorem


__all__ = ["TheoremCertificate"]
