"""Certify Q({2, infinity}, 2) and a one-dimensional Selmer group."""

from __future__ import annotations

from arbogast.arithmetic import SelmerGroup, local_condition, selmer
from arbogast.galois import (
    FinitePlace,
    InfinitePlace,
    KummerSpace,
    LocalH1Space,
    LocalizationMap,
    NumberField,
    kummer_space,
    local_h1,
    localize,
)


def main() -> int:
    rationals = NumberField.rationals()
    place_2 = FinitePlace(rationals, 2, ((2,),), 1, 1)
    place_real = InfinitePlace(
        rationals,
        "real",
        (-1, 1),
        embedding_index=0,
    )

    global_space = kummer_space(rationals, (place_2, place_real))
    assert isinstance(global_space, KummerSpace)
    assert global_space.dimension == 2
    assert tuple(item.coefficients[0] for item in global_space.generators) == (-1, 2)
    assert global_space.verify()

    h1_2 = local_h1(place_2)
    h1_real = local_h1(place_real)
    assert isinstance(h1_2, LocalH1Space)
    assert isinstance(h1_real, LocalH1Space)
    assert (h1_2.dimension, h1_real.dimension) == (3, 1)

    localization_2 = localize(global_space, h1_2)
    localization_real = localize(global_space, h1_real)
    assert isinstance(localization_2, LocalizationMap)
    assert isinstance(localization_real, LocalizationMap)
    assert localization_2.matrix.rows == ((1, 0), (0, 1), (0, 0))
    assert localization_real.matrix.rows == ((1, 0),)
    assert localization_2.verify()
    assert localization_real.verify()

    # Impose no condition at 2 and the zero condition at the real place. The
    # only remaining global class is [2].
    condition_2 = local_condition(
        h1_2,
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    )
    condition_real = local_condition(h1_real)
    localizations = {place_2: localization_2, place_real: localization_real}
    conditions = {place_2: condition_2, place_real: condition_real}
    result = selmer(
        global_space,
        localizations,
        conditions,
        places=global_space.places,
        place_set_complete=True,
    )

    assert isinstance(result, SelmerGroup)
    assert result.dimension == 1
    assert result.basis == ((0, 1),)
    assert result.basis_classes[0].representative == rationals(2)
    assert result.verify().valid
    assert result.claim_graph().verify().verified

    print("K({2, infinity}, 2) basis: [-1], [2]")
    print(f"Q_2 localization rows: {localization_2.matrix.rows}")
    print(f"real localization rows: {localization_real.matrix.rows}")
    print(f"Selmer dimension: {result.dimension}")
    print("Selmer basis: [2]")
    print("completeness: COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
