from __future__ import annotations

from copy import deepcopy

import pytest

from arbogast.deform.certificate import DeformationReceipt
from arbogast.deform.complex import DeformationComplex
from arbogast.deform.equivariant import (
    DeformationAction,
    equivariant,
    invariant_deformations,
)
from arbogast.deform.errors import (
    DeformationVerificationError,
    UnsupportedDeformation,
    UnsupportedDeformationOperation,
)
from arbogast.deform.lifting import (
    ContractionCertificate,
    FixedLift,
    LiftDatum,
    LiftEndomorphism,
    LiftFamily,
    LiftObstructed,
    LiftUnknown,
    NonUniqueLift,
    UniqueLift,
    fixed_lift,
    lift,
    unique_lift,
)
from arbogast.deform.problem import deformation_problem
from arbogast.deform.rings import ArtinRing, ArtinRingMap, SmallExtension
from arbogast.deform.semantic import receipt_for_result
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup, Representation

F3 = PrimeField(3)


def _truncated_polynomial_ring(exponent: int) -> ArtinRing:
    constants = []
    for left in range(exponent):
        rows = []
        for right in range(exponent):
            product = [0] * exponent
            if left + right < exponent:
                product[left + right] = 1
            rows.append(tuple(product))
        constants.append(tuple(rows))
    return ArtinRing(
        F3,
        tuple(constants),
        (1,) + (0,) * (exponent - 1),
        (1,) + (0,) * (exponent - 1),
        basis_names=tuple("1" if index == 0 else f"e^{index}" for index in range(exponent)),
    )


def _dual_number_extension() -> SmallExtension:
    dual = _truncated_polynomial_ring(2)
    residue = _truncated_polynomial_ring(1)
    projection = ArtinRingMap(dual, residue, ((1, 0),))
    return SmallExtension(projection, ((0, 1),))


def _family(*, gauge_kills_kernel: bool = False) -> LiftFamily:
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 2, 0),
        DenseMatrix.zeros(F3, 0, 2),
        name="two lift directions",
    )
    correction = DenseMatrix(F3, ((1, 0),))
    gauge = (
        DenseMatrix.from_columns(F3, ((0, 1),), nrows=2)
        if gauge_kills_kernel
        else DenseMatrix.zeros(F3, 2, 0)
    )
    datum = LiftDatum(
        deformation_problem(complex_),
        _dual_number_extension(),
        (1,),
        correction_matrix=correction,
        gauge_matrix=gauge,
    )
    result = lift(datum)
    assert isinstance(result, LiftFamily)
    return result


def test_solvable_affine_lift_retains_the_complete_solution_family() -> None:
    family = _family()

    assert family.verify()
    assert family.representative == (1, 0)
    assert family.dimension == 1
    assert family.mod_gauge_dimension == 1
    assert family.contains((1, 2))
    assert not family.contains((0, 2))


def test_inconsistent_lift_has_a_literal_separator_and_obstruction_class() -> None:
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 0),
        DenseMatrix.zeros(F3, 1, 1),
        name="obstructed lift",
    )
    datum = LiftDatum(
        deformation_problem(complex_),
        _dual_number_extension(),
        (1,),
    )

    result = lift(datum)

    assert isinstance(result, LiftObstructed)
    assert result.verify()
    assert result.separating_witness == (1,)
    assert result.obstruction_class is not None
    assert not result.obstruction_class.is_zero
    assert unique_lift(result) is result
    assert fixed_lift(result) is result


def test_obstructed_receipt_binds_the_nested_class_to_the_lift_target() -> None:
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 0),
        DenseMatrix.zeros(F3, 2, 1),
        name="two-dimensional obstruction",
    )
    result = lift(LiftDatum(complex_, _dual_number_extension(), (1, 0)))
    assert isinstance(result, LiftObstructed)

    receipt = receipt_for_result(result)
    payload = deepcopy(receipt.payload.to_dict())
    nested = payload["obstruction_class"]
    assert isinstance(nested, dict)
    nested["ambient_vector"] = [0, 1]
    nested["class_coordinates"] = [0, 1]
    forged = DeformationReceipt.create(
        "lift-obstructed",
        payload,
        dependencies=receipt.dependencies,
    )

    with pytest.raises(DeformationVerificationError, match="class of the lift target"):
        forged.verify()


def test_unique_and_nonunique_are_decided_only_modulo_pinned_gauge() -> None:
    nonunique = unique_lift(_family())
    unique = unique_lift(_family(gauge_kills_kernel=True))

    assert isinstance(nonunique, NonUniqueLift)
    assert nonunique.verify()
    assert nonunique.first != nonunique.second
    assert nonunique.separating_class_coordinates == (1,)
    assert isinstance(unique, UniqueLift)
    assert unique.verify()
    assert unique.family.mod_gauge_dimension == 0


def test_nilpotent_affine_endomorphism_produces_a_checked_fixed_lift() -> None:
    family = _family()
    endomorphism = LiftEndomorphism(
        family,
        DenseMatrix.zeros(F3, 2, 2),
        (1, 2),
    )
    contraction = ContractionCertificate(endomorphism, 1)

    result = fixed_lift(family, endomorphism, contraction=contraction)

    assert isinstance(result, FixedLift)
    assert result.verify()
    assert result.representative == (1, 2)
    assert endomorphism.apply(result.representative) == result.representative


def test_noncontracting_action_is_rejected_instead_of_claiming_a_fixed_lift() -> None:
    family = _family()
    identity = LiftEndomorphism(
        family,
        DenseMatrix.identity(F3, 2),
        (0, 0),
    )

    with pytest.raises(DeformationVerificationError, match="does not kill"):
        ContractionCertificate(identity, 1)
    with pytest.raises(DeformationVerificationError, match="does not kill"):
        fixed_lift(family, identity, exponent=1)


def test_missing_fixed_point_evidence_is_a_typed_unknown() -> None:
    family = _family()
    endomorphism = LiftEndomorphism(
        family,
        DenseMatrix.zeros(F3, 2, 2),
        (1, 2),
    )

    no_action = fixed_lift(family)
    no_contraction = fixed_lift(family, endomorphism)

    assert isinstance(no_action, LiftUnknown)
    assert isinstance(no_contraction, LiftUnknown)
    assert "endomorphism" in no_action.reason
    assert "contraction" in no_contraction.reason
    assert no_action.verify() and no_contraction.verify()


def test_lift_accepts_a_higher_nilpotent_small_extension() -> None:
    cubic = _truncated_polynomial_ring(3)
    dual = _truncated_polynomial_ring(2)
    extension = SmallExtension(
        ArtinRingMap(cubic, dual, ((1, 0, 0), (0, 1, 0))),
        ((0, 0, 1),),
    )
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 0),
        DenseMatrix(F3, ((1,),)),
    )

    result = lift(LiftDatum(complex_, extension, (2,)))

    assert isinstance(result, LiftFamily)
    assert result.representative == (2,)


def test_higher_dimensional_kernel_needs_an_explicit_chart_in_convenience_api() -> None:
    square_zero_plane = ArtinRing(
        F3,
        (
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            ((0, 1, 0), (0, 0, 0), (0, 0, 0)),
            ((0, 0, 1), (0, 0, 0), (0, 0, 0)),
        ),
        (1, 0, 0),
        (1, 0, 0),
    )
    residue = _truncated_polynomial_ring(1)
    extension = SmallExtension(
        ArtinRingMap(square_zero_plane, residue, ((1, 0, 0),)),
        ((0, 1, 0), (0, 0, 1)),
    )
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 0),
        DenseMatrix.zeros(F3, 1, 1),
    )

    result = lift(complex_, extension, target=(0,))

    assert isinstance(result, UnsupportedDeformation)
    assert result.verify()
    assert result.requested.to_dict()["kernel_dimension"] == 2
    with pytest.raises(UnsupportedDeformationOperation, match="higher-dimensional kernels"):
        LiftDatum(complex_, extension, (0,))


def test_lift_convenience_accepts_an_invariant_deformations_wrapper() -> None:
    complex_ = DeformationComplex(
        F3,
        DenseMatrix.zeros(F3, 1, 1),
        DenseMatrix.zeros(F3, 1, 1),
        name="invariant lift source",
    )
    group = CyclicGroup(2)
    trivial = Representation.trivial(group, F3)
    invariant = invariant_deformations(
        equivariant(complex_, DeformationAction(complex_, trivial, trivial, trivial))
    )

    result = lift(invariant, _dual_number_extension(), target=(0,))
    uniqueness = unique_lift(invariant, _dual_number_extension(), target=(0,))

    assert isinstance(result, LiftFamily)
    assert result.verify()
    assert result.datum.problem is invariant.problem
    assert isinstance(uniqueness, NonUniqueLift)
    assert uniqueness.verify()


def test_tampered_lift_and_fixed_point_witnesses_fail_replay() -> None:
    family = _family()
    object.__setattr__(family, "particular", (0, 0))
    with pytest.raises(DeformationVerificationError, match="particular"):
        family.verify()

    valid_family = _family()
    endomorphism = LiftEndomorphism(
        valid_family,
        DenseMatrix.zeros(F3, 2, 2),
        (1, 2),
    )
    result = fixed_lift(valid_family, endomorphism, exponent=1)
    assert isinstance(result, FixedLift)
    object.__setattr__(result, "representative", (1, 1))
    with pytest.raises(DeformationVerificationError, match="contracted iterate"):
        result.verify()
