from __future__ import annotations

import pytest

from arbogast.linalg import DenseMatrix, LinearSubspace, PrimeField
from arbogast.rep import (
    Character,
    ConcreteEmbeddingError,
    CyclicGroup,
    InvalidActionError,
    NonSplitRepresentationError,
    Permutation,
    PermutationGroup,
    Representation,
    symmetric_group,
)


def test_permutation_representation_validates_and_computes_fixed_spaces() -> None:
    field = PrimeField(5)
    group = symmetric_group(3)
    transposition = Permutation.from_cycles(3, ((0, 1),))
    representation = Representation.permutation(group, field)

    assert representation.validation is not None
    assert representation.validation.multiplication_checks == 36
    assert representation.validation.verify(representation)
    assert isinstance(representation.invariant_space(), LinearSubspace)
    assert representation.invariant_space().basis == ((1, 1, 1),)
    assert representation.fixed_space(transposition).dimension == 2
    assert representation.apply(transposition, (1, 2, 3)) == (2, 1, 3)


def test_invalid_action_is_rejected_exhaustively() -> None:
    field = PrimeField(5)
    group = CyclicGroup(3)
    generator = group.generator
    wrong_order = DenseMatrix(field, ((2, 0), (0, 1)))
    with pytest.raises(InvalidActionError, match="action multiplication failed"):
        Representation.from_generators(group, field, {generator: wrong_order})


def test_cyclic_split_weight_decomposition_and_projectors() -> None:
    field = PrimeField(7)
    group = CyclicGroup(3)
    generator_action = DenseMatrix(field, ((1, 0, 0), (0, 2, 0), (0, 0, 4)))
    representation = Representation.from_generators(
        group,
        field,
        {group.generator: generator_action},
    )

    decomposition = representation.cyclic_decomposition()
    assert decomposition.verify()
    assert decomposition.is_split
    weights = representation.weight_spaces()
    assert set(weights.weights) == {1, 2, 4}
    assert all(weights[weight].dimension == 1 for weight in weights)
    assert all(
        weights.projector(weight) @ weights.projector(weight) == weights.projector(weight)
        for weight in weights
    )
    assert representation.isotypic(2).basis == ((0, 1, 0),)


def test_cyclic_nonsplit_component_is_retained_without_fake_eigenvalues() -> None:
    field = PrimeField(5)
    group = CyclicGroup(3)
    # Companion block for x^2 + x + 1 together with a trivial line.
    generator_action = DenseMatrix(field, ((1, 0, 0), (0, 0, 4), (0, 1, 4)))
    representation = Representation.from_generators(
        group,
        field,
        {group.generator: generator_action},
    )

    decomposition = representation.cyclic_decomposition()
    assert decomposition.verify()
    assert sorted(component.dimension for component in decomposition) == [1, 2]
    assert not decomposition.is_split
    with pytest.raises(NonSplitRepresentationError):
        representation.weight_spaces()


def test_character_projectors_give_s3_isotypic_parts() -> None:
    field = PrimeField(5)
    group = symmetric_group(3)
    representation = Representation.permutation(group, field)
    trivial = Character(group, field, {element: 1 for element in group.elements}, name="trivial")
    standard = Character(
        group,
        field,
        {
            element: (sum(element(point) == point for point in range(group.degree)) - 1) % field.p
            for element in group.elements
        },
        dimension=2,
        name="standard",
    )

    trivial_projector = representation.projector(trivial)
    standard_projector = representation.projector(standard)
    identity = DenseMatrix.identity(field, 3)
    assert trivial_projector @ trivial_projector == trivial_projector
    assert standard_projector @ standard_projector == standard_projector
    assert trivial_projector @ standard_projector == DenseMatrix.zeros(field, 3, 3)
    assert trivial_projector + standard_projector == identity
    assert representation.isotypic(trivial).dimension == 1
    assert representation.isotypic(standard).dimension == 2
    decomposition = representation.isotypic_decomposition(
        (trivial, standard), require_complete=True
    )
    assert decomposition.complete
    assert decomposition.verify()
    assert decomposition["trivial"].dimension == 1
    assert decomposition["standard"].dimension == 2


def test_representation_never_transports_between_conjugate_embeddings() -> None:
    field = PrimeField(5)
    first = PermutationGroup(
        (
            Permutation.from_cycles(4, ((0, 1),)),
            Permutation.from_cycles(4, ((0, 1, 2),)),
        )
    )
    transport = Permutation.from_cycles(4, ((2, 3),))
    second = first.conjugate_by(transport)
    representation = Representation.permutation(first, field)

    foreign = next(element for element in second.elements if element not in first)
    with pytest.raises(ConcreteEmbeddingError, match="no transport"):
        representation.action_matrix(foreign)
    with pytest.raises(ConcreteEmbeddingError, match="literal concrete subgroup"):
        representation.restrict(second)
