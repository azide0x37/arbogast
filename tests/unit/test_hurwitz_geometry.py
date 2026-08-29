from __future__ import annotations

from dataclasses import replace

import pytest

from arbogast.hurwitz import (
    BraidWord,
    CertificateVerificationError,
    Collision,
    boundary_incidence,
    braid_action,
    collide,
    cusps,
    is_totally_real,
    nielsen_class,
    real_structure,
    real_witnesses,
    reduced,
    source_genus,
    source_genus_result,
    symmetry_from_braid_word,
    totally_real,
)
from arbogast.rep import Permutation, PermutationGroup


def fixture() -> tuple[PermutationGroup, object, object]:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    return group, transpositions, nielsen_class(group, (transpositions,) * 4)


def test_real_structure_and_c_equals_one_predicate_are_exact() -> None:
    group, _, nielsen = fixture()
    structure = real_structure(nielsen)

    assert structure.verify()
    assert structure.certificate.to_dict()["certificate_id"] == structure.certificate.content_id
    assert structure.certificate.verification_certificate(structure).verify_integrity()
    assert structure.mapping == (0, 3, 2, 1)
    assert structure.fixed_indices() == (0, 2)
    real = totally_real(nielsen)
    assert len(real) == 1
    assert is_totally_real(real[0])
    witnesses = real_witnesses(nielsen, group.identity)
    assert tuple(witness.representative for witness in witnesses) == real
    assert all(witness.verify() for witness in witnesses)


def test_source_genus_is_distinct_and_certified() -> None:
    _, _, nielsen = fixture()
    for value in nielsen:
        result = source_genus_result(value)
        assert result.genus == 0
        assert result.verify(value)
        assert result.certificate.verification_certificate(value).verify_integrity()
        assert source_genus(value) == 0


def test_reduced_quotient_and_cusp_widths_use_explicit_symmetries() -> None:
    _, _, nielsen = fixture()
    action = braid_action(nielsen)
    component = action.components().one()
    cusp_data = cusps(component, "sigma_0")

    assert cusp_data.verify()
    assert cusp_data.certificate.verification_certificate().verify_integrity()
    assert sorted(cusp_data.widths) == [1, 3]
    symmetry = symmetry_from_braid_word(
        component, BraidWord.generator(0), name="sigma-zero-quotient"
    )
    quotient = reduced(component, (symmetry,))
    assert quotient.cardinality == 2
    assert quotient.verify()
    assert quotient.certificate.verification_certificate().verify_integrity()
    assert quotient.quotient_edges

    merged_orbits = replace(
        quotient.certificate,
        blocks=(component.vertex_indices,),
    )
    with pytest.raises(CertificateVerificationError, match="merges distinct"):
        merged_orbits.verify()


def test_boundary_collision_and_incidence_are_exhaustive() -> None:
    group, _, nielsen = fixture()
    action = braid_action(nielsen)
    component = action.components().one()
    value = nielsen[0]

    lower = collide(value, Collision(0, 1))
    assert next(iter(lower)) == value[0] * value[1]
    assert lower.context.product(lower.entries) == group.identity
    assert lower.verify()

    cyclic = collide(value, Collision(3, 0))
    assert cyclic.context.product(cyclic.entries) == group.identity
    incidence = boundary_incidence(component, (Collision(0, 1), Collision(1, 2)))
    assert incidence.verify()
    assert incidence.certificate.verification_certificate().verify_integrity()
    assert incidence.total_incidences == 2 * component.cardinality
    assert all(sum(row) == component.cardinality for row in incidence.matrix)
