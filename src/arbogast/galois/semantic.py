"""Central claim and verification-certificate adapters for Galois arithmetic."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

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
    KummerReceipt,
    LocalH1Receipt,
    LocalizationReceipt,
    TwistReceipt,
    external_evidence_complete,
    proving_certificates,
)

KUMMER_VERIFIER = "galois.kummer.v1"
LOCAL_H1_VERIFIER = "galois.local_h1.v1"
LOCALIZATION_VERIFIER = "galois.localization.v1"
TWIST_VERIFIER = "galois.twists.v1"

_RECEIPT_FIELD = {
    KUMMER_VERIFIER: "kummer_receipt",
    LOCAL_H1_VERIFIER: "local_h1_receipt",
    LOCALIZATION_VERIFIER: "localization_receipt",
    TWIST_VERIFIER: "twist_receipt",
}

_CHECKS = {
    KUMMER_VERIFIER: (
        "canonical-field-and-place-binding",
        "prime-field-coordinates",
        "finite-s-kummer-presentation",
        "assumptions-verifier-completeness-axes",
    ),
    LOCAL_H1_VERIFIER: (
        "canonical-place-binding",
        "genuine-local-kummer-presentation",
        "prime-field-coordinates",
        "assumptions-verifier-completeness-axes",
    ),
    LOCALIZATION_VERIFIER: (
        "nested-endpoint-receipts",
        "declared-place-membership",
        "prime-field-linear-map",
        "localized-coordinate-replay",
    ),
    TWIST_VERIFIER: (
        "finite-group-axioms",
        "action-by-automorphisms",
        "complete-nonabelian-cocycle-enumeration",
        "coboundary-orbit-partition",
        "pointed-identity-class",
    ),
}

_GUARANTEES = {
    KUMMER_VERIFIER: (
        "The result is a finite S-Kummer presentation, never unrestricted K^*/K^{*p}.",
        "Completeness and all mathematical assumptions remain explicit in the receipt.",
    ),
    LOCAL_H1_VERIFIER: (
        "The result is presented as genuine local H^1(K_v, mu_p).",
        "It is not identified with finite decomposition-quotient cohomology.",
    ),
    LOCALIZATION_VERIFIER: (
        "The localization matrix is bound to its exact global basis, local basis, and place.",
        "Matrix application is replayed over the stated prime field.",
    ),
    TWIST_VERIFIER: (
        "Every nonabelian cocycle and every coefficient-conjugacy orbit is re-enumerated.",
        "The output is a pointed set and carries no vector-space operations.",
    ),
}

ReceiptType = KummerReceipt | LocalH1Receipt | LocalizationReceipt | TwistReceipt


def _receipt_for_result(result: object) -> ReceiptType:
    """Resolve the aggregate receipt proving one public arithmetic result.

    Localized classes deliberately prefer ``proving_receipt`` over their
    ordinary local-class receipt, while individual twist classes and cocycles
    inherit the exhaustive receipt of their parent pointed set.
    """

    if isinstance(result, KummerReceipt | LocalH1Receipt | LocalizationReceipt | TwistReceipt):
        return result
    for attribute in ("proving_receipt", "receipt"):
        receipt = getattr(result, attribute, None)
        if isinstance(
            receipt,
            KummerReceipt | LocalH1Receipt | LocalizationReceipt | TwistReceipt,
        ):
            return receipt
    parent = getattr(result, "parent", None)
    receipt = getattr(parent, "receipt", None)
    if isinstance(receipt, TwistReceipt):
        return receipt
    raise TypeError("result must expose a Kummer, local-H1, localization, or twist proving receipt")


def _verifier(receipt: ReceiptType) -> str:
    if isinstance(receipt, KummerReceipt):
        return KUMMER_VERIFIER
    if isinstance(receipt, LocalH1Receipt):
        return LOCAL_H1_VERIFIER
    if isinstance(receipt, LocalizationReceipt):
        return LOCALIZATION_VERIFIER
    return TWIST_VERIFIER


def _assumptions(receipt: ReceiptType) -> tuple[str, ...]:
    if isinstance(receipt, TwistReceipt):
        return receipt.assumptions
    if isinstance(receipt, LocalizationReceipt):
        combined = {
            *cast(tuple[str, ...], receipt.domain.proof_context["assumptions"]),
            *cast(tuple[str, ...], receipt.codomain.proof_context["assumptions"]),
            *cast(tuple[str, ...], receipt.proof_context["assumptions"]),
        }
        return tuple(sorted(combined))
    return cast(tuple[str, ...], receipt.proof_context["assumptions"])


def _status(receipt: ReceiptType) -> EpistemicStatus:
    if _assumptions(receipt):
        return EpistemicStatus.CONDITIONAL
    contexts: tuple[Mapping[str, object], ...]
    if isinstance(receipt, TwistReceipt):
        contexts = ()
    elif isinstance(receipt, LocalizationReceipt):
        contexts = (
            receipt.domain.proof_context,
            receipt.codomain.proof_context,
            receipt.proof_context,
        )
    else:
        contexts = (receipt.proof_context,)
    for context in contexts:
        raw_requirements = context.get("verification_requirements", ())
        if isinstance(raw_requirements, tuple):
            requirements = raw_requirements
        else:
            requirements = tuple(cast(list[object], raw_requirements))
        for requirement in requirements:
            if isinstance(requirement, Mapping) and requirement.get("trust") == "pinned-external":
                return (
                    EpistemicStatus.CERTIFIED
                    if external_evidence_complete(receipt)
                    else EpistemicStatus.UNKNOWN
                )
    return EpistemicStatus.EXACT


def _hypotheses(receipt: ReceiptType) -> tuple[FormalStatement, ...]:
    return tuple(FormalStatement(f"Assumption: {item}.") for item in _assumptions(receipt))


def _operation(receipt: ReceiptType) -> str:
    if isinstance(receipt, KummerReceipt):
        return "galois.kummer_class" if receipt.object_type == "class" else "galois.kummer_space"
    if isinstance(receipt, LocalH1Receipt):
        return "galois.local_h1_class" if receipt.object_type == "class" else "galois.local_h1"
    if isinstance(receipt, LocalizationReceipt):
        return "galois.localize"
    return "galois.nonabelian_h1"


def _claim_id(receipt: ReceiptType) -> str:
    suffix = receipt.content_id.split(":", 1)[1]
    return f"{_operation(receipt)}.{suffix}"


def _subject(receipt: ReceiptType) -> str:
    return f"{_operation(receipt)}:{receipt.content_id}"


def _statement(receipt: ReceiptType) -> FormalStatement:
    if isinstance(receipt, KummerReceipt):
        completeness = receipt.proof_context["completeness"]
        noun = "class" if receipt.object_type == "class" else "space"
        coordinates = receipt.coordinates
        if completeness == "complete":
            text = (
                f"The finite S-Kummer {noun} over field {receipt.field_id} at the exact declared "
                f"place set has prime {receipt.prime}, dimension {receipt.dimension}, and is "
                "complete."
            )
        else:
            text = (
                f"The supplied candidate finite S-Kummer {noun} over field {receipt.field_id} "
                f"at the exact declared place set has prime {receipt.prime} and lists "
                f"{receipt.dimension} ordered candidate generators; neither independence nor "
                "completeness is claimed."
            )
        parameters: dict[str, object] = {
            "field_id": receipt.field_id,
            "prime": receipt.prime,
            "place_ids": receipt.place_ids,
            "dimension": receipt.dimension,
            "completeness": completeness,
            "receipt": receipt.content_id,
        }
        if coordinates is not None:
            parameters["coordinates"] = coordinates
        return FormalStatement.create(text, parameters=parameters)
    if isinstance(receipt, LocalH1Receipt):
        completeness = receipt.proof_context["completeness"]
        noun = "class" if receipt.object_type == "class" else "space"
        if completeness == "complete":
            text = (
                f"The genuine local Kummer cohomology H^1(K_v, mu_{receipt.prime}) {noun} "
                f"at place {receipt.place_id} has dimension {receipt.dimension} and is complete."
            )
        else:
            text = (
                f"The supplied candidate presentation for local Kummer cohomology "
                f"H^1(K_v, mu_{receipt.prime}) {noun} at place {receipt.place_id} has "
                f"{receipt.dimension} ordered candidate generators; neither independence nor "
                "completeness is claimed."
            )
        return FormalStatement.create(
            text,
            parameters={
                "place_id": receipt.place_id,
                "prime": receipt.prime,
                "dimension": receipt.dimension,
                "coordinates": receipt.coordinates,
                "completeness": completeness,
                "receipt": receipt.content_id,
                "continuous_local_cohomology": True,
            },
        )
    if isinstance(receipt, LocalizationReceipt):
        complete = receipt.proof_context["completeness"] == "complete"
        qualifier = "certified" if complete else "supplied candidate"
        conclusion = (
            "and is complete."
            if complete
            else "; no arithmetic correctness or completeness is claimed."
        )
        return FormalStatement.create(
            f"The displayed {receipt.codomain.dimension}-by-{receipt.domain.dimension} matrix "
            f"is the {qualifier} localization from the finite S-Kummer presentation to genuine "
            f"local H^1 at {receipt.codomain.place_id} {conclusion}",
            parameters={
                "domain_receipt": receipt.domain.content_id,
                "codomain_receipt": receipt.codomain.content_id,
                "matrix": receipt.matrix,
                "source_coordinates": receipt.source_coordinates,
                "image_coordinates": receipt.image_coordinates,
                "completeness": receipt.proof_context["completeness"],
                "receipt": receipt.content_id,
            },
        )
    return FormalStatement.create(
        f"Exhaustive finite nonabelian H^1 consists of exactly {len(receipt.orbits)} pointed "
        "coefficient-conjugacy classes of cocycles.",
        parameters={
            "acting_group_order": len(receipt.acting_table),
            "coefficient_group_order": len(receipt.coefficient_table),
            "cocycle_count": len(receipt.cocycles),
            "class_count": len(receipt.orbits),
            "pointed_class": 0,
            "receipt": receipt.content_id,
        },
    )


def verification_certificate_for(receipt: ReceiptType) -> VerificationCertificate:
    receipt.verify()
    verifier = _verifier(receipt)
    statement = _statement(receipt)
    claim_id = _claim_id(receipt)
    return VerificationCertificate.create(
        subject=_subject(receipt),
        verifier=verifier,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=_status(receipt),
            hypotheses=_hypotheses(receipt),
        ),
        witness={_RECEIPT_FIELD[verifier]: receipt.to_dict()},
        checks=_CHECKS[verifier],
        dependencies=tuple(
            CertificateRef.from_certificate(certificate)
            for certificate in proving_certificates(receipt)
        ),
        guarantees=_GUARANTEES[verifier],
    )


def claim_for(receipt: ReceiptType) -> Claim:
    certificate = verification_certificate_for(receipt)
    statement = _statement(receipt)
    assumptions = _assumptions(receipt)
    return Claim(
        _claim_id(receipt),
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=_hypotheses(receipt),
        how=Derivation.computation(
            _operation(receipt),
            method="Independent finite replay of the canonical arithmetic receipt",
            inputs=(receipt.content_id,),
            artifact=certificate.certificate_id,
        ),
        certificate=certificate,
        supporting_certificates=proving_certificates(receipt),
        metadata={
            "arithmetic_receipt_schema": receipt.schema_version,
            "arithmetic_receipt": receipt.content_id,
            "assumptions": assumptions,
            "verifier_trust_is_independent": True,
        },
    )


def claim_graph_for(receipt: ReceiptType) -> ClaimGraph:
    return ClaimGraph((claim_for(receipt),))


def verification_certificate_for_result(result: Any) -> VerificationCertificate:
    """Return the central certificate for a substantial public Galois result."""

    certificate = getattr(result, "certificate", None)
    if isinstance(certificate, VerificationCertificate):
        return certificate
    return verification_certificate_for(_receipt_for_result(result))


def claim_for_result(result: Any) -> Claim:
    """Return the semantic claim proved by a substantial public Galois result."""

    claim_method = getattr(result, "claim", None)
    if callable(claim_method):
        claim = claim_method()
        if isinstance(claim, Claim):
            return claim
    return claim_for(_receipt_for_result(result))


def claim_graph_for_result(result: Any) -> ClaimGraph:
    """Return the claim graph proved by a substantial public Galois result."""

    graph_method = getattr(result, "claim_graph", None)
    if callable(graph_method):
        graph = graph_method()
        if isinstance(graph, ClaimGraph):
            return graph
    return claim_graph_for(_receipt_for_result(result))


def _decode_receipt(verifier: str, payload: Mapping[str, object]) -> ReceiptType:
    field = _RECEIPT_FIELD[verifier]
    if set(payload) != {field}:
        raise CertificateVerificationError(f"{verifier} witness must contain exactly {field}")
    raw = payload[field]
    if not isinstance(raw, Mapping):
        raise CertificateVerificationError(f"{field} must be an object")
    try:
        if verifier == KUMMER_VERIFIER:
            return KummerReceipt.from_dict(raw)
        if verifier == LOCAL_H1_VERIFIER:
            return LocalH1Receipt.from_dict(raw)
        if verifier == LOCALIZATION_VERIFIER:
            return LocalizationReceipt.from_dict(raw)
        return TwistReceipt.from_dict(raw)
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error


def _verify(certificate: VerificationCertificate, verifier: str) -> VerificationReport:
    if certificate.verifier != verifier:
        raise CertificateVerificationError("arithmetic certificate names a different verifier")
    receipt = _decode_receipt(verifier, certificate.witness.to_dict())
    try:
        receipt.verify()
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    statement = _statement(receipt)
    claim_id = _claim_id(receipt)
    if certificate.subject != _subject(receipt):
        raise CertificateVerificationError("certificate subject is not bound to its receipt")
    if certificate.claim_id != claim_id:
        raise CertificateVerificationError("certificate claim ID is not bound to its receipt")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("certificate statement hash is not bound to its receipt")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=_hypotheses(receipt),
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("certificate claim boundary was altered")
    if certificate.claim_dependencies:
        raise CertificateVerificationError(
            "arithmetic receipt cannot carry mathematical claim dependencies"
        )
    expected_dependencies = tuple(
        CertificateRef.from_certificate(item) for item in proving_certificates(receipt)
    )
    if certificate.dependencies != expected_dependencies:
        raise CertificateVerificationError(
            "arithmetic certificate dependencies are not bound to nested proof evidence"
        )
    if certificate.checks != _CHECKS[verifier]:
        raise CertificateVerificationError("arithmetic verification checks were altered")
    if certificate.guarantees != _GUARANTEES[verifier]:
        raise CertificateVerificationError("arithmetic verification guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=verifier,
        certificate_id=certificate.certificate_id,
        checks=_CHECKS[verifier],
        details=freeze_mapping(
            {
                "receipt": receipt.content_id,
                "schema": receipt.schema_version,
                "assumptions": _assumptions(receipt),
            }
        ),
    )


def _verify_kummer(certificate: VerificationCertificate) -> VerificationReport:
    return _verify(certificate, KUMMER_VERIFIER)


def _verify_local_h1(certificate: VerificationCertificate) -> VerificationReport:
    return _verify(certificate, LOCAL_H1_VERIFIER)


def _verify_localization(certificate: VerificationCertificate) -> VerificationReport:
    return _verify(certificate, LOCALIZATION_VERIFIER)


def _verify_twists(certificate: VerificationCertificate) -> VerificationReport:
    return _verify(certificate, TWIST_VERIFIER)


def _register() -> None:
    for name, function in (
        (KUMMER_VERIFIER, _verify_kummer),
        (LOCAL_H1_VERIFIER, _verify_local_h1),
        (LOCALIZATION_VERIFIER, _verify_localization),
        (TWIST_VERIFIER, _verify_twists),
    ):
        if name not in default_verifiers.names():
            default_verifiers.register(name, VerificationCertificate, function)
            continue
        described = default_verifiers.describe(name)
        expected = f"{__name__}.{function.__name__}"
        if described["callable"] != expected:
            raise RuntimeError(f"verifier name collision for {name}")


_register()


__all__ = [
    "KUMMER_VERIFIER",
    "LOCALIZATION_VERIFIER",
    "LOCAL_H1_VERIFIER",
    "TWIST_VERIFIER",
    "claim_for",
    "claim_for_result",
    "claim_graph_for",
    "claim_graph_for_result",
    "verification_certificate_for",
    "verification_certificate_for_result",
]
