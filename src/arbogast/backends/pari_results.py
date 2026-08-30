"""Typed results for the closed PARI/GP arithmetic adapter.

These records deliberately do not promote a PARI calculation into a portable
Arbogast proof.  They keep mathematical assumptions, completeness, and
verifier trust as independent fields and carry the ordinary v1 discovery
receipt used by every optional backend.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arbogast.cert import (
    DiscoveryReceipt,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    content_address,
    freeze_mapping,
    verify_certificate,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
)

from .base import BackendStatus


class PariCompleteness(StrEnum):
    """Whether the returned arithmetic payload is known to be exhaustive."""

    CANDIDATE = "CANDIDATE"
    COMPLETE = "COMPLETE"


class PariOutcome(StrEnum):
    """Operational outcome without inventing a mathematical conclusion."""

    SUCCESS = "SUCCESS"
    UNKNOWN = "UNKNOWN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class PariVerificationRequirement:
    """The verifier needed to replay the arithmetic-completeness boundary."""

    verifier: str
    version: str | None
    portable: bool

    def __post_init__(self) -> None:
        if self.verifier not in {"pari", "python"}:
            raise ValueError("PARI verification requirement must name pari or python")
        if self.verifier == "pari" and self.version is None:
            raise ValueError("a PARI verification requirement must pin a normalized version")
        if self.verifier == "python" and self.version is not None:
            raise ValueError("a Python verification requirement cannot pin a PARI version")
        if self.portable != (self.verifier == "python"):
            raise ValueError("only the Python verification requirement is portable")

    @classmethod
    def pari(cls, version: str) -> PariVerificationRequirement:
        return cls("pari", version, False)

    @classmethod
    def python(cls) -> PariVerificationRequirement:
        return cls("python", None, True)

    def to_dict(self) -> dict[str, object]:
        return {
            "portable": self.portable,
            "verifier": self.verifier,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class PariProbeResult:
    """Detailed, receipt-bearing result of the version and algebra smoke probe."""

    status: BackendStatus
    normalized_version: str | None
    raw_version: str | None
    supported_range: str
    smoke_tests: FrozenMap | Mapping[str, object]
    receipt: DiscoveryReceipt | None = None

    schema: str = "arbogast.backend.pari-probe.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "smoke_tests", freeze_mapping(self.smoke_tests))
        if not isinstance(self.supported_range, str) or not self.supported_range:
            raise ValueError("PARI probe supported range must be non-empty")
        for value in (self.normalized_version, self.raw_version):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("PARI probe versions must be non-empty strings or None")
        smoke_tests = cast(FrozenMap, self.smoke_tests)
        if any(not isinstance(value, bool) for value in smoke_tests.values()):
            raise ValueError("PARI smoke-test values must be booleans")
        if self.status.available:
            if self.normalized_version is None or self.receipt is None:
                raise ValueError("an available PARI probe needs a version and receipt")
            if not smoke_tests or not all(smoke_tests.values()):
                raise ValueError("an available PARI probe requires all advertised smoke tests")

    def to_dict(self) -> dict[str, object]:
        return {
            "normalized_version": self.normalized_version,
            "raw_version": self.raw_version,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema": self.schema,
            "smoke_tests": cast(FrozenMap, self.smoke_tests).to_dict(),
            "status": self.status.to_dict(),
            "supported_range": self.supported_range,
        }


@dataclass(frozen=True, slots=True)
class PariArithmeticResult:
    """One normalized result from an operation-specific fresh GP process."""

    operation: str
    payload: FrozenMap
    receipt: DiscoveryReceipt
    assumptions: tuple[str, ...] = ()
    completeness: PariCompleteness = PariCompleteness.CANDIDATE
    outcome: PariOutcome = PariOutcome.SUCCESS
    verification_requirement: PariVerificationRequirement | None = None
    certificate: VerificationCertificate | None = None

    schema: str = "arbogast.backend.pari-arithmetic-result.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("PARI result operation must be a non-empty string")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        if any(not isinstance(item, str) or not item for item in self.assumptions):
            raise ValueError("PARI result assumptions must be non-empty strings")
        if len(set(self.assumptions)) != len(self.assumptions):
            raise ValueError("PARI result assumptions cannot contain duplicates")
        if self.outcome is PariOutcome.SUCCESS and self.verification_requirement is None:
            raise ValueError("a successful PARI result must state its verification requirement")
        if (
            self.outcome is PariOutcome.SUCCESS
            and self.verification_requirement is not None
            and self.verification_requirement.verifier == "pari"
            and self.certificate is None
        ):
            raise ValueError("a pinned-PARI result must carry central verification evidence")
        if self.outcome is not PariOutcome.SUCCESS:
            if self.completeness is not PariCompleteness.CANDIDATE:
                raise ValueError("an unknown PARI result cannot be complete")
            if self.verification_requirement is not None:
                raise ValueError("an unknown PARI result cannot claim a verification requirement")
            if self.certificate is None:
                raise ValueError("a non-success PARI result needs an operational certificate")
            if self.certificate.verifier != "arbogast.backends.pari.operational.v1":
                raise ValueError("a non-success PARI result has the wrong operational verifier")
        elif (
            self.certificate is not None
            and self.certificate.verifier != "arbogast.backends.pari.v1"
        ):
            raise ValueError("a successful PARI result has the wrong arithmetic verifier")
        if self.assumptions and self.outcome is not PariOutcome.SUCCESS:
            raise ValueError("an unknown result cannot turn assumptions into evidence")

    @property
    def conditional(self) -> bool:
        return bool(self.assumptions)

    def proof_context(self) -> object:
        """Convert to the shared arithmetic proof-axis model without an import cycle."""

        from arbogast.galois.proof import (
            Completeness,
            ProofContext,
            VerificationRequirement,
        )

        requirements: tuple[VerificationRequirement, ...] = ()
        if self.verification_requirement is not None:
            local = self.verification_requirement
            if local.verifier == "python":
                shared = VerificationRequirement.portable_python(
                    "arbogast.backends.python.v1",
                    capabilities=(self.operation,),
                )
            else:
                assert local.version is not None
                shared = VerificationRequirement.pinned_external(
                    "arbogast.backends.pari.v1",
                    local.version,
                    capabilities=(self.operation,),
                )
            requirements = (shared,)
        completeness = (
            Completeness.COMPLETE
            if self.completeness is PariCompleteness.COMPLETE
            else Completeness.CANDIDATE
        )
        return ProofContext(self.assumptions, requirements, completeness)

    def verify(self) -> VerificationReport:
        """Replay the nested central certificate in its required fresh process."""

        if self.certificate is None:
            raise ValueError("this PARI result has no verification certificate")
        return verify_certificate(self.certificate)

    def claim(self) -> Claim:
        """Return a conservative claim about exactly this normalized backend payload."""

        claim_id = _pari_claim_id(self.operation, self.payload)
        statement = _pari_statement(
            self.operation,
            self.payload,
            self.completeness,
            self.outcome,
        )
        status = _pari_status(self.assumptions, self.outcome, self.verification_requirement)
        hypotheses = _pari_hypotheses(self.assumptions)
        evidence = self.certificate if self.certificate is not None else self.receipt
        return Claim(
            claim_id,
            statement=statement,
            kind=ClaimKind.COMPUTED,
            status=status,
            hypotheses=hypotheses,
            how=Derivation.computation(
                f"backends.pari.{self.operation}",
                method="Fresh-process replay of a closed typed PARI arithmetic operation",
                inputs=(self.receipt.certificate_id,),
                artifact=evidence.certificate_id,
                parameters={
                    "completeness": self.completeness.value,
                    "outcome": self.outcome.value,
                },
            ),
            certificate=evidence,
            metadata={
                "assumptions": self.assumptions,
                "backend_receipt": self.receipt.certificate_id,
                "completeness": self.completeness.value,
                "outcome": self.outcome.value,
                "verifier_trust": (
                    None
                    if self.verification_requirement is None
                    else (
                        "portable-python"
                        if self.verification_requirement.portable
                        else "pinned-external"
                    )
                ),
            },
        )

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))

    def require_verified_payload(
        self,
        operation: str,
        *,
        complete: bool = False,
    ) -> FrozenMap:
        """Validate a typed operation boundary and replay its nested certificate."""

        if self.operation != operation:
            raise ValueError(f"expected PARI operation {operation}, got {self.operation}")
        if self.outcome is not PariOutcome.SUCCESS:
            raise ValueError(f"PARI operation did not succeed: {self.outcome.value}")
        if complete and self.completeness is not PariCompleteness.COMPLETE:
            raise ValueError("PARI operation returned only a candidate payload")
        self.verify().require_valid()
        return self.payload

    def to_dict(self) -> dict[str, object]:
        return {
            "assumptions": list(self.assumptions),
            "certificate": None if self.certificate is None else self.certificate.to_dict(),
            "completeness": self.completeness.value,
            "operation": self.operation,
            "outcome": self.outcome.value,
            "payload": self.payload.to_dict(),
            "receipt": self.receipt.to_dict(),
            "schema": self.schema,
            "verification_requirement": (
                None
                if self.verification_requirement is None
                else self.verification_requirement.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PariArithmeticResult:
        """Strictly decode the stable public transport representation."""

        expected = {
            "assumptions",
            "certificate",
            "completeness",
            "operation",
            "outcome",
            "payload",
            "receipt",
            "schema",
            "verification_requirement",
        }
        if set(value) != expected or value.get("schema") != (
            "arbogast.backend.pari-arithmetic-result.v1"
        ):
            raise ValueError("invalid PARI arithmetic-result schema")
        operation = value["operation"]
        if not isinstance(operation, str):
            raise ValueError("PARI result operation must be a string")
        payload = value["payload"]
        receipt = value["receipt"]
        if not isinstance(payload, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("PARI result payload and receipt must be objects")
        raw_assumptions = value["assumptions"]
        if isinstance(raw_assumptions, str) or not isinstance(raw_assumptions, Sequence):
            raise ValueError("PARI result assumptions must be a sequence")
        if any(not isinstance(item, str) for item in raw_assumptions):
            raise ValueError("PARI result assumptions must be strings")
        raw_requirement = value["verification_requirement"]
        requirement: PariVerificationRequirement | None
        if raw_requirement is None:
            requirement = None
        else:
            if not isinstance(raw_requirement, Mapping) or set(raw_requirement) != {
                "portable",
                "verifier",
                "version",
            }:
                raise ValueError("invalid PARI verification requirement")
            verifier_name = raw_requirement["verifier"]
            version = raw_requirement["version"]
            portable = raw_requirement["portable"]
            if (
                not isinstance(verifier_name, str)
                or (version is not None and not isinstance(version, str))
                or not isinstance(portable, bool)
            ):
                raise ValueError("invalid PARI verification requirement fields")
            requirement = PariVerificationRequirement(verifier_name, version, portable)
        raw_certificate = value["certificate"]
        if raw_certificate is None:
            certificate = None
        elif isinstance(raw_certificate, Mapping):
            certificate = VerificationCertificate.from_dict(raw_certificate)
        else:
            raise ValueError("PARI result certificate must be an object")
        raw_completeness = value["completeness"]
        raw_outcome = value["outcome"]
        if not isinstance(raw_completeness, str) or not isinstance(raw_outcome, str):
            raise ValueError("invalid PARI completeness or outcome")
        try:
            completeness = PariCompleteness(raw_completeness)
            outcome = PariOutcome(raw_outcome)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid PARI completeness or outcome") from exc
        return cls(
            operation,
            cast(FrozenMap, payload),
            DiscoveryReceipt.from_dict(receipt),
            assumptions=tuple(cast(Sequence[str], raw_assumptions)),
            completeness=completeness,
            outcome=outcome,
            verification_requirement=requirement,
            certificate=certificate,
        )


def decode_pari_arithmetic_result(value: Mapping[str, object]) -> PariArithmeticResult:
    """Decode one operation-specific public PARI result without generic evaluation."""

    return PariArithmeticResult.from_dict(value)


def _pari_claim_id(operation: str, payload: Mapping[str, object]) -> str:
    digest = content_address(payload).removeprefix("sha256:")
    return f"backends.pari.{operation}.{digest}"


def _pari_statement(
    operation: str,
    payload: Mapping[str, object],
    completeness: PariCompleteness,
    outcome: PariOutcome,
) -> FormalStatement:
    payload_id = content_address(payload)
    if outcome is PariOutcome.SUCCESS:
        scope = (
            "The returned payload is exhaustive for the stated closed operation."
            if completeness is PariCompleteness.COMPLETE
            else "The returned payload is only a candidate and is not asserted exhaustive."
        )
        text = f"Pinned PARI reproduced the exact payload for {operation}. {scope}"
    else:
        text = (
            f"The closed PARI operation {operation} ended with {outcome.value}; "
            "no mathematical conclusion is asserted."
        )
    return FormalStatement.create(
        text,
        parameters={
            "completeness": completeness.value,
            "operation": operation,
            "outcome": outcome.value,
            "payload": dict(payload),
            "payload_id": payload_id,
        },
    )


def _pari_hypotheses(assumptions: tuple[str, ...]) -> tuple[FormalStatement, ...]:
    return tuple(FormalStatement(f"Assumption: {assumption}.") for assumption in assumptions)


def _pari_status(
    assumptions: tuple[str, ...],
    outcome: PariOutcome,
    requirement: PariVerificationRequirement | None,
) -> EpistemicStatus:
    if outcome is not PariOutcome.SUCCESS:
        return EpistemicStatus.UNKNOWN
    if assumptions:
        return EpistemicStatus.CONDITIONAL
    if requirement is not None and not requirement.portable:
        return EpistemicStatus.CERTIFIED
    return EpistemicStatus.EXACT


__all__ = [
    "PariArithmeticResult",
    "PariCompleteness",
    "PariOutcome",
    "PariProbeResult",
    "PariVerificationRequirement",
    "decode_pari_arithmetic_result",
]
