from __future__ import annotations

import pytest

from arbogast.core import ValidationError, VerificationError
from arbogast.deform.certificate import DeformationReceipt
from arbogast.deform.errors import DeformationVerificationError
from arbogast.deform.rings import ArtinRing, ArtinRingElement, ArtinRingMap, SmallExtension
from arbogast.linalg import DenseMatrix, PrimeField


def _truncated_polynomial_ring(exponent: int, *, prime: int = 3) -> ArtinRing:
    """Return F_p[e]/(e^exponent) in the pinned power basis."""

    field = PrimeField(prime)
    constants = tuple(
        tuple(
            tuple(1 if output == left + right else 0 for output in range(exponent))
            if left + right < exponent
            else (0,) * exponent
            for right in range(exponent)
        )
        for left in range(exponent)
    )
    return ArtinRing(
        field,
        constants,
        (1, *((0,) * (exponent - 1))),
        (1, *((0,) * (exponent - 1))),
        basis_names=("1", *(f"e^{power}" for power in range(1, exponent))),
    )


def test_dual_numbers_have_exact_local_and_nilpotence_witnesses() -> None:
    ring = _truncated_polynomial_ring(2)
    epsilon = ring.basis_element(1)

    assert ring.dimension == 2
    assert ring.cardinality == 9
    assert ring.maximal_ideal_basis == ((0, 1),)
    assert tuple(power.dimension for power in ring.maximal_ideal_powers) == (1, 0)
    assert ring.nilpotence_index == 2
    assert epsilon * epsilon == ring.zero
    assert (ring.one + epsilon) * (ring.one - epsilon) == ring.one
    assert not epsilon.is_unit
    assert (ring.one + epsilon).is_unit
    assert epsilon.residue == ring.field.zero
    assert ring.verify()
    assert epsilon.verify()


def test_higher_nilpotent_ring_replays_every_maximal_ideal_power() -> None:
    ring = _truncated_polynomial_ring(3)
    epsilon = ring.basis_element(1)

    assert ring.dimension == 3
    assert ring.nilpotence_index == 3
    assert tuple(power.dimension for power in ring.maximal_ideal_powers) == (2, 1, 0)
    assert epsilon**2 == ring.basis_element(2)
    assert epsilon**3 == ring.zero
    assert ring.maximal_ideal_power(0).dimension == 3
    assert ring.maximal_ideal_power(1).basis == ((0, 1, 0), (0, 0, 1))
    assert ring.maximal_ideal_power(2).basis == ((0, 0, 1),)
    assert ring.maximal_ideal_power(3).dimension == 0
    assert ring.verify()


def test_artin_ring_rejects_false_unit_residue_locality_and_power_witnesses() -> None:
    field = PrimeField(3)
    dual = _truncated_polynomial_ring(2)

    with pytest.raises(ValidationError, match="two-sided identity"):
        ArtinRing(field, dual.structure_constants, (0, 1), (1, 0))
    with pytest.raises(ValidationError, match="unit to one"):
        ArtinRing(field, dual.structure_constants, (1, 0), (0, 1))
    with pytest.raises(ValidationError, match="exact sequence"):
        ArtinRing(
            field,
            dual.structure_constants,
            dual.unit,
            dual.residue,
            maximal_ideal_powers=(((0, 1),),),
        )

    # F_3 x F_3 with projection to the first factor has an idempotent residue
    # kernel, not a nilpotent maximal ideal, so it is not a local Artin ring.
    product_constants = (
        ((1, 0), (0, 0)),
        ((0, 0), (0, 1)),
    )
    with pytest.raises(ValidationError, match="not nilpotent"):
        ArtinRing(field, product_constants, (1, 1), (1, 0))


def test_ring_maps_and_dual_number_small_extension_use_column_orientation() -> None:
    residue_ring = _truncated_polynomial_ring(1)
    dual = _truncated_polynomial_ring(2)
    projection = ArtinRingMap(dual, residue_ring, ((1, 0),))
    extension = SmallExtension(projection, ((0, 1),))

    assert projection.matrix.shape == (1, 2)
    assert projection.is_surjective
    assert not projection.is_injective
    assert projection.kernel.basis == ((0, 1),)
    assert projection(dual.one + dual.basis_element(1)) == residue_ring.one
    assert extension.inclusion.shape == (2, 1)
    assert extension.include((1,)) == dual.basis_element(1)
    assert extension(extension.include((1,))) == residue_ring.zero
    assert extension.kernel_dimension == 1
    assert projection.verify()
    assert extension.verify()

    with pytest.raises(ValidationError, match=r"shape|ncols"):
        ArtinRingMap(dual, residue_ring, ((1,), (0,)))
    with pytest.raises(ValidationError, match="exact projection kernel"):
        SmallExtension(projection, ((1, 0),))
    with pytest.raises(ValidationError, match="canonical kernel_basis"):
        SmallExtension(projection, ((0, 1),), DenseMatrix(dual.field, ((0,), (2,))))


def test_cubic_to_dual_numbers_is_an_exact_square_zero_small_extension() -> None:
    cubic = _truncated_polynomial_ring(3)
    dual = _truncated_polynomial_ring(2)
    projection = ArtinRingMap(cubic, dual, ((1, 0, 0), (0, 1, 0)))
    extension = SmallExtension(projection, ((0, 0, 1),))

    assert projection.kernel.basis == ((0, 0, 1),)
    assert extension.include((2,)) == ArtinRingElement(cubic, (0, 0, 2))
    assert extension.include((1,)) * extension.include((1,)) == cubic.zero
    assert extension.verify()


def test_square_zero_kernel_not_annihilated_by_maximal_ideal_is_not_small() -> None:
    quartic = _truncated_polynomial_ring(4)
    dual = _truncated_polynomial_ring(2)
    projection = ArtinRingMap(
        quartic,
        dual,
        ((1, 0, 0, 0), (0, 1, 0, 0)),
    )
    kernel_basis = ((0, 0, 1, 0), (0, 0, 0, 1))

    # I=(e^2,e^3) has I^2=0 in F_3[e]/(e^4), but e*e^2=e^3,
    # so the source maximal ideal does not annihilate I.
    with pytest.raises(ValidationError, match="annihilated by the maximal ideal"):
        SmallExtension(projection, kernel_basis)

    forged = DeformationReceipt.create(
        "small-extension",
        {
            "inclusion": [[0, 0], [0, 0], [1, 0], [0, 1]],
            "kernel_basis": [list(vector) for vector in kernel_basis],
            "projection_id": projection.content_id,
            "type": "arbogast.deform.small_extension",
        },
        dependencies=(projection.certificate,),
    )
    with pytest.raises(DeformationVerificationError, match="source maximal ideal"):
        forged.verify()


def test_tampered_frozen_ring_state_fails_independent_replay() -> None:
    ring = _truncated_polynomial_ring(2)
    object.__setattr__(ring, "unit", (0, 1))

    with pytest.raises(VerificationError, match="verification failed"):
        ring.verify()
