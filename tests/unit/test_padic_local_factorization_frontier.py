"""Finite local-fragment replay and M23 frontier-boundary tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

import arbogast.padic.covers as padic_covers
from arbogast.claims import EpistemicStatus
from arbogast.hurwitz import load_m23_exact_dataset
from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.covers import (
    FiniteFieldFactor,
    LocalFactorizationFragment,
    local_factorization_fragment,
)
from arbogast.padic.errors import PAdicValidationError, PAdicVerificationError
from arbogast.padic.frontier import reduction_frontier
from arbogast.padic.results import Certified, Partial, Unsupported

PROJECT_ROOT = Path(__file__).resolve().parents[2]
M23_MANIFEST = (
    PROJECT_ROOT / "examples" / "hurwitz" / "m23_real_component" / "expected" / "manifest.json"
)


def _beta_zero_fragment() -> Certified[LocalFactorizationFragment]:
    return local_factorization_fragment(
        "illustrative.beta-zero-fiber.mod23",
        23,
        (0, 0, 1, 22),
        22,
        (
            FiniteFieldFactor(23, (0, 1), 2),
            FiniteFieldFactor(23, (22, 1), 1),
        ),
    )


def test_complete_fragment_replays_only_the_displayed_mod_23_polynomial() -> None:
    certified = _beta_zero_fragment()

    assert isinstance(certified, Certified)
    fragment = certified.value
    assert fragment.verify()
    assert fragment.polynomial == (0, 0, 1, 22)
    assert fragment.unit == 22
    assert fragment.factor_degrees == (1, 1)
    assert fragment.ramification_indices == (2, 1)
    assert fragment.factorization_complete is True
    assert fragment.scope == (
        "displayed-mod-p-polynomial-only; no local model/stable reduction/lift/descent claim"
    )
    assert certified.receipt.kind == "local-factorization-fragment"
    assert certified.verify()
    assert certified.receipt.verify()[-3:] == (
        "complete-displayed-polynomial-product",
        "monic-irreducible-distinct-factors",
        "strict-local-fragment-scope",
    )
    claim_parameters = certified.claim().what.parameters.to_dict()
    assert LocalFactorizationFragment.SCOPE in repr(claim_parameters["payload"])
    assert "no local model/stable reduction/lift/descent claim" in fragment.scope
    assert not hasattr(fragment, "stable_reduction")
    assert not hasattr(fragment, "lift_set")
    assert not hasattr(fragment, "descended_global_model")


def test_finite_field_factor_checks_irreducibility_not_just_roots_or_degree() -> None:
    irreducible_quadratic = FiniteFieldFactor(3, (1, 0, 1))
    assert irreducible_quadratic.degree == 2
    assert irreducible_quadratic.verify()

    with pytest.raises(PAdicValidationError, match="reducible"):
        FiniteFieldFactor(23, (22, 0, 1))
    with pytest.raises(PAdicValidationError, match="monic"):
        FiniteFieldFactor(23, (0, 2))


def test_finite_field_factor_degree_bound_precedes_irreducibility_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    degree_33_irreducible_over_f2 = (
        1,
        0,
        0,
        0,
        1,
        0,
        1,
        1,
        0,
        1,
        0,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        1,
        1,
        0,
        1,
        0,
        1,
        0,
        1,
    )
    factor = FiniteFieldFactor(2, (0, 1))
    raw = factor.to_schema_document()
    raw["coefficients"] = list(degree_33_irreducible_over_f2)
    raw["degree"] = 33
    object.__setattr__(factor, "coefficients", degree_33_irreducible_over_f2)

    def forbidden_irreducibility_work(*_args: object) -> bool:
        raise AssertionError("irreducibility replay ran before the degree bound")

    monkeypatch.setattr(
        padic_covers,
        "_is_irreducible_monic",
        forbidden_irreducibility_work,
    )
    with pytest.raises(PAdicValidationError, match="degree exceeds"):
        FiniteFieldFactor(2, degree_33_irreducible_over_f2)
    with pytest.raises(PAdicVerificationError, match="degree exceeds"):
        factor.verify()
    with pytest.raises(PAdicVerificationError, match="degree exceeds"):
        FiniteFieldFactor.from_dict(raw)


def test_fragment_rejects_incomplete_product_duplicates_and_scope_tampering() -> None:
    factors = (
        FiniteFieldFactor(23, (0, 1), 2),
        FiniteFieldFactor(23, (22, 1), 1),
    )
    with pytest.raises(PAdicValidationError, match="does not equal"):
        LocalFactorizationFragment(
            "illustrative.beta-zero-fiber.mod23",
            23,
            (0, 0, 1, 21),
            22,
            factors,
        )
    with pytest.raises(PAdicValidationError, match="duplicate"):
        LocalFactorizationFragment(
            "duplicate.factor.test",
            23,
            (0, 0, 1),
            1,
            (FiniteFieldFactor(23, (0, 1)), FiniteFieldFactor(23, (0, 1))),
        )

    fragment = _beta_zero_fragment().value
    object.__setattr__(fragment, "scope", "local-model-proved")
    with pytest.raises(PAdicVerificationError, match="scope"):
        fragment.verify()


def test_fragment_resource_bounds_fail_before_large_primality_or_factor_work() -> None:
    huge_odd = (1 << 4095) + 1
    with pytest.raises(PAdicValidationError, match="prime exceeds"):
        FiniteFieldFactor(huge_odd, (0, 1))

    factors = tuple(FiniteFieldFactor(23, (index, 1)) for index in range(17))
    with pytest.raises(PAdicValidationError, match="factor count"):
        LocalFactorizationFragment("too.many.factors", 23, (0, 1), 1, factors)


def test_fragment_receipt_rejects_polynomial_and_oversized_factor_list_tampering() -> None:
    certified = _beta_zero_fragment()
    payload = deepcopy(certified.receipt.payload.to_dict())
    result = cast(dict[str, object], payload["result"])
    result["polynomial"] = [0, 0, 1, 21]
    altered = PAdicReceipt.create(
        "local-factorization-fragment",
        "certified",
        payload,
        proof_context=certified.proof_context,
    )
    with pytest.raises(PAdicVerificationError, match="factorization"):
        altered.verify()

    payload = deepcopy(certified.receipt.payload.to_dict())
    result = cast(dict[str, object], payload["result"])
    raw_factors = cast(list[object], result["factors"])
    raw_factors.extend(deepcopy(raw_factors[0]) for _ in range(16))
    oversized = PAdicReceipt.create(
        "local-factorization-fragment",
        "certified",
        payload,
        proof_context=certified.proof_context,
    )
    with pytest.raises(PAdicVerificationError, match="too many factors"):
        oversized.verify()


def test_certified_fragment_yields_partial_with_explicit_terminal_obligations() -> None:
    fragment = _beta_zero_fragment()
    result = reduction_frontier(fragment, prime=23)

    assert isinstance(result, Partial)
    assert result.operation == "padic.reduction_frontier"
    assert result.fragments == (fragment,)
    assert len(result.obligations) == 4
    assert {item.required_witness_kind for item in result.obligations} == {
        "ThreePointCoverAndSpecialFiberBinding",
        "SemistableReductionWitness",
        "FixedLiftSetWitness",
        "EffectiveDescentWitness",
    }
    assert result.proof_context.completeness.value == "candidate"
    assert result.claim().status is EpistemicStatus.UNKNOWN
    assert "full requested result remains unknown" in result.claim().what.text
    assert "effective descent remain unproved" in repr(result.claim().what.parameters.to_dict())
    assert result.verify()
    assert not hasattr(result, "stable_reduction")
    assert not hasattr(result, "descended_model")


def test_frontier_rejects_foreign_prime_and_wrong_certified_value() -> None:
    fragment = _beta_zero_fragment()
    with pytest.raises(PAdicValidationError, match="disagrees"):
        reduction_frontier(fragment, prime=5)


def test_public_m23_four_point_dataset_is_unsupported_not_partial() -> None:
    dataset = load_m23_exact_dataset(M23_MANIFEST)
    result = reduction_frontier(dataset, prime=23)

    assert isinstance(result, Unsupported)
    assert result.reason_code == "m23-four-point-equations-and-local-model-missing"
    assert "four-point" in result.reason
    assert "not pinned three-point equations" in result.reason
    assert result.claim().status is EpistemicStatus.EXACT
    assert result.verify()
