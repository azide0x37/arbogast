"""Compute exact, framed, and equivariant finite deformation spaces."""

from __future__ import annotations

from arbogast.cert import verify_certificate
from arbogast.deform import (
    DeformationAction,
    DeformationComplex,
    EquivariantDecomposition,
    Framing,
    NonRigid,
    Rigid,
    equivariant,
    equivariant_decomposition,
    frame,
    gauge,
    invariant_deformations,
    obstructions,
    rigid,
    tangent,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import Representation, cyclic_group


def _diagonal(field: PrimeField, entries: tuple[int, ...]) -> DenseMatrix:
    return DenseMatrix(
        field,
        tuple(
            tuple(value if row == column else 0 for column, value in enumerate(entries))
            for row in range(len(entries))
        ),
    )


def main() -> int:
    field = PrimeField(3)
    complex_ = DeformationComplex(
        field,
        DenseMatrix(field, ((1, 0), (0, 0), (0, 0))),
        DenseMatrix(field, ((0, 1, 0), (0, 0, 0))),
        name="one-dimensional-spaces",
    )

    gauge_space = gauge(complex_)
    tangent_space = tangent(complex_)
    obstruction_space = obstructions(complex_)
    assert (gauge_space.dimension, tangent_space.dimension, obstruction_space.dimension) == (
        1,
        1,
        1,
    )
    assert gauge_space.verify()
    assert tangent_space.verify()
    assert obstruction_space.verify()

    framing = Framing(DenseMatrix(field, ((0, 1),)), label="fix-second-gauge-coordinate")
    framed = frame(complex_, framing)
    assert gauge(framed).dimension == 0
    assert tangent(framed).dimension == 1
    assert framed.verify()

    group = cyclic_group(2)
    degree0 = Representation.from_generators(group, field, (_diagonal(field, (1, 2)),))
    degree1 = Representation.from_generators(group, field, (_diagonal(field, (1, 2, 1)),))
    degree2 = Representation.from_generators(group, field, (_diagonal(field, (2, 1)),))
    action = DeformationAction(complex_, degree0, degree1, degree2)
    equivariant_problem = equivariant(complex_, action)
    invariants = invariant_deformations(equivariant_problem)
    assert invariants.identifies_invariant_cohomology is False
    assert tangent(invariants.problem).dimension == 1
    assert invariants.verify()

    plus = (
        _diagonal(field, (1, 0)),
        _diagonal(field, (1, 0, 1)),
        _diagonal(field, (0, 1)),
    )
    minus = (
        _diagonal(field, (0, 1)),
        _diagonal(field, (0, 1, 0)),
        _diagonal(field, (1, 0)),
    )
    decomposition = equivariant_decomposition(
        equivariant_problem,
        {"plus": plus, "minus": minus},
    )
    assert isinstance(decomposition, EquivariantDecomposition)
    assert tuple(component.label for component in decomposition) == ("minus", "plus")
    assert decomposition.verify()

    nonrigid = rigid(complex_)
    assert isinstance(nonrigid, NonRigid)
    assert nonrigid.verify()
    rigid_complex = DeformationComplex(
        field,
        DenseMatrix.identity(field, 1),
        DenseMatrix.zeros(field, 0, 1),
        name="rigid-complex",
    )
    rigid_result = rigid(rigid_complex)
    assert isinstance(rigid_result, Rigid)
    assert rigid_result.verify()

    semantic_results = (
        tangent_space,
        obstruction_space,
        invariants,
        decomposition,
        nonrigid,
        rigid_result,
    )
    claim_count = 0
    for result in semantic_results:
        assert verify_certificate(result.certificate).valid
        graph = result.claim_graph()
        assert graph.verify().verified
        claim_count += len(graph)

    print(f"spaces (gauge, tangent, obstruction): {(1, 1, 1)}")
    print(f"framed gauge dimension: {gauge(framed).dimension}")
    print(f"invariant tangent dimension: {tangent(invariants.problem).dimension}")
    print(f"equivariant components: {[item.label for item in decomposition]}")
    print(f"non-rigidity witness: {nonrigid.witness}")
    print(f"rigid tangent dimension: {rigid_result.tangent_space.dimension}")
    print(f"verified claim nodes: {claim_count}")
    print(f"tangent certificate: {tangent_space.certificate.certificate_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
