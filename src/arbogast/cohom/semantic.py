"""Bridge exact cohomology results into the central semantic claim layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from arbogast.cert import (
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    default_verifiers,
    freeze_mapping,
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

from .certificate import CohomologyCertificate
from .complex import _complex_content_hash

if TYPE_CHECKING:
    from .results import CohomologyResult


VERIFIER_NAME = "cohom.normalized_bar.v1"
VERIFICATION_CHECKS = (
    "finite-group-axioms",
    "representation-homomorphism",
    "normalized-bar-differentials",
    "d-squared-zero",
    "kernel-and-image",
    "explicit-quotient-maps",
)
VERIFICATION_GUARANTEES = (
    "The claimed H^n dimension is recomputed from ker(d_n)/im(d_{n-1}).",
    "Representative cocycles and quotient maps replay over the stated prime field.",
)


def _subject(certificate: CohomologyCertificate) -> str:
    return f"H^{certificate.degree}:sha256:{certificate.content_hash}"


def _minimal_complex_hash(certificate: CohomologyCertificate) -> str:
    """Rebuild the exact minimal complex identity carried by the domain receipt."""

    return _complex_content_hash(
        prime=certificate.prime,
        element_ids=certificate.group_element_ids,
        identity_index=certificate.identity_index,
        multiplication_table=certificate.multiplication_table,
        module_dimension=certificate.module_dimension,
        action_matrices=certificate.action_matrices,
        max_degree=certificate.degree,
        differential_hashes=certificate.differential_hashes,
    )


def _claim_identity(certificate: CohomologyCertificate) -> str:
    return f"cohom.h{certificate.degree}.{certificate.content_hash}"


def _statement(certificate: CohomologyCertificate) -> FormalStatement:
    degree = certificate.degree
    dimension = certificate.dimension
    complex_hash = _minimal_complex_hash(certificate)
    return FormalStatement.create(
        text=(
            f"The normalized-bar cohomology H^{degree}(G, M) for the concrete finite "
            f"group action sha256:{complex_hash} has dimension {dimension}."
        ),
        parameters={
            "cohomology_degree": degree,
            "dimension": dimension,
            "group_order": len(certificate.multiplication_table),
            "coefficient_characteristic": certificate.prime,
            "module_dimension": certificate.module_dimension,
            "complex_hash": f"sha256:{complex_hash}",
            "cohomology_certificate_hash": f"sha256:{certificate.content_hash}",
        },
    )


def _verify_semantic_certificate(certificate: VerificationCertificate) -> VerificationReport:
    payload = certificate.witness.to_dict()
    if set(payload) != {"cohomology_certificate"}:
        raise CertificateVerificationError(
            "cohomology verification witness must contain exactly cohomology_certificate"
        )
    raw = payload["cohomology_certificate"]
    if not isinstance(raw, dict):
        raise CertificateVerificationError("cohomology certificate witness must be an object")
    try:
        domain_certificate = CohomologyCertificate.from_dict(raw)
        report = domain_certificate.verify()
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    if certificate.subject != _subject(domain_certificate):
        raise CertificateVerificationError(
            "semantic certificate subject is not bound to its cohomology payload"
        )
    if certificate.verifier != VERIFIER_NAME:
        raise CertificateVerificationError("cohomology certificate names a different verifier")
    expected_claim_id = _claim_identity(domain_certificate)
    if certificate.claim_id != expected_claim_id:
        raise CertificateVerificationError(
            "semantic certificate claim ID is not bound to its cohomology payload"
        )
    expected_statement_hash = _statement(domain_certificate).statement_hash
    if certificate.statement_hash != expected_statement_hash:
        raise CertificateVerificationError(
            "semantic certificate statement hash is not bound to its cohomology payload"
        )
    expected_boundary_hash = claim_boundary_hash(
        expected_claim_id,
        _statement(domain_certificate),
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
    )
    if certificate.claim_boundary_hash != expected_boundary_hash:
        raise CertificateVerificationError(
            "semantic certificate claim boundary is not bound to its cohomology payload"
        )
    if certificate.claim_dependencies:
        raise CertificateVerificationError(
            "self-contained cohomology certificates cannot bind claim dependencies"
        )
    if certificate.checks != VERIFICATION_CHECKS:
        raise CertificateVerificationError("cohomology certificate check manifest was altered")
    if certificate.guarantees != VERIFICATION_GUARANTEES:
        raise CertificateVerificationError("cohomology certificate guarantees were altered")
    if certificate.dependencies:
        raise CertificateVerificationError(
            "self-contained cohomology certificates cannot carry external dependencies"
        )
    return VerificationReport(
        valid=True,
        verifier=VERIFIER_NAME,
        certificate_id=certificate.certificate_id,
        checks=report.checks,
        details=freeze_mapping(
            {
                "cohomology_certificate": f"sha256:{domain_certificate.content_hash}",
                "degree": domain_certificate.degree,
                "dimension": domain_certificate.dimension,
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


def verification_certificate_for_result(result: CohomologyResult) -> VerificationCertificate:
    """Wrap the self-contained domain receipt in a central verification certificate."""

    result.verify()
    domain_certificate = result.certificate
    claim_id = _claim_identity(domain_certificate)
    statement = _statement(domain_certificate)
    return VerificationCertificate.create(
        subject=_subject(domain_certificate),
        verifier=VERIFIER_NAME,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"cohomology_certificate": domain_certificate.to_dict()},
        checks=VERIFICATION_CHECKS,
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim_for_result(result: CohomologyResult) -> Claim:
    """Build a central, zero-argument-replayable computed claim."""

    result.verify()
    domain_certificate = result.certificate
    claim_id = _claim_identity(domain_certificate)
    statement = _statement(domain_certificate)
    certificate = verification_certificate_for_result(result)
    return Claim(
        id=claim_id,
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation(
            f"cohom.h{result.degree}",
            method="Exact normalized-bar linear algebra over a prime finite field",
            inputs=(f"sha256:{_minimal_complex_hash(domain_certificate)}",),
            artifact=certificate.certificate_id,
            parameters={"degree": result.degree},
        ),
        certificate=certificate,
        metadata={
            "domain_certificate_schema": result.certificate.schema_version,
            "domain_certificate_hash": f"sha256:{result.certificate.content_hash}",
        },
    )


def claim_graph_for_result(result: CohomologyResult) -> ClaimGraph:
    """Return the one-node theorem DAG for this exact computation."""

    return ClaimGraph((claim_for_result(result),))


__all__ = [
    "VERIFICATION_CHECKS",
    "VERIFICATION_GUARANTEES",
    "VERIFIER_NAME",
    "claim_for_result",
    "claim_graph_for_result",
    "verification_certificate_for_result",
]
