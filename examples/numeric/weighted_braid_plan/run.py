"""Exact weighted braid planning with an explicit numerical non-conclusion."""

from __future__ import annotations

from arbogast.cert import verify_certificate
from arbogast.hurwitz import BraidAction, braid_action, nielsen_class
from arbogast.numeric import (
    ComplexBall,
    ExactPolynomial,
    NumericPoint,
    NumericUnknown,
    ParameterPath,
    PolynomialFamily,
    WeightedBraidPlan,
    continue_path,
    weighted_braid_plan,
)
from arbogast.rep import Permutation, PermutationGroup


def _exact_action() -> BraidAction:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    return braid_action(nielsen_class(group, (transpositions,) * 4))


def main() -> None:
    action = _exact_action()
    costs = {
        ("sigma_0", False): 10,
        ("sigma_0", True): 10,
        ("sigma_1", False): 1,
        ("sigma_1", True): 5,
        ("sigma_2", False): 10,
        ("sigma_2", True): 10,
    }
    plan = weighted_braid_plan(action, 0, 3, costs)
    assert isinstance(plan, WeightedBraidPlan)
    assert len(plan.steps) == 2
    assert plan.total_cost.fraction == 2
    assert action.step_index(0, "sigma_1", inverse=True) == 3
    assert action.apply(0, plan.word) == action.nielsen_class[3]
    assert plan.verify()
    assert verify_certificate(plan.certificate).valid
    graph = plan.claim_graph()
    assert graph.verify().verified

    # The exact finite-action result does not authorize a numerical continuation
    # without a tube witness.  The typed outcome stays UNKNOWN.
    family = PolynomialFamily(
        1,
        (
            ExactPolynomial(
                2,
                {
                    (0, 1): -1,
                    (1, 0): 1,
                },
                variable_names=("x", "t"),
            ),
        ),
    )
    start = NumericPoint(family.fiber(0), (ComplexBall(0, 1),))
    numerical = continue_path(family, start, ParameterPath((0, 1)))
    assert isinstance(numerical, NumericUnknown)
    assert numerical.claim_graph().verify().verified

    print(f"unweighted direct edges: {1}")
    print(f"weighted exact edges: {len(plan.steps)}")
    print(f"weighted exact cost: {plan.total_cost.fraction}")
    print(f"exact replay target: {plan.target}")
    print(f"numerical continuation: {type(numerical).__name__}")
    print(f"verified claim nodes: {len(graph.claims)}")
    print(f"weighted-plan certificate: {plan.certificate.certificate_id}")


if __name__ == "__main__":
    main()
