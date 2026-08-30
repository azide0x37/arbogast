"""Independent arithmetic proof axes and typed unsupported outcomes.

The arithmetic layer deliberately keeps three questions separate:

* which mathematical assumptions remain;
* which verifier implementation must be trusted; and
* whether an enumeration is merely a candidate or is complete.

None of the types in this module silently promotes one axis from evidence on
another.  In particular, a successful pinned external verifier can be
unconditional while remaining non-portable.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arbogast.cert import (
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    freeze_mapping,
    verifier,
    verify_certificate,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError
from arbogast.formats import FrozenMapping

UNSUPPORTED_VERIFIER_ID = "galois.unsupported.v1"
_UNSUPPORTED_CHECKS = (
    "canonical unsupported payload replayed",
    "operation, request, and supported boundary bound exactly",
    "no mathematical existence or nonexistence conclusion inferred",
)
_UNSUPPORTED_GUARANTEES = (
    "Only the bounded software non-support statement is certified.",
    "No mathematical claim about the requested object is certified.",
)


def _label(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or normalized.strip() != normalized
        or any(ord(character) < 0x20 for character in normalized)
    ):
        raise ValidationError(f"{name} must be a nonempty, trimmed printable string")
    return normalized


def _labels(values: Iterable[str], name: str, *, sort: bool) -> tuple[str, ...]:
    normalized = tuple(_label(value, name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{name} values must be unique")
    return tuple(sorted(normalized)) if sort else normalized


class Completeness(StrEnum):
    """Whether a finite arithmetic answer is exhaustive."""

    CANDIDATE = "candidate"
    COMPLETE = "complete"


class VerifierTrust(StrEnum):
    """The replay environment required by one verification step."""

    PORTABLE_PYTHON = "portable-python"
    PINNED_EXTERNAL = "pinned-external"


@dataclass(frozen=True, slots=True, init=False)
class VerificationRequirement(CanonicalObject):
    """One explicit verifier dependency, independent of assumptions.

    External verification is version-pinned.  Portable verification names an
    Arbogast/Python verifier and must not smuggle a host-specific version into
    its identity.
    """

    verifier: str
    trust: VerifierTrust
    version: str | None
    capabilities: tuple[str, ...]

    def __init__(
        self,
        verifier: str,
        trust: VerifierTrust | str,
        *,
        version: str | None = None,
        capabilities: Iterable[str] = (),
    ) -> None:
        verifier = _label(verifier, "verifier")
        try:
            normalized_trust = VerifierTrust(trust)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported verifier trust boundary: {trust!r}") from error
        if version is not None:
            version = _label(version, "verifier version")
        if normalized_trust is VerifierTrust.PINNED_EXTERNAL and version is None:
            raise ValidationError("an external verifier requirement must pin an exact version")
        if normalized_trust is VerifierTrust.PORTABLE_PYTHON and version is not None:
            raise ValidationError(
                "a portable Python verifier requirement cannot pin a host version"
            )
        normalized_capabilities = _labels(capabilities, "verifier capability", sort=True)
        object.__setattr__(self, "verifier", verifier)
        object.__setattr__(self, "trust", normalized_trust)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "capabilities", normalized_capabilities)

    @classmethod
    def portable_python(
        cls,
        verifier: str,
        *,
        capabilities: Iterable[str] = (),
    ) -> VerificationRequirement:
        return cls(
            verifier,
            VerifierTrust.PORTABLE_PYTHON,
            capabilities=capabilities,
        )

    @classmethod
    def pinned_external(
        cls,
        verifier: str,
        version: str,
        *,
        capabilities: Iterable[str] = (),
    ) -> VerificationRequirement:
        return cls(
            verifier,
            VerifierTrust.PINNED_EXTERNAL,
            version=version,
            capabilities=capabilities,
        )

    @property
    def portable(self) -> bool:
        return self.trust is VerifierTrust.PORTABLE_PYTHON

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "capabilities": list(self.capabilities),
            "trust": self.trust.value,
            "type": "arbogast.verification_requirement",
            "verifier": self.verifier,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def verify(self) -> bool:
        return (
            VerificationRequirement(
                self.verifier,
                self.trust,
                version=self.version,
                capabilities=self.capabilities,
            )
            == self
        )


@dataclass(frozen=True, slots=True, init=False)
class ProofContext(CanonicalObject):
    """The three evidence axes attached to an arithmetic computation."""

    assumptions: tuple[str, ...]
    verification_requirements: tuple[VerificationRequirement, ...]
    completeness: Completeness

    def __init__(
        self,
        assumptions: Iterable[str] = (),
        verification_requirements: Iterable[VerificationRequirement] = (),
        completeness: Completeness | str = Completeness.CANDIDATE,
    ) -> None:
        normalized_assumptions = _labels(assumptions, "assumption", sort=True)
        requirements = tuple(verification_requirements)
        if any(not isinstance(item, VerificationRequirement) for item in requirements):
            raise TypeError("verification_requirements must contain VerificationRequirement values")
        requirement_keys = tuple(
            (item.verifier, item.trust.value, item.version, item.capabilities)
            for item in requirements
        )
        if len(set(requirement_keys)) != len(requirement_keys):
            raise ValidationError("verification requirements must be unique")
        requirements = tuple(
            item
            for _, item in sorted(
                zip(requirement_keys, requirements, strict=True),
                key=lambda pair: pair[0],
            )
        )
        try:
            normalized_completeness = Completeness(completeness)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported completeness value: {completeness!r}") from error
        object.__setattr__(self, "assumptions", normalized_assumptions)
        object.__setattr__(self, "verification_requirements", requirements)
        object.__setattr__(self, "completeness", normalized_completeness)

    @property
    def conditional(self) -> bool:
        return bool(self.assumptions)

    @property
    def portable(self) -> bool:
        return all(requirement.portable for requirement in self.verification_requirements)

    @property
    def complete(self) -> bool:
        return self.completeness is Completeness.COMPLETE

    def require_complete(self) -> None:
        if not self.complete:
            raise ValidationError("candidate evidence cannot satisfy a completeness requirement")

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "assumptions": list(self.assumptions),
                "completeness": self.completeness.value,
                "type": "arbogast.proof_context",
                "verification_requirements": [
                    requirement.to_canonical_data()
                    for requirement in self.verification_requirements
                ],
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def verify(self) -> bool:
        return (
            ProofContext(
                self.assumptions,
                self.verification_requirements,
                self.completeness,
            )
            == self
        )


@dataclass(frozen=True, slots=True, init=False)
class Unsupported(CanonicalObject):
    """A typed, serializable refusal for a deliberately deferred operation."""

    operation: str
    reason: str
    requested: FrozenMapping
    supported: tuple[str, ...]

    def __init__(
        self,
        operation: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None = None,
        supported: Iterable[str] = (),
    ) -> None:
        object.__setattr__(self, "operation", _label(operation, "operation"))
        object.__setattr__(self, "reason", _label(reason, "unsupported reason"))
        object.__setattr__(self, "requested", FrozenMapping(requested))
        object.__setattr__(self, "supported", _labels(supported, "supported capability", sort=True))

    def verify(self) -> bool:
        # Reconstruct to replay all normalization and validation checks.
        structurally_valid = (
            Unsupported(
                self.operation,
                self.reason,
                requested=self.requested.to_dict(),
                supported=self.supported,
            )
            == self
        )
        return structurally_valid and verify_certificate(self.certificate).valid

    @property
    def certificate(self) -> VerificationCertificate:
        statement = _unsupported_statement(self)
        claim_id = _unsupported_claim_id(self)
        return VerificationCertificate.create(
            subject=f"galois.unsupported:{self.content_id}",
            verifier=UNSUPPORTED_VERIFIER_ID,
            claim_id=claim_id,
            statement_hash=statement.statement_hash,
            claim_boundary_hash=claim_boundary_hash(
                claim_id,
                statement,
                kind=ClaimKind.COMPUTED,
                status=EpistemicStatus.EXACT,
            ),
            witness={"unsupported": self.to_dict()},
            checks=_UNSUPPORTED_CHECKS,
            guarantees=_UNSUPPORTED_GUARANTEES,
        )

    def claim(self) -> Claim:
        certificate = self.certificate
        return Claim(
            _unsupported_claim_id(self),
            statement=_unsupported_statement(self),
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation(
                self.operation,
                method="Exact replay of Arbogast's declared bounded support surface",
                inputs=(self.content_id,),
                artifact=certificate.certificate_id,
            ),
            certificate=certificate,
            metadata={
                "mathematical_conclusion": False,
                "unsupported_payload": self.content_id,
            },
        )

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "operation": self.operation,
                "reason": self.reason,
                "requested": self.requested.to_dict(),
                "supported": list(self.supported),
                "type": "arbogast.unsupported",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())


def _unsupported_claim_id(result: Unsupported) -> str:
    return f"galois.unsupported.{result.content_id.split(':', 1)[1]}"


def _unsupported_statement(result: Unsupported) -> FormalStatement:
    return FormalStatement.create(
        f"Arbogast operation {result.operation} does not support the exact requested "
        "input within the declared 0.2 bounded surface; this is a software-boundary "
        "statement and implies no mathematical nonexistence.",
        parameters={
            "operation": result.operation,
            "reason": result.reason,
            "requested": result.requested.to_dict(),
            "supported": result.supported,
            "unsupported_payload": result.content_id,
        },
    )


@verifier(UNSUPPORTED_VERIFIER_ID, certificate_type=VerificationCertificate)
def _verify_unsupported_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    if certificate.verifier != UNSUPPORTED_VERIFIER_ID:
        raise CertificateVerificationError("unsupported certificate names a different verifier")
    witness = certificate.witness.to_dict()
    if set(witness) != {"unsupported"} or not isinstance(witness["unsupported"], Mapping):
        raise CertificateVerificationError(
            "unsupported certificate must contain exactly one unsupported payload"
        )
    raw = cast(Mapping[str, object], witness["unsupported"])
    if set(raw) != {"operation", "reason", "requested", "supported", "type"}:
        raise CertificateVerificationError("unsupported payload fields were altered")
    if raw.get("type") != "arbogast.unsupported":
        raise CertificateVerificationError("unsupported payload type was altered")
    requested = raw.get("requested")
    supported = raw.get("supported")
    if (
        not isinstance(requested, Mapping)
        or isinstance(supported, str)
        or not isinstance(supported, Iterable)
    ):
        raise CertificateVerificationError("unsupported payload has malformed boundaries")
    try:
        result = Unsupported(
            cast(str, raw.get("operation")),
            cast(str, raw.get("reason")),
            requested=cast(Mapping[str, object], requested),
            supported=cast(Iterable[str], supported),
        )
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    if result.to_dict() != dict(raw):
        raise CertificateVerificationError("unsupported payload is not canonical")
    statement = _unsupported_statement(result)
    claim_id = _unsupported_claim_id(result)
    if certificate.subject != f"galois.unsupported:{result.content_id}":
        raise CertificateVerificationError("unsupported certificate subject binding was altered")
    if certificate.claim_id != claim_id or certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("unsupported certificate claim binding was altered")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("unsupported certificate claim boundary was altered")
    if certificate.dependencies or certificate.claim_dependencies:
        raise CertificateVerificationError("unsupported certificate cannot depend on evidence")
    if certificate.checks != _UNSUPPORTED_CHECKS:
        raise CertificateVerificationError("unsupported certificate checks were altered")
    if certificate.guarantees != _UNSUPPORTED_GUARANTEES:
        raise CertificateVerificationError("unsupported certificate guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=UNSUPPORTED_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_UNSUPPORTED_CHECKS,
        details=freeze_mapping(
            {
                "mathematical_conclusion": False,
                "unsupported_payload": result.content_id,
            }
        ),
    )


__all__ = [
    "UNSUPPORTED_VERIFIER_ID",
    "Completeness",
    "ProofContext",
    "Unsupported",
    "VerificationRequirement",
    "VerifierTrust",
]
