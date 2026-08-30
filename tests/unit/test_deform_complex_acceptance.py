from __future__ import annotations

import pytest

from arbogast.deform.complex import DeformationComplex
from arbogast.deform.errors import DeformationError
from arbogast.deform.framing import Framing, frame
from arbogast.deform.problem import (
    DeformationProblem,
    NonRigid,
    ObstructionClass,
    gauge,
    obstructions,
    rigid,
    tangent,
)
from arbogast.linalg import DenseMatrix, PrimeField


def _three_term_complex() -> DeformationComplex:
    """Return a complex whose H0, H1, and H2 all have dimension one."""

    field = PrimeField(3)
    return DeformationComplex(
        field,
        DenseMatrix(
            field,
            (
                (1, 0),
                (0, 0),
                (0, 0),
            ),
        ),
        DenseMatrix(
            field,
            (
                (0, 1, 0),
                (0, 0, 0),
            ),
        ),
        name="one-dimensional-cohomology",
    )


def test_three_term_complex_has_pinned_dimensions_and_replays() -> None:
    complex_ = _three_term_complex()

    assert complex_.dimensions == (2, 3, 2)
    assert complex_.degree0_dimension == 2
    assert complex_.degree1_dimension == 3
    assert complex_.degree2_dimension == 2
    assert complex_.d1 @ complex_.d0 == DenseMatrix.zeros(PrimeField(3), 2, 2)
    assert complex_.verify()
    assert complex_.differential(0) == complex_.d0
    assert complex_.differential(1) == complex_.d1
    with pytest.raises(DeformationError, match="differentials only"):
        complex_.differential(2)


def test_three_term_cohomology_has_exact_t0_t1_t2_dimensions() -> None:
    complex_ = _three_term_complex()

    gauge_space = gauge(complex_)
    tangent_space = tangent(complex_)
    obstruction_space = obstructions(complex_)

    assert gauge_space.dimension == 1
    assert tangent_space.dimension == 1
    assert obstruction_space.dimension == 1
    assert gauge_space.basis == ((0, 1),)
    assert all(complex_.d0.matvec(vector) == (0, 0, 0) for vector in gauge_space.basis)
    assert all(complex_.d1.matvec(vector) == (0, 0) for vector in tangent_space.basis)
    assert gauge_space.verify()
    assert tangent_space.verify()
    assert obstruction_space.verify()

    nonzero = obstruction_space.class_of((0, 1))
    zero = obstruction_space.class_of((1, 0))
    assert isinstance(nonzero, ObstructionClass)
    assert nonzero.class_coordinates == (1,)
    assert not nonzero.is_zero
    assert zero.is_zero
    assert nonzero.verify()
    assert zero.verify()


def test_rigidity_is_witnessed_and_never_inferred_from_obstructions() -> None:
    result = rigid(_three_term_complex())

    assert isinstance(result, NonRigid)
    assert not result.is_rigid
    assert tangent(result.problem).class_coordinates(result.witness) != (0,)
    assert result.verify()

    field = PrimeField(3)
    rigid_complex = DeformationComplex(
        field,
        DenseMatrix.identity(field, 1),
        DenseMatrix.zeros(field, 1, 1),
    )
    rigid_result = rigid(rigid_complex)
    assert rigid_result.is_rigid
    assert tangent(rigid_result.problem).dimension == 0
    # A nonzero obstruction space does not undermine the correctly scoped
    # assertion: rigidity here means zero first-order tangent freedom only.
    assert obstructions(rigid_result.problem).dimension == 1
    assert rigid_result.verify()


def test_full_framing_kills_gauge_and_changes_the_tangent_quotient() -> None:
    complex_ = _three_term_complex()
    framing = Framing(DenseMatrix.identity(complex_.field, 2), "pin-degree-zero")
    framed = frame(complex_, framing)

    assert isinstance(framed, DeformationProblem)
    assert framing.allowed_dimension == 0
    assert framing.verify()
    assert framed.framing == framing
    assert framed.complex.degree0_dimension == 0
    assert gauge(framed).dimension == 0
    # Framing removes im(d0) from the gauge quotient, so this example gains
    # the formerly gauge-equivalent tangent direction.
    assert tangent(complex_).dimension == 1
    assert tangent(framed).dimension == 2
    assert obstructions(framed).dimension == obstructions(complex_).dimension == 1
    assert framed.verify()


def test_framing_rejects_foreign_fields_and_wrong_degree_zero_dimension() -> None:
    complex_ = _three_term_complex()

    with pytest.raises(DeformationError, match="different fields"):
        frame(complex_, Framing(DenseMatrix.identity(PrimeField(2), 2)))
    with pytest.raises(DeformationError, match="wrong degree-zero dimension"):
        frame(complex_, Framing(DenseMatrix.identity(complex_.field, 3)))


def test_deformation_complex_rejects_nonzero_composite() -> None:
    field = PrimeField(3)

    with pytest.raises(DeformationError, match=r"d1\*d0 = 0"):
        DeformationComplex(
            field,
            DenseMatrix(field, ((1,), (0,))),
            DenseMatrix(field, ((1, 0),)),
        )


def test_deformation_complex_rejects_dimension_and_field_mismatches() -> None:
    field = PrimeField(3)

    with pytest.raises(DeformationError, match="dimensions differ"):
        DeformationComplex(
            field,
            DenseMatrix(field, ((1,), (0,))),
            DenseMatrix(field, ((0, 0, 0),)),
        )
    with pytest.raises(DeformationError, match="different coefficient field"):
        DeformationComplex(
            field,
            DenseMatrix(PrimeField(2), ((1,),)),
            DenseMatrix(field, ((0,),)),
        )


@pytest.mark.parametrize("name", ("", "   "))
def test_deformation_complex_rejects_blank_names(name: str) -> None:
    field = PrimeField(3)
    with pytest.raises(DeformationError, match="complex name"):
        DeformationComplex(
            field,
            DenseMatrix.zeros(field, 1, 1),
            DenseMatrix.zeros(field, 1, 1),
            name=name,
        )
