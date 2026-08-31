"""Independent replay for the template's finite modular-square certificate."""

from __future__ import annotations

from arbogast.campaign import Outcome, OutcomeScope, closure_subject
from arbogast.cert import (
    CertificateVerificationError,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    VerifierRegistry,
)

from .specification import (
    CLAIM_ID,
    MODULUS,
    RESULT_BOUNDARY_HASH,
    RESULT_STATEMENT_HASH,
    TARGET_RESIDUE,
    VERIFIER,
    target_spec,
)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateVerificationError(f"{name} must be an integer")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CertificateVerificationError(f"{name} must be a nonempty string")
    return value


def verify_residue_square(certificate: VerificationCertificate) -> VerificationReport:
    """Replay completeness and the claimed square root without discovery code."""

    witness = certificate.witness.to_dict()
    target_id = _string(witness.get("target_id"), "target_id")
    task_hash = _string(witness.get("task_hash"), "task_hash")
    modulus = _integer(witness.get("modulus"), "modulus")
    target = _integer(witness.get("target"), "target")
    outcome = Outcome(_string(witness.get("outcome"), "outcome"))
    scope = OutcomeScope(_string(witness.get("outcome_scope"), "outcome_scope"))
    rows = witness.get("rows")

    if certificate.verifier != VERIFIER:
        raise CertificateVerificationError("certificate names another verifier")
    if modulus != MODULUS or target != TARGET_RESIDUE:
        raise CertificateVerificationError("certificate is bound to another modular fixture")
    if target_id != target_spec().target_id:
        raise CertificateVerificationError("certificate is bound to another campaign target")
    if not isinstance(rows, list):
        raise CertificateVerificationError("rows must be an array")
    expected_rows = [
        {"residue": residue, "square": residue * residue % modulus} for residue in range(modulus)
    ]
    if rows != expected_rows:
        raise CertificateVerificationError("rows do not exhaust the canonical residue domain")
    roots = [row["residue"] for row in expected_rows if row["square"] == target]
    if outcome is not Outcome.FOUND or not roots:
        raise CertificateVerificationError("the certificate does not contain a verified root")
    if scope is not OutcomeScope.TARGET_GLOBAL:
        raise CertificateVerificationError("the complete-domain certificate must be target-global")
    if certificate.subject != closure_subject(target_id, outcome, scope):
        raise CertificateVerificationError("certificate subject does not bind target and scope")
    if certificate.claim_id != CLAIM_ID:
        raise CertificateVerificationError("certificate is bound to another claim")
    if certificate.statement_hash != RESULT_STATEMENT_HASH:
        raise CertificateVerificationError("certificate statement hash does not match")
    if certificate.claim_boundary_hash != RESULT_BOUNDARY_HASH:
        raise CertificateVerificationError("certificate claim boundary does not match")
    if certificate.claim_dependencies:
        raise CertificateVerificationError("template certificate has no logical dependencies")
    if certificate.checks != ("canonical-domain", "modular-squares", "claim-binding"):
        raise CertificateVerificationError("certificate check set is not canonical")
    if len(task_hash) != 64 or any(character not in "0123456789abcdef" for character in task_hash):
        raise CertificateVerificationError("task hash is not canonical lowercase SHA-256")

    return VerificationReport(
        valid=True,
        verifier=VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=("canonical-domain", "modular-squares", "claim-binding"),
        details=FrozenMap({"checked": modulus, "roots": roots}),
    )


def register_verifiers(registry: VerifierRegistry) -> VerifierRegistry:
    """Register the exact verifier in one explicitly trusted runtime."""

    registry.register(VERIFIER, VerificationCertificate, verify_residue_square)
    return registry


__all__ = ["register_verifiers", "verify_residue_square"]
