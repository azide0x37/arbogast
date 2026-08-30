from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import Claim, ClaimGraph, EpistemicStatus
from arbogast.deform import (
    ArtinRing,
    ArtinRingMap,
    ContractionCertificate,
    DeformationAction,
    DeformationComplex,
    DeformationReceipt,
    EquivariantDecomposition,
    FixedLift,
    Framing,
    LiftDatum,
    LiftEndomorphism,
    LiftFamily,
    LiftObstructed,
    LiftUnknown,
    NonRigid,
    NonUniqueLift,
    Rigid,
    SmallExtension,
    UniqueLift,
    UnsupportedDeformation,
    deformation_problem,
    equivariant,
    equivariant_decomposition,
    fixed_lift,
    gauge,
    invariant_deformations,
    lift,
    obstructions,
    rigid,
    tangent,
    unique_lift,
)
from arbogast.deform.certificate import RECEIPT_SCHEMAS
from arbogast.deform.semantic import claim_for_receipt, receipt_for_result
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import Representation, cyclic_group

F3 = PrimeField(3)


class _ProofBearing(Protocol):
    @property
    def certificate(self) -> VerificationCertificate: ...

    def verify(self) -> bool: ...

    def claim(self) -> Claim: ...

    def claim_graph(self) -> ClaimGraph: ...


def _truncated_ring(exponent: int) -> ArtinRing:
    constants = []
    for left in range(exponent):
        rows = []
        for right in range(exponent):
            vector = [0] * exponent
            if left + right < exponent:
                vector[left + right] = 1
            rows.append(tuple(vector))
        constants.append(tuple(rows))
    return ArtinRing(
        F3,
        tuple(constants),
        (1,) + (0,) * (exponent - 1),
        (1,) + (0,) * (exponent - 1),
    )


@dataclass(frozen=True)
class _SemanticFixtures:
    results: tuple[_ProofBearing, ...]
    unknowns: tuple[_ProofBearing, ...]


def _semantic_fixtures() -> _SemanticFixtures:
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 1),
        DenseMatrix.zeros(F3, 1, 1),
        name="semantic-fixture",
    )
    problem = deformation_problem(complex_)
    gauge_space = gauge(problem)
    tangent_space = tangent(problem)
    obstruction_space = obstructions(problem)
    obstruction_class = obstruction_space.class_of((1,))
    framing = Framing(DenseMatrix.identity(F3, 1), "kill-gauge")

    group = cyclic_group(2)
    representation = Representation.from_generators(
        group,
        F3,
        {group.generator: DenseMatrix.identity(F3, 1)},
    )
    action = DeformationAction(
        complex_,
        representation,
        representation,
        representation,
    )
    equivariant_problem = equivariant(problem, action)
    invariants = invariant_deformations(equivariant_problem)
    identity = DenseMatrix.identity(F3, 1)
    decomposition = equivariant_decomposition(
        equivariant_problem,
        {"trivial": (identity, identity, identity)},
    )
    assert isinstance(decomposition, EquivariantDecomposition)
    unsupported = equivariant_decomposition(equivariant_problem)
    assert isinstance(unsupported, UnsupportedDeformation)

    residue = _truncated_ring(1)
    dual = _truncated_ring(2)
    projection = ArtinRingMap(dual, residue, ((1, 0),))
    extension = SmallExtension(projection, ((0, 1),))

    datum = LiftDatum(problem, extension, (0,))
    family = lift(datum)
    assert isinstance(family, LiftFamily)
    nonunique = unique_lift(family)
    assert isinstance(nonunique, NonUniqueLift)
    obstructed = lift(LiftDatum(problem, extension, (1,)))
    assert isinstance(obstructed, LiftObstructed)
    unique_family = lift(
        LiftDatum(
            problem,
            extension,
            (1,),
            correction_matrix=DenseMatrix.identity(F3, 1),
        )
    )
    assert isinstance(unique_family, LiftFamily)
    unique = unique_lift(unique_family)
    assert isinstance(unique, UniqueLift)
    endomorphism = LiftEndomorphism(
        family,
        DenseMatrix.zeros(F3, 1, 1),
        (0,),
    )
    contraction = ContractionCertificate(endomorphism, 1)
    fixed = fixed_lift(family, endomorphism, contraction=contraction)
    assert isinstance(fixed, FixedLift)
    unknown = fixed_lift(family)
    assert isinstance(unknown, LiftUnknown)

    nonrigid = rigid(problem)
    assert isinstance(nonrigid, NonRigid)
    rigid_result = rigid(
        DeformationComplex(
            F3,
            DenseMatrix.identity(F3, 1),
            DenseMatrix.zeros(F3, 0, 1),
            name="rigid-fixture",
        )
    )
    assert isinstance(rigid_result, Rigid)

    results = (
        dual,
        projection,
        extension,
        complex_,
        problem,
        gauge_space,
        tangent_space,
        obstruction_space,
        obstruction_class,
        framing,
        action,
        equivariant_problem,
        invariants,
        decomposition,
        datum,
        family,
        obstructed,
        unknown,
        unique,
        nonunique,
        endomorphism,
        contraction,
        fixed,
        rigid_result,
        nonrigid,
        unsupported,
    )
    return _SemanticFixtures(results, (unknown, unsupported))


def test_every_substantial_result_exposes_one_replayable_central_proof_boundary() -> None:
    fixtures = _semantic_fixtures()
    receipt_kinds: set[str] = set()

    for result in fixtures.results:
        assert result.verify()
        receipt = receipt_for_result(result)
        assert receipt.verify()
        receipt_kinds.add(receipt.kind)
        assert hasattr(type(result), "certificate")
        assert callable(result.claim)
        assert callable(result.claim_graph)

    assert receipt_kinds == set(RECEIPT_SCHEMAS)

    # Exercise the generic central adapter itself once; the two packaged
    # journeys below exercise dependency-deep invariant and lift-family graphs.
    result = next(item for item in fixtures.results if isinstance(item, DeformationComplex))
    certificate = result.certificate
    assert isinstance(certificate, VerificationCertificate)
    assert certificate.verifier == "deform.finite-exact.v1"
    assert verify_certificate(certificate).valid
    claim = result.claim()
    assert certificate.certificate_id in {item.ref for item in claim.evidence}
    assert claim.verify().verified
    graph = result.claim_graph()
    assert graph.claims == (claim,)
    assert graph.verify().verified


def test_unknown_and_unsupported_results_remain_candidate_non_conclusions() -> None:
    fixtures = _semantic_fixtures()

    for result in fixtures.unknowns:
        receipt = receipt_for_result(result)
        claim = result.claim()

        assert receipt.completeness == "candidate"
        assert claim.status is EpistemicStatus.UNKNOWN
        assert claim.verify().verified


def test_unknown_status_dominates_unresolved_assumptions() -> None:
    unsupported = _semantic_fixtures().unknowns[1]
    receipt = receipt_for_result(unsupported)
    conditional_unknown = DeformationReceipt.create(
        receipt.kind,
        receipt.payload.to_dict(),
        dependencies=receipt.dependencies,
        assumptions=("imported hypothesis",),
        completeness="candidate",
    )

    assert conditional_unknown.verify()
    claim = claim_for_receipt(conditional_unknown)
    assert claim.status is EpistemicStatus.UNKNOWN
    assert tuple(item.text for item in claim.hypotheses) == ("imported hypothesis",)
    assert claim.verify().verified
