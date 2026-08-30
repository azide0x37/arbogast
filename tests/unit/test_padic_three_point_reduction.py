"""Exact and tamper tests for the bounded three-point reduction lane."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from typing import Any, cast

import pytest

import arbogast.padic.covers as padic_covers
import arbogast.padic.reduction as padic_reduction
from arbogast.numeric import ExactCover, ExactPolynomial
from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.covers import (
    BranchFiberWitness,
    BranchValue,
    DerivativeWitness,
    FiberFactor,
    ProjectiveRationalPoint,
    RiemannHurwitzWitness,
    ThreePointCover,
)
from arbogast.padic.errors import PAdicValidationError, PAdicVerificationError
from arbogast.padic.reduction import (
    GoodReduction,
    GoodReductionWitness,
    ReducedBranchFiber,
    ReducedFiberFactor,
    ReducedProjectivePoint,
    SemistableReduction,
    SemistableReductionWitness,
    StableReduction,
    StableReductionWitness,
    good_reduction,
    semistable_reduction,
    stable_reduction,
)
from arbogast.padic.results import Certified, Unsupported


def _beta_cover(*, label: str = "beta") -> ThreePointCover:
    polynomial = ExactPolynomial(
        1,
        (
            ((2,), Fraction(27, 4)),
            ((3,), Fraction(-27, 4)),
        ),
        variable_names=("z",),
    )
    zero = ProjectiveRationalPoint.finite(0)
    one = ProjectiveRationalPoint.finite(1)
    two_thirds = ProjectiveRationalPoint.finite(Fraction(2, 3))
    minus_one_third = ProjectiveRationalPoint.finite(Fraction(-1, 3))
    infinity = ProjectiveRationalPoint.infinity()
    fibers = (
        BranchFiberWitness(
            BranchValue.ZERO,
            Fraction(-27, 4),
            (FiberFactor(zero, 2), FiberFactor(one, 1)),
        ),
        BranchFiberWitness(
            BranchValue.ONE,
            Fraction(-1, 4),
            (FiberFactor(two_thirds, 2), FiberFactor(minus_one_third, 1)),
        ),
        BranchFiberWitness(
            BranchValue.INFINITY,
            1,
            (FiberFactor(infinity, 3),),
        ),
    )
    derivative = DerivativeWitness(
        polynomial.derivative(0),
        Fraction(-27, 4),
        (FiberFactor(zero, 1), FiberFactor(two_thirds, 1)),
    )
    return ThreePointCover(polynomial, fibers, derivative, label=label)


def _reflected_beta_cover() -> ThreePointCover:
    polynomial = ExactPolynomial(
        1,
        (
            ((1,), Fraction(27, 4)),
            ((2,), Fraction(-27, 2)),
            ((3,), Fraction(27, 4)),
        ),
        variable_names=("z",),
    )
    zero = ProjectiveRationalPoint.finite(0)
    one = ProjectiveRationalPoint.finite(1)
    one_third = ProjectiveRationalPoint.finite(Fraction(1, 3))
    four_thirds = ProjectiveRationalPoint.finite(Fraction(4, 3))
    infinity = ProjectiveRationalPoint.infinity()
    fibers = (
        BranchFiberWitness(
            BranchValue.ZERO,
            Fraction(27, 4),
            (FiberFactor(zero, 1), FiberFactor(one, 2)),
        ),
        BranchFiberWitness(
            BranchValue.ONE,
            Fraction(1, 4),
            (FiberFactor(one_third, 2), FiberFactor(four_thirds, 1)),
        ),
        BranchFiberWitness(
            BranchValue.INFINITY,
            1,
            (FiberFactor(infinity, 3),),
        ),
    )
    derivative = DerivativeWitness(
        polynomial.derivative(0),
        Fraction(27, 4),
        (FiberFactor(one_third, 1), FiberFactor(one, 1)),
    )
    return ThreePointCover(polynomial, fibers, derivative, label="reflected-beta")


def test_beta_is_an_independent_exact_normalized_three_point_cover() -> None:
    cover = _beta_cover()

    assert not isinstance(cover, ExactCover)
    assert cover.verify()
    assert cover.degree == 3
    assert cover.generic_degree_witness.degree == 3
    assert cover.ramification_profiles == ((2, 1), (2, 1), (3,))
    assert cover.riemann_hurwitz_witness.ramification_sum == 4
    assert cover.riemann_hurwitz_witness.expected_ramification == 4
    assert cover.derivative_witness.derivative == cover.polynomial.derivative(0)
    assert tuple(factor.point.fraction for factor in cover.derivative_witness.factors) == (
        Fraction(0),
        Fraction(2, 3),
    )
    assert cover.to_schema_document()["schema"] == "arbogast.padic.three-point-cover/v1"


def test_cover_rejects_incomplete_fibers_and_wrong_derivative_data() -> None:
    cover = _beta_cover()
    wrong_one = BranchFiberWitness(
        BranchValue.ONE,
        Fraction(1, 4),
        cover.one_fiber.factors,
    )
    with pytest.raises(PAdicValidationError, match="one-fibre factorization"):
        ThreePointCover(
            cover.polynomial,
            (cover.zero_fiber, wrong_one, cover.infinity_fiber),
            cover.derivative_witness,
        )

    with pytest.raises(PAdicValidationError, match="do not reconstruct"):
        DerivativeWitness(
            cover.polynomial.derivative(0),
            Fraction(27, 4),
            cover.derivative_witness.factors,
        )

    with pytest.raises(TypeError, match="integer"):
        ProjectiveRationalPoint(True)
    with pytest.raises(PAdicValidationError, match="not a projective point"):
        ProjectiveRationalPoint(0, 0)


def test_projective_coordinate_bounds_precede_fraction_and_gcd_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = 1 << 4096
    with pytest.raises(PAdicValidationError, match="portable integer bound"):
        ProjectiveRationalPoint(oversized, oversized - 1)

    point = ProjectiveRationalPoint.finite(0)
    object.__setattr__(point, "numerator", oversized)

    def forbidden_gcd(*_args: object) -> int:
        raise AssertionError("gcd ran before the projective-coordinate bound")

    monkeypatch.setattr(padic_covers, "gcd", forbidden_gcd)
    with pytest.raises(PAdicVerificationError, match="portable integer bound"):
        point.verify()


def test_rational_scalar_bounds_precede_factor_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cover = _beta_cover()
    oversized_scalar = Fraction(1 << 4096)
    with pytest.raises(PAdicValidationError, match="portable rational bound"):
        BranchFiberWitness(
            BranchValue.ZERO,
            oversized_scalar,
            cover.zero_fiber.factors,
        )
    with pytest.raises(PAdicValidationError, match="portable rational bound"):
        DerivativeWitness(
            cover.derivative_witness.derivative,
            oversized_scalar,
            cover.derivative_witness.factors,
        )

    branch = cover.zero_fiber
    derivative = cover.derivative_witness
    object.__setattr__(branch, "scalar", oversized_scalar)
    object.__setattr__(derivative, "scalar", oversized_scalar)

    def forbidden_factor_replay(_factor: FiberFactor) -> bool:
        raise AssertionError("factor replay ran before the rational bound")

    monkeypatch.setattr(FiberFactor, "verify", forbidden_factor_replay)
    with pytest.raises(PAdicVerificationError, match="portable rational bound"):
        branch.verify()
    with pytest.raises(PAdicVerificationError, match="portable rational bound"):
        derivative.verify()


def test_geometry_sequence_bounds_precede_nested_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cover = _beta_cover()
    factor = cover.zero_fiber.factors[0]
    with pytest.raises(PAdicValidationError, match="factor count"):
        BranchFiberWitness(BranchValue.ZERO, 1, (factor,) * 65)

    altered_fiber = cover.zero_fiber
    object.__setattr__(altered_fiber, "factors", (factor,) * 65)

    def forbidden_factor_replay(_factor: FiberFactor) -> bool:
        raise AssertionError("factor replay ran before the collection bound")

    monkeypatch.setattr(FiberFactor, "verify", forbidden_factor_replay)
    with pytest.raises(PAdicVerificationError, match="factor tuple"):
        altered_fiber.verify()

    monkeypatch.undo()
    cover = _beta_cover()

    def forbidden_polynomial_scan(_polynomial: ExactPolynomial) -> object:
        raise AssertionError("polynomial scan ran before the fiber-count bound")

    monkeypatch.setattr(padic_covers, "_univariate_rational", forbidden_polynomial_scan)
    with pytest.raises(PAdicValidationError, match="exactly three"):
        ThreePointCover(
            cover.polynomial,
            (*cover.fibers, cover.zero_fiber),
            cover.derivative_witness,
        )

    with pytest.raises(PAdicValidationError, match="exactly three profiles"):
        RiemannHurwitzWitness(3, ((3,), (3,), (3,), (3,)))
    with pytest.raises(PAdicValidationError, match="profile cardinality"):
        RiemannHurwitzWitness(64, ((1,) * 65, (64,), (64,)))


def test_derivative_schema_enforces_degree_and_factor_cardinality_bounds() -> None:
    cover = _beta_cover()
    zero = FiberFactor(ProjectiveRationalPoint.finite(0), 1)

    with pytest.raises(PAdicValidationError, match="factor count"):
        DerivativeWitness(cover.polynomial.derivative(0), 1, (zero,) * 64)

    degree_64 = ExactPolynomial(
        1,
        (((64,), 1),),
        variable_names=("z",),
    )
    with pytest.raises(PAdicValidationError, match="derivative degree"):
        DerivativeWitness(degree_64, 1, (zero,))

    witness = cover.derivative_witness
    object.__setattr__(witness, "factors", witness.factors * 33)
    with pytest.raises(PAdicVerificationError, match="factor tuple"):
        witness.verify()


def test_reduced_branch_schema_enforces_total_degree_before_factor_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    high_degree_factors = tuple(
        ReducedFiberFactor(ReducedProjectivePoint(5, residue), 64, 1) for residue in range(5)
    )
    with pytest.raises(PAdicValidationError, match="branch degree"):
        ReducedBranchFiber(BranchValue.ZERO, 5, 1, high_degree_factors)

    linear = ReducedFiberFactor(ReducedProjectivePoint(5, 0), 1, 1)
    with pytest.raises(PAdicValidationError, match="factor count"):
        ReducedBranchFiber(BranchValue.ZERO, 5, 1, (linear,) * 65)

    witness = GoodReductionWitness(_beta_cover(), 5)
    reduced_fiber = witness.reduced_fibers[0]
    object.__setattr__(reduced_fiber, "factors", high_degree_factors)

    def forbidden_factor_replay(_factor: ReducedFiberFactor) -> bool:
        raise AssertionError("factor replay ran before the total-degree bound")

    monkeypatch.setattr(ReducedFiberFactor, "verify", forbidden_factor_replay)
    with pytest.raises(PAdicVerificationError, match="branch degree"):
        reduced_fiber.verify()


def test_cover_receipt_decoders_bound_raw_collections_before_nested_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cover = _beta_cover()

    def forbidden_nested_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("nested replay ran before the collection bound")

    raw_cover = cast(dict[str, object], deepcopy(cover.to_schema_document()))
    raw_fibers = cast(list[object], raw_cover["fibers"])
    raw_fibers.append(deepcopy(raw_fibers[0]))
    monkeypatch.setattr(padic_reduction, "_decode_branch_fiber", forbidden_nested_decode)
    with pytest.raises(PAdicVerificationError, match="exactly three"):
        padic_reduction._decode_cover(raw_cover, "cover", document=True)

    monkeypatch.undo()
    raw_branch = cast(dict[str, object], deepcopy(cover.zero_fiber.to_canonical_data()))
    raw_branch_factors = cast(list[object], raw_branch["factors"])
    raw_branch_factors.extend(deepcopy(raw_branch_factors[0]) for _ in range(63))
    monkeypatch.setattr(padic_reduction, "_decode_fiber_factor", forbidden_nested_decode)
    with pytest.raises(PAdicVerificationError, match="factor count"):
        padic_reduction._decode_branch_fiber(raw_branch, "branch")

    raw_derivative = cast(
        dict[str, object],
        deepcopy(cover.derivative_witness.to_canonical_data()),
    )
    raw_derivative_factors = cast(list[object], raw_derivative["factors"])
    raw_derivative_factors.extend(deepcopy(raw_derivative_factors[0]) for _ in range(62))
    with pytest.raises(PAdicVerificationError, match="factor count"):
        padic_reduction._decode_derivative_witness(raw_derivative, "derivative")


def test_cover_replay_rejects_altered_degree_fibers_and_riemann_hurwitz() -> None:
    cover = _beta_cover()
    object.__setattr__(cover, "degree", 4)
    with pytest.raises(PAdicVerificationError, match="generic cover degree"):
        cover.verify()

    cover = _beta_cover()
    object.__setattr__(cover, "fibers", tuple(reversed(cover.fibers)))
    with pytest.raises(PAdicVerificationError, match="order"):
        cover.verify()

    cover = _beta_cover()
    object.__setattr__(cover.riemann_hurwitz_witness, "ramification_sum", 3)
    with pytest.raises(PAdicVerificationError, match="equality"):
        cover.verify()


def test_beta_has_complete_tame_good_reduction_at_five() -> None:
    cover = _beta_cover()
    result = good_reduction(cover, 5)

    assert isinstance(result, Certified)
    assert isinstance(result.value, GoodReduction)
    assert id(result.value.witness) != id(result.value)
    assert result.value.verify()
    assert result.verify()
    assert result.receipt.kind == "good-reduction"
    assert result.receipt.verifier == "padic.three-point-exact.v1"
    assert result.receipt.verify()[-3:] == (
        "exact-normalized-three-point-cover",
        "degree-preserving-special-fiber",
        "tame-separated-marked-ramification",
    )
    witness = result.value.witness
    assert witness.reduced_polynomial == (0, 0, 3, 2)
    assert witness.reduced_derivative == (0, 1, 1)
    assert tuple(point.residue for point in witness.ramification_points) == (0, 4, None)
    assert tuple(
        tuple(factor.point.residue for factor in fiber.factors) for fiber in witness.reduced_fibers
    ) == ((0, 1), (3, 4), (None,))
    assert len(witness.marked_source_points) == 5
    assert witness.degree_preserved is True
    assert witness.tame is True


def test_other_prime_is_outside_the_exact_0_5_geometry_slice() -> None:
    result = good_reduction(_beta_cover(), 7)

    assert isinstance(result, Unsupported)
    assert result.reason_code == "outside-beta-p5-certified-slice"
    assert result.verify()


def test_good_reduction_leads_to_one_component_semistable_and_stable_models() -> None:
    cover = _beta_cover()
    good = good_reduction(cover, 5)
    assert isinstance(good, Certified)

    semistable = semistable_reduction(good)
    assert isinstance(semistable, Certified)
    assert isinstance(semistable.value, SemistableReduction)
    assert semistable.value.verify()
    assert semistable.receipt.kind == "semistable-reduction"
    assert len(semistable.value.source_components) == 1
    assert len(semistable.value.target_components) == 1
    assert semistable.value.nodes == ()
    source_component = semistable.value.source_components[0]
    target_component = semistable.value.target_components[0]
    assert source_component.genus == target_component.genus == 0
    assert len(source_component.markings) == 5
    assert len(target_component.markings) == 3
    assert source_component.stability_index == 3
    assert target_component.stability_index == 1
    assert semistable.verify()

    stable = stable_reduction(semistable)
    assert isinstance(stable, Certified)
    assert isinstance(stable.value, StableReduction)
    assert stable.value.verify()
    assert stable.receipt.kind == "stable-reduction"
    assert stable.value.witness.source_stability_indices == (3,)
    assert stable.value.witness.target_stability_indices == (1,)
    assert stable.value.witness.contracted_components == ()
    assert stable.verify()
    stable_claim = stable.claim()
    assert "stable-reduction" in stable_claim.what.text
    assert not hasattr(stable.value, "lift_set")
    assert not hasattr(stable.value, "fixed_lifts")
    assert not hasattr(stable.value, "descended_global_model")

    direct_semistable = semistable_reduction(cover, 5)
    direct_stable = stable_reduction(cover, 5)
    assert isinstance(direct_semistable, Certified)
    assert isinstance(direct_stable, Certified)
    assert direct_semistable.value == semistable.value
    assert direct_stable.value == stable.value


@pytest.mark.parametrize("prime", [2, 3, 7])
def test_out_of_slice_prime_is_not_promoted_to_a_reduction_claim(prime: int) -> None:
    cover = _beta_cover()

    good = good_reduction(cover, prime)
    assert isinstance(good, Unsupported)
    assert good.reason_code == "outside-beta-p5-certified-slice"
    assert good.verify()

    semistable = semistable_reduction(cover, prime)
    stable = stable_reduction(cover, prime)
    assert isinstance(semistable, Unsupported)
    assert isinstance(stable, Unsupported)
    assert semistable.reason_code == "outside-beta-p5-certified-slice"
    assert stable.reason_code == "outside-beta-p5-certified-slice"
    assert semistable.verify()
    assert stable.verify()


def test_reduction_operations_reject_malformed_and_foreign_requests() -> None:
    cover = _beta_cover()
    with pytest.raises(TypeError, match="integer"):
        good_reduction(cover, True)
    composite = good_reduction(cover, 15)
    assert isinstance(composite, Unsupported)
    assert composite.reason_code == "outside-beta-p5-certified-slice"
    with pytest.raises(TypeError, match="prime is required"):
        semistable_reduction(cover)
    with pytest.raises(TypeError, match="prime is required"):
        stable_reduction(cover)

    witness_for_other_label = GoodReductionWitness(_beta_cover(label="other-beta"), 5)
    with pytest.raises(PAdicValidationError, match="foreign"):
        good_reduction(cover, 5, witness=witness_for_other_label)

    good = good_reduction(cover, 5)
    assert isinstance(good, Certified)
    with pytest.raises(TypeError, match="wrong result type"):
        stable_reduction(cast(Any, good))


def test_large_prime_is_a_typed_software_boundary() -> None:
    result = good_reduction(_beta_cover(), 1_000_033)

    assert isinstance(result, Unsupported)
    assert result.reason_code == "outside-beta-p5-certified-slice"
    assert result.verify()


def test_oversized_odd_characteristic_is_rejected_without_primality_work() -> None:
    oversized_odd = (1 << 4095) + 1
    result = good_reduction(_beta_cover(), oversized_odd)

    assert isinstance(result, Unsupported)
    assert result.requested["prime"] == oversized_odd
    assert result.verify()


def test_coordinate_equivalent_near_miss_is_not_silently_certified() -> None:
    cover = _reflected_beta_cover()
    assert cover.verify()

    good = good_reduction(cover, 5)
    semistable = semistable_reduction(cover, 5)
    stable = stable_reduction(cover, 5)
    assert isinstance(good, Unsupported)
    assert isinstance(semistable, Unsupported)
    assert isinstance(stable, Unsupported)
    assert all(
        result.reason_code == "outside-beta-p5-certified-slice"
        for result in (good, semistable, stable)
    )
    with pytest.raises(PAdicValidationError, match="certifies only beta"):
        GoodReductionWitness(cover, 5)


def test_reduction_witness_and_receipt_tampering_fail_closed() -> None:
    cover = _beta_cover()
    witness = GoodReductionWitness(cover, 5)
    object.__setattr__(witness, "reduced_polynomial", (0, 0, 3, 1))
    with pytest.raises(PAdicVerificationError, match="polynomial"):
        witness.verify()

    semistable = SemistableReduction(
        cover,
        5,
        SemistableReductionWitness(GoodReduction(cover, 5, GoodReductionWitness(cover, 5))),
    )
    stable_witness = StableReductionWitness(semistable)
    object.__setattr__(stable_witness, "source_stability_indices", (1,))
    with pytest.raises(PAdicVerificationError, match="inequalities"):
        stable_witness.verify()

    certified = good_reduction(cover, 5)
    assert isinstance(certified, Certified)
    payload = deepcopy(certified.receipt.payload.to_dict())
    result = cast(dict[str, object], payload["result"])
    transported_witness = cast(dict[str, object], result["witness"])
    transported_witness["reduced_polynomial"] = [0, 0, 3, 1]
    altered = PAdicReceipt.create(
        "good-reduction",
        "certified",
        payload,
        proof_context=certified.proof_context,
    )
    with pytest.raises(PAdicVerificationError, match="replay data"):
        altered.verify()

    semistable_result = semistable_reduction(certified)
    assert isinstance(semistable_result, Certified)
    payload = deepcopy(semistable_result.receipt.payload.to_dict())
    result = cast(dict[str, object], payload["result"])
    transported_witness = cast(dict[str, object], result["witness"])
    transported_witness["complete"] = False
    altered = PAdicReceipt.create(
        "semistable-reduction",
        "certified",
        payload,
        proof_context=semistable_result.proof_context,
    )
    with pytest.raises(PAdicVerificationError, match="semistable"):
        altered.verify()

    stable_result = stable_reduction(semistable_result)
    assert isinstance(stable_result, Certified)
    payload = deepcopy(stable_result.receipt.payload.to_dict())
    result = cast(dict[str, object], payload["result"])
    transported_witness = cast(dict[str, object], result["witness"])
    transported_witness["source_stability_indices"] = [1]
    altered = PAdicReceipt.create(
        "stable-reduction",
        "certified",
        payload,
        proof_context=stable_result.proof_context,
    )
    with pytest.raises(PAdicVerificationError, match="stable"):
        altered.verify()


def test_explicit_semistable_and_stable_witnesses_bind_their_requests() -> None:
    cover = _beta_cover()
    good = GoodReduction(cover, 5, GoodReductionWitness(cover, 5))
    semistable_witness = SemistableReductionWitness(good)
    semistable = semistable_reduction(cover, 5, witness=semistable_witness)
    assert isinstance(semistable, Certified)

    stable_witness = StableReductionWitness(semistable.value)
    stable = stable_reduction(cover, 5, witness=stable_witness)
    assert isinstance(stable, Certified)
    assert stable.value.witness == stable_witness
