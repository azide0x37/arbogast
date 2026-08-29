from __future__ import annotations

import arbogast.hurwitz as hurwitz
from arbogast.rep import Permutation, PermutationGroup


def test_certificate_first_small_hurwitz_workflow() -> None:
    a = Permutation.from_cycles(3, ((0, 1),))
    b = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((a, b), degree=3)
    transpositions = group.conjugacy_class(a)

    plan = hurwitz.plan_nielsen_class(
        group,
        (transpositions,) * 4,
        shards=4,
    )
    nielsen = plan.reduce(plan.run_all())
    assert nielsen.verify()

    action = hurwitz.braid_action(nielsen, mode="pure")
    component = action.components().one()
    assert component.verify()
    assert len(hurwitz.totally_real(nielsen)) == 1
    assert hurwitz.source_genus(nielsen[0]) == 0

    cusp_data = hurwitz.cusps(component, action.generators[0].name)
    boundary_data = hurwitz.boundary(component, (0, 1))
    assert cusp_data.verify()
    assert boundary_data.verify()
    assert sum(cusp_data.widths) == component.cardinality
    assert boundary_data.total_incidences == component.cardinality
