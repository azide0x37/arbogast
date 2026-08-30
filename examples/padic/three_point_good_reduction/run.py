"""Certify the bounded tame good-reduction lane for one exact cover."""

from __future__ import annotations

from fractions import Fraction

from arbogast.cert import verify_certificate
from arbogast.numeric import ExactPolynomial
from arbogast.padic import (
    BranchFiberWitness,
    Certified,
    DerivativeWitness,
    FiberFactor,
    ProjectiveRationalPoint,
    ThreePointCover,
    Unsupported,
    good_reduction,
    semistable_reduction,
    stable_reduction,
)


def factor(value: int | Fraction, multiplicity: int) -> FiberFactor:
    return FiberFactor(ProjectiveRationalPoint.finite(value), multiplicity)


def exact_cover() -> ThreePointCover:
    beta = ExactPolynomial(
        1,
        {(2,): Fraction(27, 4), (3,): Fraction(-27, 4)},
        variable_names=("z",),
    )
    fibers = (
        BranchFiberWitness("zero", Fraction(-27, 4), (factor(0, 2), factor(1, 1))),
        BranchFiberWitness(
            "one",
            Fraction(-1, 4),
            (factor(Fraction(2, 3), 2), factor(Fraction(-1, 3), 1)),
        ),
        BranchFiberWitness(
            "infinity",
            1,
            (FiberFactor(ProjectiveRationalPoint.infinity(), 3),),
        ),
    )
    derivative = DerivativeWitness(
        beta.derivative(0),
        Fraction(-27, 4),
        (factor(0, 1), factor(Fraction(2, 3), 1)),
    )
    return ThreePointCover(beta, fibers, derivative, label="beta")


def main() -> int:
    cover = exact_cover()
    assert tuple(fiber.profile for fiber in cover.fibers) == ((2, 1), (2, 1), (3,))

    good = good_reduction(cover, 5)
    assert isinstance(good, Certified)
    assert good.value.reduced_polynomial == (0, 0, 3, 2)
    assert tuple(
        "infinity" if point.is_infinity else point.residue
        for point in good.value.ramification_points
    ) == (0, 4, "infinity")

    semistable = semistable_reduction(good)
    assert isinstance(semistable, Certified)
    assert len(semistable.value.source_components) == 1
    assert len(semistable.value.target_components) == 1
    assert semistable.value.nodes == ()

    stable = stable_reduction(semistable)
    assert isinstance(stable, Certified)
    assert stable.value.witness.source_stability_indices == (3,)
    assert stable.value.witness.target_stability_indices == (1,)

    for result in (good, semistable, stable):
        assert result.verify()
        assert verify_certificate(result.certificate).valid
        assert result.claim().status.value == "exact"
        assert result.claim_graph().verify().verified

    outside_good_lane = good_reduction(cover, 2)
    assert isinstance(outside_good_lane, Unsupported)
    assert outside_good_lane.reason_code == "outside-beta-p5-certified-slice"
    assert outside_good_lane.verify()

    outside_semistable_lane = semistable_reduction(cover, prime=2)
    assert isinstance(outside_semistable_lane, Unsupported)
    assert outside_semistable_lane.reason_code == "outside-beta-p5-certified-slice"
    assert outside_semistable_lane.verify()

    print("p=5 reduction:", type(good).__name__, good.value.reduced_polynomial)
    print(
        "p=5 stable model:",
        len(stable.value.source_components),
        "source component,",
        len(stable.value.nodes),
        "nodes",
    )
    print(
        "p=2 good-reduction request:",
        type(outside_good_lane).__name__,
        outside_good_lane.reason_code,
    )
    print(
        "p=2 semistable request:",
        type(outside_semistable_lane).__name__,
        outside_semistable_lane.reason_code,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
