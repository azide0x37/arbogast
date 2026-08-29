"""Compute and independently verify H^1 for a split C5-action over GF(11)."""

from __future__ import annotations

from arbogast.cohom import h1
from arbogast.linalg import DenseMatrix, FiniteField
from arbogast.rep import CyclicGroup, Representation


def main() -> int:
    group = CyclicGroup(5)
    field = FiniteField(11)
    generator_action = DenseMatrix(
        field,
        (
            (1, 0, 0),
            (0, 3, 0),
            (0, 0, 4),
        ),
    )
    module = Representation.from_generators(
        group,
        field,
        (generator_action,),
        name="weights 1, 3, and 4",
    )

    weights = module.weight_spaces()
    if not weights.verify():
        raise RuntimeError("weight-space projectors failed exact verification")

    result = h1(group, module)
    report = result.verify()
    claim_report = result.claim().verify()
    if not report.ok or not claim_report.verified:
        raise RuntimeError("H1 certificate verification failed")

    weight_summary = ", ".join(
        f"{weight}: dimension {subspace.dimension}" for weight, subspace in sorted(weights.items())
    )
    print(f"group: C5 (order {group.order})")
    print(f"field: GF({field.order})")
    print(f"module weights: {weight_summary}")
    print(f"dim Z^1: {result.cocycles.dimension}")
    print(f"dim B^1: {result.coboundaries.dimension}")
    print(f"dim H^1: {result.dimension}")
    print(f"H^1 representative cocycles: {tuple(item.values for item in result.representatives)}")
    print(f"certificate: sha256:{result.certificate.content_hash}")
    print(f"certificate checks: {', '.join(report.checks)}")

    if result.cocycles.dimension != 2:
        raise RuntimeError("unexpected cocycle dimension")
    if result.coboundaries.dimension != 2 or result.dimension != 0:
        raise RuntimeError("expected exact vanishing H^1(C5, M) over GF(11)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
