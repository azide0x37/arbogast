from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from arbogast.arithmetic import (
    CartierDual,
    LocalCondition,
    SelmerGroup,
    SelmerKernel,
    SelmerProblem,
    dual_selmer,
    local_pairing,
    selmer,
)
from arbogast.backends.pari_certificate import create_pari_verification_certificate
from arbogast.backends.pari_results import PariOutcome
from arbogast.cert import (
    VerificationCertificate,
    VerificationReport,
    content_address,
    default_verifiers,
)
from arbogast.claims import Claim, EpistemicStatus
from arbogast.galois import (
    ArithmeticCertificateError,
    Completeness,
    FiniteGaloisQuotient,
    FinitePlace,
    InfinitePlace,
    KummerSpace,
    LocalH1Space,
    NumberField,
    ProofContext,
    TwistClassSet,
    Unsupported,
    VerificationRequirement,
    decomposition_quotient_h1,
    galois_module,
    kummer_class,
    kummer_space,
    local_h1,
    localize,
    nonabelian_h1,
    twist_classes,
)
from arbogast.galois.certificate import KummerReceipt, LocalH1Receipt, TwistReceipt
from arbogast.galois.plans import (
    ShardReductionError,
    plan_local_h1,
    plan_localize,
)
from arbogast.galois.semantic import (
    claim_for_result,
    claim_graph_for_result,
    verification_certificate_for_result,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup, cyclic_group, symmetric_group


def _pari_limits() -> dict[str, object]:
    return {
        "certification_timeout_seconds": "30",
        "cpu_limit_seconds": 30,
        "memory_limit_bytes": 268435456,
        "output_limit_bytes": 1048576,
        "pari_stack_bytes": 67108864,
        "timeout_seconds": "30",
    }


def _field_replay(field: NumberField) -> dict[str, object]:
    snapshot = field.to_dict()
    return {
        "defining_polynomial": [
            [coefficient, 1] for coefficient in snapshot["defining_polynomial"]
        ],
        "field_id": field.field_id,
        "identity": snapshot,
        "integral_basis": snapshot["integral_basis"],
    }


def _finite_place_replay(place: FinitePlace) -> dict[str, object]:
    return {
        "ideal_hnf": [list(row) for row in place.ideal_hnf],
        "identity": place.to_dict(),
        "place_id": place.place_id,
        "ramification_index": place.ramification_index,
        "rational_prime": place.rational_prime,
        "residue_degree": place.residue_degree,
    }


def _element_replay(element: Any) -> dict[str, object]:
    return {
        "coefficients": element.to_dict()["coefficients"],
        "element_id": element.element_id,
        "identity": element.to_dict(),
    }


class _StubPariResult:
    def __init__(
        self,
        operation: str,
        payload: dict[str, object],
        certificate: VerificationCertificate,
    ) -> None:
        self.operation = operation
        self.payload = payload
        self.certificate = certificate
        self.outcome = PariOutcome.SUCCESS

    def proof_context(self) -> ProofContext:
        proof_mode = self.certificate.witness.get("proof_mode")
        assumptions = ("GRH",) if proof_mode == "grh-conditional" else ()
        completeness = Completeness(
            str(self.certificate.witness.get("completeness", "CANDIDATE")).lower()
        )
        version = self.certificate.witness["backend_version"]
        assert isinstance(version, str)
        return ProofContext(
            assumptions,
            (
                VerificationRequirement.pinned_external(
                    "arbogast.backends.pari.v1",
                    version,
                    capabilities=(self.operation,),
                ),
            ),
            completeness,
        )


class _StubPariBackend:
    def __init__(self, **results: _StubPariResult) -> None:
        self.results = results

    def s_unit_squareclasses(self, *_args: object, **_kwargs: object) -> _StubPariResult:
        return self.results["s_unit_squareclasses"]

    def local_squareclasses(self, *_args: object, **_kwargs: object) -> _StubPariResult:
        return self.results["local_squareclasses"]

    def localization_matrix(self, *_args: object, **_kwargs: object) -> _StubPariResult:
        return self.results["localization_matrix"]


def _pari_certificate(
    operation: str,
    field: NumberField,
    expected_payload: dict[str, object],
    arguments: dict[str, object],
    *,
    version: str = "2.17.4",
    completeness: str = "COMPLETE",
) -> VerificationCertificate:
    return create_pari_verification_certificate(
        operation,
        replay={"arguments": arguments, "field": _field_replay(field)},
        expected_payload=expected_payload,
        backend_version=version,
        request_id="sha256:" + "1" * 64,
        deterministic_seed=1,
        proof_mode="unconditional",
        limits=_pari_limits(),
        completeness=completeness,
    )


def _accept_structurally_valid_pari_certificates(monkeypatch: pytest.MonkeyPatch) -> None:
    original_verify = default_verifiers.verify

    def verify(certificate: object, **kwargs: object) -> VerificationReport:
        if (
            isinstance(certificate, VerificationCertificate)
            and certificate.verifier == "arbogast.backends.pari.v1"
        ):
            certificate.verify_integrity()
            return VerificationReport(
                valid=True,
                verifier=certificate.verifier,
                certificate_id=certificate.certificate_id,
            )
        return original_verify(certificate, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(default_verifiers, "verify", verify)


@pytest.fixture
def rational_places() -> tuple[NumberField, FinitePlace, InfinitePlace]:
    field = NumberField.rationals()
    two_adic = FinitePlace(field, 2, ((2,),), 1, 1)
    real = InfinitePlace(field, "real", (-1, 1))
    return field, two_adic, real


def test_rational_s_kummer_and_localizations_replay_portably(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    space = kummer_space(field, (two_adic, real))

    assert isinstance(space, KummerSpace)
    assert space.completeness is Completeness.COMPLETE
    assert space.relevant_places_complete
    assert space.relevant_place_set_complete
    assert space.assumptions == ()
    assert space.dimension == 2
    assert tuple(item.representative for item in space.basis) == (
        field.element(-1),
        field.element(2),
    )
    assert space.verify()
    assert space.claim().status is EpistemicStatus.EXACT
    assert space.claim().verify().verified
    assert space.claim_graph().verify().verified

    h_two = local_h1(two_adic)
    h_real = local_h1(real)
    assert isinstance(h_two, LocalH1Space)
    assert isinstance(h_real, LocalH1Space)
    assert h_two.dimension == 3
    assert h_real.dimension == 1
    assert tuple(item.representative for item in space.basis) == (
        field.element(-1),
        field.element(2),
    )

    at_two = localize(space, h_two)
    at_real = localize(space, h_real)
    assert not isinstance(at_two, Unsupported)
    assert not isinstance(at_real, Unsupported)
    assert at_two.matrix.rows == ((1, 0), (0, 1), (0, 0))
    assert at_real.matrix.rows == ((1, 0),)
    localized_minus_one = localize(space.basis[0], h_two)
    assert localized_minus_one.coordinates == (1, 0, 0)
    assert localized_minus_one.verify()
    assert localized_minus_one.certificate.verifier == "galois.localization.v1"
    assert verification_certificate_for_result(space) == space.certificate
    assert verification_certificate_for_result(localized_minus_one) == (
        localized_minus_one.certificate
    )
    assert claim_for_result(at_two) == at_two.claim()
    assert claim_graph_for_result(h_real).verify().verified


def test_q_infinity_only_kummer_does_not_certify_the_selmer_place_set(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, _, real = rational_places
    space = kummer_space(field, (real,))
    assert isinstance(space, KummerSpace)
    assert space.completeness is Completeness.COMPLETE
    assert not space.relevant_places_complete

    real_space = local_h1(real)
    assert isinstance(real_space, LocalH1Space)
    localization = localize(space, real_space)
    assert not isinstance(localization, Unsupported)
    problem = SelmerProblem(
        space,
        (localization,),
        (LocalCondition(real_space, ((1,),)),),
        place_set_complete=True,
    )
    assert not problem.place_set_complete
    assert problem.completeness is Completeness.CANDIDATE
    assert type(selmer(problem)) is SelmerKernel

    forged = deepcopy(space.receipt.to_dict())
    forged["completeness_witness"]["relevant_place_set"]["complete"] = True
    with pytest.raises(ArithmeticCertificateError, match="contradicts the declared Q places"):
        KummerReceipt.from_dict(forged).verify()


def test_automatic_p_greater_than_two_is_typed_unsupported_but_supplied_is_finite(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    automatic = kummer_space(field, (two_adic, real), prime=3)
    assert isinstance(automatic, Unsupported)
    assert automatic.verify()

    supplied = kummer_space(
        field,
        (two_adic, real),
        prime=3,
        generators=(field.element(2),),
    )
    assert isinstance(supplied, KummerSpace)
    assert supplied.completeness is Completeness.CANDIDATE
    assert "neither independence nor completeness is claimed" in supplied.claim().statement.text
    assert kummer_class(supplied, (4,)).coordinates == (1,)


def test_certified_supplied_prime_three_closes_localization_and_selmer() -> None:
    verifier_name = "tests.galois.supplied-presentation.v1"
    verifier_version = "1.0"

    def verify_supplied(certificate: VerificationCertificate) -> VerificationReport:
        certificate.verify_integrity()
        return VerificationReport(
            valid=True,
            verifier=verifier_name,
            certificate_id=certificate.certificate_id,
            checks=("independent test presentation replay",),
        )

    default_verifiers.register(
        verifier_name,
        VerificationCertificate,
        verify_supplied,
    )

    def context(operation: str) -> ProofContext:
        return ProofContext(
            verification_requirements=(
                VerificationRequirement.pinned_external(
                    verifier_name,
                    verifier_version,
                    capabilities=(operation,),
                ),
            ),
            completeness=Completeness.COMPLETE,
        )

    def certificate(operation: str, payload: dict[str, object]) -> VerificationCertificate:
        payload_id = content_address(payload)
        return VerificationCertificate.create(
            subject=f"galois:supplied:{operation}:{payload_id}",
            verifier=verifier_name,
            witness={
                "backend_version": verifier_version,
                "expected_payload": payload,
                "expected_payload_id": payload_id,
                "operation": operation,
                "proof": {"kind": "independently-replayed-finite-presentation"},
                "schema": "arbogast.galois.supplied-presentation-witness/v1",
            },
            checks=("finite presentation independently replayed",),
            guarantees=("the exact supplied finite presentation is complete",),
        )

    try:
        field = NumberField.rationals()
        at_three = FinitePlace(field, 3, ((3,),), 1, 1)
        real = InfinitePlace(field, "real", (-1, 1))
        places = tuple(sorted((at_three, real), key=lambda item: item.place_id))
        place_ids = tuple(item.place_id for item in places)
        relevant_places = {
            "schema": "arbogast.galois.relevant-place-set/v2",
            "method": "certified-supplied-relevant-places-v1",
            "prime": 3,
            "place_ids": place_ids,
            "archimedean_place_ids": tuple(
                item.place_id for item in places if isinstance(item, InfinitePlace)
            ),
            "discriminant_place_ids": (),
            "ramified_place_ids": (),
            "coefficient_prime_place_ids": (at_three.place_id,),
            "complete": True,
            "evidence": {"operation": "supplied_kummer_presentation"},
        }
        generator = field.element(3)
        global_witness = {
            "field_id": field.field_id,
            "generator_ids": (generator.element_id,),
            "method": "certified-supplied-kummer-presentation-v1",
            "place_ids": place_ids,
            "prime": 3,
            "relevant_place_set": relevant_places,
        }
        global_payload = {
            "field_id": field.field_id,
            "generator_ids": (generator.element_id,),
            "place_ids": place_ids,
            "prime": 3,
            "relevant_place_set": relevant_places,
        }
        global_space = kummer_space(
            field,
            places,
            prime=3,
            generators=(generator,),
            proof_context=context("supplied_kummer_presentation"),
            completeness_witness=global_witness,
            proving_certificate=certificate(
                "supplied_kummer_presentation",
                global_payload,
            ),
        )
        assert isinstance(global_space, KummerSpace)
        assert global_space.relevant_places_complete

        def supplied_local(
            place: FinitePlace | InfinitePlace,
            basis: tuple[Any, ...],
        ) -> LocalH1Space:
            operation = "supplied_local_h1_presentation"
            basis_ids = tuple(item.element_id for item in basis)
            presentation = {
                "basis_ids": basis_ids,
                "continuous_local_cohomology": True,
                "method": "certified-supplied-local-h1-presentation-v1",
                "place_id": place.place_id,
                "prime": 3,
            }
            result = local_h1(
                place,
                prime=3,
                basis=basis,
                proof_context=context(operation),
                presentation=presentation,
                proving_certificate=certificate(
                    operation,
                    {
                        "basis_ids": basis_ids,
                        "place_id": place.place_id,
                        "prime": 3,
                    },
                ),
            )
            assert isinstance(result, LocalH1Space)
            return result

        three_space = supplied_local(at_three, (field.element(3), field.element(2)))
        real_space = supplied_local(real, ())

        def supplied_localization(
            local_space: LocalH1Space,
            matrix: tuple[tuple[int, ...], ...],
        ) -> Any:
            operation = "supplied_localization_presentation"
            witness = {
                "codomain_receipt": local_space.receipt.content_id,
                "domain_receipt": global_space.receipt.content_id,
                "method": "certified-supplied-localization-presentation-v1",
                "prime": 3,
            }
            result = localize(
                global_space,
                local_space,
                matrix=matrix,
                proof_context=context(operation),
                localization_witness=witness,
                proving_certificate=certificate(
                    operation,
                    {
                        "codomain_receipt": local_space.receipt.content_id,
                        "domain_receipt": global_space.receipt.content_id,
                        "matrix": matrix,
                        "prime": 3,
                    },
                ),
            )
            assert not isinstance(result, Unsupported)
            return result

        at_three_map = supplied_localization(three_space, ((1,), (0,)))
        real_map = supplied_localization(real_space, ())
        localizations = {
            at_three: at_three_map,
            real: real_map,
        }
        conditions = {
            at_three: LocalCondition(
                three_space,
                ((1, 0), (0, 1)),
            ),
            real: LocalCondition(real_space, ()),
        }
        problem = SelmerProblem(global_space, localizations, conditions)
        result = selmer(problem)
        assert isinstance(result, SelmerGroup)
        assert result.prime == 3
        assert result.dimension == 1
        assert result.verify().valid

        def supplied_pairing(local_space: LocalH1Space) -> Any:
            operation = "supplied_local_pairing"
            matrix = DenseMatrix.identity(PrimeField(3), local_space.dimension)
            payload = {
                "left_space_id": local_space.receipt.content_id,
                "matrix": matrix.rows,
                "place_id": local_space.place.place_id,
                "prime": 3,
                "right_space_id": local_space.receipt.content_id,
            }
            return local_pairing(
                local_space,
                local_space,
                matrix,
                proof_context=context(operation),
                pairing_witness={
                    "kind": "certified-supplied-tate-pairing-v1",
                    "operation": operation,
                },
                proving_certificate=certificate(operation, payload),
            )

        pairings_by_place = {
            at_three: supplied_pairing(three_space),
            real: supplied_pairing(real_space),
        }
        group = CyclicGroup(1)
        quotient = FiniteGaloisQuotient(
            field,
            group,
            label="certified-supplied-mu3-quotient",
        )
        coefficient_field = PrimeField(3)
        module = galois_module(
            quotient,
            coefficient_field,
            {group.identity: DenseMatrix.identity(coefficient_field, 1)},
            name="certified-supplied-mu3",
        )
        dual = dual_selmer(
            problem,
            pairings=tuple(pairings_by_place[place] for place in problem.places),
            cartier_dual=CartierDual(module, twist_character=(1,)),
        )
        assert dual.cartier_dual.prime == 3
        assert dual.dimension == 0
        assert dual.verify().valid

        tampered = deepcopy(global_space.receipt.to_dict())
        tampered["completeness_witness"]["prime"] = 2
        with pytest.raises(ArithmeticCertificateError, match="different data"):
            KummerReceipt.from_dict(tampered).verify()
    finally:
        default_verifiers.unregister(verifier_name)


def test_structural_witness_cannot_forge_complete_kummer_or_local_h1(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    context = ProofContext(
        verification_requirements=(
            VerificationRequirement.portable_python(
                "galois.kummer.v1",
                capabilities=("finite-s-kummer-presentation",),
            ),
        ),
        completeness=Completeness.COMPLETE,
    )
    with pytest.raises(ArithmeticCertificateError, match="unrecognized portable"):
        KummerSpace(
            field,
            (two_adic, real),
            2,
            (field.element(3),),
            context,
            {
                "method": "asserted-complete",
                "place_ids": (two_adic.place_id, real.place_id),
                "s_unit_generators": (field.element(3).element_id,),
                "class_group_p_torsion": (),
                "principalization_witnesses": (),
            },
        )

    local_context = ProofContext(
        verification_requirements=(
            VerificationRequirement.portable_python(
                "galois.local_h1.v1",
                capabilities=("local-mu2-squareclasses",),
            ),
        ),
        completeness=Completeness.COMPLETE,
    )
    with pytest.raises(ArithmeticCertificateError, match="unrecognized portable local"):
        LocalH1Space(
            two_adic,
            2,
            (field.element(3),),
            local_context,
            {
                "method": "asserted-complete",
                "place_id": two_adic.place_id,
                "basis_ids": (field.element(3).element_id,),
                "perfect_kummer_identification": True,
            },
        )


def test_assumptions_and_external_trust_are_independent_axes(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    conditional = kummer_space(
        field,
        (two_adic, real),
        generators=(field.element(2),),
        assumptions=("GRH",),
    )
    assert isinstance(conditional, KummerSpace)
    assert conditional.claim().status is EpistemicStatus.CONDITIONAL

    external_context = ProofContext(
        verification_requirements=(
            VerificationRequirement.pinned_external(
                "pari.s_unit_squareclasses",
                "2.17.4",
                capabilities=("s-unit-squareclasses",),
            ),
        ),
        completeness=Completeness.CANDIDATE,
    )
    external = kummer_space(
        field,
        (two_adic, real),
        generators=(field.element(2),),
        proof_context=external_context,
    )
    assert isinstance(external, KummerSpace)
    assert external.claim().status is EpistemicStatus.UNKNOWN
    assert external.completeness is Completeness.CANDIDATE


def test_nested_pari_kummer_certificate_accepts_units_and_rejects_missing_lift(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, two_adic, real = rational_places
    generators = (field.element(-1), field.element(2))
    s_unit_payload = {
        "certified": True,
        "complete": True,
        "field_id": field.field_id,
        "prime_ideal_hnfs": [[[2]]],
        "representatives": [[[-1, 1]], [[2, 1]]],
        "roots_of_unity_order": 2,
        "s_class_2_torsion": [],
        "s_class_group_cyclic_orders": [],
        "s_unit_rank": 2,
    }
    s_unit = _pari_certificate(
        "s_unit_squareclasses",
        field,
        s_unit_payload,
        {
            "places": [
                {
                    "ideal_hnf": [[2]],
                    "place_id": two_adic.place_id,
                    "rational_prime": 2,
                }
            ]
        },
    )
    context = ProofContext(
        verification_requirements=(
            VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v1",
                "2.17.4",
                capabilities=("s_unit_squareclasses",),
            ),
        ),
        completeness=Completeness.COMPLETE,
    )
    witness = {
        "method": "pari-s-kummer-v1",
        "field_id": field.field_id,
        "place_ids": tuple(sorted((two_adic.place_id, real.place_id))),
        "generator_ids": tuple(item.element_id for item in generators),
        "s_unit_generators": tuple(item.element_id for item in generators),
        "class_group_p_torsion": (),
        "principalization_witnesses": (),
    }
    _accept_structurally_valid_pari_certificates(monkeypatch)
    space = kummer_space(
        field,
        (two_adic, real),
        generators=generators,
        proof_context=context,
        completeness_witness=witness,
        proving_certificate=s_unit,
    )
    assert isinstance(space, KummerSpace)
    assert space.completeness is Completeness.COMPLETE
    claim = space.claim()
    assert claim.status is EpistemicStatus.CERTIFIED
    assert claim.verify().verified
    assert space.claim_graph().verify().verified
    assert Claim.from_dict(claim.to_dict()).verify().verified
    assert tuple(item.certificate_id for item in space.certificate.dependencies) == (
        s_unit.certificate_id,
    )

    even_payload = {
        **s_unit_payload,
        "complete": False,
        "s_class_group_cyclic_orders": [2],
    }
    even_s_class = _pari_certificate(
        "s_unit_squareclasses",
        field,
        even_payload,
        {
            "places": [
                {
                    "ideal_hnf": [[2]],
                    "place_id": two_adic.place_id,
                    "rational_prime": 2,
                }
            ]
        },
        completeness="CANDIDATE",
    )
    with pytest.raises(ArithmeticCertificateError, match="omitted an S-class 2-torsion lift"):
        kummer_space(
            field,
            (two_adic, real),
            generators=generators,
            proof_context=context,
            completeness_witness=witness,
            proving_certificate=even_s_class,
        )


def test_automatic_pari_kummer_accepts_s_class_lift_and_rejects_witness_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    complex_place = InfinitePlace(field, "complex", (-1, 1, 2, 3))
    payload = {
        "certified": True,
        "complete": True,
        "field_id": field.field_id,
        "prime_ideal_hnfs": [],
        "representatives": [
            [[-1, 1], [0, 1]],
            [[2, 1], [0, 1]],
        ],
        "roots_of_unity_order": 2,
        "s_class_2_torsion": [
            {
                "cyclic_order": 2,
                "ideal_hnf": [[2, 1], [0, 1]],
                "principalization_generator": [[2, 1], [0, 1]],
                "s_prime_exponents": [],
            }
        ],
        "s_class_group_cyclic_orders": [2],
        "s_unit_rank": 1,
    }
    certificate = _pari_certificate(
        "s_unit_squareclasses",
        field,
        payload,
        {"places": []},
    )
    backend = _StubPariBackend(
        s_unit_squareclasses=_StubPariResult(
            "s_unit_squareclasses",
            payload,
            certificate,
        )
    )
    _accept_structurally_valid_pari_certificates(monkeypatch)
    space = kummer_space(field, (complex_place,), backend=backend)
    assert isinstance(space, KummerSpace)
    assert space.completeness is Completeness.COMPLETE
    assert space.dimension == 2
    assert space.generators == (field.element(-1), field.element(2))
    assert space.claim().status is EpistemicStatus.CERTIFIED
    assert space.completeness_witness["class_group_p_torsion"] == (
        {
            "cyclic_order": 2,
            "ideal_hnf": [[2, 1], [0, 1]],
            "s_prime_exponents": [],
        },
    )

    missing = deepcopy(space.receipt.to_dict())
    missing["completeness_witness"]["principalization_witnesses"] = []
    with pytest.raises(ArithmeticCertificateError, match="principalization witnesses differ"):
        KummerReceipt.from_dict(missing).verify()

    duplicate = deepcopy(space.receipt.to_dict())
    class_witness = duplicate["completeness_witness"]["class_group_p_torsion"][0]
    duplicate["completeness_witness"]["class_group_p_torsion"] = [
        class_witness,
        class_witness,
    ]
    with pytest.raises(ArithmeticCertificateError, match="torsion witnesses differ"):
        KummerReceipt.from_dict(duplicate).verify()

    reordered = deepcopy(space.receipt.to_dict())
    reordered["generators"].reverse()
    reordered["generator_ids"].reverse()
    reordered["completeness_witness"]["generator_ids"].reverse()
    with pytest.raises(ArithmeticCertificateError, match="order S-units before S-class lifts"):
        KummerReceipt.from_dict(reordered).verify()


def test_pari_relevant_place_evidence_closes_quadratic_set_and_rejects_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    at_two = FinitePlace(field, 2, ((2, 1), (0, 1)), 2, 1)
    at_five = FinitePlace(field, 5, ((5, 0), (0, 1)), 2, 1)
    infinity = InfinitePlace(field, "complex", (-1, 1, 2, 3))

    def decomposition_payload(place: FinitePlace) -> dict[str, object]:
        return {
            "field_id": field.field_id,
            "prime_ideals": [
                {
                    "ideal_hnf": [list(row) for row in place.ideal_hnf],
                    "norm": place.norm,
                    "place_id": content_address(
                        {
                            "field_id": field.field_id,
                            "ideal_hnf": place.ideal_hnf,
                            "rational_prime": place.rational_prime,
                        }
                    ),
                    "ramification_index": place.ramification_index,
                    "residue_degree": place.residue_degree,
                }
            ],
            "rational_prime": place.rational_prime,
        }

    invariants_payload = {
        "degree": 2,
        "discriminant": -20,
        "field_id": field.field_id,
        "index": 1,
        "integral_basis": field.to_dict()["integral_basis"],
        "signature": [0, 1],
    }
    invariants_certificate = _pari_certificate(
        "field_invariants",
        field,
        invariants_payload,
        {},
    )
    decomposition_results: dict[int, _StubPariResult] = {}
    for place in (at_two, at_five):
        payload = decomposition_payload(place)
        certificate = _pari_certificate(
            "prime_decomposition",
            field,
            payload,
            {"rational_prime": place.rational_prime},
        )
        decomposition_results[place.rational_prime] = _StubPariResult(
            "prime_decomposition",
            payload,
            certificate,
        )

    class RelevantPlaceBackend(_StubPariBackend):
        def field_invariants(self, *_args: object) -> _StubPariResult:
            return self.results["field_invariants"]

        def prime_decomposition(
            self,
            _field: object,
            rational_prime: int,
        ) -> _StubPariResult:
            return decomposition_results[rational_prime]

    def backend_for(finite_places: tuple[FinitePlace, ...]) -> RelevantPlaceBackend:
        generators = (field.element(-1), *(field.element(p.rational_prime) for p in finite_places))
        payload = {
            "certified": True,
            "complete": True,
            "field_id": field.field_id,
            "prime_ideal_hnfs": [[list(row) for row in place.ideal_hnf] for place in finite_places],
            "representatives": [item.to_dict()["coefficients"] for item in generators],
            "roots_of_unity_order": 2,
            "s_class_2_torsion": [],
            "s_class_group_cyclic_orders": [],
            "s_unit_rank": len(generators),
        }
        certificate = _pari_certificate(
            "s_unit_squareclasses",
            field,
            payload,
            {"places": [_finite_place_replay(place) for place in finite_places]},
        )
        return RelevantPlaceBackend(
            s_unit_squareclasses=_StubPariResult(
                "s_unit_squareclasses",
                payload,
                certificate,
            ),
            field_invariants=_StubPariResult(
                "field_invariants",
                invariants_payload,
                invariants_certificate,
            ),
        )

    _accept_structurally_valid_pari_certificates(monkeypatch)
    complete_places = tuple(
        place
        for place in sorted((at_two, at_five, infinity), key=lambda item: item.place_id)
        if isinstance(place, FinitePlace)
    )
    space = kummer_space(
        field,
        (at_two, at_five, infinity),
        backend=backend_for(complete_places),
    )
    assert isinstance(space, KummerSpace)
    assert space.relevant_places_complete
    relevant = space.completeness_witness["relevant_place_set"]
    assert relevant["complete"] is True
    assert len(space.proving_certificates) == 4

    missing_five_places = tuple(
        place
        for place in sorted((at_two, infinity), key=lambda item: item.place_id)
        if isinstance(place, FinitePlace)
    )
    missing_five = kummer_space(
        field,
        (at_two, infinity),
        backend=backend_for(missing_five_places),
    )
    assert isinstance(missing_five, KummerSpace)
    assert missing_five.completeness is Completeness.COMPLETE
    assert not missing_five.relevant_places_complete

    tampered = deepcopy(space.receipt.to_dict())
    evidence = tampered["completeness_witness"]["relevant_place_set"]["evidence"]
    evidence["prime_decomposition_certificates"] = evidence["prime_decomposition_certificates"][:-1]
    with pytest.raises(ArithmeticCertificateError, match="missing, duplicated, or reordered"):
        KummerReceipt.from_dict(tampered).verify()

    bad_factorization = deepcopy(space.receipt.to_dict())
    bad_factorization["completeness_witness"]["relevant_place_set"]["evidence"][
        "discriminant_factorization"
    ] = [[2, 2]]
    with pytest.raises(ArithmeticCertificateError, match="independent exact replay"):
        KummerReceipt.from_dict(bad_factorization).verify()

    recategorized = deepcopy(space.receipt.to_dict())
    recategorized["completeness_witness"]["relevant_place_set"]["discriminant_place_ids"] = []
    with pytest.raises(ArithmeticCertificateError, match="discriminant place IDs"):
        KummerReceipt.from_dict(recategorized).verify()


def test_automatic_pari_nonrational_kummer_local_h1_and_localization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    two_adic = FinitePlace(field, 2, ((2, 1), (0, 1)), 2, 1)
    complex_place = InfinitePlace(field, "complex", (-1, 1, 2, 3))
    global_generators = (field.element(-1), field.element(2))
    local_basis = (
        field.element((-1, 0)),
        field.element((-1, -1)),
        field.element((-2, -4)),
        field.element((4, -4)),
    )
    s_unit_payload = {
        "certified": True,
        "complete": True,
        "field_id": field.field_id,
        "prime_ideal_hnfs": [[[2, 1], [0, 1]]],
        "representatives": [
            [[-1, 1], [0, 1]],
            [[2, 1], [0, 1]],
        ],
        "roots_of_unity_order": 2,
        "s_class_2_torsion": [],
        "s_class_group_cyclic_orders": [],
        "s_unit_rank": 2,
    }
    local_payload = {
        "complete": True,
        "dimension": 4,
        "field_id": field.field_id,
        "place_id": two_adic.place_id,
        "ramification_index": 2,
        "rational_prime": 2,
        "representatives": [
            [[-1, 1], [0, 1]],
            [[-1, 1], [-1, 1]],
            [[-2, 1], [-4, 1]],
            [[4, 1], [-4, 1]],
        ],
        "residue_degree": 1,
        "tested_candidates": 81,
    }
    matrix = ((1, 1), (0, 1), (0, 0), (0, 1))
    localization_payload = {
        "complete": True,
        "field_id": field.field_id,
        "generator_ids": [item.element_id for item in global_generators],
        "local_basis": local_payload["representatives"],
        "matrix": [list(row) for row in matrix],
        "place_id": two_adic.place_id,
        "rational_prime": 2,
    }
    s_unit_certificate = _pari_certificate(
        "s_unit_squareclasses",
        field,
        s_unit_payload,
        {"places": [_finite_place_replay(two_adic)]},
    )
    local_certificate = _pari_certificate(
        "local_squareclasses",
        field,
        local_payload,
        {
            "max_candidates": 4096,
            "place": _finite_place_replay(two_adic),
            "search_bound": 4,
        },
    )
    localization_certificate = _pari_certificate(
        "localization_matrix",
        field,
        localization_payload,
        {
            "generators": [_element_replay(item) for item in global_generators],
            "max_candidates": 4096,
            "place": _finite_place_replay(two_adic),
            "search_bound": 4,
        },
    )
    backend = _StubPariBackend(
        s_unit_squareclasses=_StubPariResult(
            "s_unit_squareclasses",
            s_unit_payload,
            s_unit_certificate,
        ),
        local_squareclasses=_StubPariResult(
            "local_squareclasses",
            local_payload,
            local_certificate,
        ),
        localization_matrix=_StubPariResult(
            "localization_matrix",
            localization_payload,
            localization_certificate,
        ),
    )
    _accept_structurally_valid_pari_certificates(monkeypatch)

    global_space = kummer_space(field, (two_adic, complex_place), backend=backend)
    local_space = local_h1(two_adic, backend=backend)
    assert isinstance(global_space, KummerSpace)
    assert isinstance(local_space, LocalH1Space)
    assert global_space.generators == global_generators
    assert local_space.basis_representatives == local_basis
    localization = localize(global_space, local_space, backend=backend)
    assert not isinstance(localization, Unsupported)
    assert localization.matrix.rows == matrix
    assert localization.completeness is Completeness.COMPLETE
    assert localization.claim().status is EpistemicStatus.CERTIFIED
    assert {item.certificate_id for item in localization.certificate.dependencies} == {
        s_unit_certificate.certificate_id,
        local_certificate.certificate_id,
        localization_certificate.certificate_id,
    }


def test_automatic_pari_incomplete_local_search_remains_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    two_adic = FinitePlace(field, 2, ((2, 1), (0, 1)), 2, 1)
    payload = {
        "complete": False,
        "dimension": 4,
        "field_id": field.field_id,
        "place_id": two_adic.place_id,
        "ramification_index": 2,
        "rational_prime": 2,
        "representatives": [
            [[-1, 1], [0, 1]],
            [[-1, 1], [-1, 1]],
        ],
        "residue_degree": 1,
        "tested_candidates": 2,
    }
    certificate = _pari_certificate(
        "local_squareclasses",
        field,
        payload,
        {
            "max_candidates": 2,
            "place": _finite_place_replay(two_adic),
            "search_bound": 1,
        },
        completeness="CANDIDATE",
    )
    backend = _StubPariBackend(
        local_squareclasses=_StubPariResult(
            "local_squareclasses",
            payload,
            certificate,
        )
    )
    _accept_structurally_valid_pari_certificates(monkeypatch)
    candidate = local_h1(
        two_adic,
        backend=backend,
        search_bound=1,
        max_candidates=2,
    )
    assert isinstance(candidate, LocalH1Space)
    assert candidate.completeness is Completeness.CANDIDATE
    assert candidate.dimension == 2
    assert candidate.claim().status is EpistemicStatus.CERTIFIED
    assert "neither independence nor completeness is claimed" in candidate.claim().statement.text


def test_nested_pari_local_certificate_accepts_exact_binding_and_rejects_version_tamper(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, two_adic, _ = rational_places
    basis = (field.element(-1), field.element(2), field.element(5))
    payload = {
        "complete": True,
        "dimension": 3,
        "field_id": field.field_id,
        "place_id": two_adic.place_id,
        "ramification_index": 1,
        "rational_prime": 2,
        "representatives": [[[-1, 1]], [[2, 1]], [[5, 1]]],
        "residue_degree": 1,
        "tested_candidates": 9,
    }
    arguments = {
        "max_candidates": 4096,
        "place": {
            "ideal_hnf": [[2]],
            "place_id": two_adic.place_id,
            "rational_prime": 2,
        },
        "search_bound": 4,
    }
    certificate = _pari_certificate(
        "local_squareclasses",
        field,
        payload,
        arguments,
    )
    context = ProofContext(
        verification_requirements=(
            VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v1",
                "2.17.4",
                capabilities=("local_squareclasses",),
            ),
        ),
        completeness=Completeness.COMPLETE,
    )
    presentation = {
        "method": "pari-local-squareclasses-v1",
        "place_id": two_adic.place_id,
        "basis_ids": tuple(item.element_id for item in basis),
    }
    _accept_structurally_valid_pari_certificates(monkeypatch)
    space = local_h1(
        two_adic,
        basis=basis,
        proof_context=context,
        presentation=presentation,
        proving_certificate=certificate,
    )
    assert isinstance(space, LocalH1Space)
    assert space.claim().status is EpistemicStatus.CERTIFIED
    assert space.certificate.dependencies[0].certificate_id == certificate.certificate_id

    wrong_version = _pari_certificate(
        "local_squareclasses",
        field,
        payload,
        arguments,
        version="2.15.5",
    )
    with pytest.raises(ArithmeticCertificateError, match="no matching pinned requirement"):
        local_h1(
            two_adic,
            basis=basis,
            proof_context=context,
            presentation=presentation,
            proving_certificate=wrong_version,
        )


def test_supplied_localization_matrix_remains_candidate_and_cannot_promote_selmer(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    global_space = kummer_space(field, (two_adic, real))
    two_space = local_h1(two_adic)
    real_space = local_h1(real)
    assert isinstance(global_space, KummerSpace)
    assert isinstance(two_space, LocalH1Space)
    assert isinstance(real_space, LocalH1Space)
    forged = localize(
        global_space,
        two_space,
        matrix=((0, 0), (0, 0), (0, 0)),
    )
    real_map = localize(global_space, real_space)
    assert not isinstance(forged, Unsupported)
    assert not isinstance(real_map, Unsupported)
    assert forged.completeness is Completeness.CANDIDATE
    assert "no arithmetic correctness or completeness is claimed" in forged.claim().statement.text
    with pytest.raises(ArithmeticCertificateError, match="unrecognized portable localization"):
        localize(
            global_space,
            two_space,
            matrix=((0, 0), (0, 0), (0, 0)),
            completeness=Completeness.COMPLETE,
        )

    problem = SelmerProblem(
        global_space,
        (forged, real_map),
        (
            LocalCondition(two_space, ((1, 0, 0),)),
            LocalCondition(real_space, ((1,),)),
        ),
    )
    assert problem.completeness is Completeness.CANDIDATE
    assert type(selmer(problem)) is SelmerKernel


def test_nested_pari_localization_certificate_binds_matrix_and_dependencies(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field, two_adic, real = rational_places
    global_space = kummer_space(field, (two_adic, real))
    two_space = local_h1(two_adic)
    assert isinstance(global_space, KummerSpace)
    assert isinstance(two_space, LocalH1Space)
    matrix = ((1, 0), (0, 1), (0, 0))
    payload = {
        "complete": True,
        "field_id": field.field_id,
        "generator_ids": [item.element_id for item in global_space.generators],
        "local_basis": [[[-1, 1]], [[2, 1]], [[5, 1]]],
        "matrix": [list(row) for row in matrix],
        "place_id": two_adic.place_id,
        "rational_prime": 2,
    }
    certificate = _pari_certificate(
        "localization_matrix",
        field,
        payload,
        {
            "generators": [
                {
                    "coefficients": item.to_dict()["coefficients"],
                    "element_id": item.element_id,
                }
                for item in global_space.generators
            ],
            "max_candidates": 4096,
            "place": {
                "ideal_hnf": [[2]],
                "place_id": two_adic.place_id,
                "rational_prime": 2,
            },
            "search_bound": 4,
        },
    )
    context = ProofContext(
        verification_requirements=(
            VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v1",
                "2.17.4",
                capabilities=("localization_matrix",),
            ),
        ),
        completeness=Completeness.COMPLETE,
    )
    _accept_structurally_valid_pari_certificates(monkeypatch)
    localization = localize(
        global_space,
        two_space,
        matrix=matrix,
        proof_context=context,
        proving_certificate=certificate,
    )
    assert not isinstance(localization, Unsupported)
    assert localization.completeness is Completeness.COMPLETE
    assert localization.claim().status is EpistemicStatus.CERTIFIED
    assert tuple(item.certificate_id for item in localization.certificate.dependencies) == (
        certificate.certificate_id,
    )

    with pytest.raises(ArithmeticCertificateError, match="matrix differs"):
        localize(
            global_space,
            two_space,
            matrix=((0, 0), (0, 0), (0, 0)),
            proof_context=context,
            proving_certificate=certificate,
        )

    conditional = localize(
        global_space,
        two_space,
        matrix=matrix,
        proof_context=ProofContext(("GRH",), completeness=Completeness.CANDIDATE),
    )
    assert not isinstance(conditional, Unsupported)
    assert conditional.claim().status is EpistemicStatus.CONDITIONAL


def test_kummer_certificate_tampering_is_rejected(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    space = kummer_space(field, (two_adic, real))
    assert isinstance(space, KummerSpace)
    payload = space.certificate.to_dict()
    payload.pop("certificate_id")
    witness = payload["witness"]
    assert isinstance(witness, dict)
    receipt = witness["kummer_receipt"]
    assert isinstance(receipt, dict)
    receipt["generator_ids"] = list(reversed(receipt["generator_ids"]))
    tampered = VerificationCertificate.from_dict(payload)
    with pytest.raises(ValueError, match="generator ID"):
        default_verifiers.verify(tampered)

    domain = KummerReceipt.from_dict(space.receipt.to_dict())
    assert domain.verify()

    other_field = NumberField((5, 0, 1), generator_name="u")
    foreign_generator = deepcopy(space.receipt.to_dict())
    replacement = other_field.element(-1)
    foreign_generator["generators"][0] = replacement.to_dict()
    foreign_generator["generator_ids"][0] = replacement.element_id
    foreign_generator["completeness_witness"]["s_unit_generators"][0] = replacement.element_id
    with pytest.raises(ArithmeticCertificateError, match="generator belongs to another field"):
        KummerReceipt.from_dict(foreign_generator).verify()

    foreign_place = deepcopy(space.receipt.to_dict())
    other_infinity = InfinitePlace(other_field, "complex", (-1, 1, 2, 3))
    entries = [
        (foreign_place["place_ids"][0], foreign_place["places"][0]),
        (other_infinity.place_id, other_infinity.to_dict()),
    ]
    entries.sort(key=lambda item: item[0])
    foreign_place["place_ids"] = [item[0] for item in entries]
    foreign_place["places"] = [item[1] for item in entries]
    foreign_place["completeness_witness"]["place_ids"] = foreign_place["place_ids"]
    with pytest.raises(ArithmeticCertificateError, match="place belongs to another field"):
        KummerReceipt.from_dict(foreign_place).verify()

    invalid_real = deepcopy(space.receipt.to_dict())
    real_index = next(
        index
        for index, place in enumerate(invalid_real["places"])
        if place["type"] == "arbogast.infinite_place"
    )
    invalid_real["places"][real_index]["isolation"] = [[1, 1], [2, 1]]
    invalid_real["place_ids"][real_index] = content_address(invalid_real["places"][real_index])
    ordered_places = sorted(
        zip(invalid_real["place_ids"], invalid_real["places"], strict=True),
        key=lambda item: item[0],
    )
    invalid_real["place_ids"] = [item[0] for item in ordered_places]
    invalid_real["places"] = [item[1] for item in ordered_places]
    invalid_real["completeness_witness"]["place_ids"] = invalid_real["place_ids"]
    relevant_places = invalid_real["completeness_witness"]["relevant_place_set"]
    relevant_places["place_ids"] = invalid_real["place_ids"]
    relevant_places["archimedean_place_ids"] = [
        identifier
        for identifier, place in zip(invalid_real["place_ids"], invalid_real["places"], strict=True)
        if place["type"] == "arbogast.infinite_place"
    ]
    relevant_places["dyadic_place_ids"] = [
        identifier
        for identifier, place in zip(invalid_real["place_ids"], invalid_real["places"], strict=True)
        if place["type"] == "arbogast.finite_place" and place["rational_prime"] == 2
    ]
    with pytest.raises(ArithmeticCertificateError, match="does not contain the unique root"):
        KummerReceipt.from_dict(invalid_real).verify()

    assumptions = deepcopy(space.receipt.to_dict())
    assumptions["proof_context"]["assumptions"] = ["GRH", "GRH"]
    with pytest.raises(ArithmeticCertificateError, match="assumptions are not canonical"):
        KummerReceipt.from_dict(assumptions).verify()

    local_space = local_h1(two_adic)
    assert isinstance(local_space, LocalH1Space)
    foreign_local = deepcopy(local_space.receipt.to_dict())
    foreign_local["basis"][0] = replacement.to_dict()
    foreign_local["basis_ids"][0] = replacement.element_id
    foreign_local["presentation"]["basis_ids"][0] = replacement.element_id
    with pytest.raises(ArithmeticCertificateError, match="basis belongs to another field"):
        LocalH1Receipt.from_dict(foreign_local).verify()


def test_nonabelian_h1_trivial_c2_action_on_s3_has_two_pointed_classes() -> None:
    acting = cyclic_group(2)
    coefficients = symmetric_group(3)
    result = nonabelian_h1(acting, coefficients)

    assert isinstance(result, TwistClassSet)
    assert len(result) == 2
    assert result.basepoint.is_basepoint
    assert result.basepoint.representative(acting.generator) == coefficients.identity
    assert result.basepoint.verify()
    assert result.basepoint.certificate == result.certificate
    assert result.basepoint.claim_graph().verify().verified
    nontrivial = result.classes[1].representative(acting.generator)
    assert nontrivial.order == 2
    assert not nontrivial.is_identity
    assert len(result.cocycles) == 4
    assert result.cocycles[0].verify()
    assert result.cocycles[0].certificate == result.certificate
    assert result.cocycles[0].claim().verify().verified
    assert verification_certificate_for_result(result.basepoint) == result.certificate
    assert claim_for_result(result.cocycles[0]) == result.claim()
    assert claim_graph_for_result(result.classes[1]).verify().verified
    assert result.verify()
    assert result.claim().verify().verified
    assert twist_classes(acting, coefficients).content_id == result.content_id


def test_twist_receipt_rejects_missing_cocycle_and_vector_space_operations() -> None:
    result = nonabelian_h1(cyclic_group(2), symmetric_group(3))
    assert isinstance(result, TwistClassSet)
    payload = result.receipt.to_dict()
    payload["cocycles"] = payload["cocycles"][:-1]
    forged = TwistReceipt.from_dict(payload)
    with pytest.raises(ArithmeticCertificateError, match="complete exhaustive"):
        forged.verify()
    with pytest.raises(TypeError):
        _ = result.basepoint + result.classes[1]  # type: ignore[operator]


def test_decomposition_quotient_h1_is_not_a_local_h1_space() -> None:
    class PrimeField:
        characteristic = 2
        order = 2

    class Module:
        field = PrimeField()
        dimension = 1

        @staticmethod
        def action_matrix(_element: object) -> tuple[tuple[int, ...], ...]:
            return ((1,),)

    result = decomposition_quotient_h1(cyclic_group(2), Module())
    assert result.dimension == 1
    assert not isinstance(result, LocalH1Space)
    assert result.verify()


def test_local_arithmetic_plans_are_deterministic_and_strict(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    space = kummer_space(field, (two_adic, real))
    assert isinstance(space, KummerSpace)
    local_plan = plan_local_h1((real, two_adic))
    local_results = local_plan.run_all()
    local_spaces = local_plan.reduce(local_results)
    assert all(isinstance(item, LocalH1Space) for item in local_spaces)
    with pytest.raises(ShardReductionError, match="reordered"):
        local_plan.reduce(tuple(reversed(local_results)))
    duplicate = (local_results[0], local_results[0])
    with pytest.raises(ShardReductionError, match="duplicate"):
        local_plan.reduce(duplicate)
    foreign = replace(local_results[0], plan_id="sha256:" + "0" * 64)
    with pytest.raises(ShardReductionError, match="foreign"):
        local_plan.reduce((foreign, *local_results[1:]))

    complete_locals = tuple(item for item in local_spaces if isinstance(item, LocalH1Space))
    localization_plan = plan_localize(space, complete_locals)
    localization_results = localization_plan.run_all()
    maps = localization_plan.reduce(localization_results)
    assert len(maps) == 2
    assert all(item.verify() for item in maps)
    with pytest.raises(ShardReductionError, match="reordered"):
        localization_plan.reduce(tuple(reversed(localization_results)))


def test_galois_claim_replays_in_a_fresh_python_process(
    rational_places: tuple[NumberField, FinitePlace, InfinitePlace],
) -> None:
    field, two_adic, real = rational_places
    space = kummer_space(field, (two_adic, real))
    assert isinstance(space, KummerSpace)
    encoded = json.dumps(space.claim().to_dict())
    program = """
import json, sys
from arbogast.claims import Claim
claim = Claim.from_dict(json.load(sys.stdin))
assert claim.verify().verified
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
