"""Portable, fail-closed adapters from exact Hurwitz receipts to claims."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from arbogast.cert import VerificationCertificate, default_verifiers
from arbogast.cert.canonical import validate_content_address
from arbogast.cert.registry import CertificateVerificationError as SemanticVerificationError
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
)

from .nielsen import (
    NielsenClass,
    NielsenEnumerationCertificate,
    verify_nielsen_certificate_payload,
)
from .portable import (
    PORTABLE_OPERATIONS,
    HurwitzOperationCertificate,
    operation_certificate_for,
)

_VERIFIER = "hurwitz.nielsen_class"
_CHECKS = (
    "explicit-classes",
    "product-one",
    "generation",
    "inner-canonicalization",
    "exhaustion",
)
_GUARANTEES = ("the representative list is the complete inner Nielsen class",)

_OPERATION_CONTRACTS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "braid_action": (
        (
            "portable-Nielsen-replay",
            "right-Hurwitz-words",
            "inner-canonicalization",
            "inverse-permutations",
        ),
        ("the advertised named braid words induce exactly the certified vertex permutations",),
    ),
    "components": (
        (
            "portable-Nielsen-replay",
            "braid-action-replay",
            "forward-and-inverse-closure",
            "orbit-exhaustion",
        ),
        ("the listed blocks are exactly all orbits of the supplied named braid action",),
    ),
    "real_structure": (
        (
            "portable-Nielsen-replay",
            "tuple-transform-replay",
            "Nielsen-closure",
            "bijection-and-involution",
        ),
        ("the advertised serializable transform is exactly the certified Nielsen involution",),
    ),
    "real_census": (
        (
            "portable-Nielsen-replay",
            "branch-cycle-equations",
            "deterministic-witness-search",
            "representative-exhaustion",
        ),
        ("the listed representatives are exactly those satisfying the stated real-witness policy",),
    ),
    "reduced": (
        (
            "portable-Nielsen-replay",
            "component-replay",
            "explicit-permutation-validation",
            "finite-orbit-exhaustion",
        ),
        ("the blocks are exactly the orbits of the supplied explicit vertex permutations",),
    ),
    "cusps": (
        (
            "portable-Nielsen-replay",
            "component-replay",
            "operator-word-replay",
            "cycle-exhaustion-and-widths",
        ),
        ("the listed cycles exhaust the component for the supplied braid word",),
    ),
    "boundary": (
        (
            "portable-Nielsen-replay",
            "component-replay",
            "adjacent-collision-product",
            "stratum-and-incidence-exhaustion",
        ),
        ("every component vertex has exactly one certified image for each supplied collision",),
    ),
}


@dataclass(frozen=True)
class _NielsenAssertion:
    text: str
    parameters: Mapping[str, object]

    @property
    def statement(self) -> FormalStatement:
        return FormalStatement.create(self.text, parameters=self.parameters)


@dataclass(frozen=True)
class _PortableSource:
    certificate: NielsenEnumerationCertificate | HurwitzOperationCertificate
    assertion: _NielsenAssertion
    verifier: str
    checks: tuple[str, ...]
    guarantees: tuple[str, ...]
    schema: str


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SemanticVerificationError(f"portable Nielsen {field} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise SemanticVerificationError(f"portable Nielsen {field} must contain strings")
    return cast(tuple[str, ...], result)


def _nielsen_assertion(payload: Mapping[str, object]) -> _NielsenAssertion:
    """Derive the only proposition justified by a portable Nielsen payload."""

    group_fingerprint = payload.get("group_fingerprint")
    if not isinstance(group_fingerprint, str) or not group_fingerprint:
        raise SemanticVerificationError("portable Nielsen group fingerprint is missing")
    class_fingerprints = _string_tuple(
        payload.get("class_fingerprints"), field="class fingerprints"
    )
    representatives = payload.get("representative_keys")
    if isinstance(representatives, (str, bytes)) or not isinstance(representatives, Sequence):
        raise SemanticVerificationError("portable Nielsen representatives must be a sequence")
    cardinality = len(representatives)
    return _NielsenAssertion(
        (
            "The complete inner Nielsen class for the pinned concrete group and "
            f"ordered class vector has cardinality {cardinality}."
        ),
        {
            "group_fingerprint": group_fingerprint,
            "class_fingerprints": class_fingerprints,
            "cardinality": cardinality,
        },
    )


def _canonical_claim_id(certificate_id: str, *, verifier: str = _VERIFIER) -> str:
    """Derive a collision-resistant semantic identity from the exact receipt."""

    algorithm, separator, digest = certificate_id.partition(":")
    if algorithm != "sha256" or separator != ":" or len(digest) != 64:
        raise SemanticVerificationError("Nielsen receipt has a noncanonical content address")
    return f"{verifier}.{digest}"


def _operation_assertion(certificate: HurwitzOperationCertificate) -> _NielsenAssertion:
    """Derive exactly one public proposition from independently replayed data."""

    certificate.verify()
    nielsen = certificate.nielsen_certificate
    group_fingerprint = _string_value(
        nielsen.get("group_fingerprint"), field="operation group fingerprint"
    )
    class_fingerprints = _string_tuple(
        nielsen.get("class_fingerprints"), field="operation class fingerprints"
    )
    representatives = nielsen.get("representative_keys")
    if isinstance(representatives, (str, bytes)) or not isinstance(representatives, Sequence):
        raise SemanticVerificationError("operation Nielsen representatives must be a sequence")
    inputs = certificate.inputs
    result = certificate.result
    common: dict[str, object] = {
        "operation_certificate_id": certificate.certificate_id,
        "group_fingerprint": group_fingerprint,
        "class_fingerprints": class_fingerprints,
        "nielsen_cardinality": len(representatives),
    }
    operation = certificate.operation
    if operation == "braid_action":
        generators = cast(Sequence[Mapping[str, object]], result["generators"])
        names = tuple(
            _string_value(item.get("name"), field="braid generator name") for item in generators
        )
        common.update({"generator_names": names, "generator_count": len(names)})
        text = (
            f"The {len(names)} supplied named braid words induce the certified exact "
            f"permutations of all {len(representatives)} inner Nielsen vertices."
        )
    elif operation == "components":
        components = tuple(
            tuple(cast(Sequence[int], block))
            for block in cast(Sequence[object], result["components"])
        )
        selected = inputs.get("selected_component")
        common.update(
            {
                "component_count": len(components),
                "component_cardinalities": tuple(len(block) for block in components),
            }
        )
        if selected is None:
            text = (
                f"The supplied named braid action has exactly {len(components)} components "
                f"with cardinalities {tuple(len(block) for block in components)}."
            )
        else:
            selected_tuple = tuple(cast(Sequence[int], selected))
            common["selected_component"] = selected_tuple
            text = (
                f"The selected {len(selected_tuple)}-vertex block is one exact component of "
                "the supplied named braid action; its full partition has "
                f"{len(components)} components."
            )
    elif operation == "real_structure":
        fixed = tuple(cast(Sequence[int], result["fixed_indices"]))
        name = _string_value(inputs.get("name"), field="real-structure name")
        common.update({"name": name, "fixed_indices": fixed, "fixed_count": len(fixed)})
        text = (
            f"The serializable real transform {name!r} is an exact involution of the complete "
            f"inner Nielsen class and fixes exactly {len(fixed)} vertices."
        )
    elif operation == "real_census":
        count = cast(int, result["count"])
        fiber_mode = _string_value(inputs.get("fiber_mode"), field="real-census fiber mode")
        fiber_index = inputs.get("fiber_index")
        up_to_inner = cast(bool, inputs["up_to_inner"])
        common.update(
            {
                "fiber_mode": fiber_mode,
                "fiber_index": fiber_index,
                "up_to_inner": up_to_inner,
                "count": count,
            }
        )
        policy = (
            "all involutions"
            if fiber_mode == "all_involutions"
            else f"the fixed involution at group index {fiber_index}"
        )
        text = (
            f"Exactly {count} inner Nielsen representatives satisfy the straight-bouquet "
            f"real branch-cycle equations under the exhaustive policy using {policy} "
            f"(up_to_inner={up_to_inner})."
        )
    elif operation == "reduced":
        blocks = cast(Sequence[object], result["blocks"])
        symmetries = cast(Sequence[Mapping[str, object]], inputs["symmetries"])
        names = tuple(_string_value(item.get("name"), field="symmetry name") for item in symmetries)
        common.update({"symmetry_names": names, "orbit_count": len(blocks)})
        text = (
            f"The supplied explicit vertex permutations {names} have exactly {len(blocks)} "
            "orbits on the selected braid component."
        )
    elif operation == "cusps":
        widths = tuple(cast(Sequence[int], result["widths"]))
        name = _string_value(inputs.get("operator_name"), field="cusp operator name")
        common.update({"operator_name": name, "widths": widths, "cusp_count": len(widths)})
        text = (
            f"The supplied braid word {name!r} has exactly {len(widths)} cycles on the "
            f"selected component, with widths {widths}."
        )
    elif operation == "boundary":
        collisions = cast(Sequence[object], inputs["collisions"])
        strata = cast(Sequence[object], result["strata"])
        total = cast(int, result["total_incidences"])
        common.update(
            {
                "collision_count": len(collisions),
                "stratum_count": len(strata),
                "total_incidences": total,
            }
        )
        text = (
            f"The {len(collisions)} supplied adjacent collisions give exactly {len(strata)} "
            f"inner-canonical boundary strata and {total} total incidences on the selected "
            "component."
        )
    else:  # pragma: no cover - constructor and replay already reject this.
        raise SemanticVerificationError(f"unsupported portable operation {operation!r}")
    return _NielsenAssertion(text, common)


def _string_value(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticVerificationError(f"{field} must be a nonempty string")
    return value


def _verify_portable_nielsen(certificate: VerificationCertificate) -> bool:
    """Replay the finite table and bind it to exactly one derived proposition."""

    if certificate.verifier != _VERIFIER:
        raise SemanticVerificationError("Nielsen certificate names a different verifier")
    raw = certificate.witness.get("hurwitz_certificate")
    if not isinstance(raw, Mapping):
        raise SemanticVerificationError("Hurwitz witness lacks a certificate mapping")
    transported = dict(raw)
    raw_id = transported.pop("certificate_id", None)
    if not isinstance(raw_id, str):
        raise SemanticVerificationError("Hurwitz witness lacks a specialized content ID")
    try:
        validate_content_address(raw_id, transported)
    except ValueError as exc:
        raise SemanticVerificationError("Hurwitz specialized content address mismatch") from exc

    verify_nielsen_certificate_payload(transported)
    assertion = _nielsen_assertion(transported)
    if certificate.claim_id != _canonical_claim_id(raw_id):
        raise SemanticVerificationError("Nielsen envelope claim ID is not receipt-derived")
    if certificate.subject != assertion.text:
        raise SemanticVerificationError("Nielsen envelope subject overstates its receipt")
    if certificate.statement_hash != assertion.statement.statement_hash:
        raise SemanticVerificationError(
            "Nielsen envelope statement is not derived from its receipt"
        )
    if certificate.checks != _CHECKS:
        raise SemanticVerificationError("Nielsen envelope check set is not canonical")
    if certificate.guarantees != _GUARANTEES:
        raise SemanticVerificationError("Nielsen envelope guarantee set is not canonical")
    return True


def _verify_portable_operation(certificate: VerificationCertificate) -> bool:
    """Replay a transported operation and bind its only canonical assertion."""

    raw = certificate.witness.get("hurwitz_certificate")
    if not isinstance(raw, Mapping):
        raise SemanticVerificationError("Hurwitz witness lacks a certificate mapping")
    specialized = HurwitzOperationCertificate.from_dict(cast(Mapping[str, object], raw))
    specialized.verify()
    expected_verifier = f"hurwitz.{specialized.operation}"
    if certificate.verifier != expected_verifier:
        raise SemanticVerificationError("Hurwitz operation certificate names a different verifier")
    assertion = _operation_assertion(specialized)
    checks, guarantees = _OPERATION_CONTRACTS[specialized.operation]
    if certificate.claim_id != _canonical_claim_id(
        specialized.certificate_id, verifier=expected_verifier
    ):
        raise SemanticVerificationError("Hurwitz operation claim ID is not receipt-derived")
    if certificate.subject != assertion.text:
        raise SemanticVerificationError("Hurwitz operation subject overstates its receipt")
    if certificate.statement_hash != assertion.statement.statement_hash:
        raise SemanticVerificationError("Hurwitz operation statement is not receipt-derived")
    if certificate.checks != checks:
        raise SemanticVerificationError("Hurwitz operation check set is not canonical")
    if certificate.guarantees != guarantees:
        raise SemanticVerificationError("Hurwitz operation guarantee set is not canonical")
    return True


def register_hurwitz_replay(
    certificate: NielsenEnumerationCertificate | HurwitzOperationCertificate | None = None,
) -> None:
    """Register stateless portable verifiers, optionally preflight one receipt.

    Registration stores no group object or closure. Supplying a receipt merely
    performs both its concrete replay and its table-only replay before returning.
    """

    default_verifiers.register(_VERIFIER, VerificationCertificate, _verify_portable_nielsen)
    for operation in PORTABLE_OPERATIONS:
        default_verifiers.register(
            f"hurwitz.{operation}", VerificationCertificate, _verify_portable_operation
        )
    if certificate is not None:
        certificate.verify()
        if isinstance(certificate, NielsenEnumerationCertificate):
            verify_nielsen_certificate_payload(certificate.to_canonical())


def _source_for(value: object) -> _PortableSource:
    if isinstance(value, NielsenEnumerationCertificate):
        value.verify()
        payload = value.to_canonical()
        verify_nielsen_certificate_payload(payload)
        return _PortableSource(
            value,
            _nielsen_assertion(payload),
            _VERIFIER,
            _CHECKS,
            _GUARANTEES,
            value.schema,
        )
    if isinstance(value, NielsenClass):
        certificate = value.certificate
        if certificate is None:
            raise SemanticVerificationError(
                "an imported Nielsen list cannot become a computed completeness claim"
            )
        value.verify()
        payload = certificate.to_canonical()
        verify_nielsen_certificate_payload(payload)
        return _PortableSource(
            certificate,
            _nielsen_assertion(payload),
            _VERIFIER,
            _CHECKS,
            _GUARANTEES,
            certificate.schema,
        )
    specialized = (
        value
        if isinstance(value, HurwitzOperationCertificate)
        else operation_certificate_for(value)
    )
    specialized.verify()
    assertion = _operation_assertion(specialized)
    checks, guarantees = _OPERATION_CONTRACTS[specialized.operation]
    return _PortableSource(
        specialized,
        assertion,
        f"hurwitz.{specialized.operation}",
        checks,
        guarantees,
        specialized.schema_version,
    )


def verification_certificate_for(
    value: object,
    *,
    claim_id: str | None = None,
) -> VerificationCertificate:
    """Return the public, claim-bound, independently replayable certificate."""

    source = _source_for(value)
    certificate = source.certificate
    assertion = source.assertion
    canonical_identity = _canonical_claim_id(certificate.certificate_id, verifier=source.verifier)
    if claim_id is not None and claim_id != canonical_identity:
        raise SemanticVerificationError(
            f"Hurwitz claim ID must be the receipt-derived identity {canonical_identity!r}"
        )
    identity = canonical_identity
    statement = assertion.statement
    semantic_certificate = VerificationCertificate.create(
        subject=assertion.text,
        verifier=source.verifier,
        claim_id=identity,
        statement_hash=statement.statement_hash,
        witness={"hurwitz_certificate": certificate.to_dict()},
        checks=source.checks,
        guarantees=source.guarantees,
    )
    register_hurwitz_replay()
    default_verifiers.verify(semantic_certificate)
    return semantic_certificate


def claim_for(value: object, *, claim_id: str | None = None) -> Claim:
    """Promote a self-contained Nielsen enumeration to one computed claim."""

    source = _source_for(value)
    certificate = source.certificate
    statement = source.assertion.statement
    semantic_certificate = verification_certificate_for(value, claim_id=claim_id)
    identity = cast(str, semantic_certificate.claim_id)
    claim = Claim(
        identity,
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        derivation=Derivation.computation(
            source.verifier,
            artifact=certificate.certificate_id,
            parameters={"specialized_schema": source.schema},
        ),
        certificate=semantic_certificate,
        metadata={"specialized_certificate_id": certificate.certificate_id},
    )
    claim.verify()
    return claim


def claim_graph_for(value: object, *, claim_id: str | None = None) -> ClaimGraph:
    """Return a one-node, fresh-process-replayable Hurwitz claim graph."""

    graph = ClaimGraph((claim_for(value, claim_id=claim_id),))
    graph.verify()
    return graph


register_hurwitz_replay()


__all__ = [
    "claim_for",
    "claim_graph_for",
    "register_hurwitz_replay",
    "verification_certificate_for",
]
