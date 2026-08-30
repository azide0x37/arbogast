from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from itertools import repeat

import pytest

from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.errors import (
    PAdicResourceError,
    PAdicValidationError,
    PAdicVerificationError,
)
from arbogast.padic.fields import (
    PAdicAutomorphism,
    PAdicField,
    PAdicPrecisionRing,
)
from arbogast.padic.frobenius import (
    FrobeniusConvention,
    FrobeniusOperator,
    SlopeDecomposition,
    SlopeProjector,
    frobenius,
    ordinary_part,
    slopes,
)
from arbogast.padic.inertia import (
    FiniteInertiaQuotient,
    InertiaFiltration,
    InertiaRepresentation,
    inertia_action,
)
from arbogast.padic.matrices import PAdicMatrix
from arbogast.padic.modules import PAdicModule, PAdicSubmodule
from arbogast.padic.results import Certified, Unknown
from arbogast.rep import Permutation, PermutationGroup


def _rational_frobenius(
    prime: int = 5,
    precision: int = 4,
) -> tuple[PAdicPrecisionRing, PAdicModule, FrobeniusOperator]:
    ring = PAdicPrecisionRing(PAdicField.rational(prime), precision)
    module = PAdicModule(ring, 2)
    operator = FrobeniusOperator(
        module,
        PAdicMatrix(ring, ((1, 0), (0, prime))),
        PAdicAutomorphism.identity(ring),
        FrobeniusConvention.ARITHMETIC,
    )
    return ring, module, operator


def _ordinary_projector(
    ring: PAdicPrecisionRing,
    operator: FrobeniusOperator,
) -> SlopeProjector:
    identity = PAdicMatrix.identity(ring, 2)
    return SlopeProjector(
        operator,
        0,
        1,
        PAdicMatrix(ring, ((1, 0), (0, 0))),
        identity,
        identity,
    )


def _permutation_matrix(
    ring: PAdicPrecisionRing,
    permutation: Permutation,
) -> PAdicMatrix:
    return PAdicMatrix(
        ring,
        tuple(
            tuple(1 if row == permutation(column) else 0 for column in range(permutation.degree))
            for row in range(permutation.degree)
        ),
    )


def test_certified_slopes_and_ordinary_projector_replay_end_to_end() -> None:
    ring, module, operator = _rational_frobenius()
    projector = _ordinary_projector(ring, operator)

    operator_result = frobenius(module, datum=operator)
    slope_result = slopes(operator, projectors=(projector,))
    ordinary_result = ordinary_part(operator, projector=projector)

    assert isinstance(operator_result, Certified)
    assert isinstance(slope_result, Certified)
    assert isinstance(slope_result.value, SlopeDecomposition)
    assert tuple((item.slope, item.multiplicity) for item in slope_result.value.multiplicities) == (
        (Fraction(0), 1),
        (Fraction(1), 1),
    )
    assert not slope_result.value.projectors_complete
    assert isinstance(ordinary_result, Certified)
    assert ordinary_result.value == projector
    assert projector.submodule.cardinality == ring.cardinality
    assert all(result.verify() for result in (operator_result, slope_result, ordinary_result))


def test_projector_binds_the_exact_saturated_image_submodule() -> None:
    ring, module, operator = _rational_frobenius()
    identity = PAdicMatrix.identity(ring, 2)
    matrix = PAdicMatrix(ring, ((1, 0), (0, 0)))

    with pytest.raises(PAdicValidationError, match="not the image"):
        SlopeProjector(
            operator,
            0,
            1,
            matrix,
            identity,
            identity,
            submodule=PAdicSubmodule.zero(module),
        )

    decomposition = slopes(
        operator, projectors=(SlopeProjector(operator, 0, 1, matrix, identity, identity),)
    )
    assert isinstance(decomposition, Certified)
    with pytest.raises(PAdicResourceError, match="projector count"):
        SlopeDecomposition(
            operator,
            decomposition.value.intervals,
            decomposition.value.segments,
            decomposition.value.multiplicities,
            repeat(decomposition.value.projectors[0]),
        )
    with pytest.raises(PAdicValidationError, match="not the image"):
        SlopeProjector(
            operator,
            0,
            1,
            matrix,
            identity,
            identity,
            submodule=PAdicSubmodule.whole(module),
        )


def test_unknown_boundaries_do_not_promote_missing_or_ambiguous_data() -> None:
    ring, module, operator = _rational_frobenius()

    missing = frobenius(module)
    assert isinstance(missing, Unknown)
    assert missing.reason_code == "missing-semilinear-frobenius-datum"
    assert missing.verify()

    no_projector = ordinary_part(operator)
    assert isinstance(no_projector, Unknown)
    assert no_projector.reason_code == "missing-saturated-projector"

    rank_one = PAdicModule(ring, 1)
    zero_operator = FrobeniusOperator(
        rank_one,
        PAdicMatrix(ring, ((0,),)),
        PAdicAutomorphism.identity(ring),
        FrobeniusConvention.ARITHMETIC,
    )
    ambiguous = slopes(zero_operator)
    assert isinstance(ambiguous, Unknown)
    assert ambiguous.reason_code == "ambiguous-newton-polygon"
    assert ambiguous.verify()

    positive_operator = FrobeniusOperator(
        module,
        PAdicMatrix(ring, ((5, 0), (0, 25))),
        PAdicAutomorphism.identity(ring),
        FrobeniusConvention.ARITHMETIC,
    )
    identity = PAdicMatrix.identity(ring, 2)
    zero_projector = SlopeProjector(
        positive_operator,
        0,
        0,
        PAdicMatrix.zero(ring, 2, 2),
        identity,
        identity,
    )
    zero_ordinary = ordinary_part(positive_operator, projector=zero_projector)
    assert isinstance(zero_ordinary, Certified)
    assert zero_ordinary.value.submodule == PAdicSubmodule.zero(module)
    assert zero_ordinary.verify()


def test_semilinear_period_is_linearized_and_slopes_are_normalized() -> None:
    field = PAdicField.unramified(3, (1, 0, 1))
    ring = PAdicPrecisionRing(field, 3)
    frobenius_sigma = PAdicAutomorphism(
        ring,
        (ring.from_coordinates((1, 0)), ring.from_coordinates((0, -1))),
        (ring.from_coordinates((1, 0)), ring.from_coordinates((0, -1))),
    )
    module = PAdicModule(ring, 2)
    operator = FrobeniusOperator(
        module,
        PAdicMatrix(ring, ((1, 0), (0, 3))),
        frobenius_sigma,
        FrobeniusConvention.ARITHMETIC,
    )

    assert operator.semilinear_period == 2
    assert operator.linearized_matrix == PAdicMatrix(ring, ((1, 0), (0, 9)))
    result = slopes(operator)
    assert isinstance(result, Certified)
    assert tuple((item.slope, item.multiplicity) for item in result.value.multiplicities) == (
        (Fraction(0), 1),
        (Fraction(1), 1),
    )
    assert result.verify()

    with pytest.raises(PAdicValidationError, match="does not induce"):
        FrobeniusOperator(
            module,
            PAdicMatrix.identity(ring, 2),
            PAdicAutomorphism.identity(ring),
            FrobeniusConvention.ARITHMETIC,
        )


def test_frobenius_conventions_are_distinct_canonical_data() -> None:
    ring, module, arithmetic = _rational_frobenius()
    geometric = FrobeniusOperator(
        module,
        arithmetic.matrix,
        PAdicAutomorphism.identity(ring),
        FrobeniusConvention.GEOMETRIC,
    )

    assert arithmetic.operator_id != geometric.operator_id
    assert arithmetic.to_schema_document()["convention"] == "arithmetic"
    assert geometric.to_schema_document()["convention"] == "geometric"


def test_geometric_frobenius_uses_inverse_residue_action_in_degree_three() -> None:
    field = PAdicField.unramified(2, (1, 1, 0, 1))
    ring = PAdicPrecisionRing(field, 1)
    one = ring.from_coordinates((1, 0, 0))
    x = ring.from_coordinates((0, 1, 0))
    x_squared = ring.from_coordinates((0, 0, 1))
    x_plus_x_squared = ring.from_coordinates((0, 1, 1))
    arithmetic_sigma = PAdicAutomorphism(
        ring,
        (one, x_squared, x_plus_x_squared),
        (one, x_plus_x_squared, x),
    )
    geometric_sigma = PAdicAutomorphism(
        ring,
        (one, x_plus_x_squared, x),
        (one, x_squared, x_plus_x_squared),
    )
    module = PAdicModule(ring, 1)
    identity = PAdicMatrix.identity(ring, 1)

    arithmetic = FrobeniusOperator(
        module,
        identity,
        arithmetic_sigma,
        FrobeniusConvention.ARITHMETIC,
    )
    geometric = FrobeniusOperator(
        module,
        identity,
        geometric_sigma,
        FrobeniusConvention.GEOMETRIC,
    )

    assert arithmetic.verify()
    assert geometric.verify()
    assert arithmetic.to_schema_document()["sigma_residue_action"] == (
        "x -> x^p modulo uniformizer"
    )
    assert geometric.to_schema_document()["sigma_residue_action"] == (
        "sigma(x)^p -> x modulo uniformizer"
    )
    with pytest.raises(PAdicValidationError, match="inverse x -> x\\^p"):
        FrobeniusOperator(
            module,
            identity,
            arithmetic_sigma,
            FrobeniusConvention.GEOMETRIC,
        )


def test_frobenius_receipt_recomputes_nested_witnesses_after_tampering() -> None:
    _ring, module, operator = _rational_frobenius()
    result = frobenius(module, datum=operator)
    assert isinstance(result, Certified)
    payload = deepcopy(result.receipt.payload.to_dict())
    document = payload["result"]
    assert isinstance(document, dict)
    document["semilinear_period"] = 2
    forged = PAdicReceipt.create(
        result.receipt.kind,
        result.receipt.closure,
        payload,
        proof_context=result.receipt.proof_context,
        evidence=result.receipt.evidence,
    )

    with pytest.raises(PAdicVerificationError, match="failed independent replay"):
        forged.verify()


def test_frobenius_replay_caps_nested_matrix_projector_and_hnf_collections() -> None:
    ring, _module, operator = _rational_frobenius()
    projector = _ordinary_projector(ring, operator)
    operator_result = frobenius(operator.module, datum=operator)
    slope_result = slopes(operator, projectors=(projector,))
    ordinary_result = ordinary_part(operator, projector=projector)
    assert isinstance(operator_result, Certified)
    assert isinstance(slope_result, Certified)
    assert isinstance(ordinary_result, Certified)

    oversized_matrix_payload = deepcopy(operator_result.receipt.payload.to_dict())
    oversized_matrix_document = oversized_matrix_payload["result"]
    assert isinstance(oversized_matrix_document, dict)
    oversized_matrix = oversized_matrix_document["matrix"]
    assert isinstance(oversized_matrix, dict)
    matrix_entries = oversized_matrix["entries"]
    assert isinstance(matrix_entries, list)
    matrix_entries.extend(deepcopy(matrix_entries[0]) for _ in range(63))
    oversized_matrix_receipt = PAdicReceipt.create(
        operator_result.receipt.kind,
        operator_result.receipt.closure,
        oversized_matrix_payload,
        proof_context=operator_result.receipt.proof_context,
        evidence=operator_result.receipt.evidence,
    )
    with pytest.raises(PAdicResourceError, match="row count"):
        oversized_matrix_receipt.verify()

    oversized_projectors_payload = deepcopy(slope_result.receipt.payload.to_dict())
    oversized_projectors_document = oversized_projectors_payload["result"]
    assert isinstance(oversized_projectors_document, dict)
    projector_documents = oversized_projectors_document["projectors"]
    assert isinstance(projector_documents, list) and projector_documents
    oversized_projectors_document["projectors"] = [
        deepcopy(projector_documents[0]) for _ in range(operator.rank + 1)
    ]
    oversized_projectors_receipt = PAdicReceipt.create(
        slope_result.receipt.kind,
        slope_result.receipt.closure,
        oversized_projectors_payload,
        proof_context=slope_result.receipt.proof_context,
        evidence=slope_result.receipt.evidence,
    )
    with pytest.raises(PAdicResourceError, match="projector count"):
        oversized_projectors_receipt.verify()

    oversized_hnf_payload = deepcopy(ordinary_result.receipt.payload.to_dict())
    oversized_hnf_document = oversized_hnf_payload["result"]
    assert isinstance(oversized_hnf_document, dict)
    submodule = oversized_hnf_document["submodule"]
    assert isinstance(submodule, dict)
    hnf = submodule["preimage_hnf"]
    assert isinstance(hnf, list) and hnf
    hnf.append(deepcopy(hnf[0]))
    oversized_hnf_receipt = PAdicReceipt.create(
        ordinary_result.receipt.kind,
        ordinary_result.receipt.closure,
        oversized_hnf_payload,
        proof_context=ordinary_result.receipt.proof_context,
        evidence=ordinary_result.receipt.evidence,
    )
    with pytest.raises(PAdicResourceError, match="HNF"):
        oversized_hnf_receipt.verify()


def test_frobenius_work_bound_fails_before_large_matrix_replay() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(3), 1)
    module = PAdicModule(ring, 64)
    with pytest.raises(PAdicResourceError, match="algebra-work"):
        FrobeniusOperator(
            module,
            PAdicMatrix.identity(ring, 64),
            PAdicAutomorphism.identity(ring),
            FrobeniusConvention.ARITHMETIC,
        )


def test_finite_inertia_table_filtration_and_action_are_complete() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(5), 3)
    module = PAdicModule(ring, 1)
    generator = Permutation.from_cycles(3, ((0, 1, 2),))
    group = PermutationGroup((generator,), degree=3)
    quotient = FiniteInertiaQuotient(module.module_id, "v2", 2, 1, group)
    filtration = InertiaFiltration(quotient, (group.elements, (group.identity,)))
    identity = PAdicMatrix.identity(ring, 1)
    representation = InertiaRepresentation(
        module,
        quotient,
        filtration,
        {element: identity for element in group.elements},
    )
    result = inertia_action(module, 2, datum=representation)

    assert quotient.verify() and filtration.verify() and representation.verify()
    assert quotient.arithmetic_origin_claimed is False
    assert filtration.arithmetic_lower_numbering_claimed is False
    assert isinstance(result, Certified)
    assert result.verify()
    quotient_document = quotient.to_schema_document()
    filtration_document = filtration.to_schema_document()
    representation_document = representation.to_schema_document()
    assert quotient_document["arithmetic_origin_claimed"] is False
    assert "no arithmetic-origin" in quotient_document["scope"]
    assert filtration_document["arithmetic_lower_numbering_claimed"] is False
    assert filtration_document["numbering"] == "declared-indexed-series"
    assert "no arithmetic" in filtration_document["scope"]
    assert "declared finite group presentation" in representation_document["scope"]


def test_lower_filtration_preserves_wild_repeats_and_rejects_non_elementary_jump() -> None:
    source_id = "source"
    order_two_generator = Permutation.from_cycles(2, ((0, 1),))
    order_two = PermutationGroup((order_two_generator,), degree=2)
    quotient_two = FiniteInertiaQuotient(source_id, "v2", 2, 1, order_two)
    filtration = InertiaFiltration(
        quotient_two,
        (order_two.elements, order_two.elements, (order_two.identity,)),
    )
    assert filtration.level_indices[0] == filtration.level_indices[1]
    assert filtration.verify()

    # These finite identities alone also accept a deliberately repeated series
    # whose index labels are not a proof of arithmetic lower ramification.
    declared_only = InertiaFiltration(
        quotient_two,
        (
            order_two.elements,
            order_two.elements,
            order_two.elements,
            (order_two.identity,),
        ),
    )
    assert declared_only.verify()
    assert declared_only.arithmetic_lower_numbering_claimed is False

    order_four_generator = Permutation.from_cycles(4, ((0, 1, 2, 3),))
    order_four = PermutationGroup((order_four_generator,), degree=4)
    quotient_four = FiniteInertiaQuotient(source_id, "v2", 2, 1, order_four)
    with pytest.raises(PAdicVerificationError, match="exponent greater than p"):
        InertiaFiltration(
            quotient_four,
            (order_four.elements, order_four.elements, (order_four.identity,)),
        )


def test_arithmetic_and_geometric_frobenius_inertia_relations_are_separate() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(3), 2)
    module = PAdicModule(ring, 5)
    tame_generator = Permutation.from_cycles(5, ((0, 1, 2, 3, 4),))
    group = PermutationGroup((tame_generator,), degree=5)
    quotient = FiniteInertiaQuotient(module.module_id, "v2", 2, 1, group)
    filtration = InertiaFiltration(quotient, (group.elements, (group.identity,)))
    action = {element: _permutation_matrix(ring, element) for element in group.elements}
    sigma = PAdicAutomorphism.identity(ring)
    multiply_by_two = Permutation(tuple(2 * index % 5 for index in range(5)))
    multiply_by_three = Permutation(tuple(3 * index % 5 for index in range(5)))
    arithmetic = FrobeniusOperator(
        module,
        _permutation_matrix(ring, multiply_by_two),
        sigma,
        FrobeniusConvention.ARITHMETIC,
    )
    geometric = FrobeniusOperator(
        module,
        _permutation_matrix(ring, multiply_by_three),
        sigma,
        FrobeniusConvention.GEOMETRIC,
    )

    arithmetic_representation = InertiaRepresentation(
        module,
        quotient,
        filtration,
        action,
        frobenius_operator=arithmetic,
        tame_generator=tame_generator,
    )
    geometric_representation = InertiaRepresentation(
        module,
        quotient,
        filtration,
        action,
        frobenius_operator=geometric,
        tame_generator=tame_generator,
    )
    assert (
        arithmetic_representation.to_schema_document()["frobenius_relation"][
            "exponent_mod_tame_order"
        ]
        == 2
    )
    assert (
        geometric_representation.to_schema_document()["frobenius_relation"][
            "exponent_mod_tame_order"
        ]
        == 3
    )
    assert inertia_action(module, datum=arithmetic_representation).verify()
    assert inertia_action(module, datum=geometric_representation).verify()

    with pytest.raises(PAdicVerificationError, match="relation fails"):
        InertiaRepresentation(
            module,
            quotient,
            filtration,
            action,
            frobenius_operator=FrobeniusOperator(
                module,
                _permutation_matrix(ring, multiply_by_two),
                sigma,
                FrobeniusConvention.GEOMETRIC,
            ),
            tame_generator=tame_generator,
        )


def test_inertia_resource_bound_and_huge_prime_fail_fast() -> None:
    trivial = PermutationGroup.trivial(0)
    with pytest.raises(PAdicResourceError, match="bit bound"):
        FiniteInertiaQuotient("source", "v", (1 << 4095) + 1, 1, trivial)

    elementary_generators = tuple(
        Permutation.from_cycles(20, ((2 * index, 2 * index + 1),)) for index in range(10)
    )
    large_table_group = PermutationGroup(elementary_generators, degree=20)
    assert large_table_group.order == 1024
    with pytest.raises(PAdicResourceError, match="group table"):
        FiniteInertiaQuotient("source", "v2", 2, 1, large_table_group)

    ring = PAdicPrecisionRing(PAdicField.rational(5), 1)
    module = PAdicModule(ring, 32)
    generator = Permutation.from_cycles(32, (tuple(range(32)),))
    group = PermutationGroup((generator,), degree=32)
    quotient = FiniteInertiaQuotient(module.module_id, "v3", 3, 1, group)
    filtration = InertiaFiltration(quotient, (group.elements, (group.identity,)))
    identity = PAdicMatrix.identity(ring, 32)
    with pytest.raises(PAdicResourceError, match="matrix action"):
        InertiaRepresentation(
            module,
            quotient,
            filtration,
            (identity,) * group.order,
        )

    precision_ring = PAdicPrecisionRing(PAdicField.rational(5), 64)
    precision_module = PAdicModule(precision_ring, 4)
    precision_generator = Permutation.from_cycles(32, (tuple(range(32)),))
    precision_group = PermutationGroup((precision_generator,), degree=32)
    precision_quotient = FiniteInertiaQuotient(
        precision_module.module_id,
        "v3",
        3,
        1,
        precision_group,
    )
    precision_filtration = InertiaFiltration(
        precision_quotient,
        (precision_group.elements, (precision_group.identity,)),
    )
    with pytest.raises(PAdicResourceError, match="precision-work"):
        InertiaRepresentation(
            precision_module,
            precision_quotient,
            precision_filtration,
            repeat(PAdicMatrix.identity(precision_ring, 4)),
        )


def test_inertia_iterable_inputs_are_bounded_before_materialization() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(5), 2)
    module = PAdicModule(ring, 1)
    generator = Permutation.from_cycles(3, ((0, 1, 2),))
    group = PermutationGroup((generator,), degree=3)
    quotient = FiniteInertiaQuotient(module.module_id, "v2", 2, 1, group)

    with pytest.raises(PAdicResourceError, match="level bound"):
        InertiaFiltration(quotient, repeat(group.elements))
    with pytest.raises(PAdicResourceError, match="quotient order bound"):
        InertiaFiltration(
            quotient,
            (repeat(group.identity), (group.identity,)),
        )

    filtration = InertiaFiltration(quotient, (group.elements, (group.identity,)))
    with pytest.raises(PAdicValidationError, match="group cardinality"):
        InertiaRepresentation(
            module,
            quotient,
            filtration,
            repeat(PAdicMatrix.identity(ring, 1)),
        )
