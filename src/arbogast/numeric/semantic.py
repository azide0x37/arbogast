"""Central certificate and claim adapters for exact numeric bridge results."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from typing import Protocol, cast, runtime_checkable

from arbogast.cert import (
    CertificateRef,
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

from .certificate import (
    EXPECTED_TYPES,
    PORTABLE_VERIFIER,
    NumericCertificateError,
    NumericReceipt,
)

VERIFIER_NAME = PORTABLE_VERIFIER
VERIFICATION_CHECKS = (
    "numeric-receipt-integrity",
    "portable-dyadic-interval-replay",
    "dependency-closed-exact-evidence",
    "scope-preserving-result-boundary",
)
VERIFICATION_GUARANTEES = (
    "The embedded numeric receipt is replayed with exact integer and dyadic arithmetic.",
    "Every external Hurwitz prerequisite is embedded and independently replayed.",
    "Unknown, unsupported, local-monodromy, regular-fiber, and generic claims are not conflated.",
)

_KIND_BY_TYPE = {type_tag: kind for kind, type_tag in EXPECTED_TYPES.items()}

_OPERATIONS = {
    "dyadic": "numeric.dyadic",
    "complex-dyadic": "numeric.complex_dyadic",
    "real-ball": "numeric.real_ball",
    "complex-ball": "numeric.complex_ball",
    "exact-polynomial": "numeric.exact_polynomial",
    "polynomial-system": "numeric.polynomial_system",
    "polynomial-family": "numeric.polynomial_family",
    "parameter-path": "numeric.path",
    "point": "numeric.point",
    "exact-cover": "numeric.exact_cover",
    "continuation-step": "numeric.continue_path",
    "continuation-tube": "numeric.continue_path",
    "continuation-result": "numeric.continue_path",
    "condition-bound": "numeric.condition_number",
    "recognition-bounds": "numeric.recognize",
    "algebraic-candidate": "numeric.recognize",
    "exactification-result": "numeric.exactify",
    "regular-fiber-witness": "numeric.projection_degree",
    "generic-degree-witness": "numeric.projection_degree",
    "regular-fiber-degree": "numeric.projection_degree",
    "degree-result": "numeric.projection_degree",
    "branch-loop": "numeric.branch_cycles",
    "branch-tracking": "numeric.branch_cycles",
    "numerical-cover": "numeric.branch_cycles",
    "branch-cycle-tuple": "numeric.branch_cycles",
    "nielsen-vertex": "numeric.bind_vertex",
    "braid-continuation-witness": "numeric.braid_continue",
    "quadratic-b2-homotopy": "numeric.braid_continue",
    "braid-continuation-result": "numeric.braid_continue",
    "weighted-braid-plan": "numeric.weighted_braid_plan",
    "unknown": "numeric.unknown",
    "unsupported": "numeric.unsupported",
}

_STATEMENTS = {
    "dyadic": "The displayed rational is in canonical exact dyadic form.",
    "complex-dyadic": "The displayed complex number has exact canonical dyadic coordinates.",
    "real-ball": "The displayed closed real interval has exact dyadic endpoints.",
    "complex-ball": "The displayed closed complex enclosure has exact dyadic data.",
    "exact-polynomial": "The displayed sparse polynomial has exact complex-dyadic coefficients.",
    "polynomial-system": "The displayed ordered polynomial system replays exactly.",
    "polynomial-family": "The displayed one-parameter polynomial family replays exactly.",
    "parameter-path": "The displayed piecewise-linear parameter path is exact and nonstationary.",
    "point": "The displayed exact balls are bound to the displayed polynomial system.",
    "exact-cover": (
        "The displayed cover is a monic quadratic whose exact discriminant is completely "
        "factored by the declared finite branches, with infinity ramification bound by parity."
    ),
    "continuation-step": (
        "The exact interval bounds make the displayed Newton-like map a strict self-map "
        "contraction over one parameter segment."
    ),
    "continuation-tube": (
        "The displayed compatible contraction steps certify one unique branch along the path."
    ),
    "continuation-result": (
        "The displayed endpoint enclosure is the terminal ball of the certified continuation tube."
    ),
    "condition-bound": (
        "The displayed exact Jacobian inverse gives the certified row-sum condition upper bound."
    ),
    "recognition-bounds": "The displayed algebraic-recognition search bounds are finite and exact.",
    "algebraic-candidate": (
        "The displayed primitive irreducible polynomial has exactly one real root in the enclosure."
    ),
    "exactification-result": (
        "The recognized minimal polynomial divides every displayed univariate system equation."
    ),
    "regular-fiber-witness": (
        "The displayed complete factorization proves the degree of one square-free regular fiber."
    ),
    "generic-degree-witness": (
        "The exact nonzero leading term proves the generic degree of this "
        "univariate polynomial map."
    ),
    "regular-fiber-degree": (
        "The displayed number is the degree of one certified regular fiber; "
        "no generic claim is made."
    ),
    "degree-result": "The displayed number is the generic degree of the pinned polynomial map.",
    "branch-loop": (
        "The exact polygon winds once around its selected finite branch and around no other."
    ),
    "branch-tracking": (
        "The complete pairwise-disjoint continuation tubes induce the displayed sheet permutation."
    ),
    "numerical-cover": (
        "The complete quadratic fiber and every finite local branch permutation replay exactly; "
        "the infinity cycle is the exact inverse product when required."
    ),
    "branch-cycle-tuple": (
        "The displayed concrete generating product-one Nielsen tuple is exactly the tracked branch "
        "cycle tuple of the certified numerical cover."
    ),
    "nielsen-vertex": (
        "The tracked concrete branch cycles equal the displayed vertex of the complete exact "
        "Nielsen class."
    ),
    "braid-continuation-witness": (
        "The exact Nielsen edge and local sheet paths replay separately; this receipt does not "
        "certify deformation of cover coefficients along a nontrivial Hurwitz braid."
    ),
    "quadratic-b2-homotopy": (
        "The normalized x^2-t(t-1) coefficient homotopy exchanges 0 and 1 with the displayed "
        "orientation, has an exact sum-of-squares noncollision proof, carries both fixed-base "
        "sheets to their displayed endpoints, and induces the displayed exact Nielsen edge."
    ),
    "braid-continuation-result": (
        "The displayed exact Nielsen cover endpoint is reached by the replayed normalized "
        "quadratic B2 coefficient homotopy, not merely by local sheet monodromy."
    ),
    "weighted-braid-plan": (
        "The displayed exact-cost braid path is globally optimal by its checked distance potential."
    ),
    "unknown": (
        "The requested numeric conclusion remains explicitly unknown for the displayed reason."
    ),
    "unsupported": (
        "The requested operation lies outside the bounded certified numeric slice; no mathematical "
        "conclusion is asserted."
    ),
}

_NUMERICAL_KINDS = {
    "real-ball",
    "complex-ball",
    "point",
    "continuation-step",
    "continuation-tube",
    "continuation-result",
    "condition-bound",
    "algebraic-candidate",
    "branch-loop",
    "branch-tracking",
    "numerical-cover",
    "braid-continuation-witness",
}


@runtime_checkable
class _CanonicalNumericResult(Protocol):
    def verify(self) -> bool: ...

    def to_canonical_data(self) -> object: ...


def _claim_id(receipt: NumericReceipt) -> str:
    digest = receipt.certificate_id.removeprefix("sha256:")
    return f"numeric.{receipt.kind.replace('-', '_')}.{digest}"


def _subject(receipt: NumericReceipt) -> str:
    return f"numeric:{receipt.kind}:{receipt.certificate_id}"


def _status(receipt: NumericReceipt) -> EpistemicStatus:
    if receipt.kind in {"unknown", "unsupported"}:
        return EpistemicStatus.UNKNOWN
    if receipt.assumptions:
        return EpistemicStatus.CONDITIONAL
    if receipt.kind in _NUMERICAL_KINDS:
        return EpistemicStatus.NUMERICAL
    return EpistemicStatus.EXACT


def _dependency_refs(receipt: NumericReceipt) -> tuple[CertificateRef, ...]:
    return tuple(CertificateRef.from_certificate(item) for item in receipt.dependencies)


def _assumptions_for_result(result: object) -> tuple[str, ...]:
    raw = getattr(result, "assumptions", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise NumericCertificateError("numeric assumptions must be a sequence")
    assumptions = tuple(raw)
    if any(
        not isinstance(item, str)
        or not item.strip()
        or item != unicodedata.normalize("NFC", item.strip())
        for item in assumptions
    ):
        raise NumericCertificateError(
            "numeric assumptions must contain canonical stripped NFC strings"
        )
    return tuple(sorted(set(cast(tuple[str, ...], assumptions))))


def _supporting_certificates(result: object) -> tuple[VerificationCertificate, ...]:
    raw = getattr(result, "supporting_certificates", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise NumericCertificateError("supporting certificates must be a sequence")
    certificates = tuple(raw)
    if any(not isinstance(item, VerificationCertificate) for item in certificates):
        raise NumericCertificateError(
            "numeric supporting evidence must contain VerificationCertificate objects"
        )
    typed = cast(tuple[VerificationCertificate, ...], certificates)
    by_id = {item.certificate_id: item for item in typed}
    return tuple(by_id[certificate_id] for certificate_id in sorted(by_id))


def receipt_for_result(result: object) -> NumericReceipt:
    """Freeze one exact runtime result and every external proving prerequisite."""

    if isinstance(result, NumericReceipt):
        result.verify()
        return result
    if not isinstance(result, _CanonicalNumericResult):
        raise TypeError("numeric result must expose verify() and to_canonical_data()")
    if result.verify() is not True:
        raise NumericCertificateError("numeric result verification returned false")
    raw = result.to_canonical_data()
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise NumericCertificateError("numeric canonical payload must be a string-keyed mapping")
    payload = cast(Mapping[str, object], raw)
    type_tag = payload.get("type")
    if not isinstance(type_tag, str) or type_tag not in _KIND_BY_TYPE:
        raise NumericCertificateError("unsupported numeric canonical type tag")
    kind = _KIND_BY_TYPE[type_tag]
    receipt = NumericReceipt.create(
        kind,
        payload,
        dependencies=_supporting_certificates(result),
        assumptions=_assumptions_for_result(result),
    )
    receipt.verify()
    return receipt


def statement_for_receipt(receipt: NumericReceipt) -> FormalStatement:
    return FormalStatement.create(
        _STATEMENTS[receipt.kind],
        parameters={
            "receipt_kind": receipt.kind,
            "receipt_id": receipt.certificate_id,
            "receipt_schema": receipt.schema_version,
            "object_id": receipt.object_id,
            "payload": receipt.payload,
            "assumptions": receipt.assumptions,
            "completeness": receipt.completeness,
            "verifier_trust": receipt.verifier_trust,
        },
    )


def _verify_semantic_certificate(certificate: VerificationCertificate) -> VerificationReport:
    witness = certificate.witness.to_dict()
    if set(witness) != {"numeric_receipt"}:
        raise CertificateVerificationError("numeric witness must contain exactly numeric_receipt")
    raw = witness["numeric_receipt"]
    if not isinstance(raw, Mapping):
        raise CertificateVerificationError("embedded numeric receipt must be an object")
    try:
        receipt = NumericReceipt.from_dict(raw)
        replay_checks = receipt.verify()
    except (TypeError, ValueError) as exc:
        raise CertificateVerificationError(str(exc)) from exc
    statement = statement_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    if certificate.subject != _subject(receipt):
        raise CertificateVerificationError("numeric subject is not bound to its receipt")
    if certificate.verifier != VERIFIER_NAME or certificate.claim_id != claim_id:
        raise CertificateVerificationError("numeric verifier or claim identity was altered")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("numeric statement hash was altered")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=receipt.assumptions,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("numeric claim boundary was altered")
    if certificate.claim_dependencies:
        raise CertificateVerificationError("numeric receipts have no theorem-claim dependencies")
    if certificate.dependencies != _dependency_refs(receipt):
        raise CertificateVerificationError("numeric proof dependencies were altered")
    if certificate.checks != VERIFICATION_CHECKS:
        raise CertificateVerificationError("numeric verification checks were altered")
    if certificate.guarantees != VERIFICATION_GUARANTEES:
        raise CertificateVerificationError("numeric verification guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=VERIFIER_NAME,
        certificate_id=certificate.certificate_id,
        checks=replay_checks,
        details=freeze_mapping(
            {
                "numeric_receipt": receipt.certificate_id,
                "receipt_kind": receipt.kind,
                "object_id": receipt.object_id,
                "completeness": receipt.completeness,
                "verifier_trust": receipt.verifier_trust,
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


def verification_certificate_for_receipt(receipt: NumericReceipt) -> VerificationCertificate:
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
        witness={"numeric_receipt": receipt.to_dict()},
        checks=VERIFICATION_CHECKS,
        dependencies=_dependency_refs(receipt),
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim_for_receipt(receipt: NumericReceipt) -> Claim:
    certificate = verification_certificate_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    return Claim(
        claim_id,
        statement=statement_for_receipt(receipt),
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        how=Derivation.computation(
            _OPERATIONS[receipt.kind],
            method="Portable exact dyadic and finite witness replay",
            inputs=(receipt.certificate_id,),
            artifact=certificate.certificate_id,
            parameters={
                "receipt_kind": receipt.kind,
                "completeness": receipt.completeness,
                "verifier_trust": receipt.verifier_trust,
            },
        ),
        certificate=certificate,
        supporting_certificates=receipt.dependencies,
        hypotheses=receipt.assumptions,
        metadata={
            "receipt_schema": receipt.schema_version,
            "receipt_id": receipt.certificate_id,
            "object_id": receipt.object_id,
            "completeness": receipt.completeness,
            "verifier_trust": receipt.verifier_trust,
        },
    )


def claim_graph_for_receipt(receipt: NumericReceipt) -> ClaimGraph:
    return ClaimGraph((claim_for_receipt(receipt),))


def verification_certificate_for_result(result: object) -> VerificationCertificate:
    return verification_certificate_for_receipt(receipt_for_result(result))


def claim_for_result(result: object) -> Claim:
    return claim_for_receipt(receipt_for_result(result))


def claim_graph_for_result(result: object) -> ClaimGraph:
    return claim_graph_for_receipt(receipt_for_result(result))


__all__ = [
    "VERIFICATION_CHECKS",
    "VERIFICATION_GUARANTEES",
    "VERIFIER_NAME",
    "claim_for_receipt",
    "claim_for_result",
    "claim_graph_for_receipt",
    "claim_graph_for_result",
    "receipt_for_result",
    "statement_for_receipt",
    "verification_certificate_for_receipt",
    "verification_certificate_for_result",
]
