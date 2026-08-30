"""Exact boundary and tamper tests for the bounded Wewers/lift/descent lane."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from arbogast import deform
from arbogast.galois import (
    Completeness,
    FiniteGaloisQuotient,
    NumberField,
    ProofContext,
    finite_galois_quotient_certificate,
)
from arbogast.numeric import ExactPolynomial
from arbogast.padic import (
    AutomorphismTrivialityWitness,
    BranchFiberWitness,
    BranchValue,
    Certified,
    DeformationDatum,
    DeformationDatumWitness,
    DeformationSignature,
    DerivativeWitness,
    DescendedModel,
    DescentCocycle,
    DescentIsomorphism,
    FiberFactor,
    FiniteLiftAction,
    FixedLift,
    LiftCandidate,
    LiftChart,
    LiftEnumerationWitness,
    LiftGaloisAction,
    LiftSet,
    LiftTransportWitness,
    PAdicReceipt,
    ProjectiveRationalPoint,
    RationalDifferential,
    RigidDescentWitness,
    RigidFixedLift,
    SpecialityWitness,
    ThreePointCover,
    Unknown,
    Unsupported,
    deformation_datum,
    effective_descent,
    fixed_lifts,
    lift_galois_action,
    lift_set,
    stable_reduction,
)
from arbogast.padic.errors import (
    PAdicResourceError,
    PAdicValidationError,
    PAdicVerificationError,
)
from arbogast.padic.results import certified_result
from arbogast.rep import CyclicGroup, Permutation, PermutationGroup


def _internal_datum(*, tame_order: int = 1) -> DeformationDatum:
    differential = RationalDifferential(5, (0, 4, 1))
    signature = DeformationSignature((("zero", 1, 0), ("one", 1, 0), ("infinity", 1, 0)))
    speciality = SpecialityWitness(signature)
    return DeformationDatum(
        differential,
        signature,
        speciality,
        tame_order=tame_order,
        character_exponent=0 if tame_order == 1 else 1,
        label="synthetic-f5",
    )


def _lift_result(*, constant_model: bool = False) -> Certified[LiftSet]:
    datum = _internal_datum()
    models = ((2,),) if constant_model else ((0, 1), (1,))
    labels = ("a",) if constant_model else ("a", "unit")
    chart = LiftChart(
        datum,
        (4, 0, 1),
        models,
        coordinate_labels=labels,
        label="u-square-equals-one",
    )
    witness = LiftEnumerationWitness(
        chart,
        (LiftCandidate(chart, 1), LiftCandidate(chart, 4)),
    )
    datum_result = certified_result(datum, "deformation-datum")
    result = lift_set(datum_result, chart=chart, witness=witness)
    assert isinstance(result, Certified)
    return result


def _trivial_quotient() -> FiniteGaloisQuotient:
    field = NumberField.rationals()
    group = PermutationGroup.trivial(1)
    presentation = {
        "arithmetic_action": "trivial",
        "method": "portable-trivial-quotient-v1",
    }
    certificate = finite_galois_quotient_certificate(
        field,
        group,
        label="bounded-trivial-quotient",
        presentation=presentation,
    )
    return FiniteGaloisQuotient(
        field,
        group,
        label="bounded-trivial-quotient",
        presentation=presentation,
        proof_context=ProofContext(completeness=Completeness.COMPLETE),
        quotient_certificate=certificate,
    )


def _arithmetic_action() -> Certified[LiftGaloisAction]:
    lifts = _lift_result()
    quotient = _trivial_quotient()
    witness = LiftTransportWitness(
        lifts.value,
        quotient.identity,
        Permutation.identity(lifts.value.size),
        model_coordinate_permutations=tuple(
            Permutation.identity(len(lifts.value.chart.coordinate_labels))
            for _ in lifts.value.representatives
        ),
    )
    result = lift_galois_action(
        lifts,
        quotient,
        witnesses=(witness,),
    )
    assert isinstance(result, Certified)
    assert isinstance(result.value, LiftGaloisAction)
    return result


def _beta_cover() -> ThreePointCover:
    polynomial = ExactPolynomial(
        1,
        (((2,), Fraction(27, 4)), ((3,), Fraction(-27, 4))),
        variable_names=("z",),
    )
    zero = ProjectiveRationalPoint.finite(0)
    one = ProjectiveRationalPoint.finite(1)
    two_thirds = ProjectiveRationalPoint.finite(Fraction(2, 3))
    minus_one_third = ProjectiveRationalPoint.finite(Fraction(-1, 3))
    infinity = ProjectiveRationalPoint.infinity()
    fibers = (
        BranchFiberWitness(
            BranchValue.ZERO,
            Fraction(-27, 4),
            (FiberFactor(zero, 2), FiberFactor(one, 1)),
        ),
        BranchFiberWitness(
            BranchValue.ONE,
            Fraction(-1, 4),
            (FiberFactor(two_thirds, 2), FiberFactor(minus_one_third, 1)),
        ),
        BranchFiberWitness(
            BranchValue.INFINITY,
            1,
            (FiberFactor(infinity, 3),),
        ),
    )
    derivative = DerivativeWitness(
        polynomial.derivative(0),
        Fraction(-27, 4),
        (FiberFactor(zero, 1), FiberFactor(two_thirds, 1)),
    )
    return ThreePointCover(polynomial, fibers, derivative, label="beta")


def test_synthetic_datum_states_its_nonrelation_and_tampering_fails() -> None:
    datum = _internal_datum(tame_order=2)

    assert datum.verify()
    assert datum.origin_scope == "internal-identities-only"
    assert datum.differential_signature_relation_claimed is False
    assert "no-divisor-or-point-binding" in datum.component_relation_scope
    assert datum.character_values == (1, 4)

    altered_origin = _internal_datum(tame_order=2)
    object.__setattr__(altered_origin, "origin_scope", "stable-reduction")
    with pytest.raises(PAdicVerificationError, match=r"internal-identities-only|altered"):
        altered_origin.verify()

    altered_relation = _internal_datum(tame_order=2)
    object.__setattr__(altered_relation, "differential_signature_relation_claimed", True)
    with pytest.raises(PAdicVerificationError, match="altered"):
        altered_relation.verify()

    altered_character = _internal_datum(tame_order=2)
    object.__setattr__(altered_character, "character_values", (1, 1))
    with pytest.raises(PAdicVerificationError, match="altered"):
        altered_character.verify()


def test_datum_prime_cap_precedes_expensive_primality_replay() -> None:
    with pytest.raises(PAdicResourceError, match="primality-replay"):
        RationalDifferential((1 << 127) + 1, (0, 1))


def test_lift_chart_coordinate_bound_precedes_polynomial_evaluation() -> None:
    from arbogast.padic import lifts as padic_lifts

    datum = _internal_datum()
    too_many_coordinates = tuple((0,) for _ in range(65))

    with pytest.raises(PAdicResourceError, match="model-coordinate"):
        LiftChart(
            datum,
            (4, 0, 1),
            too_many_coordinates,
        )

    valid = LiftChart(datum, (4, 0, 1), ((0, 1),)).to_schema_document()
    valid["model_coordinate_polynomials"] = [[0] * 66]
    with pytest.raises(PAdicResourceError, match="bounded degree"):
        padic_lifts._chart_from_schema(valid)


def test_stable_reduction_cannot_supply_missing_wewers_origin_data() -> None:
    stable = stable_reduction(_beta_cover(), 5)
    assert isinstance(stable, Certified)

    absent = deformation_datum(stable)
    assert isinstance(absent, Unknown)
    assert absent.reason_code == "missing-deformation-datum-witness"
    assert absent.verify()

    witness = DeformationDatumWitness(
        _internal_datum(),
        stable.value.content_id,
        stable.value.source_components[0].to_schema_document(),
        {"declared_action": "not-present-in-stable-model"},
        {"declared_divisor_data": "not-derived-from-stable-model"},
        differential_extraction_rule="not-present-in-stable-model",
    )
    refused = deformation_datum(stable, witness=witness)
    assert isinstance(refused, Unsupported)
    assert refused.reason_code == "stable-profile-lacks-wewers-extraction"
    assert refused.verify()


def test_lift_completeness_is_exactly_one_chart_and_dedup_is_literal() -> None:
    lifts = _lift_result()
    assert lifts.verify()
    assert lifts.receipt.kind == "lift-set"
    assert lifts.value.completeness_scope == "pinned-chart"
    assert lifts.value.size == 2
    assert lifts.value.class_indices in {(0, 1), (1, 0)}

    deduplicated = _lift_result(constant_model=True)
    assert deduplicated.value.size == 1
    assert deduplicated.value.class_indices == (0, 0)

    chart = lifts.value.chart
    with pytest.raises(PAdicValidationError, match="exhaust"):
        LiftEnumerationWitness(chart, (LiftCandidate(chart, 1),))

    missing = lift_set(_internal_datum())
    assert isinstance(missing, Unknown)
    assert missing.reason_code == "missing-pinned-chart-exhaustion"


def test_finite_set_action_is_not_arithmetic_and_fixed_is_not_descent() -> None:
    lifts = _lift_result()
    group = CyclicGroup(2)
    identity, nonidentity = group.elements
    if not identity.is_identity:
        identity, nonidentity = nonidentity, identity
    action = FiniteLiftAction(
        lifts.value,
        group,
        (
            LiftTransportWitness(
                lifts.value,
                identity,
                Permutation.identity(2),
            ),
            LiftTransportWitness(
                lifts.value,
                nonidentity,
                Permutation((1, 0)),
            ),
        ),
    )
    assert action.verify()
    assert action.arithmetic_galois_action is False

    fixed = fixed_lifts(action)
    assert fixed.verify()
    assert fixed.value.fixed == ()
    assert fixed.value.descent_claimed is False
    assert FixedLift.__module__ != deform.FixedLift.__module__

    candidate_quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="candidate-c2-only",
    )
    unknown = lift_galois_action(
        lifts,
        candidate_quotient,
        witnesses=action.witnesses,
    )
    assert isinstance(unknown, Unknown)
    assert unknown.reason_code == "incomplete-arithmetic-quotient"

    forged_complete = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="forged-complete-c2",
    )
    object.__setattr__(
        forged_complete,
        "proof_context",
        ProofContext(completeness=Completeness.COMPLETE),
    )
    object.__setattr__(
        forged_complete,
        "quotient_certificate",
        _trivial_quotient().proving_certificate,
    )
    unsupported = lift_galois_action(
        lifts,
        forged_complete,
        witnesses=action.witnesses,
    )
    assert isinstance(unsupported, Unsupported)
    assert unsupported.reason_code == "nontrivial-quotient-outside-pinned-model-action"

    trivial_quotient = _trivial_quotient()
    declared_only = LiftTransportWitness(
        lifts.value,
        trivial_quotient.identity,
        Permutation.identity(lifts.value.size),
        transport_labels=("declared.0", "declared.1"),
    )
    unproved = lift_galois_action(
        lifts,
        trivial_quotient,
        witnesses=(declared_only,),
    )
    assert isinstance(unproved, Unknown)
    assert unproved.reason_code == "unverified-arithmetic-model-transport"

    fixed_trivial_finite = fixed_lifts(
        FiniteLiftAction(
            lifts.value,
            group,
            (
                LiftTransportWitness(
                    lifts.value,
                    identity,
                    Permutation.identity(lifts.value.size),
                ),
                LiftTransportWitness(
                    lifts.value,
                    nonidentity,
                    Permutation.identity(lifts.value.size),
                ),
            ),
        )
    )
    forged_fixed = fixed_trivial_finite.value.fixed[0]
    coordinate_identity = Permutation.identity(len(forged_fixed.candidate.model_coefficients))
    forged_rigid = RigidFixedLift(
        forged_fixed,
        AutomorphismTrivialityWitness(forged_fixed, (coordinate_identity,)),
    )
    forged_iso = DescentIsomorphism(
        forged_rigid,
        identity,
        coordinate_identity,
        coordinate_identity,
    )
    with pytest.raises(TypeError, match="arithmetic"):
        DescentCocycle(
            cast(LiftGaloisAction, fixed_trivial_finite.value.action),
            forged_rigid,
            (forged_iso,),
        )


def test_arithmetic_model_transport_and_scope_tampering_fail_closed() -> None:
    action = _arithmetic_action()

    assert action.value.coefficient_action_rule == ("trivial-on-prime-field-F_p-coefficients-v1")
    assert action.value.characteristic_zero_lift_action_claimed is False
    assert action.value.geometric_lift_action_claimed is False
    transport = action.value.witnesses[0]
    assert transport.model_transport_verified is True
    assert transport.arithmetic_compatible is True
    assert len(transport.model_coordinate_permutations) == action.value.lifts.size

    object.__setattr__(transport, "model_coordinate_permutations", ())
    with pytest.raises(PAdicVerificationError, match="one coordinate map"):
        transport.verify()

    altered_action = _arithmetic_action().value
    object.__setattr__(altered_action, "coefficient_action_rule", "declared-only")
    with pytest.raises(PAdicVerificationError, match="boundary"):
        altered_action.verify()


def test_rigid_effective_descent_requires_every_separate_witness() -> None:
    action = _arithmetic_action()
    assert action.verify()
    fixed = fixed_lifts(action)
    assert fixed.verify()
    assert len(fixed.value.fixed) == 2

    no_witness = effective_descent(fixed)
    assert isinstance(no_witness, Unknown)
    assert no_witness.reason_code == "missing-rigid-descent-witness"

    chosen = fixed.value.fixed[0]
    coordinate_identity = Permutation.identity(len(chosen.candidate.model_coefficients))
    triviality = AutomorphismTrivialityWitness(chosen, (coordinate_identity,))
    rigid = RigidFixedLift(chosen, triviality)
    assert isinstance(fixed.value.action, LiftGaloisAction)
    quotient_identity = fixed.value.action.group.identity
    isomorphism = DescentIsomorphism(
        rigid,
        quotient_identity,
        coordinate_identity,
        coordinate_identity,
    )
    cocycle = DescentCocycle(fixed.value.action, rigid, (isomorphism,))
    witness = RigidDescentWitness(
        fixed.value,
        rigid,
        cocycle,
        chosen.candidate.model_coefficients,
        coordinate_identity,
        coordinate_identity,
    )
    result = effective_descent(fixed, witness=witness)

    assert isinstance(result, Certified)
    assert isinstance(result.value, DescendedModel)
    assert result.value.automorphisms_trivial is True
    assert result.value.cocycle_verified is True
    assert result.value.two_sided_base_change_verified is True
    assert result.value.model_field_scope == "prime-field-F_p-chart-coefficients"
    assert result.value.characteristic_zero_descent_claimed is False
    assert result.value.number_field_descent_claimed is False
    assert result.value.geometric_cover_descent_claimed is False
    assert result.value.coefficients == chosen.candidate.model_coefficients
    assert result.verify()
    assert PAdicReceipt.from_dict(result.receipt.to_dict()).verify()

    bad_triviality = AutomorphismTrivialityWitness(chosen, (coordinate_identity,))
    object.__setattr__(bad_triviality, "automorphisms", (Permutation((1, 0)),))
    with pytest.raises(PAdicVerificationError, match="identity only"):
        bad_triviality.verify()

    bad_isomorphism = DescentIsomorphism(
        rigid,
        quotient_identity,
        coordinate_identity,
        coordinate_identity,
    )
    object.__setattr__(bad_isomorphism, "forward", Permutation((1, 0)))
    with pytest.raises(PAdicVerificationError, match=r"two-sided|labels"):
        bad_isomorphism.verify()

    bad_cocycle = DescentCocycle(fixed.value.action, rigid, (isomorphism,))
    object.__setattr__(bad_cocycle, "cocycle_convention", "reversed")
    with pytest.raises(PAdicVerificationError, match="altered"):
        bad_cocycle.verify()

    bad_base_change = RigidDescentWitness(
        fixed.value,
        rigid,
        cocycle,
        chosen.candidate.model_coefficients,
        coordinate_identity,
        coordinate_identity,
    )
    object.__setattr__(bad_base_change, "base_change_inverse", Permutation((1, 0)))
    with pytest.raises(PAdicVerificationError, match="two-sided"):
        bad_base_change.verify()

    altered_receipt_payload = deepcopy(result.receipt.payload.to_dict())
    altered_result = altered_receipt_payload["result"]
    assert isinstance(altered_result, dict)
    altered_result["two_sided_base_change_verified"] = False
    tampered_receipt = PAdicReceipt.create(
        "descended-model",
        "certified",
        altered_receipt_payload,
        proof_context=result.receipt.proof_context,
        evidence=result.receipt.evidence,
    )
    with pytest.raises(PAdicVerificationError, match="transport"):
        tampered_receipt.verify()


def test_all_new_success_receipts_certificates_and_claims_replay_fresh(
    tmp_path: Path,
) -> None:
    datum_result = certified_result(_internal_datum(), "deformation-datum")
    lifts = _lift_result()
    action = _arithmetic_action()
    fixed = fixed_lifts(action)
    chosen = fixed.value.fixed[0]
    coordinate_identity = Permutation.identity(len(chosen.candidate.model_coefficients))
    rigid = RigidFixedLift(
        chosen,
        AutomorphismTrivialityWitness(chosen, (coordinate_identity,)),
    )
    assert isinstance(fixed.value.action, LiftGaloisAction)
    isomorphism = DescentIsomorphism(
        rigid,
        fixed.value.action.group.identity,
        coordinate_identity,
        coordinate_identity,
    )
    cocycle = DescentCocycle(fixed.value.action, rigid, (isomorphism,))
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

    results = (datum_result, lifts, action, fixed, descended)
    bundle = {
        "receipts": [item.receipt.to_dict() for item in results],
        "certificates": [item.certificate.to_dict() for item in results],
        "claims": [item.claim().to_dict() for item in results],
    }
    program = """
import json
import sys

from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import Claim
from arbogast.padic import PAdicReceipt

bundle = json.load(sys.stdin)
for raw in bundle["receipts"]:
    assert PAdicReceipt.from_dict(raw).verify()
for raw in bundle["certificates"]:
    assert verify_certificate(VerificationCertificate.from_dict(raw)).valid
for raw in bundle["claims"]:
    assert Claim.from_dict(raw).verify().verified
"""
    environment = os.environ.copy()
    source = Path(__file__).resolve().parents[2] / "src"
    environment["PYTHONPATH"] = str(source)
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(bundle),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr


def test_hostile_lift_group_replay_is_bounded_before_general_group_closure(
    tmp_path: Path,
) -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    program = """
import sys
sys.path.insert(0, sys.argv[1])

from arbogast.padic import lifts as padic_lifts
from arbogast.padic.errors import PAdicVerificationError

degree = 10
cycle = [*range(1, degree), 0]
transposition = [1, 0, *range(2, degree)]
hostile = {
    "degree": degree,
    "elements": [cycle, transposition],
    "fingerprint": "foreign",
    "order": 2,
    "type": "arbogast.finite_permutation_group",
}
try:
    padic_lifts._group_from_schema(hostile, "hostile lift group")
except PAdicVerificationError as error:
    assert "not closed" in str(error)
else:
    raise AssertionError("hostile generators reached an unbounded group closure")
print("bounded-lift-group-replay-ok")
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", program, str(source)),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == "bounded-lift-group-replay-ok"
