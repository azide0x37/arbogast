from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from arbogast.cert import CertificateError, VerificationCertificate, verify_certificate
from arbogast.claims import Claim, ClaimGraph, EpistemicStatus
from arbogast.numeric import (
    AlgebraicCandidate,
    ComplexBall,
    ComplexDyadic,
    ConditionBound,
    ContinuationResult,
    ContinuationStep,
    ContinuationTube,
    DegreeResult,
    Dyadic,
    ExactCover,
    ExactificationResult,
    ExactPolynomial,
    GenericDegreeWitness,
    NumericError,
    NumericPoint,
    NumericReceipt,
    NumericUnknown,
    NumericVerificationError,
    ParameterPath,
    PolynomialFamily,
    PolynomialSystem,
    RealBall,
    RecognitionBounds,
    RegularFiberDegree,
    RegularFiberWitness,
    UnsupportedNumeric,
    _schema,
    condition_number,
    continue_path,
    exactify,
    projection_degree,
    recognize,
)
from arbogast.numeric.semantic import claim_for_receipt, receipt_for_result


def _linear_continuation() -> tuple[
    PolynomialFamily,
    ParameterPath,
    NumericPoint,
    ContinuationTube,
]:
    polynomial = ExactPolynomial(
        2,
        {(1, 0): 1, (0, 1): -1},
        variable_names=("x", "t"),
    )
    family = PolynomialFamily(1, (polynomial,))
    path = ParameterPath((0, Fraction(1, 2)))
    start = NumericPoint(
        family.fiber(0),
        (ComplexBall(0, Fraction(3, 4)),),
    )
    step = ContinuationStep(
        family,
        0,
        Fraction(1, 2),
        (ComplexBall(Fraction(1, 4), Fraction(1, 2)),),
        ((1,),),
    )
    return family, path, start, ContinuationTube(family, path, start, (step,))


def _sqrt_two_point() -> tuple[NumericPoint, AlgebraicCandidate]:
    enclosure = ComplexBall(Dyadic(181, -7), Dyadic(1, -10))
    recognized = recognize(enclosure, RecognitionBounds(2, 2))
    assert isinstance(recognized, AlgebraicCandidate)
    system = PolynomialSystem(
        1,
        (ExactPolynomial(1, {(2,): 1, (0,): -2}, variable_names=("x",)),),
    )
    return NumericPoint(system, (enclosure,)), recognized


def test_exact_dyadics_and_runtime_text_bounds() -> None:
    assert Dyadic(2, -1) == Dyadic.one()
    assert Dyadic(1 << 20_000, -20_000) == Dyadic.one()
    assert Dyadic.coerce(Fraction(3, 8)).fraction == Fraction(3, 8)
    assert ComplexDyadic(Fraction(1, 2), Fraction(-1, 4)).norm_squared() == Dyadic(5, -4)
    with pytest.raises(TypeError):
        Dyadic.coerce(0.5)  # type: ignore[arg-type]
    with pytest.raises(NumericError, match="not dyadic"):
        Dyadic.coerce(Fraction(1, 3))
    with pytest.raises(NumericError, match="raw dyadic exponent"):
        Dyadic(1, 1_000_001)
    with pytest.raises(ValueError, match="text-length"):
        ExactPolynomial(1, {(1,): 1}, variable_names=("x" * 16_385,))


def test_composite_runtime_budget_matches_receipt_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polynomial = ExactPolynomial(
        2,
        {(0, 2): 1, (1, 1): 1, (2, 0): 1},
    )
    assert _schema.ensure_canonical_bounds(polynomial.to_canonical_data()) == 49
    system = PolynomialSystem(2, (polynomial, polynomial))
    monkeypatch.setattr(_schema, "MAX_CANONICAL_NODES", 100)
    assert polynomial.verify()
    with pytest.raises(NumericVerificationError, match="node bound"):
        system.verify()

    unknown = NumericUnknown("op", "reason", requested={"items": list(range(8))})
    monkeypatch.setattr(_schema, "MAX_CANONICAL_NODES", 10)
    with pytest.raises(NumericVerificationError, match="node bound"):
        unknown.verify()


def test_composite_runtime_replay_rejects_mutated_nested_presentations() -> None:
    vertex = ComplexDyadic(1)
    path = ParameterPath((vertex, 2))
    object.__setattr__(vertex.real, "mantissa", 2)
    object.__setattr__(vertex.real, "exponent", -1)
    with pytest.raises(NumericVerificationError, match="canonical"):
        path.verify()

    polynomial = ExactPolynomial(2, {(1, 0): 1, (0, 1): -1})
    family = PolynomialFamily(1, (polynomial,))
    coefficient = polynomial.terms[0][1]
    object.__setattr__(coefficient.real, "mantissa", 2)
    object.__setattr__(coefficient.real, "exponent", -1)
    with pytest.raises(NumericVerificationError, match="canonical"):
        family.verify()

    cover_family = PolynomialFamily(
        1,
        (ExactPolynomial(2, {(2, 0): 1, (0, 1): -1}),),
    )
    cover = ExactCover(cover_family, 2, (0,))
    object.__setattr__(cover.branch_points[0].real, "exponent", 1)
    with pytest.raises(NumericVerificationError, match="canonical"):
        cover.verify()


def test_linear_continuation_replays_nonstationary_segment() -> None:
    family, path, start, tube = _linear_continuation()
    step = tube.steps[0]
    assert step.residual_bound == Dyadic(1, -2)
    assert step.contraction_bound == Dyadic.zero()

    missing = continue_path(family, start, path)
    assert isinstance(missing, NumericUnknown)
    assert missing.claim().status is EpistemicStatus.UNKNOWN

    result = continue_path(family, start, path, tube=tube)
    assert isinstance(result, ContinuationResult)
    assert result.verify()
    assert result.endpoint.coordinates[0].contains(Fraction(1, 2))
    assert result.claim().status is EpistemicStatus.NUMERICAL
    assert result.claim().verify().verified
    assert result.claim_graph().verify().verified


def test_continuation_receipt_rejects_readdressed_bound_tamper() -> None:
    family, path, start, tube = _linear_continuation()
    result = continue_path(family, start, path, tube=tube)
    assert isinstance(result, ContinuationResult)
    receipt = receipt_for_result(result)
    payload = receipt.payload.to_dict()
    residual = payload["tube"]["steps"][0]["residual_bound"]
    residual["mantissa"] = 3
    tampered = NumericReceipt.create(receipt.kind, payload)
    with pytest.raises(NumericVerificationError, match=r"canonical snapshot|altered"):
        tampered.verify()


def test_condition_number_is_a_proof_bearing_real_ball() -> None:
    polynomial = ExactPolynomial(1, {(1,): 1, (0,): -1}, variable_names=("x",))
    system = PolynomialSystem(1, (polynomial,))
    point = NumericPoint(system, (ComplexBall(1, Fraction(1, 8)),))
    missing = condition_number(system, point)
    assert isinstance(missing, NumericUnknown)

    bound = condition_number(system, point, inverse_jacobian=((1,),))
    assert isinstance(bound, ConditionBound)
    assert isinstance(bound, RealBall)
    assert bound.center == Dyadic.one() and bound.radius == Dyadic.zero()
    assert bound.claim().status is EpistemicStatus.NUMERICAL
    with pytest.raises(NumericError, match="not an exact inverse"):
        condition_number(system, point, inverse_jacobian=((2,),))


def test_bounded_recognition_and_exactification_keep_distinct_statuses() -> None:
    point, candidate = _sqrt_two_point()
    assert candidate.minimal_polynomial == (-2, 0, 1)
    assert candidate.claim().status is EpistemicStatus.NUMERICAL

    result = exactify(point, candidate=candidate)
    assert isinstance(result, ExactificationResult)
    assert result.verify()
    assert result.claim().status is EpistemicStatus.EXACT
    assert result.claim().verify().verified

    unsupported = recognize(point.coordinates[0], RecognitionBounds(3, 2))
    assert isinstance(unsupported, UnsupportedNumeric)
    ambiguous = recognize(RealBall(0, 2), RecognitionBounds(1, 2))
    assert isinstance(ambiguous, NumericUnknown)


def test_recognition_respects_closed_and_zero_radius_balls() -> None:
    one = recognize(RealBall(1, 0), RecognitionBounds(1, 1))
    assert isinstance(one, AlgebraicCandidate)
    assert one.minimal_polynomial == (-1, 1)

    zero = recognize(RealBall(0, Dyadic(1, -4)), RecognitionBounds(1, 1))
    assert isinstance(zero, AlgebraicCandidate)
    assert zero.minimal_polynomial == (0, 1)

    both_endpoints = recognize(
        RealBall(Dyadic(1, -1), Dyadic(1, -1)),
        RecognitionBounds(1, 1),
    )
    assert isinstance(both_endpoints, NumericUnknown)
    assert both_endpoints.requested["compatible_polynomials"] == 2


def test_projection_degree_separates_generic_and_regular_fiber_claims() -> None:
    polynomial = ExactPolynomial(1, {(5,): 1, (0,): -1})
    generic = projection_degree(polynomial, ())
    assert isinstance(generic, DegreeResult)
    assert generic.degree == 5 and generic.generic
    assert generic.claim().status is EpistemicStatus.EXACT

    fiber_polynomial = ExactPolynomial(1, {(2,): 1, (0,): -1})
    system = PolynomialSystem(1, (fiber_polynomial,))
    fiber_witness = RegularFiberWitness(system, ((-1, 1), (1, 1)))
    regular = projection_degree(system, (), regular_fiber_witness=fiber_witness)
    assert isinstance(regular, RegularFiberDegree)
    assert regular.degree == 2 and not regular.generic

    unrelated = projection_degree(
        system,
        (polynomial,),
        generic_witness=GenericDegreeWitness(polynomial),
    )
    assert isinstance(unrelated, UnsupportedNumeric)
    foreign_regular = projection_degree(
        PolynomialSystem(1, (ExactPolynomial(1, {(1,): 1}),)),
        (),
        regular_fiber_witness=fiber_witness,
    )
    assert isinstance(foreign_regular, UnsupportedNumeric)
    with pytest.raises(NumericError, match="cannot be supplied together"):
        projection_degree(
            polynomial,
            (),
            regular_fiber_witness=fiber_witness,
            generic_witness=GenericDegreeWitness(polynomial),
        )

    generic_witness = GenericDegreeWitness(ExactPolynomial(1, {(1,): 1}))
    object.__setattr__(generic_witness, "degree", True)
    with pytest.raises(NumericVerificationError, match="not an integer"):
        generic_witness.verify()

    generic_result = DegreeResult(GenericDegreeWitness(ExactPolynomial(1, {(1,): 1})))
    object.__setattr__(generic_result, "generic", 1)
    with pytest.raises(NumericVerificationError, match="noncanonical types"):
        generic_result.verify()


def test_exact_cover_proves_complete_quadratic_discriminant() -> None:
    family = PolynomialFamily(
        1,
        (
            ExactPolynomial(
                2,
                {(2, 0): 1, (0, 1): -1},
                variable_names=("x", "t"),
            ),
        ),
    )
    cover = ExactCover(family, 2, (0,))
    assert cover.infinity_branch
    assert cover.branch_count == 2
    assert cover.verify()
    assert cover.claim().status is EpistemicStatus.EXACT

    finite_family = PolynomialFamily(
        1,
        (
            ExactPolynomial(
                2,
                {(2, 0): 1, (0, 2): -1, (0, 1): 1},
                variable_names=("x", "t"),
            ),
        ),
    )
    finite_cover = ExactCover(finite_family, 2, (0, 1))
    assert not finite_cover.infinity_branch
    assert finite_cover.branch_count == 2

    with pytest.raises(NumericError, match="do not exhaust"):
        ExactCover(finite_family, 2, (0,))
    with pytest.raises(NumericError, match="degree two"):
        ExactCover(family, 3, (0,))
    nonmonic = PolynomialFamily(
        1,
        (ExactPolynomial(2, {(2, 0): 2, (0, 1): -1}),),
    )
    with pytest.raises(NumericError, match="monic"):
        ExactCover(nonmonic, 2, (0,))


def test_receipt_canonicalization_and_backend_leaks_fail_closed() -> None:
    with pytest.raises(NumericError, match="backend-local"):
        NumericUnknown(
            "recognize",
            "no conclusion",
            requested={"backend": {"handle": "session-7", "transcript": "secret"}},
        )
    with pytest.raises(NumericError, match="noncanonical"):
        NumericUnknown("recognize", "no conclusion", requested={"fraction": Fraction(1, 2)})
    with pytest.raises(NumericError, match="oversized integer"):
        NumericUnknown(
            "recognize",
            "no conclusion",
            requested={"integer": 1 << 4096},
        )

    deeply_nested: object = 0
    for _ in range(130):
        deeply_nested = [deeply_nested]
    with pytest.raises(NumericError, match="nesting-depth"):
        NumericUnknown("recognize", "no conclusion", requested={"nested": deeply_nested})

    payload = Dyadic.one().to_canonical_data()
    with pytest.raises(CertificateError, match="noncanonical Unicode"):
        NumericReceipt.create(
            "unknown",
            {
                "type": "arbogast.numeric.unknown",
                "operation": "cafe\u0301",
                "reason": "unknown",
                "requested": {},
            },
        )
    aliased = {**payload, "alias": ()}
    with pytest.raises(CertificateError, match="noncanonical"):
        NumericReceipt.create("dyadic", aliased)
    fractional = {**payload, "alias": Fraction(1, 2)}
    with pytest.raises(CertificateError, match="noncanonical"):
        NumericReceipt.create("dyadic", fractional)
    with pytest.raises(CertificateError, match="canonical NFC"):
        NumericReceipt.create("dyadic", payload, assumptions=(" GRH",))
    with pytest.raises(CertificateError, match=r"length|oversized"):
        NumericReceipt.create("dyadic", payload, assumptions=("x" * 16_385,))


def test_receipt_claim_roundtrip_and_fresh_process(
    tmp_path: Path,
) -> None:
    point, candidate = _sqrt_two_point()
    result = exactify(point, candidate=candidate)
    assert isinstance(result, ExactificationResult)
    receipt = receipt_for_result(result)
    replayed_receipt = NumericReceipt.from_dict(receipt.to_dict())
    assert replayed_receipt.verify()

    certificate = VerificationCertificate.from_dict(result.certificate.to_dict())
    assert verify_certificate(certificate).valid
    claim = Claim.from_dict(result.claim().to_dict())
    assert claim.verify().verified
    graph = ClaimGraph.from_dict(result.claim_graph().to_dict())
    assert graph.verify().verified

    conditional = NumericReceipt.create(
        "real-ball",
        RealBall(0, 1).to_canonical_data(),
        assumptions=("GRH",),
    )
    assert claim_for_receipt(conditional).status is EpistemicStatus.CONDITIONAL

    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(result.claim().to_dict()), encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(project_root / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,sys; from arbogast.claims import Claim; "
                "claim=Claim.from_dict(json.load(open(sys.argv[1], encoding='utf-8'))); "
                "assert claim.verify().verified"
            ),
            str(claim_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_exactify_rejects_ambiguous_candidate_and_bounds_bundle() -> None:
    point, candidate = _sqrt_two_point()
    with pytest.raises(NumericError, match="cannot be supplied together"):
        exactify(point, candidate=candidate, bounds=RecognitionBounds(1, 1))


def test_completeness_and_assumption_tampering_are_bound() -> None:
    family, path, start, tube = _linear_continuation()
    result = continue_path(family, start, path, tube=tube)
    assert isinstance(result, ContinuationResult)
    raw = deepcopy(receipt_for_result(result).to_dict())
    raw["completeness"] = "candidate"
    raw.pop("certificate_id", None)
    with pytest.raises(CertificateError, match="marked complete"):
        NumericReceipt.from_dict(raw)

    raw = deepcopy(receipt_for_result(result).to_dict())
    raw["assumptions"] = [" GRH"]
    raw.pop("certificate_id", None)
    with pytest.raises(CertificateError, match="canonical NFC"):
        NumericReceipt.from_dict(raw)
