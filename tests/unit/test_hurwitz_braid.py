from __future__ import annotations

import pytest

from arbogast.hurwitz import (
    BraidClosureError,
    BraidMove,
    BraidWord,
    apply_braid_word,
    braid_action,
    nielsen_class,
    pure_braid_word,
)
from arbogast.rep import Permutation, PermutationGroup


def s3_data() -> tuple[PermutationGroup, tuple[Permutation, ...]]:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    return group, group.conjugacy_class(left)


def test_hurwitz_generator_and_inverse_use_the_documented_right_action() -> None:
    group, transpositions = s3_data()
    value = nielsen_class(group, (transpositions,) * 4)[1]
    left, right = value.entries[:2]

    moved = apply_braid_word(value, BraidWord.generator(0))
    assert moved.entries[:2] == (left * right * left.inverse(), left)
    restored = apply_braid_word(moved, BraidWord.generator(0, inverse=True))
    assert restored.entries == value.entries
    assert moved.product == group.identity


def test_standard_braid_relations_hold_exactly() -> None:
    group, transpositions = s3_data()
    value = nielsen_class(group, (transpositions,) * 4)[1]
    s0 = BraidWord.generator(0)
    s1 = BraidWord.generator(1)
    s2 = BraidWord.generator(2)

    assert (
        apply_braid_word(value, s0.then(s1).then(s0)).entries
        == apply_braid_word(value, s1.then(s0).then(s1)).entries
    )
    assert (
        apply_braid_word(value, s0.then(s2)).entries == apply_braid_word(value, s2.then(s0)).entries
    )


def test_full_action_edges_components_and_paths_have_replayable_receipts() -> None:
    group, transpositions = s3_data()
    nielsen = nielsen_class(group, (transpositions,) * 4)
    action = braid_action(nielsen)

    assert action.verify()
    assert len(action.edge_certificates) == 3 * len(nielsen)
    edge = action.edge_certificates[0]
    assert edge.to_dict()["certificate_id"] == edge.content_id
    assert edge.verification_certificate(action).verify_integrity()
    components = action.components()
    assert components.verify()
    component = components.one()
    assert component.cardinality == 4
    assert component.verify()
    assert component.certificate.verification_certificate(action).verify_integrity()

    path = action.braid_distance(0, 3)
    assert path.verify()
    assert path.distance == 1
    weighted = action.weighted_braid_path(
        0,
        3,
        {
            "sigma_0": 10.0,
            "sigma_1": 1.0,
            "sigma_2": 10.0,
        },
    )
    assert weighted.verify()
    assert weighted.total_cost <= 10.0


def test_pure_generators_preserve_an_ordered_mixed_class_vector() -> None:
    group, transpositions = s3_data()
    three_cycle = next(element for element in group.elements if element.order == 3)
    three_cycles = group.conjugacy_class(three_cycle)
    nielsen = nielsen_class(group, (transpositions, transpositions, three_cycles))

    with pytest.raises(BraidClosureError):
        braid_action(nielsen, mode="full")
    pure = braid_action(nielsen, mode="pure")
    assert len(pure.generators) == 3
    assert pure.verify()
    assert all(
        apply_braid_word(nielsen[0], generator.word).classes == nielsen[0].classes
        for generator in pure.generators
    )
    assert pure_braid_word(0, 2).moves == (
        BraidMove(1, True),
        BraidMove(0),
        BraidMove(0),
        BraidMove(1),
    )
