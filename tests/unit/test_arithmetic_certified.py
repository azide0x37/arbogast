from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field, replace

import pytest

from arbogast.arithmetic import (
    AffineFamily,
    ArithmeticError,
    ArithmeticReceipt,
    ArithmeticVerificationError,
    CartierDual,
    KummerDescentProblem,
    LeftNullspaceObstruction,
    LocalCondition,
    LocalPairing,
    Obstructed,
    Realized,
    SelmerGroup,
    SelmerKernel,
    SelmerProblem,
    Unknown,
    aim,
    dual_selmer,
    elementary_descent,
    selmer,
    unique,
)
from arbogast.arithmetic.plans import SelmerPlanError, plan_selmer
from arbogast.arithmetic.semantic import (
    _status,
    claim_for_receipt,
    claim_for_result,
    claim_graph_for_result,
    verification_certificate_for_result,
)
from arbogast.cert import CertificateRef, VerificationCertificate, default_verifiers
from arbogast.claims import Claim
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois import (
    Completeness,
    FiniteGaloisQuotient,
    FinitePlace,
    InfinitePlace,
    LocalizationMap,
    NumberField,
    ProofContext,
    Unsupported,
    VerificationRequirement,
    galois_module,
    kummer_space,
    local_h1,
    localize,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup


@dataclass(frozen=True, slots=True)
class ToySpace(CanonicalObject):
    label: str
    dimension: int
    place: str | None = None
    places: tuple[str, ...] = ()
    proof_context: ProofContext = field(default_factory=ProofContext)
    prime: int = 2
    proving_certificates: tuple[VerificationCertificate, ...] = ()

    @property
    def field(self) -> PrimeField:
        return PrimeField(self.prime)

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    def verify(self) -> bool:
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "dimension": self.dimension,
            "label": self.label,
            "place": self.place,
            "places": list(self.places),
            "prime": self.prime,
            "proof_context": self.proof_context.to_canonical_data(),
            "type": "test.toy_space",
        }


@pytest.fixture
def rational_selmer() -> tuple[SelmerProblem, object, object]:
    field = NumberField.rationals()
    at_two = FinitePlace(field, 2, ((2,),), 1, 1)
    at_real = InfinitePlace(field, "real", (-1, 1))
    global_space = kummer_space(field, (at_two, at_real))
    assert not isinstance(global_space, Unsupported)
    two_space = local_h1(at_two)
    real_space = local_h1(at_real)
    at_two_map = localize(global_space, two_space)
    at_real_map = localize(global_space, real_space)
    at_two_condition = LocalCondition(two_space, ((1, 0, 0),))
    at_real_condition = LocalCondition(real_space, ((1,),))
    return (
        SelmerProblem(
            global_space,
            (at_two_map, at_real_map),
            (at_two_condition, at_real_condition),
        ),
        two_space,
        real_space,
    )


def _mu2_cartier_dual(dimension: int = 1) -> CartierDual:
    group = CyclicGroup(1)
    quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="mu2-coefficient-quotient",
    )
    field = PrimeField(2)
    module = galois_module(
        quotient,
        field,
        {group.identity: DenseMatrix.identity(field, dimension)},
        name="mu2",
    )
    return CartierDual(module)


def test_complete_q_selmer_promotes_only_after_nested_replay(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, _, _ = rational_selmer
    result = selmer(problem)

    assert problem.place_set_complete
    assert isinstance(result, SelmerGroup)
    assert result.dimension == 1
    assert result.basis == ((1, 0),)
    assert result.receipt.evidence
    assert result.verify().valid
    assert result.claim().status.value == "exact"
    assert result.claim().verify().verified
    assert result.claim_graph().verify().verified
    assert verification_certificate_for_result(result) == result.certificate
    assert claim_for_result(result) == result.claim()
    assert claim_graph_for_result(result).to_dict() == result.claim_graph().to_dict()
    with pytest.raises(TypeError, match="ArithmeticSemanticResult"):
        verification_certificate_for_result(object())  # type: ignore[arg-type]


def test_complete_kummer_space_with_incomplete_relevant_places_stays_candidate() -> None:
    field = NumberField.rationals()
    at_real = InfinitePlace(field, "real", (-1, 1))
    global_space = kummer_space(field, (at_real,))
    assert not isinstance(global_space, Unsupported)
    assert global_space.completeness is Completeness.COMPLETE
    assert not global_space.relevant_places_complete
    real_space = local_h1(at_real)
    localization = localize(global_space, real_space)
    condition = LocalCondition(real_space, ((1,),))

    problem = SelmerProblem(global_space, (localization,), (condition,))
    result = selmer(problem)

    assert not problem.place_set_complete
    assert problem.completeness is Completeness.CANDIDATE
    assert type(result) is SelmerKernel


def test_structural_flags_and_manual_place_assertions_never_promote() -> None:
    global_space = ToySpace("global", 2, places=("v",))
    local_space = ToySpace("local", 1, place="v")
    condition = LocalCondition(local_space, ((1,),))
    problem = SelmerProblem(
        global_space,
        DenseMatrix(PrimeField(2), ((1, 0),)),
        condition,
        places=("v",),
        place_set_complete=True,
    )

    assert not problem.place_set_complete
    result = selmer(problem)
    assert type(result) is SelmerKernel
    assert result.completeness is Completeness.CANDIDATE

    forged_context = ProofContext(completeness=Completeness.COMPLETE)
    forged_space = ToySpace("forged", 1, place="v", proof_context=forged_context)
    with pytest.raises(ArithmeticError, match="cannot be COMPLETE"):
        LocalCondition(forged_space, ((1,),))


def test_external_completeness_requires_concrete_nested_evidence() -> None:
    verifier_name = "tests.arithmetic.pinned-external.v1"
    leaf_verifier = "tests.arithmetic.portable-leaf.v1"
    replayed: list[str] = []

    def replay(certificate: VerificationCertificate) -> bool:
        replayed.append(verifier_name)
        return certificate.witness.to_dict() == {"version": "test-1"}

    def replay_leaf(certificate: VerificationCertificate) -> bool:
        replayed.append(leaf_verifier)
        return certificate.witness.to_dict() == {"finite": True}

    default_verifiers.register(verifier_name, VerificationCertificate, replay)
    default_verifiers.register(
        leaf_verifier,
        VerificationCertificate,
        replay_leaf,
    )
    try:
        requirement = VerificationRequirement.pinned_external(
            verifier_name,
            "test-1",
        )
        context = ProofContext(
            verification_requirements=(requirement,),
            completeness=Completeness.COMPLETE,
        )
        forged = ToySpace("forged-external", 1, place="v", proof_context=context)
        with pytest.raises(ArithmeticError, match="cannot be COMPLETE"):
            LocalCondition(forged, ((1,),))

        leaf = VerificationCertificate.create(
            "test portable leaf",
            leaf_verifier,
            witness={"finite": True},
        )
        external = VerificationCertificate.create(
            "test external completeness",
            verifier_name,
            witness={"version": "test-1"},
            dependencies=(CertificateRef.from_certificate(leaf),),
        )
        certified = ToySpace(
            "certified-external",
            1,
            place="v",
            proof_context=context,
            proving_certificates=(external, leaf),
        )
        condition = LocalCondition(certified, ((1,),))
        assert condition.completeness is Completeness.COMPLETE
        assert condition.verify().valid
        claim = condition.claim()
        assert claim.status.value == "certified"
        assert claim.verify().verified
        assert condition.claim_graph().verify().verified
        assert Claim.from_dict(claim.to_dict()).verify().verified
        assert {verifier_name, leaf_verifier} <= set(replayed)
    finally:
        default_verifiers.unregister(verifier_name)
        default_verifiers.unregister(leaf_verifier)


def test_caller_supplied_localization_matrix_cannot_promote_selmer() -> None:
    field = NumberField.rationals()
    at_two = FinitePlace(field, 2, ((2,),), 1, 1)
    at_real = InfinitePlace(field, "real", (-1, 1))
    global_space = kummer_space(field, (at_two, at_real))
    assert not isinstance(global_space, Unsupported)
    two_space = local_h1(at_two)
    real_space = local_h1(at_real)
    assert not isinstance(two_space, Unsupported)
    assert not isinstance(real_space, Unsupported)
    forged = LocalizationMap(
        global_space,
        two_space,
        DenseMatrix.zeros(PrimeField(2), two_space.dimension, global_space.dimension),
    )
    assert forged.completeness is Completeness.CANDIDATE
    real_map = localize(global_space, real_space)
    conditions = (
        LocalCondition(two_space, ((1, 0, 0),)),
        LocalCondition(real_space, ((1,),)),
    )
    problem = SelmerProblem(global_space, (forged, real_map), conditions)
    assert type(selmer(problem)) is SelmerKernel


def test_aim_returns_affine_family_or_literal_separator() -> None:
    field = PrimeField(2)
    matrix = DenseMatrix(field, ((1, 0), (0, 0)))

    solved = aim(matrix, (1, 0))
    assert isinstance(solved, AffineFamily)
    assert solved.representative == (1, 0)
    assert solved.kernel.basis == ((0, 1),)
    assert not unique(solved)
    assert solved.verify().valid

    obstructed = aim(matrix, (0, 1))
    assert isinstance(obstructed, LeftNullspaceObstruction)
    assert matrix.transpose().matvec(obstructed.witness) == (0, 0)
    assert obstructed.pairing == 1
    assert not unique(obstructed)
    assert obstructed.verify().valid


def test_dual_selmer_rejects_degenerate_pairing_before_orthogonals(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, two_space, real_space = rational_selmer
    field = PrimeField(2)
    degenerate = LocalPairing(two_space, two_space, DenseMatrix.zeros(field, 3, 3))
    real = LocalPairing(real_space, real_space, DenseMatrix.identity(field, 1))

    with pytest.raises(ArithmeticError, match="perfect"):
        dual_selmer(problem, pairings=(degenerate, real))

    candidate = LocalPairing(two_space, two_space, DenseMatrix.identity(field, 3))
    assert candidate.completeness is Completeness.CANDIDATE
    with pytest.raises(ArithmeticError, match="certified perfect"):
        dual_selmer(
            problem,
            pairings=(candidate, real),
            cartier_dual=_mu2_cartier_dual(),
        )

    perfect = LocalPairing.hilbert(two_space)
    certified_real = LocalPairing.hilbert(real_space)
    with pytest.raises(ArithmeticError, match="explicit certified CartierDual"):
        dual_selmer(problem, pairings=(perfect, certified_real))
    with pytest.raises(ArithmeticError, match="one-dimensional trivial Cartier dual"):
        dual_selmer(
            problem,
            pairings=(perfect, certified_real),
            cartier_dual=_mu2_cartier_dual(2),
        )
    result = dual_selmer(
        problem,
        pairings=(perfect, certified_real),
        cartier_dual=_mu2_cartier_dual(),
    )
    assert result.dimension == 1
    assert result.verify().valid


def test_elementary_descent_has_three_nonconflated_outcomes() -> None:
    field = PrimeField(2)
    realized_problem = KummerDescentProblem(DenseMatrix(field, ((1, 0),)), (1,))
    obstructed_problem = KummerDescentProblem(DenseMatrix(field, ((0, 0),)), (1,))
    unknown_problem = KummerDescentProblem(
        DenseMatrix(field, ((1, 0),)),
        (1,),
        linear_realization=False,
        search_complete=True,
    )

    realized = elementary_descent(realized_problem)
    obstructed = elementary_descent(obstructed_problem)
    unknown = elementary_descent(unknown_problem)
    assert isinstance(realized, Realized)
    assert isinstance(obstructed, Obstructed)
    assert isinstance(unknown, Unknown)
    assert "no checked global realization" in unknown.reason
    assert realized.verify().valid
    assert obstructed.verify().valid
    assert unknown.verify().valid


def test_descent_cannot_promote_local_consistency_to_global_realization(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, _, _ = rational_selmer
    target = (0,) * problem.global_to_local_quotient.nrows
    with pytest.raises(ArithmeticError, match="bare finite linear problem"):
        KummerDescentProblem(problem, target, linear_realization=True)
    with pytest.raises(ArithmeticError, match="certified global witness"):
        KummerDescentProblem(problem, target, witness=(0,) * problem.global_dimension)

    zero = getattr(problem.global_space, "zero", None)
    assert callable(zero)
    global_zero = zero()
    without_witness = KummerDescentProblem(problem, target)
    with pytest.raises(ArithmeticError, match="certified global witness"):
        Realized(without_witness, (0,) * problem.global_dimension)
    realized = elementary_descent(KummerDescentProblem(problem, target, witness=global_zero))
    assert isinstance(realized, Realized)
    assert realized.verify().valid

    payload = realized.receipt.payload.to_dict()
    payload["witness_certificate_id"] = "sha256:" + "0" * 64
    rebound = ArithmeticReceipt.create(
        "descent-realized",
        payload,
        context=realized.proof_context,
        evidence=realized.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="missing Kummer-class evidence"):
        rebound.verify()


def test_receipts_reject_completeness_place_pairing_and_dependency_forgery(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, two_space, _ = rational_selmer
    group = selmer(problem)

    place_payload = group.receipt.payload.to_dict()
    place_payload["place_set_complete"] = False
    bad_place = ArithmeticReceipt.create(
        "selmer-group",
        place_payload,
        context=group.proof_context,
        evidence=group.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="incomplete place set"):
        bad_place.verify()

    candidate_problem = SelmerProblem(
        ToySpace("global", 1, places=("v",)),
        DenseMatrix(PrimeField(2), ((1,),)),
        LocalCondition(ToySpace("local", 1, place="v"), ((1,),)),
        places=("v",),
        place_set_complete=True,
    )
    candidate = selmer(candidate_problem)
    forged_complete = ArithmeticReceipt.create(
        "selmer-group",
        candidate.receipt.payload.to_dict(),
        context=ProofContext(
            verification_requirements=(
                VerificationRequirement.portable_python("arithmetic.finite-linear.v1"),
            ),
            completeness=Completeness.COMPLETE,
        ),
    )
    with pytest.raises(ArithmeticVerificationError, match="nest its input certificates"):
        forged_complete.verify()

    pairing = LocalPairing.hilbert(two_space)
    pairing_payload = pairing.receipt.payload.to_dict()
    pairing_payload["perfect"] = False
    bad_pairing = ArithmeticReceipt.create(
        "local-pairing",
        pairing_payload,
        context=pairing.proof_context,
        evidence=pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="perfectness flag"):
        bad_pairing.verify()

    matrix_payload = pairing.receipt.payload.to_dict()
    pairing_matrix = matrix_payload["matrix"]
    assert isinstance(pairing_matrix, list)
    first_row = pairing_matrix[0]
    assert isinstance(first_row, list)
    first_row[1] = 1
    bad_matrix = ArithmeticReceipt.create(
        "local-pairing",
        matrix_payload,
        context=pairing.proof_context,
        evidence=pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="Hilbert pairing matrix"):
        bad_matrix.verify()

    witness_payload = pairing.receipt.payload.to_dict()
    pairing_witness = witness_payload["pairing_witness"]
    assert isinstance(pairing_witness, dict)
    left_values = pairing_witness["left_values"]
    assert isinstance(left_values, list)
    left_values[0] = [1, 1]
    bad_witness = ArithmeticReceipt.create(
        "local-pairing",
        witness_payload,
        context=pairing.proof_context,
        evidence=pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="different local bases"):
        bad_witness.verify()

    candidate_pairing = LocalPairing(
        two_space,
        two_space,
        DenseMatrix.identity(PrimeField(2), 3),
    )
    forged_pairing = ArithmeticReceipt.create(
        "local-pairing",
        candidate_pairing.receipt.payload.to_dict(),
        context=ProofContext(
            verification_requirements=candidate_pairing.proof_context.verification_requirements,
            completeness=Completeness.COMPLETE,
        ),
        evidence=candidate_pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="lacks a replayable"):
        forged_pairing.verify()

    external = ProofContext(
        verification_requirements=(
            VerificationRequirement.pinned_external("pari.missing", "2.17.4"),
        ),
        completeness=Completeness.COMPLETE,
    )
    missing_external = ArithmeticReceipt.create(
        "selmer-group",
        group.receipt.payload.to_dict(),
        context=external,
    )
    assert _status(missing_external).value == "exact"
    with pytest.raises(ArithmeticVerificationError, match="lacks nested evidence"):
        missing_external.verify()

    rebound_global_payload = group.receipt.payload.to_dict()
    rebound_global_payload["global_certificate_id"] = "sha256:" + "0" * 64
    rebound_global = ArithmeticReceipt.create(
        "selmer-group",
        rebound_global_payload,
        context=group.proof_context,
        evidence=group.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="lacks its Kummer certificate"):
        rebound_global.verify()

    rebound_local_payload = group.receipt.payload.to_dict()
    local_blocks = rebound_local_payload["local_blocks"]
    assert isinstance(local_blocks, list)
    first_block = local_blocks[0]
    assert isinstance(first_block, dict)
    first_block["condition_certificate_id"] = "sha256:" + "0" * 64
    rebound_local = ArithmeticReceipt.create(
        "selmer-group",
        rebound_local_payload,
        context=group.proof_context,
        evidence=group.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="names missing evidence"):
        rebound_local.verify()

    cartier = _mu2_cartier_dual()
    evidence_by_id = {
        certificate.certificate_id: certificate for certificate in cartier.receipt.evidence
    }
    assert evidence_by_id
    assert all(
        reference.certificate_id in evidence_by_id
        for certificate in cartier.receipt.evidence
        for reference in certificate.dependencies
    )
    assert cartier.claim().verify().verified
    assert cartier.claim_graph().verify().verified
    assert Claim.from_dict(cartier.claim().to_dict()).verify().verified
    module_certificate = next(
        certificate
        for certificate in cartier.receipt.evidence
        if certificate.verifier == "galois.module.v1"
    )
    assert module_certificate.dependencies
    omitted_dependency = module_certificate.dependencies[0].certificate_id
    incomplete_evidence = tuple(
        certificate
        for certificate in cartier.receipt.evidence
        if certificate.certificate_id != omitted_dependency
    )
    incomplete_cartier = ArithmeticReceipt.create(
        "cartier-dual",
        cartier.receipt.payload.to_dict(),
        context=cartier.proof_context,
        evidence=incomplete_evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="lacks dependency"):
        incomplete_cartier.verify()
    with pytest.raises(ArithmeticVerificationError, match="lacks dependency"):
        claim_for_receipt(incomplete_cartier)

    cartier_payload = cartier.receipt.payload.to_dict()
    cartier_payload["dual_action_matrices"] = [[[0]]]
    rebound_cartier = ArithmeticReceipt.create(
        "cartier-dual",
        cartier_payload,
        context=cartier.proof_context,
        evidence=cartier.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="singular action matrix"):
        rebound_cartier.verify()

    conditional_context = ProofContext(
        assumptions=("GRH",),
        verification_requirements=group.proof_context.verification_requirements,
        completeness=group.completeness,
    )
    conditional = ArithmeticReceipt.create(
        "selmer-group",
        group.receipt.payload.to_dict(),
        context=conditional_context,
        evidence=group.receipt.evidence,
    )
    conditional_claim = claim_for_receipt(conditional)
    assert conditional_claim.status.value == "conditional"
    assert conditional_claim.verify().verified


def test_selmer_plan_rejects_missing_duplicate_foreign_and_reordered_blocks(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, _, _ = rational_selmer
    plan = plan_selmer(problem)
    blocks = plan.run_all()
    assert plan.shard_specs == plan.tasks
    assert isinstance(plan.reduce(blocks), SelmerGroup)

    with pytest.raises(SelmerPlanError, match="missing or extra"):
        plan.reduce(blocks[:-1])
    with pytest.raises(SelmerPlanError, match=r"duplicate|reordered"):
        plan.reduce((blocks[0], blocks[0], *blocks[2:]))
    with pytest.raises(SelmerPlanError, match="reordered"):
        plan.reduce(tuple(reversed(blocks)))
    with pytest.raises(SelmerPlanError, match="foreign"):
        plan.reduce((replace(blocks[0], plan_id="sha256:" + "0" * 64), *blocks[1:]))
    with pytest.raises(SelmerPlanError, match="not bound"):
        plan.reduce(
            (
                replace(
                    blocks[0],
                    local_condition_certificate_id="sha256:" + "0" * 64,
                ),
                *blocks[1:],
            )
        )


def test_public_arithmetic_function_surface_is_additive() -> None:
    import arbogast.arithmetic as arithmetic

    functions = {
        "aim",
        "dual_selmer",
        "elementary_descent",
        "local_condition",
        "selmer",
        "unique",
    }
    assert functions <= set(arithmetic.__all__)
    assert "plan_selmer" not in arithmetic.__all__


def test_selmer_claim_replays_in_a_fresh_python_process(
    rational_selmer: tuple[SelmerProblem, object, object],
) -> None:
    problem, _, _ = rational_selmer
    encoded = json.dumps(selmer(problem).claim().to_dict())
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
