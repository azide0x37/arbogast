"""Separate internal Wewers identities from geometric extraction."""

from __future__ import annotations

import sys
from pathlib import Path

from arbogast.cert import verify_certificate
from arbogast.padic import (
    Certified,
    DeformationDatum,
    DeformationSignature,
    RationalDifferential,
    SpecialityWitness,
    Unknown,
    certified_result,
    deformation_datum,
    good_reduction,
    semistable_reduction,
    stable_reduction,
)

# Reuse the exact cover constructor without duplicating its proof witness.
SIBLING = Path(__file__).resolve().parents[1] / "three_point_good_reduction"
sys.path.insert(0, str(SIBLING))
from run import exact_cover  # noqa: E402


def internal_datum() -> DeformationDatum:
    differential = RationalDifferential(5, (0, 4, 1))  # u=x(x-1)
    signature = DeformationSignature((("zero", 2, 1), ("one", 2, 1), ("infinity", 1, 0)))
    speciality = SpecialityWitness(signature)
    return DeformationDatum(
        differential,
        signature,
        speciality,
        tame_order=2,
        character_exponent=1,
        label="internal-demo",
    )


def main() -> int:
    internal = certified_result(internal_datum(), "deformation-datum")
    assert isinstance(internal, Certified)
    assert internal.value.completeness_scope == "componentwise-rank-one-tame-formal-identities"
    assert (
        internal.value.component_relation_scope
        == "componentwise-formal-identities-no-divisor-or-point-binding"
    )
    assert not internal.value.differential_signature_relation_claimed
    assert internal.verify()
    assert verify_certificate(internal.certificate).valid
    assert internal.claim().status.value == "exact"
    assert internal.claim_graph().verify().verified

    good = good_reduction(exact_cover(), 5)
    assert isinstance(good, Certified)
    semistable = semistable_reduction(good)
    assert isinstance(semistable, Certified)
    stable = stable_reduction(semistable)
    assert isinstance(stable, Certified)

    geometric = deformation_datum(stable)
    assert isinstance(geometric, Unknown)
    assert geometric.reason_code == "missing-deformation-datum-witness"
    assert geometric.verify()
    assert geometric.claim().status.value == "unknown"
    assert geometric.claim_graph().verify().verified

    print("internal datum:", type(internal).__name__, internal.value.completeness_scope)
    print("character values:", internal.value.character_values)
    print("geometric extraction:", type(geometric).__name__, geometric.reason_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
