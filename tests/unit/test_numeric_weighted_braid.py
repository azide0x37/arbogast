from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

import pytest

import arbogast.numeric as numeric
from arbogast.claims import EpistemicStatus
from arbogast.hurwitz import BraidAction, braid_action, nielsen_class
from arbogast.numeric import (
    NumericError,
    NumericReceipt,
    NumericVerificationError,
    UnsupportedNumeric,
    WeightedBraidPlan,
    weighted_braid_plan,
)
from arbogast.numeric import braid as numeric_braid
from arbogast.numeric.semantic import receipt_for_result
from arbogast.rep import Permutation, PermutationGroup


@lru_cache(maxsize=1)
def _action() -> BraidAction:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    return braid_action(nielsen_class(group, (transpositions,) * 4))


def _directed_costs() -> dict[tuple[str, bool], int]:
    return {
        ("sigma_0", False): 10,
        ("sigma_0", True): 10,
        ("sigma_1", False): 1,
        ("sigma_1", True): 5,
        ("sigma_2", False): 10,
        ("sigma_2", True): 10,
    }


def test_weighted_plan_carries_exact_global_optimality_witness() -> None:
    action = _action()
    plan = weighted_braid_plan(action, 0, 3, _directed_costs())
    assert isinstance(plan, WeightedBraidPlan)
    assert len(plan.steps) == 2
    assert plan.total_cost.fraction == 2
    assert plan.verify()
    assert plan.claim().status is EpistemicStatus.EXACT
    assert plan.claim().verify().verified

    payload = deepcopy(receipt_for_result(plan).payload.to_dict())
    payload["total_cost"]["mantissa"] = 3
    tampered = NumericReceipt.create(
        "weighted-braid-plan",
        payload,
        dependencies=receipt_for_result(plan).dependencies,
    )
    with pytest.raises(NumericVerificationError, match=r"cost|altered"):
        tampered.verify()


@pytest.mark.parametrize(
    "costs",
    (
        {"sigma_0": 1, "sigma_1": 1},
        {"sigma_0": 1, "sigma_1": 1, "sigma_2": 1, "foreign": 1},
        {
            "sigma_0": 1,
            "sigma_1": 1,
            "sigma_2": 1,
            ("sigma_0", False): 1,
        },
        {"sigma_0": 1, "sigma_1": -1, "sigma_2": 1},
    ),
)
def test_cost_maps_reject_missing_foreign_mixed_and_negative_keys(
    costs: dict[object, int],
) -> None:
    with pytest.raises(NumericError):
        weighted_braid_plan(_action(), 0, 3, costs)  # type: ignore[arg-type]


def test_cost_maps_reject_floats_and_resource_caps_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError):
        weighted_braid_plan(
            _action(),
            0,
            3,
            {"sigma_0": 1, "sigma_1": 1.0, "sigma_2": 1},  # type: ignore[dict-item]
        )

    monkeypatch.setattr(numeric_braid, "MAX_GRAPH_VERTICES", 1)
    capped = weighted_braid_plan(
        _action(),
        0,
        3,
        {"sigma_0": 1, "sigma_1": 1, "sigma_2": 1},
    )
    assert isinstance(capped, UnsupportedNumeric)
    assert capped.claim().status is EpistemicStatus.UNKNOWN


def test_weighted_step_is_nested_and_not_a_public_result() -> None:
    assert not hasattr(numeric, "WeightedBraidStep")
