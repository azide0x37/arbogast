"""Replay exact witnesses in the pinned field Q[t]/(t^2 - t - 1)."""

from __future__ import annotations

import argparse
from fractions import Fraction

from arbogast.backends.pari import PariBackend
from arbogast.cohom import corestriction_map, h1, restriction_map
from arbogast.galois import FieldEmbedding, NumberField
from arbogast.linalg import PrimeField
from arbogast.rep import CyclicGroup, FiniteGroupMap, Representation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-pari",
        action="store_true",
        help="also discover and fresh-replay the relative norm with supported PARI/GP",
    )
    return parser.parse_args()


def _cyclic_exponent(group: CyclicGroup, element: object) -> int:
    return next(exponent for exponent in range(group.order) if group.generator**exponent == element)


def replay_restriction_corestriction() -> tuple[str, str]:
    """Replay the degree-one restriction/transfer pair for C2 inside C4."""

    subgroup = CyclicGroup(2)
    group = CyclicGroup(4)
    inclusion = FiniteGroupMap(
        subgroup,
        group,
        lambda element: group.generator ** (2 * _cyclic_exponent(subgroup, element)),
        require_injective=True,
    )
    module = Representation.trivial(group, PrimeField(2))
    restricted = restriction_map(h1(group, module), subgroup, inclusion)
    transferred = corestriction_map(restricted.target, group, module, inclusion)
    assert restricted.matrix == ((0,),)
    assert transferred.matrix == ((1,),)
    assert restricted.verify() and transferred.verify()
    assert restricted.claim_graph().verify().verified
    assert transferred.claim_graph().verify().verified
    return (
        restricted.verification_certificate().certificate_id,
        transferred.verification_certificate().certificate_id,
    )


def main() -> int:
    args = parse_args()
    # Coefficients are in ascending order: -1 - t + t^2.
    field = NumberField((-1, -1, 1), generator_name="t")
    t = field.generator
    conjugation = FieldEmbedding(field, field, 1 - t)

    norm_witness = t * conjugation(t)
    square_root = 2 * t - 1
    square_witness = square_root**2

    assert field.verify()
    assert t.verify()
    assert conjugation.verify()
    assert conjugation(conjugation(t)) == t
    assert t.norm() == Fraction(-1)
    assert norm_witness == field(-1)
    assert square_witness == field(5)
    restriction_certificate, corestriction_certificate = replay_restriction_corestriction()

    if args.with_pari:
        discovered = PariBackend().relative_norm(field, t)
        assert discovered.payload.to_dict()["norm"] == [-1, 1]
        assert discovered.verify().valid
        print("PARI relative norm discovery: -1 (fresh pinned replay verified)")

    print("field: Q[t]/(t^2 - t - 1), presentation pinned")
    print(f"field id: {field.field_id}")
    print(f"conjugate of t: {conjugation(t).coefficients}")
    print(f"Norm(t): {t.norm()}")
    print(f"(2t - 1)^2: {square_witness.coefficients[0]}")
    print(f"restriction certificate: {restriction_certificate}")
    print(f"corestriction certificate: {corestriction_certificate}")
    print("portable replay: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
