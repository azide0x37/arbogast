"""Central claims and certificates for portable finite deformation results.

This module is deliberately an adapter, not a second proof system.  It turns
the independently replayable :class:`DeformationReceipt` into the unchanged
``VerificationCertificate`` v1 envelope and binds the complete semantic
boundary of the resulting claim.  Runtime deformation objects are used only
to construct receipts; verification starts again from the embedded canonical
snapshots and their recursively embedded prerequisite certificates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast, runtime_checkable

from arbogast.cert import (
    CertificateRef,
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    content_address,
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

from .certificate import (
    EXPECTED_TYPES,
    PORTABLE_VERIFIER,
    Completeness,
    DeformationCertificateError,
    DeformationReceipt,
)

VERIFIER_NAME = PORTABLE_VERIFIER
VERIFICATION_CHECKS = (
    "deformation-receipt-integrity",
    "portable-prime-field-replay",
    "dependency-closed-finite-evidence",
    "assumptions-completeness-trust-axes",
)
VERIFICATION_GUARANTEES = (
    "The embedded deformation receipt is replayed using exact prime-field arithmetic.",
    "Every referenced prerequisite is supplied as recursively replayable verification evidence.",
    "Assumptions, completeness, and portable verifier trust are bound without promotion.",
)


_KIND_BY_TYPE = {type_tag: kind for kind, type_tag in EXPECTED_TYPES.items()}

_OPERATIONS = {
    "artin-ring": "deform.artin_ring",
    "artin-map": "deform.artin_map",
    "small-extension": "deform.small_extension",
    "complex": "deform.complex",
    "problem": "deform.problem",
    "gauge": "deform.gauge",
    "tangent": "deform.tangent",
    "obstruction-space": "deform.obstructions",
    "obstruction-class": "deform.obstruction_class",
    "framing": "deform.frame",
    "action": "deform.action",
    "equivariant": "deform.equivariant",
    "invariant-complex": "deform.invariant_deformations",
    "decomposition": "deform.equivariant_decomposition",
    "lift-datum": "deform.lift_datum",
    "lift-family": "deform.lift",
    "lift-obstructed": "deform.lift",
    "lift-unknown": "deform.lift",
    "unique-lift": "deform.unique_lift",
    "nonunique-lift": "deform.unique_lift",
    "lift-endomorphism": "deform.lift_endomorphism",
    "contraction": "deform.contraction",
    "fixed-lift": "deform.fixed_lift",
    "rigid": "deform.rigid",
    "nonrigid": "deform.rigid",
    "unsupported": "deform.unsupported",
}

_STATEMENTS = {
    "artin-ring": "The displayed finite presentation is a commutative local Artin algebra.",
    "artin-map": (
        "The displayed linear map is a unit-, residue-, and "
        "multiplication-preserving Artin-ring map."
    ),
    "small-extension": "The displayed surjection has the exact supplied square-zero kernel.",
    "complex": "The displayed three-term prime-field complex has zero consecutive composite.",
    "problem": (
        "The pinned presentation, framing, and effective deformation complex replay exactly."
    ),
    "gauge": "The displayed gauge space is exactly the degree-zero cocycle kernel.",
    "tangent": "The displayed tangent space is exactly ker(d1) modulo im(d0).",
    "obstruction-space": "The displayed obstruction space is exactly degree two modulo im(d1).",
    "obstruction-class": (
        "The displayed vector is the canonical representative of its obstruction class."
    ),
    "framing": "The displayed allowed gauge directions are exactly the framing-constraint kernel.",
    "action": (
        "The displayed finite-group action is a degreewise representation by chain automorphisms."
    ),
    "equivariant": "The checked chain action is bound to the displayed deformation problem.",
    "invariant-complex": (
        "The displayed problem is the exact invariant subcomplex; no "
        "invariant-cohomology identification is asserted."
    ),
    "decomposition": (
        "The displayed equivariant projectors form a complete orthogonal chain decomposition."
    ),
    "lift-datum": (
        "The displayed affine correction datum is bound to its problem and small extension."
    ),
    "lift-family": (
        "The displayed affine family is the complete solution space modulo the pinned "
        "gauge directions."
    ),
    "lift-obstructed": (
        "The displayed left-nullspace witness proves the lift equation inconsistent."
    ),
    "lift-unknown": (
        "The lift result is explicitly unknown for the displayed reason; no existence or "
        "obstruction conclusion is asserted."
    ),
    "unique-lift": (
        "The displayed representative is the unique lift modulo the pinned gauge directions."
    ),
    "nonunique-lift": (
        "The two displayed solutions have a checked nonzero separating mod-gauge class."
    ),
    "lift-endomorphism": "The displayed affine map preserves the complete lift family.",
    "contraction": "The displayed exponent kills every homogeneous lift difference.",
    "fixed-lift": (
        "The displayed contracted iterate lies in the lift family and is fixed by its "
        "affine endomorphism."
    ),
    "rigid": (
        "The supplied exact finite deformation complex has zero tangent quotient; this is "
        "infinitesimal rigidity for the pinned presentation only."
    ),
    "nonrigid": "The displayed nonzero tangent class witnesses failure of infinitesimal rigidity.",
    "unsupported": (
        "The requested deformation operation is explicitly unsupported; no mathematical "
        "conclusion is asserted."
    ),
}


@runtime_checkable
class _CanonicalDeformationResult(Protocol):
    def verify(self) -> bool: ...

    def to_canonical_data(self) -> object: ...


def _claim_id(receipt: DeformationReceipt) -> str:
    digest = receipt.certificate_id.removeprefix("sha256:")
    return f"deform.{receipt.kind.replace('-', '_')}.{digest}"


def _subject(receipt: DeformationReceipt) -> str:
    return f"deform:{receipt.kind}:{receipt.certificate_id}"


def _status(receipt: DeformationReceipt) -> EpistemicStatus:
    if receipt.kind in {"lift-unknown", "unsupported"}:
        return EpistemicStatus.UNKNOWN
    if receipt.assumptions:
        return EpistemicStatus.CONDITIONAL
    return EpistemicStatus.EXACT


def _dependency_refs(receipt: DeformationReceipt) -> tuple[CertificateRef, ...]:
    return tuple(
        CertificateRef.from_certificate(certificate) for certificate in receipt.dependencies
    )


def _dependency_certificate_closure(
    receipt: DeformationReceipt,
) -> tuple[VerificationCertificate, ...]:
    """Recover the complete certificate DAG embedded in receipt witnesses."""

    by_id: dict[str, VerificationCertificate] = {}
    pending = list(receipt.dependencies)
    while pending:
        certificate = pending.pop()
        if certificate.certificate_id in by_id:
            continue
        by_id[certificate.certificate_id] = certificate
        if certificate.verifier != VERIFIER_NAME:
            raise DeformationCertificateError(
                "deformation receipt dependency names a foreign verifier"
            )
        witness = certificate.witness.to_dict()
        raw = witness.get("deformation_receipt")
        if set(witness) != {"deformation_receipt"} or not isinstance(raw, Mapping):
            raise DeformationCertificateError(
                "deformation receipt dependency lacks its embedded receipt"
            )
        nested = DeformationReceipt.from_dict(raw)
        pending.extend(nested.dependencies)
    return tuple(by_id[certificate_id] for certificate_id in sorted(by_id))


def _assumptions_for_result(result: object) -> tuple[str, ...]:
    raw = getattr(result, "assumptions", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise DeformationCertificateError("result assumptions must be a sequence")
    assumptions = tuple(raw)
    if any(not isinstance(item, str) or not item.strip() for item in assumptions):
        raise DeformationCertificateError("result assumptions must be non-blank strings")
    return tuple(sorted(set(cast(tuple[str, ...], assumptions))))


def _completeness_for_result(result: object, kind: str) -> Completeness | None:
    raw = getattr(result, "completeness", None)
    if raw is not None and not isinstance(raw, str):
        raw = getattr(raw, "value", raw)
    if raw is None:
        return None
    if raw not in {"candidate", "complete"}:
        raise DeformationCertificateError("result completeness must be candidate or complete")
    completeness = cast(Completeness, raw)
    if kind in {"lift-unknown", "unsupported"} and completeness != "candidate":
        raise DeformationCertificateError("unknown and unsupported outcomes cannot be complete")
    return completeness


def _required_attribute(result: object, name: str) -> object:
    try:
        return getattr(result, name)
    except AttributeError as exc:
        raise DeformationCertificateError(
            f"{type(result).__qualname__} lacks proving dependency {name}"
        ) from exc


def _dependency_results(result: object, kind: str) -> tuple[object, ...]:
    if kind == "artin-map":
        return (
            _required_attribute(result, "domain"),
            _required_attribute(result, "codomain"),
        )
    if kind == "small-extension":
        return (_required_attribute(result, "projection"),)
    if kind in {"gauge", "tangent", "obstruction-space"}:
        return (_required_attribute(result, "problem"),)
    if kind == "obstruction-class":
        return (_required_attribute(result, "space"),)
    if kind == "action":
        return (_required_attribute(result, "complex"),)
    if kind == "equivariant":
        # The action snapshot is nested in the result.  The problem dependency
        # supplies the effective complex referenced by that action.
        return (_required_attribute(result, "problem"),)
    if kind in {"invariant-complex", "decomposition"}:
        return (_required_attribute(result, "equivariant_deformation"),)
    if kind == "lift-datum":
        return (
            _required_attribute(result, "problem"),
            _required_attribute(result, "extension"),
        )
    if kind in {"lift-family", "lift-obstructed"}:
        return (_required_attribute(result, "datum"),)
    if kind == "lift-unknown":
        datum = _required_attribute(result, "datum")
        return () if datum is None else (datum,)
    if kind in {"unique-lift", "nonunique-lift", "lift-endomorphism"}:
        return (_required_attribute(result, "family"),)
    if kind == "contraction":
        return (_required_attribute(result, "endomorphism"),)
    if kind == "fixed-lift":
        # The contraction receipt recursively contains its endomorphism and
        # family.  One closed chain supplies all three IDs without duplicating
        # an exponentially growing proof tree.
        return (_required_attribute(result, "contraction"),)
    if kind in {"rigid", "nonrigid"}:
        # A tangent receipt already carries its problem prerequisite.
        return (_required_attribute(result, "tangent_space"),)
    return ()


def _canonical_payload(result: object) -> tuple[str, Mapping[str, object]]:
    if not isinstance(result, _CanonicalDeformationResult):
        raise TypeError("result must expose verify() and to_canonical_data()")
    if result.verify() is False:
        raise DeformationCertificateError("deformation result verification returned false")
    raw = result.to_canonical_data()
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise DeformationCertificateError(
            "deformation result canonical data must be a string-keyed mapping"
        )
    payload = cast(Mapping[str, object], raw)
    type_tag = payload.get("type")
    if not isinstance(type_tag, str) or type_tag not in _KIND_BY_TYPE:
        raise DeformationCertificateError(
            "result is structural-only or has an unsupported deformation type tag"
        )
    return _KIND_BY_TYPE[type_tag], payload


def _receipt_for_result(
    result: object,
    receipt_cache: dict[tuple[str, str], DeformationReceipt],
    certificate_cache: dict[tuple[str, str], VerificationCertificate],
    active: set[tuple[str, str]],
) -> DeformationReceipt:
    if isinstance(result, DeformationReceipt):
        result.verify()
        return result
    kind, payload = _canonical_payload(result)
    key = (kind, content_address(payload))
    cached = receipt_cache.get(key)
    if cached is not None:
        return cached
    if key in active:
        raise DeformationCertificateError("runtime deformation dependency graph contains a cycle")
    active.add(key)
    dependencies_by_id: dict[str, VerificationCertificate] = {}
    try:
        for dependency in _dependency_results(result, kind):
            dependency_kind, dependency_payload = _canonical_payload(dependency)
            dependency_key = (dependency_kind, content_address(dependency_payload))
            certificate = certificate_cache.get(dependency_key)
            if certificate is None:
                dependency_receipt = _receipt_for_result(
                    dependency,
                    receipt_cache,
                    certificate_cache,
                    active,
                )
                certificate = verification_certificate_for_receipt(dependency_receipt)
                certificate_cache[dependency_key] = certificate
            dependencies_by_id[certificate.certificate_id] = certificate
        receipt = DeformationReceipt.create(
            kind,
            payload,
            dependencies=tuple(dependencies_by_id.values()),
            assumptions=_assumptions_for_result(result),
            completeness=_completeness_for_result(result, kind),
        )
        receipt.verify()
        receipt_cache[key] = receipt
        return receipt
    finally:
        active.remove(key)


def receipt_for_result(result: object) -> DeformationReceipt:
    """Freeze a substantial runtime result and all of its prerequisites."""

    return _receipt_for_result(result, {}, {}, set())


def statement_for_receipt(receipt: DeformationReceipt) -> FormalStatement:
    """Return the complete semantic statement bound by a receipt."""

    return FormalStatement.create(
        text=_STATEMENTS[receipt.kind],
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


def _verify_semantic_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    witness = certificate.witness.to_dict()
    if set(witness) != {"deformation_receipt"}:
        raise CertificateVerificationError(
            "deformation witness must contain exactly deformation_receipt"
        )
    raw_receipt = witness["deformation_receipt"]
    if not isinstance(raw_receipt, Mapping):
        raise CertificateVerificationError("embedded deformation receipt must be an object")
    try:
        receipt = DeformationReceipt.from_dict(raw_receipt)
        replay_checks = receipt.verify()
    except (TypeError, ValueError) as exc:
        raise CertificateVerificationError(str(exc)) from exc
    return _verify_semantic_certificate_with_receipt(
        certificate,
        receipt,
        replay_checks,
    )


def _verify_semantic_certificate_with_receipt(
    certificate: VerificationCertificate,
    receipt: DeformationReceipt,
    replay_checks: tuple[str, ...],
) -> VerificationReport:
    """Check the central envelope after one shared-DAG receipt replay."""

    statement = statement_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    if certificate.subject != _subject(receipt):
        raise CertificateVerificationError("deformation subject is not bound to its receipt")
    if certificate.verifier != VERIFIER_NAME:
        raise CertificateVerificationError("deformation certificate names a different verifier")
    if certificate.claim_id != claim_id:
        raise CertificateVerificationError("deformation claim ID is not bound to its receipt")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("deformation statement hash is not bound to its receipt")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        hypotheses=receipt.assumptions,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("deformation claim boundary was altered")
    if certificate.claim_dependencies:
        raise CertificateVerificationError(
            "finite deformation receipts have no theorem-claim dependencies"
        )
    if certificate.dependencies != _dependency_refs(receipt):
        raise CertificateVerificationError(
            "deformation proof dependencies do not match the embedded receipt"
        )
    if certificate.checks != VERIFICATION_CHECKS:
        raise CertificateVerificationError("deformation verification check manifest was altered")
    if certificate.guarantees != VERIFICATION_GUARANTEES:
        raise CertificateVerificationError("deformation verification guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=VERIFIER_NAME,
        certificate_id=certificate.certificate_id,
        checks=replay_checks,
        details=freeze_mapping(
            {
                "deformation_receipt": receipt.certificate_id,
                "receipt_kind": receipt.kind,
                "object_id": receipt.object_id,
                "assumptions": receipt.assumptions,
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


def verification_certificate_for_receipt(
    receipt: DeformationReceipt,
) -> VerificationCertificate:
    """Nest a replayable receipt in the unchanged central certificate schema."""

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
        witness={"deformation_receipt": receipt.to_dict()},
        checks=VERIFICATION_CHECKS,
        dependencies=_dependency_refs(receipt),
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim_for_receipt(receipt: DeformationReceipt) -> Claim:
    """Build the central computed claim for one finite deformation receipt."""

    certificate = verification_certificate_for_receipt(receipt)
    claim_id = _claim_id(receipt)
    return Claim(
        id=claim_id,
        statement=statement_for_receipt(receipt),
        kind=ClaimKind.COMPUTED,
        status=_status(receipt),
        how=Derivation.computation(
            _OPERATIONS[receipt.kind],
            method="Exact finite deformation replay over a prime field",
            inputs=(receipt.certificate_id,),
            artifact=certificate.certificate_id,
            parameters={
                "receipt_kind": receipt.kind,
                "completeness": receipt.completeness,
                "verifier_trust": receipt.verifier_trust,
            },
        ),
        certificate=certificate,
        supporting_certificates=_dependency_certificate_closure(receipt),
        hypotheses=receipt.assumptions,
        metadata={
            "receipt_schema": receipt.schema_version,
            "receipt_id": receipt.certificate_id,
            "object_id": receipt.object_id,
            "assumptions": receipt.assumptions,
            "completeness": receipt.completeness,
            "verifier_trust": receipt.verifier_trust,
        },
    )


def claim_graph_for_receipt(receipt: DeformationReceipt) -> ClaimGraph:
    """Return the one-node theorem DAG backed by dependency-closed evidence."""

    return ClaimGraph((claim_for_receipt(receipt),))


class DeformationSemanticResult:
    """Optional mixin exposing the same hooks as the core lazy adapter."""

    @property
    def receipt(self) -> DeformationReceipt:
        return receipt_for_result(self)

    @property
    def certificate(self) -> VerificationCertificate:
        return verification_certificate_for_result(self)

    def claim(self) -> Claim:
        return claim_for_result(self)

    def claim_graph(self) -> ClaimGraph:
        return claim_graph_for_result(self)

    def _verify_semantics(self) -> VerificationReport:
        self.receipt.verify()
        return verify_certificate(self.certificate)


def verification_certificate_for_result(result: object) -> VerificationCertificate:
    """Return the central certificate for a substantial deformation result."""

    return verification_certificate_for_receipt(receipt_for_result(result))


def claim_for_result(result: object) -> Claim:
    """Return the central claim bound to a substantial deformation result."""

    return claim_for_receipt(receipt_for_result(result))


def claim_graph_for_result(result: object) -> ClaimGraph:
    """Return the claim graph bound to a substantial deformation result."""

    return claim_graph_for_receipt(receipt_for_result(result))


__all__ = [
    "VERIFICATION_CHECKS",
    "VERIFICATION_GUARANTEES",
    "VERIFIER_NAME",
    "DeformationSemanticResult",
    "claim_for_receipt",
    "claim_for_result",
    "claim_graph_for_receipt",
    "claim_graph_for_result",
    "receipt_for_result",
    "statement_for_receipt",
    "verification_certificate_for_receipt",
    "verification_certificate_for_result",
]
