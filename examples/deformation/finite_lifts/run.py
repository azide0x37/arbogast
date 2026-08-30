"""Exercise solved, obstructed, unique, non-unique, and fixed finite lifts."""

from __future__ import annotations

from arbogast.cert import verify_certificate
from arbogast.deform import (
    ArtinRing,
    ArtinRingMap,
    ContractionCertificate,
    DeformationComplex,
    FixedLift,
    LiftDatum,
    LiftEndomorphism,
    LiftFamily,
    LiftObstructed,
    NonUniqueLift,
    SmallExtension,
    UniqueLift,
    fixed_lift,
    lift,
    unique_lift,
)
from arbogast.linalg import DenseMatrix, PrimeField


def _dual_number_extension(field: PrimeField) -> SmallExtension:
    residue_field = ArtinRing(
        field,
        (((1,),),),
        (1,),
        (1,),
        basis_names=("1",),
    )
    dual_numbers = ArtinRing(
        field,
        (
            ((1, 0), (0, 1)),
            ((0, 1), (0, 0)),
        ),
        (1, 0),
        (1, 0),
        basis_names=("1", "epsilon"),
    )
    projection = ArtinRingMap(dual_numbers, residue_field, ((1, 0),))
    extension = SmallExtension(projection, ((0, 1),))
    assert extension.verify()
    return extension


def main() -> int:
    field = PrimeField(3)
    extension = _dual_number_extension(field)
    problem = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 2, 0),
        DenseMatrix(field, ((1, 0), (0, 0))),
        name="two-variable-lift-equation",
    )

    solved_datum = LiftDatum(problem, extension, (1, 0), label="affine-family")
    solved = lift(solved_datum)
    assert isinstance(solved, LiftFamily)
    assert solved.representative == (1, 0)
    assert solved.dimension == 1
    assert solved.mod_gauge_dimension == 1
    assert solved.verify()

    nonunique = unique_lift(solved)
    assert isinstance(nonunique, NonUniqueLift)
    assert nonunique.first != nonunique.second
    assert nonunique.verify()

    obstructed_datum = LiftDatum(problem, extension, (0, 1), label="literal-obstruction")
    obstructed = lift(obstructed_datum)
    assert isinstance(obstructed, LiftObstructed)
    assert obstructed.obstruction_class is not None
    assert not obstructed.obstruction_class.is_zero
    assert obstructed.verify()

    unique_datum = LiftDatum(
        problem,
        extension,
        (1, 2),
        correction_matrix=DenseMatrix.identity(field, 2),
        label="unique-lift",
    )
    unique_family = lift(unique_datum)
    assert isinstance(unique_family, LiftFamily)
    unique = unique_lift(unique_family)
    assert isinstance(unique, UniqueLift)
    assert unique.representative == (1, 2)
    assert unique.verify()

    endomorphism = LiftEndomorphism(
        solved,
        DenseMatrix.zeros(field, 2, 2),
        (1, 2),
    )
    contraction = ContractionCertificate(endomorphism, 1)
    fixed = fixed_lift(solved, endomorphism, contraction=contraction)
    assert isinstance(fixed, FixedLift)
    assert fixed.representative == (1, 2)
    assert endomorphism.apply(fixed.representative) == fixed.representative
    assert fixed.verify()

    # Replay one negative and one positive endpoint through the central proof
    # envelope.  The fixed-lift graph recursively closes over its solved
    # family, endomorphism, contraction, problem, and small extension.
    semantic_results = (obstructed, fixed)
    claim_count = 0
    fixed_certificate = fixed.certificate
    for result in semantic_results:
        certificate = fixed_certificate if result is fixed else result.certificate
        assert verify_certificate(certificate).valid
        graph = result.claim_graph()
        assert graph.verify().verified
        claim_count += len(graph)

    print(f"small-extension kernel dimension: {extension.kernel_dimension}")
    print(f"lift family dimension modulo gauge: {solved.mod_gauge_dimension}")
    print(f"obstruction separator: {obstructed.separating_witness}")
    print(f"unique lift: {unique.representative}")
    print(f"non-unique lifts: {nonunique.first}, {nonunique.second}")
    print(f"fixed lift: {fixed.representative}")
    print(f"verified claim nodes: {claim_count}")
    print(f"fixed-lift certificate: {fixed_certificate.certificate_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
