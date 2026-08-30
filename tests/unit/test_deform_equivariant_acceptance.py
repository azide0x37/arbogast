from __future__ import annotations

import pytest

from arbogast.deform.complex import DeformationComplex
from arbogast.deform.equivariant import (
    DeformationAction,
    EquivariantDecomposition,
    EquivariantDeformation,
    equivariant,
    equivariant_decomposition,
    invariant_deformations,
)
from arbogast.deform.errors import DeformationVerificationError, UnsupportedDeformation
from arbogast.deform.problem import gauge, obstructions, tangent
from arbogast.deform.semantic import receipt_for_result
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup, Representation


def _c2_representation(field: PrimeField, generator: DenseMatrix) -> Representation:
    group = CyclicGroup(2)
    return Representation.from_generators(
        group,
        field,
        {group.generator: generator},
    )


def _semisimple_equivariant() -> EquivariantDeformation:
    field = PrimeField(3)
    group = CyclicGroup(2)
    generator = DenseMatrix(field, ((1, 0), (0, 2)))
    representations = tuple(
        Representation.from_generators(group, field, {group.generator: generator}) for _ in range(3)
    )
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 2, 2),
        DenseMatrix.zeros(field, 2, 2),
        name="C2 semisimple deformation",
    )
    action = DeformationAction(complex_, *representations)
    return equivariant(complex_, action)


def test_c2_over_f3_invariant_subcomplex_has_exact_dimensions() -> None:
    source = _semisimple_equivariant()

    invariant = invariant_deformations(source)

    assert invariant.verify()
    assert invariant.complex.dimensions == (1, 1, 1)
    assert gauge(invariant).dimension == 1
    assert tangent(invariant).dimension == 1
    assert obstructions(invariant).dimension == 1
    assert gauge(invariant).problem is invariant.problem
    assert invariant.identifies_invariant_cohomology is False


def test_supplied_semisimple_projectors_give_a_complete_chain_decomposition() -> None:
    source = _semisimple_equivariant()
    field = source.complex.field
    plus = DenseMatrix(field, ((1, 0), (0, 0)))
    minus = DenseMatrix(field, ((0, 0), (0, 1)))

    result = equivariant_decomposition(
        source,
        {
            "trivial": (plus, plus, plus),
            "sign": (minus, minus, minus),
        },
    )

    assert isinstance(result, EquivariantDecomposition)
    assert result.verify()
    assert result.complete
    assert tuple(component.label for component in result) == ("sign", "trivial")
    assert all(component.complex.dimensions == (1, 1, 1) for component in result)

    reordered = EquivariantDecomposition(source, tuple(reversed(result.components)))
    assert reordered.components == result.components
    assert reordered.content_id == result.content_id
    assert receipt_for_result(reordered).verify()

    object.__setattr__(reordered, "components", tuple(reversed(reordered.components)))
    with pytest.raises(DeformationVerificationError, match="canonical and unique"):
        reordered.verify()


def test_incomplete_or_nonorthogonal_projectors_are_rejected() -> None:
    source = _semisimple_equivariant()
    field = source.complex.field
    plus = DenseMatrix(field, ((1, 0), (0, 0)))
    identity = DenseMatrix.identity(field, 2)
    zero = DenseMatrix.zeros(field, 2, 2)

    with pytest.raises(DeformationVerificationError, match="not complete"):
        equivariant_decomposition(source, {"only": (plus, plus, plus)})
    with pytest.raises(DeformationVerificationError, match="not pairwise orthogonal"):
        equivariant_decomposition(
            source,
            {"all": (identity, identity, identity), "plus": (plus, plus, plus)},
        )
    with pytest.raises(DeformationVerificationError, match="all-zero component"):
        equivariant_decomposition(
            source,
            {"all": (identity, identity, identity), "zero": (zero, zero, zero)},
        )


def test_modular_c2_boundary_is_explicit_and_does_not_identify_cohomology() -> None:
    field = PrimeField(2)
    group = CyclicGroup(2)
    swap = DenseMatrix(field, ((0, 1), (1, 0)))
    representations = tuple(
        Representation.from_generators(group, field, {group.generator: swap}) for _ in range(3)
    )
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 2, 2),
        DenseMatrix.zeros(field, 2, 2),
        name="modular C2 deformation",
    )
    source = equivariant(complex_, DeformationAction(complex_, *representations))

    invariant = invariant_deformations(source)
    automatic = equivariant_decomposition(source)

    assert invariant.complex.dimensions == (1, 1, 1)
    assert invariant.identifies_invariant_cohomology is False
    assert isinstance(automatic, UnsupportedDeformation)
    assert automatic.verify()
    assert "automatic" in automatic.reason
    assert automatic.operation == "equivariant_decomposition"


def test_non_equivariant_differential_is_rejected() -> None:
    field = PrimeField(3)
    group = CyclicGroup(2)
    plus_minus = DenseMatrix(field, ((1, 0), (0, 2)))
    minus_plus = DenseMatrix(field, ((2, 0), (0, 1)))
    degree0 = Representation.from_generators(group, field, {group.generator: plus_minus})
    degree1 = Representation.from_generators(group, field, {group.generator: minus_plus})
    degree2 = Representation.from_generators(group, field, {group.generator: minus_plus})
    complex_ = DeformationComplex(
        field,
        DenseMatrix.identity(field, 2),
        DenseMatrix.zeros(field, 2, 2),
    )

    with pytest.raises(DeformationVerificationError, match="d0 is not equivariant"):
        DeformationAction(complex_, degree0, degree1, degree2)


def test_action_tampering_fails_exact_replay() -> None:
    source = _semisimple_equivariant()
    object.__setattr__(source.action, "identity_index", 1)

    with pytest.raises(DeformationVerificationError, match="identity index"):
        source.verify()
