from __future__ import annotations

from fractions import Fraction

import pytest

from arbogast.campaign import (
    Campaign,
    CampaignError,
    CampaignInvariantError,
    CampaignSerializationError,
    CampaignSpec,
    CampaignTask,
    CapabilityUnavailableError,
    DerivationRule,
    EventKind,
    FunctionalGate,
    GateDecision,
    LedgerEvent,
    Observation,
    OperationalState,
    Outcome,
    OutcomeScope,
    PriorityPolicy,
    Strategy,
    TargetLedger,
    TargetSpec,
    closure_certificate,
)
from arbogast.cert import (
    CertificateLayer,
    CertificateRef,
    VerificationCertificate,
    default_verifiers,
)
from arbogast.fleet import TaskSpec
from arbogast.formats import FrozenMapping


def _test_closure_verifier(certificate: VerificationCertificate) -> bool:
    return certificate.subject.startswith("campaign:sha256:") and bool(certificate.checks)


for _verifier_name in ("test.parity", "test.exhaustion"):
    default_verifiers.register(
        _verifier_name,
        VerificationCertificate,
        _test_closure_verifier,
    )


def _task(target: TargetSpec, *, operation: str = "test.search") -> CampaignTask:
    return CampaignTask(
        TaskSpec(operation),
        target,
        "test-strategy",
        "exercise a finite exact candidate set",
    )


def test_preemption_and_timeout_states_never_close_a_target() -> None:
    target = TargetSpec("case:preempted")
    ledger = TargetLedger((target,))
    task = _task(target)
    ledger.plan_task(task)

    observation = Observation(
        target.target_id,
        task.campaign_task_id,
        Outcome.PREEMPTED,
        operational_state=OperationalState.PREEMPTED,
        checkpoint_ref="sha256:" + "1" * 64,
    )
    ledger.record(observation)

    state = ledger.status(target)
    assert state.open
    assert state.mathematical_outcome.value == "UNKNOWN"
    assert state.checkpoint_ref == "sha256:" + "1" * 64


def test_closure_rejects_missing_or_bare_certificate_reference() -> None:
    target = TargetSpec("case:proof-boundary")
    task = _task(target)
    fake_ref = CertificateRef("sha256:" + "0" * 64, CertificateLayer.VERIFICATION)

    with pytest.raises(CampaignInvariantError, match="embedded, replayable"):
        Observation(target.target_id, task.campaign_task_id, Outcome.FOUND)
    with pytest.raises(CampaignInvariantError, match="embedded, replayable"):
        Observation(
            target.target_id,
            task.campaign_task_id,
            Outcome.PROVED_IMPOSSIBLE,
            certificate_ref=fake_ref,
        )
    with pytest.raises(CampaignInvariantError, match="actual replayable"):
        GateDecision.impossible("local obstruction", fake_ref)


def test_unregistered_or_rejecting_verifier_cannot_close_target() -> None:
    target = TargetSpec("case:unregistered-verifier")
    task = _task(target)
    ledger = TargetLedger((target,))
    ledger.plan_task(task)
    certificate = closure_certificate(
        target.target_id,
        Outcome.FOUND,
        "test.no-such-verifier",
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        witness={"candidate": 1},
        checks=("candidate checked",),
    )
    observation = Observation(
        target.target_id,
        task.campaign_task_id,
        Outcome.FOUND,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        certificate=certificate,
    )
    ledger.record(observation)
    assert not observation.verified
    assert ledger.status(target).open


def test_exact_gate_can_close_only_with_bound_replayable_certificate() -> None:
    target = TargetSpec("case:local-obstruction")
    strategy = Strategy(
        "local-gate",
        "test.expensive-search",
        "run the exact local obstruction first",
        gate=FunctionalGate(
            "parity-obstruction",
            lambda candidate, _ledger: GateDecision.impossible(
                "parity obstruction",
                closure_certificate(
                    candidate.target_id,
                    Outcome.PROVED_IMPOSSIBLE,
                    "test.parity",
                    outcome_scope=OutcomeScope.TARGET_GLOBAL,
                    witness={"parity": 1},
                    checks=("parity is incompatible",),
                ),
                outcome_scope=OutcomeScope.TARGET_GLOBAL,
            ),
        ),
    )
    campaign = Campaign(
        "gate-demo",
        objective="Resolve the finite target",
        targets=(target,),
        strategies=(strategy,),
    )

    assert len(campaign.recommend()) == 0
    state = campaign.ledger.status(target)
    assert state.closed
    assert state.mathematical_outcome.value == "PROVED_IMPOSSIBLE"


def test_task_local_gate_obstruction_leaves_alternate_strategy_plannable() -> None:
    target = TargetSpec("case:local-obstruction-with-alternate")
    gated = Strategy(
        "locally-obstructed",
        "test.expensive-search",
        "rule out only this construction branch",
        gate=FunctionalGate(
            "branch-parity-obstruction",
            lambda candidate, _ledger: GateDecision.impossible(
                "this construction has the wrong parity",
                closure_certificate(
                    candidate.target_id,
                    Outcome.PROVED_IMPOSSIBLE,
                    "test.parity",
                    outcome_scope=OutcomeScope.TASK_LOCAL,
                    witness={"parity": 1},
                    checks=("branch parity is incompatible",),
                ),
            ),
        ),
    )
    alternate = Strategy(
        "alternate-construction",
        "test.alternate-search",
        "try a construction not covered by the local obstruction",
    )
    campaign = Campaign(
        "local-gate-demo",
        objective="Resolve the target using either construction",
        targets=(target,),
        strategies=(gated, alternate),
    )

    plan = campaign.recommend()

    assert campaign.ledger.status(target).open
    assert not campaign.claims.claims
    assert {item.task.strategy for item in plan.recommendations} == {"alternate-construction"}
    observations = campaign.ledger.observations_for(target)
    assert len(observations) == 1
    assert observations[0].verified
    assert observations[0].mathematical_outcome.value == "PROVED_IMPOSSIBLE"
    assert observations[0].outcome_scope is OutcomeScope.TASK_LOCAL
    assert not observations[0].closes_target


@pytest.mark.parametrize(
    "outcome",
    (Outcome.PROVED_IMPOSSIBLE, Outcome.SEARCH_EXHAUSTED),
)
def test_task_local_exact_outcome_does_not_suppress_another_strategy(
    outcome: Outcome,
) -> None:
    target = TargetSpec(f"case:local-{outcome.value.lower()}")
    first = Strategy("first-branch", "test.first", "search one declared branch")
    alternate = Strategy("alternate-branch", "test.alternate", "search a disjoint branch")
    campaign = Campaign(
        "local-outcome-demo",
        objective="Resolve the target across both branches",
        targets=(target,),
        strategies=(first, alternate),
    )
    initial = campaign.recommend()
    first_task = next(
        item.task for item in initial.recommendations if item.task.strategy == first.name
    )
    certificate = closure_certificate(
        target.target_id,
        outcome,
        "test.exhaustion",
        outcome_scope=OutcomeScope.TASK_LOCAL,
        task_hash=first_task.task.task_hash,
        witness={"branch": first.name},
        checks=("declared branch checked exactly",),
    )

    observation = Observation(
        target.target_id,
        first_task.campaign_task_id,
        outcome,
        outcome_scope=OutcomeScope.TASK_LOCAL,
        certificate=certificate,
        input_refs=first_task.task.input_refs,
        parameters=first_task.provenance.parameters.to_dict(),
        source_refs=first_task.provenance.source_refs,
    )
    campaign.observe(observation)
    replanned = campaign.recommend()

    assert observation.verified
    assert not observation.closes_target
    assert campaign.ledger.status(target).open
    assert not campaign.claims.claims
    assert {item.task.strategy for item in replanned.recommendations} == {alternate.name}


@pytest.mark.parametrize(
    "outcome",
    (Outcome.FOUND, Outcome.PROVED_IMPOSSIBLE, Outcome.SEARCH_EXHAUSTED),
)
def test_explicit_target_global_exact_outcomes_close_and_stop_alternates(
    outcome: Outcome,
) -> None:
    target = TargetSpec(f"case:global-{outcome.value.lower()}")
    first = Strategy("first-branch", "test.first", "resolve the complete target")
    alternate = Strategy("alternate-branch", "test.alternate", "try another construction")
    campaign = Campaign(
        "target-global-outcome-demo",
        objective="Resolve the complete target",
        targets=(target,),
        strategies=(first, alternate),
    )
    initial = campaign.recommend()
    first_task = next(
        item.task for item in initial.recommendations if item.task.strategy == first.name
    )
    certificate = closure_certificate(
        target.target_id,
        outcome,
        "test.exhaustion",
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        task_hash=first_task.task.task_hash,
        witness={"target": target.key},
        checks=("target-global criterion checked exactly",),
    )

    observation = Observation(
        target.target_id,
        first_task.campaign_task_id,
        outcome,
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        certificate=certificate,
        input_refs=first_task.task.input_refs,
        parameters=first_task.provenance.parameters.to_dict(),
        source_refs=first_task.provenance.source_refs,
    )
    campaign.observe(observation)
    replanned = campaign.recommend()

    assert observation.closes_target
    assert campaign.ledger.status(target).closed
    assert len(campaign.claims.claims) == 1
    assert not replanned.recommendations
    assert any(
        item.task.strategy == alternate.name and item.action.value == "STOP"
        for item in replanned.advisories
    )


def test_deferred_gate_is_rechecked_instead_of_becoming_terminal() -> None:
    target = TargetSpec("case:deferred")
    ready = False
    calls = 0

    def evaluate(_target: TargetSpec, _ledger: TargetLedger) -> GateDecision:
        nonlocal calls
        calls += 1
        return GateDecision.passed() if ready else GateDecision.deferred("await dependency")

    campaign = Campaign(
        "defer-demo",
        objective="Wait for an exact dependency",
        targets=(target,),
        strategies=(
            Strategy(
                "gated-search",
                "test.search",
                "run after dependency",
                gate=FunctionalGate("dependency", evaluate),
            ),
        ),
    )
    assert len(campaign.recommend()) == 0
    assert calls == 1
    assert not campaign.ledger.observations

    ready = True
    assert len(campaign.recommend()) == 1
    assert calls == 2


def test_dispatch_rechecks_direct_and_stale_gate_decisions() -> None:
    target = TargetSpec("case:dispatch-gate")
    ready = False
    calls = 0

    def evaluate(_target: TargetSpec, _ledger: TargetLedger) -> GateDecision:
        nonlocal calls
        calls += 1
        return GateDecision.passed() if ready else GateDecision.deferred("not ready")

    strategy = Strategy(
        "gated",
        "test.must-not-run",
        "run only after the exact dependency",
        gate=FunctionalGate("dependency", evaluate),
    )
    campaign = Campaign(
        "dispatch-gate-demo",
        objective="Never execute behind a deferred gate",
        targets=(target,),
        strategies=(strategy,),
    )
    planned = campaign.add_task(strategy.build_task(target))

    with pytest.raises(CampaignError, match="deferred"):
        campaign.dispatch(planned)
    assert calls == 1
    assert not campaign.ledger.observations

    ready = True
    recommendation = campaign.recommend().recommendations[0]
    ready = False
    with pytest.raises(CampaignError, match="deferred"):
        campaign.dispatch(recommendation)
    assert calls == 3
    assert not campaign.ledger.observations


def test_empty_capability_set_is_fail_closed() -> None:
    target = TargetSpec("case:capability")
    campaign = Campaign(
        "capability-demo",
        objective="Run only on eligible workers",
        targets=(target,),
        strategies=(
            Strategy(
                "gap-search",
                "test.gap",
                "requires finite-group enumeration",
                capability_requirements=("finite-groups",),
            ),
        ),
        capabilities=(),
    )
    assert len(campaign.recommend()) == 0
    planned = campaign.tasks[0]
    with pytest.raises(CapabilityUnavailableError, match="finite-groups"):
        campaign.dispatch(planned)
    explanation = campaign.explain(target)
    assert explanation.blockers
    assert "finite-groups" in explanation.blockers[0]
    assert campaign.status().blocked_tasks == 1


def test_ledger_requires_planned_task_and_exact_target_binding() -> None:
    left = TargetSpec("case:left")
    right = TargetSpec("case:right")
    ledger = TargetLedger((left, right))
    left_task = _task(left)
    ledger.plan_task(left_task)

    with pytest.raises(CampaignInvariantError, match="planned"):
        ledger.record(Observation(left.target_id, "sha256:" + "9" * 64, Outcome.PREEMPTED))
    with pytest.raises(CampaignInvariantError, match="match"):
        ledger.record(Observation(right.target_id, left_task.campaign_task_id, Outcome.PREEMPTED))


def test_priority_policy_is_exact_and_plan_order_is_deterministic() -> None:
    policy = PriorityPolicy()
    assert policy.score(
        importance=2,
        usefulness=3,
        information_gain=1,
        estimated_cost=5,
    ) == Fraction(6, 5)

    high = TargetSpec("case:high", importance=5)
    low = TargetSpec("case:low", importance=1)
    strategy = Strategy("search", "test.search", "search exact candidates")
    campaign = Campaign(
        "priority-demo",
        objective="Order finite work",
        targets=(low, high),
        strategies=(strategy,),
    )
    first = campaign.recommend().tasks
    second = campaign.recommend().tasks
    assert [task.target.key for task in first] == ["case:high", "case:low"]
    assert [task.campaign_task_id for task in first] == [task.campaign_task_id for task in second]


def test_target_dedup_and_ledger_event_tamper_detection() -> None:
    target = TargetSpec("case:dedup", {"n": 3})
    duplicate = TargetSpec("case:dedup", {"n": 3}, importance=9)
    ledger = TargetLedger((target, duplicate))
    assert len(ledger.targets) == 1

    document = ledger.to_dict()
    events = document["events"]
    assert isinstance(events, list)
    event = events[0]
    assert isinstance(event, dict)
    event["sequence"] = "0"
    with pytest.raises(CampaignSerializationError, match="integer"):
        TargetLedger.from_dict(document)


def test_campaign_rejects_spec_ledger_target_metadata_divergence() -> None:
    spec_target = TargetSpec("case:metadata", importance=99, label="spec")
    ledger_target = TargetSpec("case:metadata", importance=1, label="ledger")
    spec = CampaignSpec(
        "metadata-demo",
        "Keep planning inputs authoritative",
        targets=(spec_target,),
    )

    with pytest.raises(CampaignInvariantError, match="differs"):
        Campaign(spec, ledger=TargetLedger((ledger_target,)))


def test_runtime_derivations_and_gate_registry_must_match_descriptors() -> None:
    target = TargetSpec("case:runtime-injection")
    declared = DerivationRule("declared")
    campaign = Campaign(
        "injection-demo",
        objective="Reject runtime semantic substitution",
        targets=(target,),
        derivations=(declared,),
    )
    different = DerivationRule(
        "different",
        outcomes=(Outcome.SEARCH_EXHAUSTED,),
        rationale="different semantics",
    )
    with pytest.raises(CampaignInvariantError, match="must match"):
        Campaign.from_dict(campaign.to_dict(), derivations=(different,))

    mismatched_gate = FunctionalGate("actual", lambda _target, _ledger: GateDecision.passed())
    with pytest.raises(CampaignInvariantError, match="registry key"):
        Campaign(
            "gate-registry-demo",
            objective="Bind registry names",
            targets=(target,),
            gates={"declared": mismatched_gate},
        )


def test_required_ids_and_event_payloads_are_strict_during_replay() -> None:
    target = TargetSpec("case:strict-replay")
    target_document = target.to_dict()
    target_document["target_id"] = None
    with pytest.raises(CampaignSerializationError, match="target_id must be a string"):
        TargetSpec.from_dict(target_document)

    ledger = TargetLedger((target,))
    ledger_document = ledger.to_dict()
    ledger_events = ledger_document["events"]
    assert isinstance(ledger_events, list)
    first = ledger_events[0]
    assert isinstance(first, dict)
    first["event_id"] = None
    with pytest.raises(CampaignSerializationError, match="event_id must be a string"):
        TargetLedger.from_dict(ledger_document)

    canonical_event = ledger.events[0]
    extra_payload = canonical_event.payload.to_dict()
    extra_payload["ignored"] = "forbidden"
    malformed = LedgerEvent(
        sequence=0,
        kind=EventKind.TARGET_ADDED,
        payload=FrozenMapping(extra_payload),
    )
    with pytest.raises(CampaignSerializationError, match="payload fields"):
        TargetLedger.replay((malformed,))

    duplicate = LedgerEvent(
        sequence=1,
        kind=EventKind.TARGET_ADDED,
        payload=canonical_event.payload,
        previous_event_id=canonical_event.event_id,
    )
    with pytest.raises(CampaignSerializationError, match="duplicate target"):
        TargetLedger.replay((canonical_event, duplicate))


def test_bound_certificate_and_event_ids_detect_tampering() -> None:
    target = TargetSpec("case:tamper")
    task = _task(target)
    ledger = TargetLedger((target,))
    ledger.plan_task(task)
    certificate = closure_certificate(
        target.target_id,
        Outcome.SEARCH_EXHAUSTED,
        "test.exhaustion",
        outcome_scope=OutcomeScope.TARGET_GLOBAL,
        witness={"count": 4},
        checks=("all four cases checked",),
    )
    ledger.record(
        Observation(
            target.target_id,
            task.campaign_task_id,
            Outcome.SEARCH_EXHAUSTED,
            outcome_scope=OutcomeScope.TARGET_GLOBAL,
            certificate=certificate,
        )
    )
    document = ledger.to_dict()
    events = document["events"]
    assert isinstance(events, list)
    observation_event = events[-1]
    assert isinstance(observation_event, dict)
    payload = observation_event["payload"]
    assert isinstance(payload, dict)
    observation = payload["observation"]
    assert isinstance(observation, dict)
    observation["outcome"] = "FOUND"

    with pytest.raises(
        (CampaignInvariantError, CampaignSerializationError),
        match=r"certificate|event_id|observation_id",
    ):
        TargetLedger.from_dict(document)

    scope_document = ledger.to_dict()
    scope_events = scope_document["events"]
    assert isinstance(scope_events, list)
    scope_event = scope_events[-1]
    assert isinstance(scope_event, dict)
    scope_payload = scope_event["payload"]
    assert isinstance(scope_payload, dict)
    scope_observation = scope_payload["observation"]
    assert isinstance(scope_observation, dict)
    scope_observation["outcome_scope"] = OutcomeScope.TASK_LOCAL.value
    with pytest.raises(
        (CampaignInvariantError, CampaignSerializationError),
        match=r"certificate|event_id|observation_id|scope",
    ):
        TargetLedger.from_dict(scope_document)
