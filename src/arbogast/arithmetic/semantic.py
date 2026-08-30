"""Central claim and certificate bridge for certified arithmetic results."""

from __future__ import annotations

from collections.abc import Mapping

from arbogast.cert import (
    CertificateRef,
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    default_verifiers,
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
    claim_boundary_hash,
)
from arbogast.galois.proof import VerifierTrust

from .certificate import ArithmeticReceipt

VERIFIER_NAME = "arithmetic.finite-linear.v1"
VERIFICATION_CHECKS = (
    "arithmetic-receipt-integrity",
    "portable-prime-field-replay",
    "assumptions-and-completeness-axes",
)
VERIFICATION_GUARANTEES = (
    "The embedded arithmetic receipt is replayed using exact prime-field operations.",
    "Nested input evidence, completeness, assumptions, and verifier trust remain explicit.",
)


_OPERATIONS = {
    "aim-affine": "arithmetic.aim",
    "aim-obstruction": "arithmetic.aim",
    "cartier-dual": "arithmetic.cartier_dual",
    "descent-obstructed": "arithmetic.elementary_descent",
    "descent-realized": "arithmetic.elementary_descent",
    "descent-unknown": "arithmetic.elementary_descent",
    "dual-selmer": "arithmetic.dual_selmer",
    "local-condition": "arithmetic.local_condition",
    "local-pairing": "arithmetic.local_pairing",
    "selmer-group": "arithmetic.selmer",
    "selmer-kernel": "arithmetic.selmer",
}


def _claim_id(receipt: ArithmeticReceipt) -> str:
    digest = receipt.certificate_id.removeprefix("sha256:")
    return f"arithmetic.{receipt.kind.replace('-', '_')}.{digest}"


def _subject(receipt: ArithmeticReceipt) -> str:
    return f"arithmetic:{receipt.kind}:{receipt.certificate_id}"


def _status(receipt: ArithmeticReceipt) -> EpistemicStatus:
    if receipt.assumptions:
        return EpistemicStatus.CONDITIONAL
    external = tuple(
        requirement
        for requirement in receipt.proof_context.verification_requirements
        if requirement.trust is VerifierTrust.PINNED_EXTERNAL
    )
    evidence_verifiers = {certificate.verifier for certificate in receipt.evidence}
    if external and all(requirement.verifier in evidence_verifiers for requirement in external):
        return EpistemicStatus.CERTIFIED
    return EpistemicStatus.EXACT


def _external_dependencies(receipt: ArithmeticReceipt) -> tuple[CertificateRef, ...]:
    external_verifiers = {
        requirement.verifier
        for requirement in receipt.proof_context.verification_requirements
        if requirement.trust is VerifierTrust.PINNED_EXTERNAL
    }
    return tuple(
        CertificateRef.from_certificate(certificate)
        for certificate in receipt.evidence
        if certificate.verifier in external_verifiers
    )


def _external_certificates(
    receipt: ArithmeticReceipt,
) -> tuple[VerificationCertificate, ...]:
    reachable = {reference.certificate_id for reference in _external_dependencies(receipt)}
    by_id = {certificate.certificate_id: certificate for certificate in receipt.evidence}
    pending = list(reachable)
    while pending:
        certificate = by_id.get(pending.pop())
        if certificate is None:
            continue
        for reference in certificate.dependencies:
            if reference.certificate_id not in reachable:
                reachable.add(reference.certificate_id)
                pending.append(reference.certificate_id)
    return tuple(
        certificate for certificate in receipt.evidence if certificate.certificate_id in reachable
    )


def _statement_text(receipt: ArithmeticReceipt) -> str:
    payload = receipt.payload
    if receipt.kind == "local-condition":
        return (
            "The displayed basis defines the certified local-condition subspace at "
            f"place {payload['place_id']}."
        )
    if receipt.kind == "selmer-kernel":
        return (
            "The declared global-to-local quotient map has the displayed candidate kernel "
            f"of dimension {payload['dimension']}; no completeness conclusion is asserted."
        )
    if receipt.kind == "selmer-group":
        return (
            "For the complete declared global and local data, the Selmer group is the "
            f"displayed kernel of dimension {payload['dimension']}."
        )
    if receipt.kind == "local-pairing":
        qualifier = "perfect" if payload["perfect"] else "not perfect"
        if receipt.completeness.value == "complete":
            return (
                f"The certified local Tate/Hilbert pairing at {payload['place_id']} is {qualifier}."
            )
        return (
            f"The displayed candidate bilinear matrix at {payload['place_id']} is "
            f"{qualifier}; it is not certified as the local Tate/Hilbert pairing."
        )
    if receipt.kind == "cartier-dual":
        return (
            f"The pinned module {payload['module_id']} has the displayed Cartier dual "
            f"presentation with Tate twist {payload['tate_twist']}."
        )
    if receipt.kind == "dual-selmer":
        return (
            "After checking perfect local pairings and exact orthogonal local conditions, "
            f"the dual Selmer kernel has dimension {payload['dimension']}."
        )
    if receipt.kind == "aim-affine":
        return "The aiming equations have the displayed representative and complete affine kernel."
    if receipt.kind == "aim-obstruction":
        return (
            "The aiming target is inconsistent, as proved by the displayed left-nullspace witness."
        )
    if receipt.kind == "descent-realized":
        if payload["realization_kind"] == "finite-linear":
            return (
                "The bounded finite linear realization problem is solved by the displayed "
                "checked vector."
            )
        return "The bounded Kummer descent problem is realized by the displayed checked witness."
    if receipt.kind == "descent-obstructed":
        return (
            "The bounded linear Kummer descent problem is obstructed by the displayed "
            "separating witness."
        )
    return (
        "The bounded descent procedure returned Unknown with the recorded reason; this makes "
        "no realization or obstruction claim."
    )


def statement_for_receipt(receipt: ArithmeticReceipt) -> FormalStatement:
    """Return the complete semantic statement bound by an arithmetic receipt."""

    return FormalStatement.create(
        text=_statement_text(receipt),
        parameters={
            "receipt_kind": receipt.kind,
            "receipt_id": receipt.certificate_id,
            "receipt_schema": receipt.schema_version,
            "completeness": receipt.completeness.value,
            "assumptions": receipt.assumptions,
            "payload": receipt.payload,
        },
    )


def _verify_semantic_certificate(certificate: VerificationCertificate) -> VerificationReport:
    payload = certificate.witness.to_dict()
    if set(payload) != {"arithmetic_receipt"}:
        raise CertificateVerificationError(
            "arithmetic witness must contain exactly arithmetic_receipt"
        )
    raw = payload["arithmetic_receipt"]
    if not isinstance(raw, Mapping):
        raise CertificateVerificationError("embedded arithmetic receipt must be an object")
    try:
        receipt = ArithmeticReceipt.from_dict(raw)
        replay_checks = receipt.verify()
    except (TypeError, ValueError) as exc:
        raise CertificateVerificationError(str(exc)) from exc
    statement = statement_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    if certificate.subject != _subject(receipt):
        raise CertificateVerificationError("arithmetic subject is not bound to its receipt")
    if certificate.verifier != VERIFIER_NAME:
        raise CertificateVerificationError("arithmetic certificate names a different verifier")
    if certificate.claim_id != claim_id:
        raise CertificateVerificationError("arithmetic claim ID is not bound to its receipt")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("arithmetic statement hash is not bound to its receipt")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=receipt.assumptions,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("arithmetic claim boundary was altered")
    if certificate.claim_dependencies:
        raise CertificateVerificationError("arithmetic finite receipts are self-contained")
    if certificate.dependencies != _external_dependencies(receipt):
        raise CertificateVerificationError(
            "arithmetic external proof dependencies do not match the proof context"
        )
    if certificate.checks != VERIFICATION_CHECKS:
        raise CertificateVerificationError("arithmetic verification check manifest was altered")
    if certificate.guarantees != VERIFICATION_GUARANTEES:
        raise CertificateVerificationError("arithmetic verification guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=VERIFIER_NAME,
        certificate_id=certificate.certificate_id,
        checks=replay_checks,
        details=freeze_mapping(
            {
                "arithmetic_receipt": receipt.certificate_id,
                "receipt_kind": receipt.kind,
                "completeness": receipt.completeness.value,
                "assumptions": receipt.assumptions,
            }
        ),
    )


def _register_verifier() -> None:
    if VERIFIER_NAME not in default_verifiers.names():
        default_verifiers.register(
            VERIFIER_NAME,
            VerificationCertificate,
            _verify_semantic_certificate,
        )
        return
    registered = default_verifiers.describe(VERIFIER_NAME)
    expected = f"{__name__}._verify_semantic_certificate"
    if registered["callable"] != expected:
        raise RuntimeError(f"verifier name collision for {VERIFIER_NAME}: {registered['callable']}")


_register_verifier()


def verification_certificate_for_receipt(
    receipt: ArithmeticReceipt,
) -> VerificationCertificate:
    """Nest a replayable arithmetic receipt in the existing central schema."""

    receipt.verify()
    claim_id = _claim_id(receipt)
    statement = statement_for_receipt(receipt)
    return VerificationCertificate.create(
        subject=_subject(receipt),
        verifier=VERIFIER_NAME,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=_status(receipt),
            hypotheses=receipt.assumptions,
        ),
        witness={"arithmetic_receipt": receipt.to_dict()},
        checks=VERIFICATION_CHECKS,
        dependencies=_external_dependencies(receipt),
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim_for_receipt(receipt: ArithmeticReceipt) -> Claim:
    """Build a zero-argument-replayable central computed claim."""

    certificate = verification_certificate_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    return Claim(
        id=claim_id,
        statement=statement_for_receipt(receipt),
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        how=Derivation.computation(
            _OPERATIONS[receipt.kind],
            method="Exact finite linear algebra with a portable arithmetic receipt",
            inputs=(receipt.certificate_id,),
            artifact=certificate.certificate_id,
            parameters={
                "receipt_kind": receipt.kind,
                "completeness": receipt.completeness.value,
            },
        ),
        certificate=certificate,
        supporting_certificates=_external_certificates(receipt),
        hypotheses=receipt.assumptions,
        metadata={
            "receipt_schema": receipt.schema_version,
            "receipt_id": receipt.certificate_id,
            "completeness": receipt.completeness.value,
            "assumptions": receipt.assumptions,
            "verifier_trust": (
                "pinned-external" if _external_dependencies(receipt) else "portable-python"
            ),
        },
    )


def claim_graph_for_receipt(receipt: ArithmeticReceipt) -> ClaimGraph:
    return ClaimGraph((claim_for_receipt(receipt),))


class ArithmeticSemanticResult:
    """Shared semantic hooks for immutable arithmetic results."""

    @property
    def receipt(self) -> ArithmeticReceipt:
        raise NotImplementedError

    @property
    def certificate(self) -> VerificationCertificate:
        return verification_certificate_for_receipt(self.receipt)

    def claim(self) -> Claim:
        return claim_for_receipt(self.receipt)

    def claim_graph(self) -> ClaimGraph:
        return claim_graph_for_receipt(self.receipt)

    def _verify_semantics(self) -> VerificationReport:
        self.receipt.verify()
        return verify_certificate(self.certificate)


def verification_certificate_for_result(
    result: ArithmeticSemanticResult,
) -> VerificationCertificate:
    """Return the central certificate for a substantial arithmetic result."""

    if not isinstance(result, ArithmeticSemanticResult):
        raise TypeError("result must be an ArithmeticSemanticResult")
    return verification_certificate_for_receipt(result.receipt)


def claim_for_result(result: ArithmeticSemanticResult) -> Claim:
    """Return the computed claim bound to an arithmetic result."""

    if not isinstance(result, ArithmeticSemanticResult):
        raise TypeError("result must be an ArithmeticSemanticResult")
    return claim_for_receipt(result.receipt)


def claim_graph_for_result(result: ArithmeticSemanticResult) -> ClaimGraph:
    """Return the one-node claim graph bound to an arithmetic result."""

    if not isinstance(result, ArithmeticSemanticResult):
        raise TypeError("result must be an ArithmeticSemanticResult")
    return claim_graph_for_receipt(result.receipt)


__all__ = [
    "VERIFICATION_CHECKS",
    "VERIFICATION_GUARANTEES",
    "VERIFIER_NAME",
    "ArithmeticSemanticResult",
    "claim_for_receipt",
    "claim_for_result",
    "claim_graph_for_receipt",
    "claim_graph_for_result",
    "statement_for_receipt",
    "verification_certificate_for_receipt",
    "verification_certificate_for_result",
]
