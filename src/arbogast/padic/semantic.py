"""Central certificate and claim adapters for bounded p-adic results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from arbogast.cert import (
    CertificateRef,
    CertificateVerificationError,
    ClaimBinding,
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
from arbogast.galois.proof import VerificationRequirement, VerifierTrust

from ._schema import PAdicSemanticObject
from .certificate import (
    FINITE_EXACT_VERIFIER,
    RECEIPT_KINDS,
    THREE_POINT_EXACT_VERIFIER,
    PAdicReceipt,
    complete_proof_context,
)
from .errors import PAdicCertificateError
from .results import Certified, Partial, Unknown, Unsupported

VERIFIER_NAMES = (FINITE_EXACT_VERIFIER, THREE_POINT_EXACT_VERIFIER)
VERIFICATION_CHECKS = (
    "padic-receipt-integrity",
    "strict-canonical-resource-envelope",
    "dependency-closed-exact-evidence",
    "scope-preserving-result-boundary",
)
VERIFICATION_GUARANTEES = (
    "The embedded p-adic receipt is replayed using exact finite witnesses only.",
    "Completeness, assumptions, verifier trust, and non-success closure remain independent.",
    "Partial, unknown, and unsupported outcomes imply no unproved mathematical conclusion.",
)


def _claim_id(receipt: PAdicReceipt) -> str:
    digest = receipt.certificate_id.removeprefix("sha256:")
    return f"padic.{receipt.kind.replace('-', '_')}.{digest}"


def _subject(receipt: PAdicReceipt) -> str:
    family = "finite" if receipt.verifier == FINITE_EXACT_VERIFIER else "three-point"
    return f"padic:{family}:{receipt.kind}:{receipt.certificate_id}"


def _status(receipt: PAdicReceipt) -> EpistemicStatus:
    if receipt.closure in {"partial", "unknown"}:
        return EpistemicStatus.UNKNOWN
    if receipt.closure == "unsupported":
        return EpistemicStatus.EXACT
    if receipt.proof_context.assumptions:
        return EpistemicStatus.CONDITIONAL
    if any(
        requirement.trust is VerifierTrust.PINNED_EXTERNAL
        for requirement in receipt.proof_context.verification_requirements
    ):
        return EpistemicStatus.CERTIFIED
    return EpistemicStatus.EXACT


def _operation(receipt: PAdicReceipt) -> str:
    if receipt.closure == "certified":
        return f"padic.{receipt.kind.replace('-', '_')}"
    operation = receipt.payload.to_dict().get("operation")
    if not isinstance(operation, str):
        raise PAdicCertificateError("p-adic non-success payload omits its operation")
    return operation


def _claim_dependency_ids(receipt: PAdicReceipt) -> tuple[str, ...]:
    del receipt
    return ()


def _claim_bindings(receipt: PAdicReceipt) -> tuple[ClaimBinding, ...]:
    del receipt
    return ()


def _embedded_receipt(
    certificate: VerificationCertificate,
) -> PAdicReceipt | None:
    witness = certificate.witness.to_dict()
    raw = witness.get("padic_receipt")
    if raw is None:
        return None
    if set(witness) != {"padic_receipt"} or type(raw) is not dict:
        raise PAdicCertificateError("p-adic evidence carries a malformed embedded receipt")
    receipt = PAdicReceipt.from_dict(cast(dict[str, object], raw))
    if certificate.verifier != receipt.verifier:
        raise PAdicCertificateError("embedded p-adic receipt names another verifier family")
    return receipt


def _supporting_certificate_closure(
    receipt: PAdicReceipt,
) -> tuple[VerificationCertificate, ...]:
    """Recover every nested prerequisite certificate embedded by p-adic receipts."""

    collected: dict[str, VerificationCertificate] = {}
    active: set[str] = set()

    def visit(certificate: VerificationCertificate) -> None:
        certificate_id = certificate.certificate_id
        if certificate_id in active:
            raise PAdicCertificateError("cycle in embedded p-adic evidence closure")
        incumbent = collected.get(certificate_id)
        if incumbent is not None:
            if incumbent != certificate:
                raise PAdicCertificateError("conflicting p-adic evidence content identity")
            return
        active.add(certificate_id)
        collected[certificate_id] = certificate
        nested = _embedded_receipt(certificate)
        if nested is not None:
            dependency_refs = tuple(item.certificate_id for item in certificate.dependencies)
            nested_ids = tuple(item.certificate_id for item in nested.evidence)
            if dependency_refs != nested_ids:
                raise PAdicCertificateError(
                    "embedded p-adic certificate dependency closure was altered"
                )
            for child in nested.evidence:
                visit(child)
        active.remove(certificate_id)

    for root in receipt.evidence:
        visit(root)
    return tuple(collected[key] for key in sorted(collected))


def _dependency_refs(receipt: PAdicReceipt) -> tuple[CertificateRef, ...]:
    return tuple(CertificateRef.from_certificate(item) for item in receipt.evidence)


def statement_for_receipt(receipt: PAdicReceipt) -> FormalStatement:
    if receipt.closure == "certified":
        text = (
            f"The displayed {receipt.kind} result satisfies the bounded p-adic claim "
            "encoded by its complete canonical witness."
        )
    elif receipt.closure == "partial":
        text = (
            "The displayed p-adic fragments are independently certified, while the full "
            "requested result remains unknown subject to the listed proof obligations."
        )
    elif receipt.closure == "unknown":
        text = (
            "The requested p-adic conclusion remains explicitly unknown for the displayed "
            "bounded reason; no positive or negative conclusion is asserted."
        )
    else:
        text = (
            "The requested operation lies outside the bounded p-adic software surface; this "
            "asserts no mathematical existence or nonexistence conclusion."
        )
    return FormalStatement.create(
        text,
        parameters={
            "assumptions": receipt.proof_context.assumptions,
            "closure": receipt.closure,
            "completeness": receipt.proof_context.completeness.value,
            "object_id": receipt.object_id,
            "payload": receipt.payload,
            "receipt_id": receipt.certificate_id,
            "receipt_kind": receipt.kind,
            "receipt_schema": receipt.schema_version,
            "verification_requirements": tuple(
                item.to_dict() for item in receipt.proof_context.verification_requirements
            ),
        },
    )


def _verify_semantic_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    witness = certificate.witness.to_dict()
    if type(witness) is not dict or set(witness) != {"padic_receipt"}:
        raise CertificateVerificationError("p-adic witness must contain exactly padic_receipt")
    raw = witness["padic_receipt"]
    if type(raw) is not dict:
        raise CertificateVerificationError("embedded p-adic receipt must be an object")
    try:
        receipt = PAdicReceipt.from_dict(cast(dict[str, object], raw))
        replay_checks = receipt.verify()
    except (TypeError, ValueError) as exc:
        raise CertificateVerificationError(str(exc)) from exc
    if certificate.verifier != receipt.verifier:
        raise CertificateVerificationError("p-adic verifier family was altered")
    statement = statement_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    dependency_ids = _claim_dependency_ids(receipt)
    if certificate.subject != _subject(receipt) or certificate.claim_id != claim_id:
        raise CertificateVerificationError("p-adic subject or claim identity was altered")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("p-adic statement hash was altered")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=receipt.proof_context.assumptions,
        dependency_ids=dependency_ids,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("p-adic claim boundary was altered")
    if certificate.claim_dependencies != _claim_bindings(receipt):
        raise CertificateVerificationError("p-adic claim dependency bindings were altered")
    if certificate.dependencies != _dependency_refs(receipt):
        raise CertificateVerificationError("p-adic proof dependencies were altered")
    if certificate.checks != VERIFICATION_CHECKS:
        raise CertificateVerificationError("p-adic verification checks were altered")
    if certificate.guarantees != VERIFICATION_GUARANTEES:
        raise CertificateVerificationError("p-adic verification guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=receipt.verifier,
        certificate_id=certificate.certificate_id,
        checks=(*VERIFICATION_CHECKS, *replay_checks),
        details=freeze_mapping(
            {
                "closure": receipt.closure,
                "completeness": receipt.proof_context.completeness.value,
                "mathematical_conclusion": receipt.closure == "certified",
                "object_id": receipt.object_id,
                "receipt_id": receipt.certificate_id,
                "receipt_kind": receipt.kind,
            }
        ),
    )


def _register_verifiers() -> None:
    for verifier_name in VERIFIER_NAMES:
        if verifier_name not in default_verifiers.names():
            default_verifiers.register(
                verifier_name,
                VerificationCertificate,
                _verify_semantic_certificate,
            )
            continue
        registered = default_verifiers.describe(verifier_name)
        expected = f"{__name__}._verify_semantic_certificate"
        if registered["callable"] != expected:
            raise RuntimeError(
                f"verifier name collision for {verifier_name}: {registered['callable']}"
            )


_register_verifiers()


def receipt_for_result(result: object) -> PAdicReceipt:
    """Return or construct the complete receipt for one p-adic semantic result."""

    if isinstance(result, PAdicReceipt):
        result.verify()
        return result
    if isinstance(result, (Certified, Partial, Unknown, Unsupported)):
        result.verify()
        return result.receipt
    if not isinstance(result, PAdicSemanticObject):
        raise TypeError("p-adic result must be a semantic p-adic object or result variant")
    if result.verify() is not True:
        raise PAdicCertificateError("p-adic result verification returned false")
    schema = result.schema_version
    prefix = "arbogast.padic."
    suffix = "/v1"
    if not schema.startswith(prefix) or not schema.endswith(suffix):
        raise PAdicCertificateError("p-adic result carries an unsupported schema identity")
    kind = schema.removeprefix(prefix).removesuffix(suffix)
    if kind not in RECEIPT_KINDS:
        raise PAdicCertificateError(
            "schema object is not a standalone proving result; wrap the operation output"
        )
    assumptions = getattr(result, "assumptions", ())
    requirements = getattr(result, "verification_requirements", ())
    evidence = getattr(result, "supporting_certificates", ())
    if isinstance(assumptions, (str, bytes)) or not isinstance(assumptions, Sequence):
        raise PAdicCertificateError("p-adic assumptions must be a sequence")
    if isinstance(requirements, (str, bytes)) or not isinstance(requirements, Sequence):
        raise PAdicCertificateError("p-adic verification requirements must be a sequence")
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise PAdicCertificateError("p-adic supporting certificates must be a sequence")
    receipt = PAdicReceipt.create(
        kind,
        "certified",
        {"result": result.to_schema_document()},
        proof_context=complete_proof_context(
            kind,
            assumptions=cast(Sequence[str], assumptions),
            verification_requirements=cast(
                Sequence[VerificationRequirement],
                requirements,
            ),
        ),
        evidence=cast(Sequence[VerificationCertificate], evidence),
    )
    receipt.verify()
    return receipt


def verification_certificate_for_receipt(
    receipt: PAdicReceipt,
) -> VerificationCertificate:
    receipt.verify()
    claim_id = _claim_id(receipt)
    statement = statement_for_receipt(receipt)
    dependency_ids = _claim_dependency_ids(receipt)
    return VerificationCertificate.create(
        subject=_subject(receipt),
        verifier=receipt.verifier,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=_status(receipt),
            hypotheses=receipt.proof_context.assumptions,
            dependency_ids=dependency_ids,
        ),
        claim_dependencies=_claim_bindings(receipt),
        witness={"padic_receipt": receipt.to_dict()},
        checks=VERIFICATION_CHECKS,
        dependencies=_dependency_refs(receipt),
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim_for_receipt(receipt: PAdicReceipt) -> Claim:
    certificate = verification_certificate_for_receipt(receipt)
    metadata: dict[str, object] = {
        "closure": receipt.closure,
        "completeness": receipt.proof_context.completeness.value,
        "mathematical_conclusion": receipt.closure == "certified",
        "object_id": receipt.object_id,
        "receipt_id": receipt.certificate_id,
        "receipt_schema": receipt.schema_version,
        "verifier": receipt.verifier,
    }
    if receipt.closure == "unsupported":
        metadata["software_boundary_only"] = True
    return Claim(
        _claim_id(receipt),
        statement=statement_for_receipt(receipt),
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        why=_claim_dependency_ids(receipt),
        how=Derivation.computation(
            _operation(receipt),
            method="Portable exact replay of the bounded p-adic receipt",
            inputs=(receipt.certificate_id,),
            artifact=certificate.certificate_id,
            parameters={
                "closure": receipt.closure,
                "receipt_kind": receipt.kind,
                "verifier": receipt.verifier,
            },
        ),
        certificate=certificate,
        supporting_certificates=_supporting_certificate_closure(receipt),
        hypotheses=receipt.proof_context.assumptions,
        metadata=metadata,
    )


def claim_graph_for_receipt(receipt: PAdicReceipt) -> ClaimGraph:
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
    "VERIFIER_NAMES",
    "claim_for_receipt",
    "claim_for_result",
    "claim_graph_for_receipt",
    "claim_graph_for_result",
    "receipt_for_result",
    "statement_for_receipt",
    "verification_certificate_for_receipt",
    "verification_certificate_for_result",
]
