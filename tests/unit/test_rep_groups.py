from __future__ import annotations

import pytest

from arbogast.rep import CyclicGroup, Permutation, PermutationGroup, symmetric_group


def test_permutation_convention_inverse_power_cycles_and_encoding() -> None:
    transposition = Permutation.from_cycles(4, ((0, 1),))
    cycle = Permutation.from_cycles(4, ((0, 1, 2),))

    product = transposition * cycle
    assert tuple(product(point) for point in range(4)) == tuple(
        transposition(cycle(point)) for point in range(4)
    )
    assert product * product.inverse() == Permutation.identity(4)
    assert cycle**3 == Permutation.identity(4)
    assert cycle**-1 == cycle.inverse()
    assert transposition.parity == 1
    assert transposition.sign == -1
    assert cycle.parity == 0
    assert cycle.cycles() == ((0, 1, 2),)
    assert cycle.cycles(include_fixed=True) == ((0, 1, 2), (3,))
    assert cycle.cycle_type == (3, 1)
    assert Permutation.from_canonical_bytes(cycle.canonical_bytes()) == cycle


def test_concrete_degree_is_never_silently_changed() -> None:
    degree_three = Permutation.identity(3)
    degree_four = Permutation.identity(4)
    assert degree_three != degree_four
    with pytest.raises(ValueError, match="different degrees"):
        _ = degree_three * degree_four
    with pytest.raises(ValueError, match="exact concrete degree"):
        PermutationGroup((degree_three,), degree=4)


def test_s3_closure_classes_centralizer_orbits_and_witnesses() -> None:
    group = symmetric_group(3)
    assert group.order == 6
    assert group.identity == Permutation.identity(3)
    assert group.is_transitive()
    assert group.orbits() == ((0, 1, 2),)
    assert sorted(len(conjugacy_class) for conjugacy_class in group.conjugacy_classes()) == [
        1,
        2,
        3,
    ]

    transposition = Permutation.from_cycles(3, ((0, 1),))
    assert group.centralizer(transposition).order == 2
    assert group.class_of(transposition) == group.conjugacy_class(transposition)
    assert group.class_lookup(transposition) == group.class_index(transposition)

    for element in group.elements:
        witness = group.generation_witness(element)
        assert witness.verify()
        assert witness.evaluate() == element
        assert group.evaluate_word(witness.word) == element
    assert group.generation_certificate().verify()


def test_subgroups_and_cyclic_helpers() -> None:
    group = symmetric_group(3)
    three_cycle = Permutation.from_cycles(3, ((0, 1, 2),))
    subgroup = group.subgroup((three_cycle,))
    assert subgroup.order == 3
    assert subgroup.elements == CyclicGroup(3, generator=three_cycle).elements
    assert group.is_generated_by(group.generators)
    assert not group.is_generated_by((three_cycle,))

    cyclic = CyclicGroup(5)
    assert cyclic.order == 5
    assert cyclic.generator.order == 5
    assert cyclic.generation_certificate().verify()


def test_conjugate_abstract_copies_remain_distinct_concrete_embeddings() -> None:
    first = PermutationGroup(
        (
            Permutation.from_cycles(4, ((0, 1),)),
            Permutation.from_cycles(4, ((0, 1, 2),)),
        )
    )
    transport = Permutation.from_cycles(4, ((2, 3),))
    second = first.conjugate_by(transport)

    assert first.order == second.order == 6
    assert first != second
    moved_generator = next(generator for generator in second.generators if generator not in first)
    assert moved_generator not in first
    with pytest.raises(ValueError, match="not an element"):
        first.multiply(first.identity, moved_generator)
