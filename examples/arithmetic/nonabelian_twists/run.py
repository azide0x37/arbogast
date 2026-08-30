"""Exhaust H^1(C2, S3) for the trivial action as a finite pointed set."""

from __future__ import annotations

from arbogast.galois import TwistClassSet, nonabelian_h1, twist_classes
from arbogast.rep import CyclicGroup, symmetric_group


def main() -> int:
    acting_group = CyclicGroup(2)
    coefficient_group = symmetric_group(3)

    result = nonabelian_h1(acting_group, coefficient_group, "trivial")
    assert isinstance(result, TwistClassSet)
    assert result.verify()
    assert result.cardinality == 2
    assert len(result.cocycles) == 4
    assert result.basepoint.is_basepoint
    assert len(result.basepoint.members) == 1

    nontrivial = result.classes[1]
    image = nontrivial.representative(acting_group.generator)
    assert not image.is_identity
    assert image.order == 2
    assert len(nontrivial.members) == 3
    assert result.claim_graph().verify().verified

    # The descent terminology is an exact alias, not a vector-space wrapper.
    replay = twist_classes(acting_group, coefficient_group, "trivial")
    assert isinstance(replay, TwistClassSet)
    assert replay.receipt == result.receipt
    assert not hasattr(result, "dimension")

    print(f"cocycles: {len(result.cocycles)}")
    print(f"pointed twist classes: {result.cardinality}")
    print("class 0: identity")
    print("class 1: transpositions")
    print("twisted models constructed: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
