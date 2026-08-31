from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from arbogast.bootstrap import (
    BootstrapError,
    CertifiedBlocked,
    CertifiedReady,
    EnvironmentSnapshot,
    ReadinessProfile,
    ReadinessResult,
    certify_campaign_readiness,
)
from arbogast.campaign import (
    AttemptRecord,
    Campaign,
    CampaignInvariantError,
    CampaignPlan,
    CampaignReadinessError,
    CampaignSerializationError,
    CandidateEvidence,
    Observation,
    OperationalState,
    Outcome,
    OutcomeScope,
    Strategy,
    TargetSpec,
    closure_certificate,
)
from arbogast.cert import VerificationCertificate, VerifierRegistry
from arbogast.fleet import (
    LOCAL_ECHO_OPERATION,
    FleetOperationRegistry,
    LocalExecutor,
    default_fleet_operation_registry,
)

_PRIVATE_CLOSURE_VERIFIER = "test.campaign.private-readiness-closure.v1"
_ROGUE_CLOSURE_VERIFIER = "test.campaign.rogue-readiness-closure.v1"


def _private_closure_verifier(certificate: VerificationCertificate) -> bool:
    witness = certificate.witness.to_dict()
    return (
        certificate.subject.endswith(":TARGET_GLOBAL:FOUND")
        and isinstance(witness.get("result_ref"), str)
        and isinstance(witness.get("task_hash"), str)
    )


def _closure_bound_campaign(
    tmp_path: Path,
    *,
    closure_verifiers: tuple[str, ...],
    registered_verifiers: tuple[str, ...],
) -> tuple[Campaign, CampaignPlan, FleetOperationRegistry, VerifierRegistry, LocalExecutor]:
    defaults = default_fleet_operation_registry()
    operation = replace(
        defaults.resolve(LOCAL_ECHO_OPERATION),
        closure_verifiers=closure_verifiers,
    )
    operations = FleetOperationRegistry({LOCAL_ECHO_OPERATION: operation})
    verifiers = VerifierRegistry()
    for verifier_name in registered_verifiers:
        verifiers.register(
            verifier_name,
            VerificationCertificate,
            _private_closure_verifier,
        )
    executor = LocalExecutor(tmp_path / "closure-fleet")
    campaign = Campaign(
        "closure-verifier-readiness",
        objective="bind every possible verified result closure to certified V",
        targets=(TargetSpec("case:closure-verifier"),),
        strategies=(
            Strategy(
                "verified-echo",
                LOCAL_ECHO_OPERATION,
                "exercise operation-derived closure verifier requirements",
                verify_results=True,
            ),
        ),
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
        strict_readiness=True,
    )
    return campaign, campaign.recommend(limit=1), operations, verifiers, executor


def _activate_closure_bound_case(
    tmp_path: Path,
) -> tuple[Campaign, CampaignPlan, VerifierRegistry]:
    campaign, plan, operations, verifiers, executor = _closure_bound_campaign(
        tmp_path,
        closure_verifiers=(_PRIVATE_CLOSURE_VERIFIER,),
        registered_verifiers=(
            _PRIVATE_CLOSURE_VERIFIER,
            _ROGUE_CLOSURE_VERIFIER,
        ),
    )
    environment = EnvironmentSnapshot.capture(project_root=Path.cwd())
    profile = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
    )
    assert profile.required_verifiers == (_PRIVATE_CLOSURE_VERIFIER,)
    result = certify_campaign_readiness(environment=environment, profile=profile)
    assert isinstance(result, CertifiedReady)
    campaign.record_environment_claim(result.claim())
    campaign.activate_readiness(result.certificate, environment=environment)
    return campaign, plan, verifiers


def _closure_observation(
    plan: CampaignPlan,
    verifier: str,
) -> Observation:
    task = plan.recommendations[0].task
    result_ref = "sha256:" + "9" * 64
    certificate = closure_certificate(
        task.target_id,
        Outcome.FOUND,
        verifier,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        task_hash=task.task.task_hash,
        witness={"result_ref": result_ref},
    )
    return Observation(
        task.target_id,
        task.campaign_task_id,
        Outcome.FOUND,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        certificate=certificate,
        result_ref=result_ref,
        input_refs=task.task.input_refs,
        parameters=task.provenance.parameters.to_dict(),
        source_refs=task.provenance.source_refs,
    )


@dataclass(frozen=True)
class _ReadyCase:
    campaign: Campaign
    plan: CampaignPlan
    environment: EnvironmentSnapshot
    profile: ReadinessProfile
    result: ReadinessResult
    operations: FleetOperationRegistry
    verifiers: VerifierRegistry
    executor: LocalExecutor


def _campaign(
    tmp_path: Path,
    *,
    target_count: int = 1,
    strict_readiness: bool = True,
) -> tuple[Campaign, FleetOperationRegistry, VerifierRegistry, LocalExecutor]:
    operations = default_fleet_operation_registry()
    verifiers = VerifierRegistry()
    executor = LocalExecutor(tmp_path / "fleet")
    campaign = Campaign(
        "environmental-readiness-integration",
        objective="exercise an exact environmental dispatch gate",
        targets=tuple(TargetSpec(f"case:ready-{index}") for index in range(target_count)),
        strategies=(
            Strategy(
                "bounded-echo",
                LOCAL_ECHO_OPERATION,
                "run the fixed finite echo operation",
            ),
        ),
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
        strict_readiness=strict_readiness,
    )
    return campaign, operations, verifiers, executor


def _ready_case(tmp_path: Path, *, target_count: int = 1) -> _ReadyCase:
    campaign, operations, verifiers, executor = _campaign(
        tmp_path,
        target_count=target_count,
    )
    plan = campaign.recommend(limit=1)
    environment = EnvironmentSnapshot.capture(
        project_root=Path.cwd(),
        capabilities=campaign.capabilities or (),
    )
    profile = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
    )
    result = certify_campaign_readiness(
        environment=environment,
        profile=profile,
    )
    assert isinstance(result, CertifiedReady)
    return _ReadyCase(
        campaign,
        plan,
        environment,
        profile,
        result,
        operations,
        verifiers,
        executor,
    )


def test_verified_plan_derives_closure_verifier_and_caller_cannot_substitute(
    tmp_path: Path,
) -> None:
    campaign, plan, operations, verifiers, executor = _closure_bound_campaign(
        tmp_path,
        closure_verifiers=(_PRIVATE_CLOSURE_VERIFIER,),
        registered_verifiers=(
            _PRIVATE_CLOSURE_VERIFIER,
            _ROGUE_CLOSURE_VERIFIER,
        ),
    )

    omitted = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
    )
    attempted_substitution = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
        required_verifiers=(_ROGUE_CLOSURE_VERIFIER,),
    )

    assert omitted.required_verifiers == (_PRIVATE_CLOSURE_VERIFIER,)
    assert attempted_substitution.required_verifiers == (
        _PRIVATE_CLOSURE_VERIFIER,
        _ROGUE_CLOSURE_VERIFIER,
    )


def test_verified_plan_rejects_operation_without_closure_verifier_contract(
    tmp_path: Path,
) -> None:
    campaign, plan, operations, verifiers, executor = _closure_bound_campaign(
        tmp_path,
        closure_verifiers=(),
        registered_verifiers=(_PRIVATE_CLOSURE_VERIFIER,),
    )

    with pytest.raises(BootstrapError, match="declares no closure verifiers"):
        ReadinessProfile.from_plan(
            campaign,
            plan,
            operations,
            verifiers,
            executor,
            required_verifiers=(_PRIVATE_CLOSURE_VERIFIER,),
        )


def test_derived_closure_verifier_absence_is_bound_as_missing_v(tmp_path: Path) -> None:
    campaign, plan, operations, verifiers, executor = _closure_bound_campaign(
        tmp_path,
        closure_verifiers=(_PRIVATE_CLOSURE_VERIFIER,),
        registered_verifiers=(_ROGUE_CLOSURE_VERIFIER,),
    )

    profile = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
    )

    assert profile.required_verifiers == (_PRIVATE_CLOSURE_VERIFIER,)
    assert profile.verifier_registry.manifest["missing"] == (_PRIVATE_CLOSURE_VERIFIER,)


def test_active_derived_private_v_allows_its_exact_closure(tmp_path: Path) -> None:
    campaign, plan, _ = _activate_closure_bound_case(tmp_path)

    campaign.observe(_closure_observation(plan, _PRIVATE_CLOSURE_VERIFIER))

    task = plan.recommendations[0].task
    assert campaign.ledger.status(task.target_id).closed


def test_active_readiness_rejects_registered_verifier_outside_required_v_roster(
    tmp_path: Path,
) -> None:
    campaign, plan, verifiers = _activate_closure_bound_case(tmp_path)
    rogue = _closure_observation(plan, _ROGUE_CLOSURE_VERIFIER)

    assert rogue.verify(verifiers)
    with pytest.raises(CampaignInvariantError, match="certified required V roster"):
        campaign.observe(rogue)

    task = plan.recommendations[0].task
    assert campaign.ledger.status(task.target_id).open
    assert campaign.ledger.observations_for_task(task.campaign_task_id) == ()


def test_strict_dispatch_refuses_before_any_ledger_mutation(tmp_path: Path) -> None:
    campaign, _, _, _ = _campaign(tmp_path)
    before = campaign.to_json()
    event_ids = tuple(item.event_id for item in campaign.ledger.events)

    with pytest.raises(CampaignReadinessError) as raised:
        campaign.dispatch()

    assert raised.value.code == "READINESS_NOT_ACTIVE"
    assert campaign.to_json() == before
    assert tuple(item.event_id for item in campaign.ledger.events) == event_ids
    assert campaign.ledger.plan_documents == ()
    assert campaign.ledger.observations == ()


def test_certificate_only_activation_is_runtime_only_and_run_records_provenance(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    claim = case.result.claim()
    case.campaign.record_environment_claim(claim)
    persistent_bytes = case.campaign.to_json()

    report = case.campaign.activate_readiness(case.result.certificate)

    assert report.valid
    assert case.campaign.to_json() == persistent_bytes
    assert case.campaign.active_readiness_certificate == case.result.certificate
    readiness = case.campaign.status().readiness
    assert readiness["active"] is True
    assert readiness["valid"] is True
    assert readiness["claim_id"] == claim.id
    plan_count = len(case.campaign.ledger.plan_documents)

    observations = case.campaign.run(limit=1)

    assert len(observations) == 1
    assert len(case.campaign.ledger.plan_documents) == plan_count
    task = case.plan.recommendations[0].task
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    assert len(attempts) == 2
    assert {item.readiness_claim_id for item in attempts} == {claim.id}
    assert all(item.to_dict()["readiness_claim_id"] == claim.id for item in attempts)

    case.campaign.deactivate_readiness()
    assert case.campaign.active_readiness_certificate is None
    saved = case.campaign.to_json()
    restored = Campaign.from_json(
        saved,
        executor=case.executor,
        operation_registry=case.operations,
        verifier_registry=case.verifiers,
        strict_readiness=True,
    )
    assert restored.to_json() == saved
    assert restored.active_readiness_certificate is None
    assert claim.id in restored.claims
    with pytest.raises(CampaignReadinessError, match="active readiness theorem"):
        restored.dispatch(task.campaign_task_id)

    # Runtime authority has no additive campaign transport field.  The
    # environmental claim and its certificate legitimately remain in history.
    assert set(case.campaign.to_dict()) == {
        "campaign_id",
        "claims",
        "ledger",
        "schema",
        "spec",
    }


def test_activation_requires_the_exact_recorded_certificate_boundary(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    substituted_environment = replace(
        case.environment,
        platform=f"{case.environment.platform}-substituted",
    )
    substituted = certify_campaign_readiness(
        environment=substituted_environment,
        profile=case.profile,
    )
    assert isinstance(substituted, CertifiedReady)
    assert substituted.claim().id != case.result.claim().id
    assert substituted.certificate.certificate_id != case.result.certificate.certificate_id
    recorded = case.result.claim()
    case.campaign.record_environment_claim(recorded)
    # Simulate an in-memory graph substitution that preserves the dictionary
    # key/claim ID while changing the exact environmental statement boundary.
    # The public Claim constructor and strict replay reject this naturally;
    # activation must still defend its final certificate-to-claim join.
    object.__setattr__(recorded, "what", substituted.claim().what)

    with pytest.raises(CampaignReadinessError) as raised:
        case.campaign.activate_readiness(
            case.result.certificate,
            environment=case.environment,
        )

    assert raised.value.code == "READINESS_CLAIM_CERTIFICATE_MISMATCH"
    assert case.campaign.active_readiness_certificate is None


def test_non_ready_and_out_of_roster_work_are_refused_without_mutation(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path, target_count=2)
    blocked_environment = replace(case.environment, python_version="2.7.18")
    blocked = certify_campaign_readiness(
        environment=blocked_environment,
        profile=case.profile,
        run_fresh_process=False,
    )
    assert isinstance(blocked, CertifiedBlocked)
    case.campaign.record_environment_claim(blocked.claim())
    with pytest.raises(CampaignReadinessError) as blocked_error:
        case.campaign.activate_readiness(
            blocked.certificate,
            environment=blocked_environment,
        )
    assert blocked_error.value.code == "READINESS_ACTIVATION_INVALID"

    # Use a fresh graph because READY and BLOCKED determinations intentionally
    # have distinct environmental claim boundaries.
    ready = _ready_case(tmp_path / "ready-roster", target_count=2)
    ready.campaign.record_environment_claim(ready.result.claim())
    ready.campaign.activate_readiness(
        ready.result.certificate,
        environment=ready.environment,
    )
    certified_task_id = ready.plan.recommendations[0].task.campaign_task_id
    other_task = next(
        item for item in ready.campaign.tasks if item.campaign_task_id != certified_task_id
    )
    before = ready.campaign.to_json()
    with pytest.raises(CampaignReadinessError) as roster_error:
        ready.campaign.dispatch(other_task)
    assert roster_error.value.code == "READINESS_TASK_NOT_COVERED"
    assert ready.campaign.to_json() == before
    assert ready.campaign.status().blocked_tasks >= 1


def test_attempt_readiness_provenance_is_additive_to_legacy_v1_bytes() -> None:
    target_id = "sha256:" + "1" * 64
    task_id = "sha256:" + "2" * 64
    claim_id = "bootstrap.readiness.test.ready"
    legacy = AttemptRecord(
        target_id,
        task_id,
        1,
        OperationalState.RUNNING,
    )
    legacy_payload = legacy.to_dict()
    legacy_id = legacy.record_id

    assert "readiness_claim_id" not in legacy_payload
    assert AttemptRecord.from_dict(legacy_payload) == legacy
    assert AttemptRecord.from_dict(legacy_payload).record_id == legacy_id

    ready = AttemptRecord(
        target_id,
        task_id,
        1,
        OperationalState.RUNNING,
        readiness_claim_id=claim_id,
    )
    assert ready.to_dict()["readiness_claim_id"] == claim_id
    assert AttemptRecord.from_dict(ready.to_dict()) == ready
    assert ready.record_id != legacy_id


def test_private_campaign_verifier_drives_observation_candidate_and_replay(
    tmp_path: Path,
) -> None:
    campaign, operations, verifiers, executor = _campaign(
        tmp_path,
        strict_readiness=False,
    )
    verifiers.register(
        _PRIVATE_CLOSURE_VERIFIER,
        VerificationCertificate,
        _private_closure_verifier,
    )
    plan = campaign.recommend(limit=1)
    task = plan.recommendations[0].task
    result_ref = "sha256:" + "9" * 64
    certificate = closure_certificate(
        task.target_id,
        Outcome.FOUND,
        _PRIVATE_CLOSURE_VERIFIER,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        task_hash=task.task.task_hash,
        witness={"result_ref": result_ref},
    )
    observation = Observation(
        task.target_id,
        task.campaign_task_id,
        Outcome.FOUND,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        certificate=certificate,
        result_ref=result_ref,
        input_refs=task.task.input_refs,
        parameters=task.provenance.parameters.to_dict(),
        source_refs=task.provenance.source_refs,
        details={
            "result": {
                "candidates": [
                    {
                        "canonical_key": "private-verifier-candidate",
                        "canonicalizer": "test.private-canonicalizer/v1",
                        "equivalence_scope": "TARGET",
                        "evidence": CandidateEvidence.VERIFIED.value,
                    }
                ]
            }
        },
    )

    # Legacy standalone behavior remains global-default replay, while the
    # explicit and Campaign-bound paths honor the injected private V.
    assert not observation.verified
    assert not observation.verify(VerifierRegistry())
    assert observation.verify(verifiers)
    assert observation.closes_target_with(verifiers)

    campaign.observe(observation)

    assert campaign.ledger.status(task.target_id).closed
    candidates = campaign.ledger.candidates_for(task.target_id)
    assert len(candidates) == 1
    assert candidates[0].evidence is CandidateEvidence.VERIFIED
    payload = campaign.to_json()
    restored = Campaign.from_json(
        payload,
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
    )
    assert restored.to_json() == payload
    assert restored.ledger.status(task.target_id).closed

    with pytest.raises(CampaignSerializationError, match="verified candidate"):
        Campaign.from_json(
            payload,
            executor=executor,
            operation_registry=operations,
        )

    tampered = observation.to_dict()
    raw_certificate = tampered["certificate_payload"]
    assert isinstance(raw_certificate, dict)
    raw_witness = raw_certificate["witness"]
    assert isinstance(raw_witness, dict)
    raw_witness["result_ref"] = "sha256:" + "8" * 64
    with pytest.raises(CampaignInvariantError, match="strict replay"):
        Observation.from_dict(tampered, verifier_registry=verifiers)
