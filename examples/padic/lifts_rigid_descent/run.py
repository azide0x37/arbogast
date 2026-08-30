"""Certify a finite lift set and its exact arithmetic fixed subset."""

from __future__ import annotations

from arbogast.cert import verify_certificate
from arbogast.galois import (
    Completeness,
    FiniteGaloisQuotient,
    NumberField,
    ProofContext,
    finite_galois_quotient_certificate,
)
from arbogast.padic import (
    AutomorphismTrivialityWitness,
    Certified,
    DeformationDatum,
    DeformationSignature,
    DescentCocycle,
    DescentIsomorphism,
    LiftCandidate,
    LiftChart,
    LiftEnumerationWitness,
    LiftTransportWitness,
    RationalDifferential,
    RigidDescentWitness,
    RigidFixedLift,
    SpecialityWitness,
    Unknown,
    certified_result,
    effective_descent,
    fixed_lifts,
    lift_galois_action,
    lift_set,
)
from arbogast.rep import Permutation, PermutationGroup


def internal_datum() -> Certified[DeformationDatum]:
    differential = RationalDifferential(5, (0, 4, 1))
    signature = DeformationSignature((("zero", 2, 1), ("one", 2, 1), ("infinity", 1, 0)))
    datum = DeformationDatum(
        differential,
        signature,
        SpecialityWitness(signature),
        tame_order=2,
        character_exponent=1,
        label="lift-demo",
    )
    return certified_result(datum, "deformation-datum")


def complete_trivial_quotient() -> FiniteGaloisQuotient:
    field = NumberField.rationals()
    group = PermutationGroup.trivial(1)
    label = "trivial-lift-quotient"
    presentation = {
        "arithmetic_action": "trivial",
        "method": "portable-trivial-quotient-v1",
    }
    proving = finite_galois_quotient_certificate(
        field,
        group,
        label=label,
        presentation=presentation,
    )
    return FiniteGaloisQuotient(
        field,
        group,
        label=label,
        presentation=presentation,
        proof_context=ProofContext(completeness=Completeness.COMPLETE),
        quotient_certificate=proving,
    )


def main() -> int:
    datum = internal_datum()

    missing_chart = lift_set(datum)
    assert isinstance(missing_chart, Unknown)
    assert missing_chart.reason_code == "missing-pinned-chart-exhaustion"
    assert missing_chart.verify()

    chart = LiftChart(
        datum.value,
        (4, 0, 1),  # T^2-1
        ((0, 1), (1, 1)),
        coordinate_labels=("a", "b"),
        label="two-root-chart",
    )
    witness = LiftEnumerationWitness(
        chart,
        tuple(LiftCandidate(chart, root) for root in chart.roots()),
    )
    lifts = lift_set(datum, chart=chart, witness=witness)
    assert isinstance(lifts, Certified)
    assert lifts.value.size == 2
    assert tuple(candidate.parameter for candidate in lifts.value.candidates) == (1, 4)

    quotient = complete_trivial_quotient()
    set_identity = Permutation.identity(lifts.value.size)
    incomplete_transports = (
        LiftTransportWitness(
            lifts.value,
            quotient.group.identity,
            set_identity,
        ),
    )
    unverified_action = lift_galois_action(
        lifts,
        quotient,
        witnesses=incomplete_transports,
    )
    assert isinstance(unverified_action, Unknown)
    assert unverified_action.reason_code == "unverified-arithmetic-model-transport"
    assert unverified_action.verify()

    coordinate_identity = Permutation.identity(len(chart.coordinate_labels))
    transports = (
        LiftTransportWitness(
            lifts.value,
            quotient.group.identity,
            set_identity,
            model_coordinate_permutations=(coordinate_identity,) * lifts.value.size,
        ),
    )
    action = lift_galois_action(lifts, quotient, witnesses=transports)
    assert isinstance(action, Certified)
    assert action.value.arithmetic_galois_action

    fixed = fixed_lifts(action)
    assert isinstance(fixed, Certified)
    assert len(fixed.value.fixed) == 2
    assert not fixed.value.descent_claimed

    missing_descent = effective_descent(fixed)
    assert isinstance(missing_descent, Unknown)
    assert missing_descent.reason_code == "missing-rigid-descent-witness"
    assert missing_descent.verify()

    chosen = fixed.value.fixed[0]
    triviality = AutomorphismTrivialityWitness(chosen, (coordinate_identity,))
    rigid = RigidFixedLift(chosen, triviality)
    descent_isomorphism = DescentIsomorphism(
        rigid,
        fixed.value.action.group.identity,
        coordinate_identity,
        coordinate_identity,
    )
    cocycle = DescentCocycle(fixed.value.action, rigid, (descent_isomorphism,))
    descent_witness = RigidDescentWitness(
        fixed.value,
        rigid,
        cocycle,
        chosen.candidate.model_coefficients,
        coordinate_identity,
        coordinate_identity,
    )
    descended = effective_descent(fixed, witness=descent_witness)
    assert isinstance(descended, Certified)
    assert descended.value.coefficients == chosen.candidate.model_coefficients
    assert descended.value.automorphisms_trivial
    assert descended.value.cocycle_verified
    assert descended.value.two_sided_base_change_verified
    assert descended.value.model_field_scope == "prime-field-F_p-chart-coefficients"
    assert (
        descended.value.descent_scope
        == "effective-descent-in-pinned-F_p-labeled-chart-model-category"
    )
    assert not descended.value.characteristic_zero_descent_claimed
    assert not descended.value.number_field_descent_claimed
    assert not descended.value.geometric_cover_descent_claimed

    for result in (lifts, action, fixed, descended):
        assert result.verify()
        assert verify_certificate(result.certificate).valid
        assert result.claim().status.value == "exact"
        assert result.claim_graph().verify().verified

    print("missing chart:", type(missing_chart).__name__, missing_chart.reason_code)
    print("chart-complete lifts:", lifts.value.size)
    print("without exact model transports:", type(unverified_action).__name__)
    print("arithmetic fixed classes:", len(fixed.value.fixed))
    print("descent claimed by fixed_lifts:", fixed.value.descent_claimed)
    print("without descent witness:", type(missing_descent).__name__)
    print("witnessed rigid descent:", type(descended).__name__, descended.value.coefficients)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
