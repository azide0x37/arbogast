"""A small local, event-sourced research campaign engine."""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Protocol, cast

from arbogast.cert import (
    Certificate,
    CertificateError,
    VerificationCertificate,
    VerifierRegistry,
    certificate_from_dict,
    default_verifiers,
)
from arbogast.claims import (
    CLAIM_SCHEMA_V2,
    Claim,
    ClaimDomain,
    ClaimGraph,
    ClaimGraphError,
    EvidenceKind,
)
from arbogast.fleet import (
    ArtifactRef,
    CheckpointManifest,
    CheckpointRef,
    FleetDispatchError,
    FleetInterruption,
    FleetOperation,
    FleetRun,
    InterruptionReason,
    InterruptionReceipt,
    LeaseRecord,
    LeaseState,
    LocalExecutor,
    ShardSpec,
    TaskSpec,
    Worker,
)
from arbogast.formats import (
    FrozenMapping,
    JSONValue,
    canonical_bytes,
    canonical_dumps,
    canonical_sha256,
    loads,
    normalize_json,
    thaw_json,
)

from .claims import claim_for_observation
from .derive import DerivationRule
from .errors import (
    CampaignError,
    CampaignInvariantError,
    CampaignReadinessError,
    CampaignSerializationError,
    CapabilityUnavailableError,
    UnknownOperationError,
)
from .events import (
    CLOSING_OUTCOMES,
    EventKind,
    Observation,
    OperationalState,
    Outcome,
    OutcomeScope,
)
from .ledger import TargetLedger
from .planner import (
    CampaignPlan,
    CampaignTask,
    Recommendation,
    RecommendationAction,
)
from .policy import PriorityPolicy
from .results import (
    AttemptRecord,
    CandidateEvidence,
    CandidateRecord,
    CandidateScope,
    ExecutionTelemetry,
)
from .spec import CampaignSpec, Objective
from .strategy import ExactGate, GateDisposition, Strategy, TaskFactory
from .targets import TargetSpec, TargetState

if TYPE_CHECKING:
    from arbogast.bootstrap import (
        DispatchReadinessReceipt,
        EnvironmentSnapshot,
        ReadinessActivationReport,
    )


class _Sink(Protocol):
    def write(
        self,
        value: object,
        *,
        kind: str = "record",
        metadata: Mapping[str, object] | None = None,
    ) -> object: ...


class _OperationRegistry(Protocol):
    def resolve(self, name: str) -> FleetOperation: ...

    def names(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class _ReadinessActivation:
    """Runtime-only acceptance of one verified plan-readiness theorem."""

    certificate: VerificationCertificate
    plan: CampaignPlan
    claim_id: str
    required_verifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CampaignStatus:
    """A read-only projection of the authoritative campaign event log."""

    campaign_id: str
    name: str
    target_count: int
    open_targets: int
    closed_targets: int
    task_count: int
    pending_tasks: int
    blocked_tasks: int
    observed_tasks: int
    candidate_count: int
    canonical_candidate_count: int
    verified_candidate_count: int
    best_known_targets: int
    live_attempts: int
    terminal_attempts: int
    checkpointed_tasks: int
    claim_count: int
    theorem_holes: int
    recorded_plans: int
    latest_plan_id: str | None
    outcomes: tuple[tuple[str, int], ...]
    resource_usage: tuple[tuple[str, int], ...]
    spent: tuple[tuple[str, int], ...]
    worker_count: int
    available_workers: int
    busy_workers: int
    fleet_status: FrozenMapping | None
    last_event_id: str | None
    readiness: FrozenMapping = field(default_factory=FrozenMapping)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "campaign_id": self.campaign_id,
            "best_known_targets": self.best_known_targets,
            "blocked_tasks": self.blocked_tasks,
            "candidate_count": self.candidate_count,
            "canonical_candidate_count": self.canonical_candidate_count,
            "checkpointed_tasks": self.checkpointed_tasks,
            "claim_count": self.claim_count,
            "closed_targets": self.closed_targets,
            "available_workers": self.available_workers,
            "busy_workers": self.busy_workers,
            "fleet_status": (None if self.fleet_status is None else self.fleet_status.to_dict()),
            "last_event_id": self.last_event_id,
            "latest_plan_id": self.latest_plan_id,
            "live_attempts": self.live_attempts,
            "name": self.name,
            "observed_tasks": self.observed_tasks,
            "open_targets": self.open_targets,
            "outcomes": {key: value for key, value in self.outcomes},
            "pending_tasks": self.pending_tasks,
            "recorded_plans": self.recorded_plans,
            "readiness": self.readiness.to_dict(),
            "resource_usage": {key: value for key, value in self.resource_usage},
            "spent": {key: value for key, value in self.spent},
            "target_count": self.target_count,
            "task_count": self.task_count,
            "terminal_attempts": self.terminal_attempts,
            "theorem_holes": self.theorem_holes,
            "verified_candidate_count": self.verified_candidate_count,
            "worker_count": self.worker_count,
        }


@dataclass(frozen=True, slots=True)
class TargetExplanation:
    """Everything the campaign currently knows about one target."""

    state: TargetState
    observations: tuple[Observation, ...]
    recommendations: tuple[Recommendation, ...]
    advisories: tuple[Recommendation, ...]
    candidates: tuple[CandidateRecord, ...]
    best_known: tuple[tuple[str, CandidateRecord], ...]
    attempts: tuple[AttemptRecord, ...]
    claims: tuple[Claim, ...]
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "advisories": [item.to_dict() for item in self.advisories],
            "attempts": [item.to_dict() for item in self.attempts],
            "best_known": {metric: candidate.to_dict() for metric, candidate in self.best_known},
            "blockers": list(self.blockers),
            "candidates": [item.to_dict() for item in self.candidates],
            "claims": [normalize_json(item.to_dict()) for item in self.claims],
            "observations": [item.to_dict() for item in self.observations],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "state": self.state.to_dict(),
        }


class Campaign:
    """Operate a mathematical objective through an injected local fleet.

    Specs and ledger events are portable data.  Operations, derivation
    callables, gates, executors, and sinks are trusted runtime injections and
    are never reconstructed from serialized input.
    """

    schema = "arbogast.campaign.v1"

    def __init__(
        self,
        spec: CampaignSpec | str,
        *,
        objective: Objective | str | None = None,
        targets: Iterable[TargetSpec] = (),
        strategies: Iterable[Strategy] = (),
        derivations: Iterable[DerivationRule] | None = None,
        policy: PriorityPolicy | None = None,
        ledger: TargetLedger | None = None,
        executor: LocalExecutor | None = None,
        operations: Mapping[str, FleetOperation] | None = None,
        operation_registry: _OperationRegistry | None = None,
        verifier_registry: VerifierRegistry | None = None,
        strict_readiness: bool = False,
        gates: Mapping[str, ExactGate] | None = None,
        task_factories: Mapping[str, TaskFactory] | None = None,
        claims: ClaimGraph | None = None,
        capabilities: Iterable[str] | None = (),
        sinks: Iterable[_Sink] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if isinstance(spec, CampaignSpec):
            if objective is not None:
                raise CampaignInvariantError("objective cannot override a CampaignSpec")
            resolved_spec = spec
        else:
            if objective is None:
                raise CampaignInvariantError("a named Campaign requires an objective")
            resolved_spec = CampaignSpec(
                spec,
                objective,
                targets,
                strategies,
                () if derivations is None else derivations,
                policy,
                metadata=metadata,
            )
        self.spec = resolved_spec
        if verifier_registry is not None and not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry or None")
        self.verifier_registry = (
            default_verifiers if verifier_registry is None else verifier_registry
        )
        self.ledger = (
            TargetLedger(
                resolved_spec.targets,
                verifier_registry=self.verifier_registry,
            )
            if ledger is None
            else ledger
        )
        self.ledger.use_verifier_registry(self.verifier_registry)
        for target in resolved_spec.targets:
            if target.target_id in self.ledger.target_ids:
                if self.ledger.get(target.target_id) != target:
                    raise CampaignInvariantError(
                        "campaign spec target differs from its authoritative ledger target"
                    )
            else:
                self.ledger.add(target)
        self.executor = LocalExecutor() if executor is None else executor
        self.operations: dict[str, FleetOperation] = dict(operations or {})
        executor_registry = getattr(self.executor, "operation_registry", None)
        self.operation_registry = (
            executor_registry if operation_registry is None else operation_registry
        )
        if not isinstance(strict_readiness, bool):
            raise TypeError("strict_readiness must be a boolean")
        self.strict_readiness = strict_readiness
        self._active_readiness: _ReadinessActivation | None = None
        self.gates: dict[str, ExactGate] = dict(gates or {})
        for gate_name, gate in self.gates.items():
            if gate.name != gate_name:
                raise CampaignInvariantError(
                    f"gate registry key {gate_name!r} does not match gate name {gate.name!r}"
                )
        for strategy in resolved_spec.strategies:
            if strategy.gate is not None:
                self.gates.setdefault(strategy.gate.name, strategy.gate)
        supplied_factories = dict(task_factories or {})
        declared_factory_names = {
            strategy.task_factory_name
            for strategy in resolved_spec.strategies
            if strategy.task_factory_name is not None
        }
        unexpected_factories = set(supplied_factories) - declared_factory_names
        if unexpected_factories:
            raise CampaignInvariantError(
                "runtime task factories were supplied for undeclared descriptors: "
                f"{sorted(unexpected_factories)}"
            )
        runtime_strategies: list[Strategy] = []
        for strategy in resolved_spec.strategies:
            factory_name = strategy.task_factory_name
            if strategy.task_factory is not None or factory_name is None:
                runtime_strategies.append(strategy)
            elif factory_name in supplied_factories:
                runtime_strategies.append(
                    strategy.bind_task_factory(supplied_factories[factory_name])
                )
            else:
                runtime_strategies.append(strategy)
        self.strategies = tuple(runtime_strategies)
        supplied_derivations = (
            tuple(resolved_spec.derivations) if derivations is None else tuple(derivations)
        )
        supplied_by_name = {rule.name: rule for rule in supplied_derivations}
        if len(supplied_by_name) != len(supplied_derivations):
            raise CampaignInvariantError("runtime derivation names must be unique")
        declared_by_name = {rule.name: rule for rule in resolved_spec.derivations}
        if set(supplied_by_name) != set(declared_by_name):
            raise CampaignInvariantError(
                "runtime derivations must match the serialized campaign descriptors exactly"
            )
        for name, declared in declared_by_name.items():
            if supplied_by_name[name].to_dict() != declared.to_dict():
                raise CampaignInvariantError(
                    f"runtime derivation {name!r} does not match its serialized descriptor"
                )
        self.derivations = tuple(supplied_by_name[rule.name] for rule in resolved_spec.derivations)
        self.capabilities = None if capabilities is None else frozenset(capabilities)
        if self.capabilities is not None and any(not item.strip() for item in self.capabilities):
            raise CampaignInvariantError("campaign capabilities cannot be blank")
        self.sinks = tuple(sinks)
        self._sink_errors: list[dict[str, str]] = []
        self._tasks: dict[str, CampaignTask] = {}
        self._deferred_task_ids: set[str] = set()
        self._active_attempts: dict[str, AttemptRecord] = {}
        self._dispatch_readiness_lock = RLock()
        for document in self.ledger.task_documents():
            task = CampaignTask.from_dict(document)
            if task.target != self.ledger.get(task.target_id):
                raise CampaignInvariantError(
                    "planned task target differs from its authoritative ledger target"
                )
            self._tasks[task.campaign_task_id] = task
        self.claim_graph = (
            ClaimGraph(graph_id=f"campaign:{self.campaign_id}") if claims is None else claims
        )
        self._validate_dispatch_receipt_history()
        self._reconcile_claim_graph()
        self.reconcile_orphaned_attempts()

    @property
    def campaign_id(self) -> str:
        return self.spec.campaign_id

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def objective(self) -> Objective:
        return self.spec.objective

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return self.ledger.targets

    @property
    def tasks(self) -> tuple[CampaignTask, ...]:
        return tuple(self._tasks[key] for key in sorted(self._tasks))

    @property
    def claims(self) -> ClaimGraph:
        """The campaign-owned typed claim graph, including readiness history."""

        return self.claim_graph

    @property
    def candidates(self) -> tuple[CandidateRecord, ...]:
        return self.ledger.canonical_candidates

    @property
    def sink_errors(self) -> tuple[dict[str, str], ...]:
        """Non-authoritative sink failures observed by this runtime."""

        return tuple(dict(item) for item in self._sink_errors)

    @property
    def active_readiness_certificate(self) -> VerificationCertificate | None:
        """Return the runtime authorization certificate, never persisted state."""

        activation = self._active_readiness
        return None if activation is None else activation.certificate

    def record_environment_claim(self, claim: Claim) -> Claim:
        """Persist a verified environmental theorem without activating it."""

        if not isinstance(claim, Claim):
            raise TypeError("environment claim must be a Claim")
        if claim.domain is not ClaimDomain.ENVIRONMENTAL:
            raise CampaignReadinessError(
                "campaign readiness history accepts only environmental claims",
                code="READINESS_CLAIM_DOMAIN_MISMATCH",
            )
        # The readiness theorem is replayed by the audited builtin verifier.
        # ``self.verifier_registry`` is instead the exact campaign-specific V
        # binding certified by that theorem and may intentionally be private.
        report = claim.verify(raise_on_failure=False)
        if not report.verified:
            raise CampaignReadinessError(
                report.error or "environmental claim verification failed",
                code="READINESS_CLAIM_UNVERIFIED",
            )
        self.claim_graph.add_claim(claim)
        return claim

    def _recorded_plan(self, plan_id: str) -> CampaignPlan | None:
        for document in self.ledger.plan_documents:
            if document.get("plan_id") == plan_id:
                return CampaignPlan.from_dict(document)
        return None

    def _validate_dispatch_receipt_history(self) -> None:
        """Cross-bind durable operational receipts after offline reconstruction."""

        from arbogast.bootstrap import DispatchReadinessReceipt, readiness_receipt
        from arbogast.cert import VerificationCertificate, certificate_from_dict

        for attempt in self.ledger.attempts:
            raw_receipt = attempt.dispatch_readiness_receipt
            if raw_receipt is None:
                continue
            try:
                receipt = DispatchReadinessReceipt.from_dict(raw_receipt.to_dict())
                embedded_certificate = certificate_from_dict(
                    receipt.readiness_certificate.to_dict()
                )
                if not isinstance(embedded_certificate, VerificationCertificate):
                    raise TypeError("embedded readiness evidence is not a verification certificate")
                theorem = readiness_receipt(embedded_certificate)
            except (KeyError, TypeError, ValueError) as error:
                raise CampaignInvariantError(
                    "serialized attempt dispatch receipt failed strict replay"
                ) from error
            task = self._tasks.get(attempt.task_id)
            plan = self._recorded_plan(receipt.campaign_plan_id)
            try:
                readiness_claim = self.claim_graph.get(receipt.readiness_claim_id)
            except Exception:
                readiness_claim = None
            if (
                task is None
                or readiness_claim is None
                or readiness_claim.to_dict() != receipt.readiness_claim.to_dict()
                or receipt.campaign_id != self.campaign_id
                or receipt.campaign_target_id != attempt.target_id
                or receipt.campaign_task_id != attempt.task_id
                or receipt.campaign_attempt != attempt.attempt
                or receipt.campaign_attempt_id != attempt.attempt_id
                or receipt.fleet_task != task.task
                or plan is None
                or tuple(sorted(item.campaign_task_id for item in plan.tasks))
                != theorem.profile.task_ids
                or all(item.campaign_task_id != task.campaign_task_id for item in plan.tasks)
            ):
                raise CampaignInvariantError(
                    "serialized attempt dispatch receipt is outside its campaign/task/plan"
                )
            if attempt.worker_id is not None and receipt.lease.worker_id != attempt.worker_id:
                raise CampaignInvariantError(
                    "serialized attempt worker differs from its dispatch lease worker"
                )

    def _validate_readiness_activation(
        self,
        certificate: VerificationCertificate,
        plan: CampaignPlan,
        *,
        environment: EnvironmentSnapshot | None = None,
    ) -> ReadinessActivationReport:
        # Imported lazily because bootstrap itself consumes campaign models.
        from arbogast.bootstrap import validate_readiness_activation

        return validate_readiness_activation(
            certificate,
            campaign=self,
            plan=plan,
            operation_registry=self.operation_registry,
            verifier_registry=self.verifier_registry,
            executor=self.executor,
            artifact_store=getattr(self.executor, "store", None),
            environment=environment,
        )

    @staticmethod
    def _report_blockers(report: object) -> tuple[str, ...]:
        raw = getattr(report, "blockers", ())
        if not isinstance(raw, tuple) or any(not isinstance(item, str) for item in raw):
            return ("readiness validator returned malformed blockers",)
        return raw

    def activate_readiness(
        self,
        certificate: VerificationCertificate,
        *,
        plan: CampaignPlan | None = None,
        environment: EnvironmentSnapshot | None = None,
    ) -> ReadinessActivationReport:
        """Accept a verified readiness theorem for this exact live runtime.

        The claim remains persistent in ``claim_graph``; this activation does
        not.  A loaded Campaign must explicitly reactivate after recomputing
        every runtime binding.
        """

        if not isinstance(certificate, VerificationCertificate):
            raise TypeError("readiness activation requires a VerificationCertificate")
        from arbogast.bootstrap import readiness_receipt

        try:
            receipt = readiness_receipt(certificate)
        except Exception as error:
            raise CampaignReadinessError(
                f"readiness certificate replay failed: {error}",
                code="READINESS_CERTIFICATE_INVALID",
                blockers=(str(error),),
            ) from error
        profile = receipt.profile
        plan_id = getattr(profile, "plan_id", None)
        if not isinstance(plan_id, str) or not plan_id:
            raise CampaignReadinessError(
                "campaign dispatch activation requires a plan-scoped readiness certificate",
                code="READINESS_PLAN_REQUIRED",
            )
        selected_plan = self._recorded_plan(plan_id) if plan is None else plan
        if selected_plan is None or selected_plan.plan_id != plan_id:
            raise CampaignReadinessError(
                "readiness certificate does not name a recorded campaign plan",
                code="READINESS_PLAN_MISMATCH",
            )
        try:
            report = self._validate_readiness_activation(
                certificate,
                selected_plan,
                environment=environment,
            )
        except Exception as error:
            raise CampaignReadinessError(
                f"readiness activation replay failed: {error}",
                code="READINESS_ACTIVATION_INVALID",
                blockers=(str(error),),
            ) from error
        valid = getattr(report, "valid", None)
        if valid is not True:
            blockers = self._report_blockers(report)
            raise CampaignReadinessError(
                "readiness activation failed" + (f": {'; '.join(blockers)}" if blockers else ""),
                code="READINESS_ACTIVATION_INVALID",
                blockers=blockers,
            )
        claim_id = getattr(report, "claim_id", None)
        if not isinstance(claim_id, str) or claim_id not in self.claim_graph:
            raise CampaignReadinessError(
                "verified readiness claim must be recorded before activation",
                code="READINESS_CLAIM_NOT_RECORDED",
            )
        claim = self.claim_graph.get(claim_id)
        evidence_ids = {
            item.ref for item in claim.evidence if item.kind is EvidenceKind.CERTIFICATE
        }
        if (
            claim.schema_version != CLAIM_SCHEMA_V2
            or claim.domain is not ClaimDomain.ENVIRONMENTAL
            or claim.id != certificate.claim_id
            or claim.what.statement_hash != certificate.statement_hash
            or claim.boundary_hash != certificate.claim_boundary_hash
            or certificate.certificate_id not in evidence_ids
        ):
            raise CampaignReadinessError(
                "recorded environmental claim does not bind the exact readiness certificate",
                code="READINESS_CLAIM_CERTIFICATE_MISMATCH",
            )
        self._active_readiness = _ReadinessActivation(
            certificate=certificate,
            plan=selected_plan,
            claim_id=claim_id,
            required_verifiers=profile.required_verifiers,
        )
        return report

    def deactivate_readiness(self) -> VerificationCertificate | None:
        """Remove runtime dispatch authority while retaining claim history."""

        previous = self._active_readiness
        self._active_readiness = None
        return None if previous is None else previous.certificate

    def _require_dispatch_readiness(
        self,
        task: CampaignTask,
        recommendation: Recommendation | None = None,
    ) -> str | None:
        activation = self._active_readiness
        if activation is None:
            if self.strict_readiness:
                raise CampaignReadinessError(
                    "campaign dispatch requires an active readiness theorem",
                    code="READINESS_NOT_ACTIVE",
                    blockers=("no readiness certificate is active",),
                )
            return None
        try:
            report = self._validate_readiness_activation(
                activation.certificate,
                activation.plan,
            )
        except Exception as error:
            if isinstance(error, CampaignReadinessError):
                raise
            raise CampaignReadinessError(
                f"readiness revalidation failed: {error}",
                code="READINESS_REVALIDATION_FAILED",
                blockers=(str(error),),
            ) from error
        blockers = self._report_blockers(report)
        if getattr(report, "valid", None) is not True:
            raise CampaignReadinessError(
                "active readiness theorem is stale or mismatched"
                + (f": {'; '.join(blockers)}" if blockers else ""),
                code="READINESS_STALE",
                blockers=blockers,
            )
        task_ids = getattr(report, "task_ids", ())
        if not isinstance(task_ids, tuple) or task.campaign_task_id not in task_ids:
            blocker = f"task {task.campaign_task_id} is outside the certified plan roster"
            raise CampaignReadinessError(
                blocker,
                code="READINESS_TASK_NOT_COVERED",
                blockers=(blocker,),
            )
        if recommendation is not None and recommendation not in activation.plan.recommendations:
            blocker = "recommendation is not part of the exact activated campaign plan"
            raise CampaignReadinessError(
                blocker,
                code="READINESS_RECOMMENDATION_NOT_COVERED",
                blockers=(blocker,),
            )
        return activation.claim_id

    def _readiness_artifact_custody_blockers(
        self,
        certificate: VerificationCertificate,
    ) -> tuple[str, ...]:
        """Replay the certified artifact fixture without writing new bytes."""

        from arbogast.bootstrap import ObligationStatus, readiness_receipt

        try:
            receipt = readiness_receipt(certificate)
            obligation = next(
                item for item in receipt.obligations if item.id == "artifact-store.roundtrip"
            )
            if obligation.status is not ObligationStatus.SATISFIED:
                return ("certified artifact-store custody is not satisfied",)
            if obligation.evidence.get("outcome") != "completed":
                return ("artifact-store custody evidence did not complete",)
            raw_reference = obligation.evidence.get("reference")
            if not isinstance(raw_reference, Mapping):
                return ("artifact-store custody reference is malformed",)
            reference = ArtifactRef.from_dict(cast(Mapping[str, Any], raw_reference))
            input_hex = obligation.evidence.get("input_hex")
            if not isinstance(input_hex, str):
                return ("artifact-store custody bytes are malformed",)
            expected = bytes.fromhex(input_hex)
            store = getattr(self.executor, "store", None)
            verify = getattr(store, "verify", None)
            get_bytes = getattr(store, "get_bytes", None)
            if not callable(verify) or not callable(get_bytes):
                return ("current executor has no readable artifact custody",)
            if verify(reference) is not True or get_bytes(reference) != expected:
                return ("certified artifact fixture is absent or corrupt",)
        except Exception as error:
            return (f"artifact-store custody replay failed: {type(error).__name__}: {error}",)
        return ()

    def _dispatch_artifact_probe(
        self,
        payload: Mapping[str, object],
    ) -> FrozenMapping:
        """Write and read the exact lease-bound operational probe document."""

        store = getattr(self.executor, "store", None)
        put_json = getattr(store, "put_json", None)
        get_bytes = getattr(store, "get_bytes", None)
        get_json = getattr(store, "get_json", None)
        verify = getattr(store, "verify", None)
        if (
            not callable(put_json)
            or not callable(get_bytes)
            or not callable(get_json)
            or not callable(verify)
        ):
            raise CampaignReadinessError(
                "the current artifact store cannot perform a lease-bound write/read probe",
                code="READINESS_ARTIFACT_PROBE_FAILED",
                blockers=("artifact store lacks put_json/get_bytes/get_json/verify",),
            )
        canonical_payload = normalize_json(payload)
        try:
            reference = put_json(canonical_payload)
            if not isinstance(reference, ArtifactRef):
                raise TypeError("artifact store returned a non-ArtifactRef")
            if verify(reference) is not True:
                raise ValueError("artifact reference failed live verification")
            read_bytes = get_bytes(reference)
            if read_bytes != canonical_bytes(canonical_payload):
                raise ValueError("artifact probe read bytes differ from canonical payload")
            replayed = get_json(reference)
            if replayed != canonical_payload:
                raise ValueError("artifact probe replay differs from the exact payload")
        except Exception as error:
            blocker = f"artifact write/read probe failed: {type(error).__name__}: {error}"
            raise CampaignReadinessError(
                "lease-scoped artifact readiness probe refused operation execution",
                code="READINESS_ARTIFACT_PROBE_FAILED",
                blockers=(blocker,),
            ) from error
        return FrozenMapping(
            {
                "payload": canonical_payload,
                "read_bytes_hex": read_bytes.hex(),
                "read_outcome": "completed",
                "reference": reference.to_dict(),
                "schema": "arbogast.bootstrap.dispatch-artifact-probe-receipt/v1",
                "write_outcome": "completed",
            }
        )

    def _lease_dispatch_readiness_context(
        self,
        task: CampaignTask,
        recommendation: Recommendation | None,
        operation: FleetOperation,
    ) -> AbstractContextManager[None]:
        """Bind live readiness replay to each acquired built-in worker lease."""

        activation = self._active_readiness
        if activation is None:
            return nullcontext()
        install = getattr(self.executor, "_guard_lease_readiness", None)
        if not callable(install):
            if callable(getattr(self.executor, "lease_records", None)):
                raise CampaignReadinessError(
                    "the lease-aware executor cannot enforce dispatch readiness",
                    code="READINESS_LEASE_GUARD_UNSUPPORTED",
                    blockers=("executor has leases but no readiness guard boundary",),
                )
            return nullcontext()
        expected_certificate_id = activation.certificate.certificate_id

        def validate(
            fleet_task: TaskSpec,
            shard: ShardSpec,
            worker: Worker,
            lease: LeaseRecord,
            fleet_plan_hash: str,
            dispatch_id: str,
            dispatch_ordinal: int,
            dispatch_runtime_nonce: str,
            checked_at: str,
            lease_blockers: tuple[str, ...],
        ) -> Callable[[LeaseRecord, str, tuple[str, ...]], None]:
            current_activation = self._active_readiness
            blockers = list(lease_blockers)
            if (
                current_activation is None
                or current_activation.certificate.certificate_id != expected_certificate_id
            ):
                blockers.append("the active readiness certificate changed after dispatch")
            if fleet_task != task.task:
                blockers.append("worker lease names a different exact fleet task")
            if shard.task_hash != task.task.task_hash:
                blockers.append("worker lease shard is outside the exact campaign task")
            if lease.state is not LeaseState.ACTIVE:
                blockers.append("worker lease is not active")
            missing = self._missing_capabilities(task)
            if missing:
                blockers.append("campaign capabilities changed; missing: " + ", ".join(missing))
            try:
                report_claim_id = self._require_dispatch_readiness(task, recommendation)
                if report_claim_id != activation.claim_id:
                    blockers.append("lease replay returned a different readiness claim")
            except CampaignReadinessError as error:
                blockers.extend(error.blockers or (str(error),))
            current_plan = None
            try:
                current_plan = self.executor.plan(fleet_task, operation)
                if current_plan.plan_hash != fleet_plan_hash:
                    blockers.append("current fleet plan identity changed after lease acquisition")
                if shard not in current_plan.shards:
                    blockers.append("leased shard is absent from the current exact fleet plan")
            except Exception as error:
                blockers.append(
                    f"current fleet plan replay failed: {type(error).__name__}: {error}"
                )
            resolve = getattr(self.operation_registry, "resolve", None)
            if not callable(resolve):
                blockers.append("current operation registry cannot resolve the leased operation")
            else:
                try:
                    if resolve(fleet_task.operation) is not operation:
                        blockers.append(
                            "leased operation is not the exact current registry implementation"
                        )
                except Exception as error:
                    blockers.append(
                        f"current operation resolution failed: {type(error).__name__}: {error}"
                    )
            blockers.extend(self._readiness_artifact_custody_blockers(activation.certificate))
            if blockers:
                unique = tuple(dict.fromkeys(blockers))
                raise CampaignReadinessError(
                    "lease-scoped readiness refresh refused operation execution: "
                    + "; ".join(unique),
                    code="READINESS_LEASE_STALE",
                    blockers=unique,
                )
            from arbogast.bootstrap import (
                DispatchReadinessReceipt,
                readiness_receipt,
            )

            assert current_plan is not None
            theorem_receipt = readiness_receipt(activation.certificate)
            bindings = theorem_receipt.profile.bindings
            try:
                readiness_claim = self.claim_graph.get(activation.claim_id)
            except Exception as error:
                raise CampaignReadinessError(
                    "active readiness claim is absent from the campaign claim graph",
                    code="READINESS_CLAIM_UNVERIFIED",
                ) from error
            with self._dispatch_readiness_lock:
                campaign_attempt = self._active_attempts.get(task.campaign_task_id)
                if campaign_attempt is None or not campaign_attempt.live:
                    raise CampaignReadinessError(
                        "dispatch readiness has no live campaign attempt",
                        code="READINESS_DISPATCH_ATTEMPT_MISSING",
                    )
                campaign_attempt_id = campaign_attempt.attempt_id
                campaign_attempt_number = campaign_attempt.attempt

            probe_payload = {
                "campaign_attempt_id": campaign_attempt_id,
                "campaign_id": bindings["C"],
                "campaign_plan_id": bindings["P"],
                "campaign_target_id": task.target_id,
                "campaign_task_id": task.campaign_task_id,
                "dispatch_id": dispatch_id,
                "environment_id": theorem_receipt.environment.environment_id,
                "fleet_plan_hash": fleet_plan_hash,
                "lease_id": lease.id,
                "profile_id": theorem_receipt.profile.profile_id,
                "readiness_certificate_id": activation.certificate.certificate_id,
                "schema": "arbogast.bootstrap.dispatch-artifact-probe/v1",
                "shard_hash": shard.shard_hash,
                "task_hash": fleet_task.task_hash,
                "worker_id": worker.id,
            }
            artifact_probe = self._dispatch_artifact_probe(probe_payload)

            def finalize(
                final_lease: LeaseRecord,
                final_checked_at: str,
                final_lease_blockers: tuple[str, ...],
            ) -> None:
                final_blockers = list(final_lease_blockers)
                live_activation = self._active_readiness
                if (
                    live_activation is None
                    or live_activation.certificate.certificate_id != expected_certificate_id
                ):
                    final_blockers.append("the active readiness certificate changed before launch")
                with self._dispatch_readiness_lock:
                    active_attempt = self._active_attempts.get(task.campaign_task_id)
                    if (
                        active_attempt is None
                        or not active_attempt.live
                        or active_attempt.attempt_id != campaign_attempt_id
                    ):
                        final_blockers.append("the live campaign attempt changed before launch")
                if final_lease != lease:
                    final_blockers.append("the final lease differs from the refreshed active lease")
                if final_blockers:
                    unique = tuple(dict.fromkeys(final_blockers))
                    raise CampaignReadinessError(
                        "final lease-scoped readiness check refused operation execution: "
                        + "; ".join(unique),
                        code="READINESS_LEASE_STALE",
                        blockers=unique,
                    )
                dispatch_receipt = DispatchReadinessReceipt(
                    environment_id=theorem_receipt.environment.environment_id,
                    profile_id=theorem_receipt.profile.profile_id,
                    readiness_receipt_id=theorem_receipt.receipt_id,
                    readiness_certificate_id=activation.certificate.certificate_id,
                    readiness_claim_id=activation.claim_id,
                    readiness_certificate=FrozenMapping(activation.certificate.to_dict()),
                    readiness_claim=FrozenMapping(readiness_claim.to_dict()),
                    campaign_id=bindings["C"],
                    campaign_plan_id=bindings["P"],
                    campaign_task_id=task.campaign_task_id,
                    campaign_target_id=task.target_id,
                    campaign_attempt=campaign_attempt_number,
                    campaign_attempt_id=campaign_attempt_id,
                    operation_registry_id=bindings["G"],
                    verifier_registry_id=bindings["V"],
                    executor_id=bindings["X"],
                    artifact_store_id=bindings["A"],
                    dispatch_id=dispatch_id,
                    dispatch_ordinal=dispatch_ordinal,
                    dispatch_runtime_nonce=dispatch_runtime_nonce,
                    fleet_task=fleet_task,
                    fleet_plan_hash=fleet_plan_hash,
                    fleet_plan_shard_hashes=tuple(item.shard_hash for item in current_plan.shards),
                    shard=shard,
                    worker=FrozenMapping(worker.to_dict()),
                    lease=final_lease,
                    artifact_probe=artifact_probe,
                    checked_at=final_checked_at,
                )
                self._record_dispatch_readiness_receipt(task, dispatch_receipt)

            return finalize

        guarded = install(task.task, validate)
        if not isinstance(guarded, AbstractContextManager):
            raise CampaignReadinessError(
                "executor returned an invalid lease readiness guard",
                code="READINESS_LEASE_GUARD_UNSUPPORTED",
            )
        return guarded

    def _next_active_readiness_recommendation(self) -> Recommendation | None:
        activation = self._active_readiness
        if activation is None:
            return None
        return next(
            (
                item
                for item in activation.plan.recommendations
                if self.ledger.status(item.task.target_id).open
                and not self.ledger.observations_for_task(item.task.campaign_task_id)
            ),
            None,
        )

    def _lease_validity_projections(
        self,
        *,
        runtime_valid: bool,
    ) -> tuple[dict[str, object], ...]:
        """Project every durable receipt; none alone represents concurrent authority."""

        from arbogast.bootstrap import DispatchReadinessReceipt

        receipts: list[DispatchReadinessReceipt] = []
        seen: set[str] = set()
        for event in self.ledger.events:
            if event.kind is not EventKind.ATTEMPT_RECORDED:
                continue
            raw_attempt = thaw_json(event.payload["attempt"])
            if not isinstance(raw_attempt, Mapping):
                continue
            try:
                attempt = AttemptRecord.from_dict(raw_attempt)
                raw_receipt = attempt.dispatch_readiness_receipt
                if raw_receipt is None:
                    continue
                receipt = DispatchReadinessReceipt.from_dict(raw_receipt.to_dict())
            except (KeyError, TypeError, ValueError):
                continue
            if receipt.receipt_id in seen:
                continue
            seen.add(receipt.receipt_id)
            receipts.append(receipt)

        records = getattr(self.executor, "lease_records", None)
        current_by_id: dict[str, LeaseRecord] = {}
        if callable(records):
            try:
                for item in records():
                    current_by_id[item.id] = item
            except Exception:
                current_by_id = {}
        now_method = getattr(self.executor, "_now", None)
        try:
            now = now_method() if callable(now_method) else datetime.now(UTC)
        except Exception:
            now = datetime.now(UTC)
        activation = self._active_readiness
        projections: list[dict[str, object]] = []
        for receipt in receipts:
            current_lease = current_by_id.get(receipt.lease.id)
            expires = datetime.strptime(
                receipt.lease.expires_at,
                "%Y-%m-%dT%H:%M:%S.%fZ",
            ).replace(tzinfo=UTC)
            same_activation = (
                activation is not None
                and activation.certificate.certificate_id == receipt.readiness_certificate_id
            )
            candidate_current = bool(
                runtime_valid
                and same_activation
                and current_lease is not None
                and current_lease.state is LeaseState.ACTIVE
                and now < expires
            )
            current_valid = False
            if candidate_current:
                validate_context = getattr(
                    self.executor,
                    "validate_dispatch_context",
                    None,
                )
                if callable(validate_context):
                    try:
                        replayed_lease = validate_context(
                            task=receipt.fleet_task,
                            lease=receipt.lease,
                            dispatch_id=receipt.dispatch_id,
                            dispatch_ordinal=receipt.dispatch_ordinal,
                            dispatch_runtime_nonce=receipt.dispatch_runtime_nonce,
                            plan_hash=receipt.fleet_plan_hash,
                            worker_id=receipt.lease.worker_id,
                        )
                        current_valid = replayed_lease == receipt.lease
                    except Exception:
                        current_valid = False
            if current_valid:
                state = "current-active"
                reason = "the exact checked lease remains active in the current runtime"
            elif current_lease is not None and current_lease.terminal:
                state = "historical-terminal"
                reason = f"the checked lease is now terminal ({current_lease.state.value})"
            elif now >= expires:
                state = "historical-expired"
                reason = "the checked lease validity interval has expired"
            else:
                state = "historical-stale-runtime"
                reason = "the historical receipt is not current runtime dispatch authority"
            projections.append(
                {
                    "receipt_id": receipt.receipt_id,
                    "task_id": receipt.campaign_task_id,
                    "dispatch_id": receipt.dispatch_id,
                    "shard_hash": receipt.shard.shard_hash,
                    "worker_id": receipt.lease.worker_id,
                    "lease_id": receipt.lease.id,
                    "lease_state_at_check": receipt.lease.state.value,
                    "lease_state_current": (
                        None if current_lease is None else current_lease.state.value
                    ),
                    "acquired_at": receipt.lease.acquired_at,
                    "checked_at": receipt.checked_at,
                    "expires_at": receipt.lease.expires_at,
                    "receipt_valid": receipt.valid,
                    "valid": current_valid,
                    "current_valid": current_valid,
                    "historical": not current_valid,
                    "status": state,
                    "reason": reason,
                }
            )
        return tuple(projections)

    def _lease_validity_projection(self, *, runtime_valid: bool) -> dict[str, object] | None:
        """Retain the latest historical projection for additive compatibility."""

        projections = self._lease_validity_projections(runtime_valid=runtime_valid)
        return None if not projections else projections[-1]

    def _readiness_projection(self) -> FrozenMapping:
        activation = self._active_readiness
        if activation is None:
            blockers = ["no readiness certificate is active"] if self.strict_readiness else []
            lease_validities = self._lease_validity_projections(runtime_valid=False)
            return FrozenMapping(
                {
                    "active": False,
                    "blockers": blockers,
                    "campaign_id": self.campaign_id,
                    "certificate_id": None,
                    "checks": [],
                    "claim_id": None,
                    "environment_id": None,
                    "lease_validity": (None if not lease_validities else lease_validities[-1]),
                    "lease_validities": lease_validities,
                    "current_lease_validities": tuple(
                        item for item in lease_validities if item["current_valid"] is True
                    ),
                    "plan_id": None,
                    "profile_id": None,
                    "required": self.strict_readiness,
                    "stale": False,
                    "task_ids": [],
                    "valid": False,
                }
            )
        try:
            report = self._validate_readiness_activation(
                activation.certificate,
                activation.plan,
            )
            valid = getattr(report, "valid", None) is True
            blockers = list(self._report_blockers(report))
            checks = getattr(report, "checks", ())
            task_ids = getattr(report, "task_ids", ())
            if not isinstance(checks, tuple):
                checks = ()
            if not isinstance(task_ids, tuple):
                task_ids = ()
            lease_validities = self._lease_validity_projections(runtime_valid=valid)
            return FrozenMapping(
                {
                    "active": True,
                    "blockers": blockers,
                    "campaign_id": getattr(report, "campaign_id", self.campaign_id),
                    "certificate_id": activation.certificate.certificate_id,
                    "checks": list(checks),
                    "claim_id": activation.claim_id,
                    "environment_id": getattr(report, "environment_id", None),
                    "lease_validity": (None if not lease_validities else lease_validities[-1]),
                    "lease_validities": lease_validities,
                    "current_lease_validities": tuple(
                        item for item in lease_validities if item["current_valid"] is True
                    ),
                    "plan_id": getattr(report, "plan_id", activation.plan.plan_id),
                    "profile_id": getattr(report, "profile_id", None),
                    "required": self.strict_readiness,
                    "stale": not valid,
                    "task_ids": list(task_ids),
                    "valid": valid,
                }
            )
        except Exception as error:
            lease_validities = self._lease_validity_projections(runtime_valid=False)
            return FrozenMapping(
                {
                    "active": True,
                    "blockers": [str(error)],
                    "campaign_id": self.campaign_id,
                    "certificate_id": activation.certificate.certificate_id,
                    "checks": [],
                    "claim_id": activation.claim_id,
                    "environment_id": None,
                    "lease_validity": (None if not lease_validities else lease_validities[-1]),
                    "lease_validities": lease_validities,
                    "current_lease_validities": tuple(
                        item for item in lease_validities if item["current_valid"] is True
                    ),
                    "plan_id": activation.plan.plan_id,
                    "profile_id": None,
                    "required": self.strict_readiness,
                    "stale": True,
                    "task_ids": [item.campaign_task_id for item in activation.plan.tasks],
                    "valid": False,
                }
            )

    def _claims_for_target(self, target_id: str) -> tuple[Claim, ...]:
        return tuple(
            claim
            for claim in self.claim_graph.claims
            if claim.metadata.get("target_id") == target_id
        )

    def _reconcile_claim_graph(self) -> None:
        expected_graph_id = f"campaign:{self.campaign_id}"
        if self.claim_graph.graph_id != expected_graph_id:
            raise CampaignInvariantError("campaign claim graph is not bound to this CampaignSpec")
        for observation in self.ledger.observations:
            if not observation.closes_target_with(self.verifier_registry):
                continue
            task = self._tasks.get(observation.task_id)
            if task is None:
                raise CampaignInvariantError(
                    "closing observation refers to an unknown campaign task"
                )
            claim = claim_for_observation(
                self.campaign_id,
                self.name,
                task,
                observation,
            )
            if claim.id in self.claim_graph:
                if self.claim_graph.get(claim.id) != claim:
                    raise CampaignInvariantError(
                        "campaign claim graph conflicts with authoritative observation"
                    )
            else:
                self.claim_graph.add_claim(claim)
            self.ledger.bind_claim(
                claim_id=claim.id,
                claim_digest=claim.digest,
                observation_id=observation.observation_id,
                target_id=observation.target_id,
            )
        for binding in self.ledger.claim_bindings:
            claim_id = binding["claim_id"]
            if not isinstance(claim_id, str) or claim_id not in self.claim_graph:
                raise CampaignInvariantError(
                    "campaign ledger claim binding is missing from the claim graph"
                )
            claim = self.claim_graph.get(claim_id)
            if binding["claim_digest"] != claim.digest:
                raise CampaignInvariantError(
                    "campaign ledger claim digest does not match the claim graph"
                )

    def _emit_latest(self) -> None:
        if not self.ledger.events:
            return
        event = self.ledger.events[-1]
        for sink in self.sinks:
            try:
                sink.write(
                    event.to_dict(),
                    kind="campaign.event",
                    metadata={"campaign_id": self.campaign_id, "campaign_name": self.name},
                )
            except Exception as error:
                self._sink_errors.append(
                    {
                        "error": str(error),
                        "error_type": type(error).__qualname__,
                        "event_id": event.event_id,
                        "sink_type": type(sink).__qualname__,
                    }
                )

    def reconcile_orphaned_attempts(self) -> tuple[AttemptRecord, ...]:
        """Fail closed on RUNNING records that survived without a runtime.

        A serialized campaign cannot prove that an in-memory worker lease is
        still alive.  Replay therefore appends an operational UNKNOWN terminal
        state for each orphan.  This never creates an Observation and cannot
        change mathematical target state or invent checkpoint custody.
        """

        recovered: list[AttemptRecord] = []
        for live in self.ledger.live_attempts:
            terminal = AttemptRecord(
                live.target_id,
                live.task_id,
                live.attempt,
                OperationalState.UNKNOWN,
                worker_id=live.worker_id,
                checkpoint_ref=live.checkpoint_ref,
                detail=(
                    "orphaned RUNNING attempt recovered during campaign load; "
                    "no live worker lease or checkpoint custody was asserted"
                ),
                progress_completed=live.progress_completed,
                progress_total=live.progress_total,
                resources=live.resources,
                readiness_claim_id=live.readiness_claim_id,
                dispatch_readiness_receipt_id=live.dispatch_readiness_receipt_id,
                dispatch_readiness_receipt=(
                    None
                    if live.dispatch_readiness_receipt is None
                    else live.dispatch_readiness_receipt.to_dict()
                ),
            )
            event = self.ledger.record_attempt(terminal)
            if event is not None:
                recovered.append(terminal)
                self._emit_latest()
        return tuple(recovered)

    def add_target(self, target: TargetSpec) -> TargetSpec:
        before = len(self.ledger.events)
        canonical = self.ledger.add(target)
        if canonical != target:
            raise CampaignInvariantError(
                "target planning metadata conflicts with its canonical ledger representative"
            )
        if len(self.ledger.events) != before:
            self._emit_latest()
        return canonical

    def add_task(self, task: CampaignTask) -> CampaignTask:
        target = self.add_target(task.target)
        if target != task.target:
            raise CampaignInvariantError(
                "campaign task target differs from its authoritative ledger target"
            )
        existing = self._tasks.get(task.campaign_task_id)
        if existing is not None:
            if existing != task:
                raise CampaignInvariantError("campaign task ID collision")
            return existing
        event = self.ledger.plan_task(task)
        self._tasks[task.campaign_task_id] = task
        if event is not None:
            self._emit_latest()
        return task

    def _preflight(self, target: TargetSpec, strategy: Strategy, task: CampaignTask) -> bool:
        gate = strategy.resolve_gate(self.gates)
        if gate is None:
            return True
        decision = gate.evaluate(target, self.ledger)
        if decision.disposition is GateDisposition.PASS:
            return True
        if decision.disposition is GateDisposition.DEFER:
            self._deferred_task_ids.add(task.campaign_task_id)
            return False
        assert decision.certificate is not None
        observation = Observation(
            target.target_id,
            task.campaign_task_id,
            Outcome.PROVED_IMPOSSIBLE,
            outcome_scope=decision.outcome_scope,
            certificate=decision.certificate,
            input_refs=task.task.input_refs,
            parameters=task.provenance.parameters.to_dict(),
            source_refs=task.provenance.source_refs,
            details={
                "gate": gate.name,
                "preflight": decision.disposition.value,
                "reason": decision.reason,
                **decision.details.to_dict(),
            },
        )
        if not observation.verify(self.verifier_registry):
            raise CampaignInvariantError(
                f"exact gate {gate.name!r} certificate failed its registered verifier"
            )
        self._observe(observation, gate_closure=True)
        return False

    def _ensure_initial_tasks(self) -> None:
        self._deferred_task_ids.clear()
        for existing in self.tasks:
            observations = self.ledger.observations_for_task(existing.campaign_task_id)
            if not observations:
                continue
            latest = observations[-1]
            if latest.operational_state not in {
                OperationalState.BUDGET_EXHAUSTED,
                OperationalState.FAILED,
                OperationalState.PREEMPTED,
            }:
                continue
            if (
                latest.operational_state is OperationalState.FAILED
                and latest.checkpoint_ref is None
            ):
                continue
            branch_interruptions = sum(
                observation.operational_state
                in {
                    OperationalState.BUDGET_EXHAUSTED,
                    OperationalState.FAILED,
                    OperationalState.PREEMPTED,
                }
                for task in self.tasks
                if task.target_id == existing.target_id and task.strategy == existing.strategy
                for observation in self.ledger.observations_for_task(task.campaign_task_id)
            )
            if branch_interruptions > self.spec.policy.max_retries:
                continue
            if latest.checkpoint_ref is not None:
                checkpoint_custody_id = self._checkpoint_custody_id_from_observation(latest)
                self.add_task(
                    existing.resume(
                        latest.checkpoint_ref,
                        checkpoint_custody_id=checkpoint_custody_id,
                        observation_id=latest.observation_id,
                    )
                )
            else:
                retry_index = existing.provenance.parameters.get("retry_index", 0)
                if isinstance(retry_index, bool) or not isinstance(retry_index, int):
                    raise CampaignInvariantError(
                        "campaign retry provenance has a non-integer retry_index"
                    )
                self.add_task(existing.retry(latest.observation_id, retry_index + 1))
        initial_target_ids = {target.target_id for target in self.spec.targets}
        for target in self.ledger.unresolved():
            if target.target_id not in initial_target_ids:
                continue
            for strategy in self.strategies:
                pending = tuple(
                    task
                    for task in self.tasks
                    if task.target_id == target.target_id
                    and task.strategy == strategy.name
                    and not self.ledger.observations_for_task(task.campaign_task_id)
                )
                if pending:
                    for task in pending:
                        if (
                            not self._preflight(target, strategy, task)
                            and self.ledger.status(target).closed
                        ):
                            break
                    if self.ledger.status(target).closed:
                        break
                    continue
                candidate = strategy.build_task(target)
                task = self.add_task(candidate)
                if self.ledger.observations_for_task(task.campaign_task_id):
                    continue
                if (
                    not self._preflight(target, strategy, task)
                    and self.ledger.status(target).closed
                ):
                    break

    def _missing_capabilities(self, task: CampaignTask) -> tuple[str, ...]:
        if self.capabilities is None:
            return ()
        return tuple(sorted(set(task.capability_requirements) - self.capabilities))

    def _worker_ineligibility(self, task: CampaignTask) -> tuple[str, ...]:
        """Project deterministic WorkerPool match reasons when one is present."""

        matches_method = getattr(self.executor, "matches", None)
        if not callable(matches_method):
            return ()
        matches = matches_method(task.task)
        if any(getattr(match, "eligible", False) is True for match in matches):
            return ()
        if not matches:
            return ("worker pool is empty",)
        reasons: list[str] = []
        for match in matches:
            worker_id = getattr(match, "worker_id", None)
            raw_reasons = getattr(match, "reasons", None)
            if not isinstance(worker_id, str) or not isinstance(raw_reasons, tuple):
                raise CampaignInvariantError(
                    "worker capability match has an invalid diagnostic projection"
                )
            if any(not isinstance(reason, str) for reason in raw_reasons):
                raise CampaignInvariantError("worker capability match reasons must be strings")
            reasons.append(f"worker {worker_id}: {', '.join(raw_reasons)}")
        return tuple(sorted(reasons))

    def _blockers_for_target(self, target_id: str) -> tuple[str, ...]:
        blockers: list[str] = []
        readiness = self._readiness_projection()
        for task in self.tasks:
            if task.target_id != target_id:
                continue
            if self.ledger.observations_for_task(task.campaign_task_id):
                continue
            missing = self._missing_capabilities(task)
            if missing:
                blockers.append(
                    f"task {task.campaign_task_id} is unavailable; missing capabilities: "
                    f"{', '.join(missing)}"
                )
            elif worker_reasons := self._worker_ineligibility(task):
                blockers.append(
                    f"task {task.campaign_task_id} has no eligible worker; "
                    f"{' ; '.join(worker_reasons)}"
                )
            elif task.campaign_task_id in self._deferred_task_ids:
                blockers.append(
                    f"task {task.campaign_task_id} is deferred by its exact preflight gate"
                )
            for reason in self._readiness_blockers_for_task(task, readiness):
                blockers.append(f"task {task.campaign_task_id} is readiness-blocked; {reason}")
        return tuple(sorted(blockers))

    def _readiness_blockers_for_task(
        self,
        task: CampaignTask,
        projection: FrozenMapping | None = None,
    ) -> tuple[str, ...]:
        readiness = self._readiness_projection() if projection is None else projection
        active = readiness.get("active") is True
        if not active and not self.strict_readiness:
            return ()
        raw_blockers: object = readiness.get("blockers", [])
        blockers = (
            tuple(item for item in raw_blockers if isinstance(item, str))
            if isinstance(raw_blockers, list | tuple)
            else ()
        )
        if readiness.get("valid") is not True:
            return blockers or ("no valid readiness theorem is active",)
        raw_task_ids: object = readiness.get("task_ids", [])
        task_ids = set(raw_task_ids) if isinstance(raw_task_ids, list | tuple) else set()
        if task.campaign_task_id not in task_ids:
            return ("task is outside the certified plan roster",)
        return ()

    def _fleet_status_projection(
        self,
    ) -> tuple[FrozenMapping | None, int, int, int]:
        """Return optional scheduler occupancy without coupling to one executor.

        Ordinary ``LocalExecutor`` instances intentionally have no scheduler
        status surface.  A worker-pool executor exposes a canonical ``to_dict``
        projection which is copied into the campaign status as diagnostic,
        non-mathematical state.
        """

        status_method = getattr(self.executor, "status", None)
        if not callable(status_method):
            return None, 0, 0, 0
        status_value = status_method()
        to_dict = getattr(status_value, "to_dict", None)
        if not callable(to_dict):
            raise CampaignInvariantError(
                "executor status must provide a canonical to_dict projection"
            )
        normalized = normalize_json(to_dict())
        if not isinstance(normalized, dict):
            raise CampaignInvariantError("executor status projection must be an object")
        raw_workers = normalized.get("workers")
        if not isinstance(raw_workers, list):
            raise CampaignInvariantError("executor status workers must be an array of objects")
        workers: list[dict[str, JSONValue]] = []
        for raw_worker in raw_workers:
            if not isinstance(raw_worker, dict):
                raise CampaignInvariantError("executor status workers must be an array of objects")
            workers.append(raw_worker)
        states = tuple(worker.get("state") for worker in workers)
        if any(not isinstance(state, str) for state in states):
            raise CampaignInvariantError("executor worker states must be strings")
        return (
            FrozenMapping(normalized),
            len(workers),
            sum(state == "available" for state in states),
            sum(state == "busy" for state in states),
        )

    def status(self) -> CampaignStatus:
        states = tuple(self.ledger.status(target) for target in self.ledger.targets)
        observations = self.ledger.observations
        observed_task_ids = {item.task_id for item in observations}
        readiness = self._readiness_projection()
        blocked_task_ids = {
            task.campaign_task_id
            for task in self.tasks
            if task.campaign_task_id not in observed_task_ids
            and self.ledger.status(task.target_id).open
            and bool(
                self._missing_capabilities(task)
                or self._worker_ineligibility(task)
                or self._checkpoint_resume_blocker(task)
                or self._readiness_blockers_for_task(task, readiness)
            )
        }
        counts = Counter(item.outcome.value for item in observations)
        canonical_candidates = self.ledger.canonical_candidates
        resource_counts: Counter[str] = Counter()
        spent_counts: Counter[str] = Counter()
        for attempt in self.ledger.latest_attempts:
            for key, value in attempt.resources.to_dict().items():
                if isinstance(value, int) and not isinstance(value, bool):
                    resource_counts[key] += value
        for observation in observations:
            raw_spent = observation.details.to_dict().get("spent", {})
            if not isinstance(raw_spent, Mapping):
                continue
            for key, value in raw_spent.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    spent_counts[key] += value
        latest_plan = self.ledger.latest_plan_document
        latest_plan_id = None if latest_plan is None else latest_plan.get("plan_id")
        if latest_plan_id is not None and not isinstance(latest_plan_id, str):
            raise CampaignInvariantError("ledger latest plan has an invalid plan_id")
        fleet_status, worker_count, available_workers, busy_workers = (
            self._fleet_status_projection()
        )
        return CampaignStatus(
            campaign_id=self.campaign_id,
            name=self.name,
            target_count=len(states),
            open_targets=sum(state.open for state in states),
            closed_targets=sum(state.closed for state in states),
            task_count=len(self._tasks),
            pending_tasks=sum(task_id not in observed_task_ids for task_id in self._tasks),
            blocked_tasks=len(blocked_task_ids),
            observed_tasks=sum(task_id in observed_task_ids for task_id in self._tasks),
            candidate_count=len(self.ledger.candidates),
            canonical_candidate_count=len(canonical_candidates),
            verified_candidate_count=sum(
                candidate.evidence is CandidateEvidence.VERIFIED
                for candidate in canonical_candidates
            ),
            best_known_targets=sum(
                bool(self.ledger.best_known_by_metric(target)) for target in self.targets
            ),
            live_attempts=len(self.ledger.live_attempts),
            terminal_attempts=sum(not attempt.live for attempt in self.ledger.latest_attempts),
            checkpointed_tasks=len(
                {
                    observation.task_id
                    for observation in observations
                    if observation.checkpoint_ref is not None
                }
            ),
            claim_count=len(self.claim_graph),
            theorem_holes=len(self.claim_graph.theorem_holes()),
            recorded_plans=len(self.ledger.plan_documents),
            latest_plan_id=latest_plan_id,
            outcomes=tuple(sorted(counts.items())),
            resource_usage=tuple(sorted(resource_counts.items())),
            spent=tuple(sorted(spent_counts.items())),
            worker_count=worker_count,
            available_workers=available_workers,
            busy_workers=busy_workers,
            fleet_status=fleet_status,
            readiness=readiness,
            last_event_id=(None if not self.ledger.events else self.ledger.events[-1].event_id),
        )

    def explain(self, target: TargetSpec | str) -> TargetExplanation:
        spec = self.ledger.get(target)
        plan = self.recommend()
        recommendations = tuple(
            item for item in plan.recommendations if item.task.target_id == spec.target_id
        )
        advisories = tuple(
            item for item in plan.advisories if item.task.target_id == spec.target_id
        )
        attempts = tuple(
            attempt
            for attempt in self.ledger.latest_attempts
            if attempt.target_id == spec.target_id
        )
        return TargetExplanation(
            state=self.ledger.status(spec),
            observations=self.ledger.observations_for(spec),
            recommendations=recommendations,
            advisories=advisories,
            candidates=self.ledger.candidates_for(spec),
            best_known=self.ledger.best_known_by_metric(spec),
            attempts=attempts,
            claims=self._claims_for_target(spec.target_id),
            blockers=self._blockers_for_target(spec.target_id),
        )

    def recommend(self, limit: int | None = None) -> CampaignPlan:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise CampaignInvariantError("recommendation limit must be a non-negative integer")
        self._ensure_initial_tasks()
        recommendations: list[Recommendation] = []
        advisories: list[Recommendation] = []
        for task in self.tasks:
            target_state = self.ledger.status(task.target_id)
            task_observations = self.ledger.observations_for_task(task.campaign_task_id)
            target_observation_count = len(self.ledger.observations_for(task.target_id))
            priority = self.spec.policy.assess(
                importance=task.target.importance,
                usefulness=task.usefulness,
                information_gain=task.information_gain,
                estimated_cost=task.estimated_cost * (1 + target_observation_count),
            )
            if target_state.closed:
                if not task_observations:
                    advisories.append(
                        Recommendation(
                            task=task,
                            priority=priority,
                            action=RecommendationAction.STOP,
                            reason="target closed by other verified evidence; stop redundant work",
                        )
                    )
                elif task_observations[-1].outcome is Outcome.FOUND:
                    source_observation = task_observations[-1]
                    expanded = any(
                        source_observation.observation_id
                        in candidate.provenance.parent_observation_ids
                        for candidate in self.tasks
                    )
                    if not expanded:
                        advisories.append(
                            Recommendation(
                                task=task,
                                priority=priority,
                                action=RecommendationAction.EXPAND,
                                reason=(
                                    "verified discovery has no derived follow-up tasks; "
                                    "consider a registered derivation rule"
                                ),
                            )
                        )
                continue
            if task_observations:
                latest = task_observations[-1]
                if latest.operational_state in {
                    OperationalState.FAILED,
                    OperationalState.UNKNOWN,
                }:
                    advisories.append(
                        Recommendation(
                            task=task,
                            priority=priority,
                            action=RecommendationAction.STOP,
                            reason=(
                                f"latest execution state is "
                                f"{latest.operational_state.value}; inspect before retry"
                            ),
                        )
                    )
                elif latest.operational_state in {
                    OperationalState.BUDGET_EXHAUSTED,
                    OperationalState.PREEMPTED,
                }:
                    pending_successor = any(
                        latest.observation_id in candidate.provenance.parent_observation_ids
                        and not self.ledger.observations_for_task(candidate.campaign_task_id)
                        for candidate in self.tasks
                    )
                    if not pending_successor:
                        advisories.append(
                            Recommendation(
                                task=task,
                                priority=priority,
                                action=RecommendationAction.STOP,
                                reason=(
                                    "interruption retry policy is exhausted; retain "
                                    "checkpoint and stop automatic work"
                                ),
                            )
                        )
                continue
            if task.campaign_task_id in self._deferred_task_ids:
                advisories.append(
                    Recommendation(
                        task=task,
                        priority=priority,
                        action=RecommendationAction.SUSPEND,
                        reason="exact preflight gate deferred pending additional evidence",
                    )
                )
                continue
            missing = self._missing_capabilities(task)
            if missing:
                advisories.append(
                    Recommendation(
                        task=task,
                        priority=priority,
                        action=RecommendationAction.SUSPEND,
                        reason=f"no eligible capability set; missing: {', '.join(missing)}",
                    )
                )
                continue
            worker_reasons = self._worker_ineligibility(task)
            if worker_reasons:
                advisories.append(
                    Recommendation(
                        task=task,
                        priority=priority,
                        action=RecommendationAction.SUSPEND,
                        reason=(f"no eligible worker: {' ; '.join(worker_reasons)}"),
                    )
                )
                continue
            resume_blocker = self._checkpoint_resume_blocker(task)
            if resume_blocker is not None:
                advisories.append(
                    Recommendation(
                        task=task,
                        priority=priority,
                        action=RecommendationAction.SUSPEND,
                        reason=resume_blocker,
                    )
                )
                continue
            action = (
                RecommendationAction.RESUME
                if task.checkpoint_ref is not None
                else RecommendationAction.DISPATCH
            )
            recommendations.append(
                Recommendation(
                    task=task,
                    priority=priority,
                    action=action,
                    reason=(
                        f"exact score {priority.numerator}/{priority.denominator}: "
                        "importance*usefulness*information_gain/"
                        "(estimated_cost*(1+target_observations))"
                    ),
                )
            )
        complete_plan = CampaignPlan(
            recommendations,
            self.spec.policy.name,
            advisories=advisories,
        )
        plan = (
            complete_plan
            if limit is None
            else CampaignPlan(
                complete_plan.recommendations[:limit],
                self.spec.policy.name,
                advisories=complete_plan.advisories,
            )
        )
        event = self.ledger.record_plan(plan)
        if event is not None:
            self._emit_latest()
        return plan

    plan = recommend

    def _resolve_task(
        self,
        task: CampaignTask | Recommendation | str | None,
    ) -> CampaignTask:
        if task is None:
            plan = self.recommend(limit=1)
            if not plan.recommendations:
                raise CampaignError("campaign has no dispatchable recommendations")
            return plan.recommendations[0].task
        if isinstance(task, Recommendation):
            return task.task
        if isinstance(task, CampaignTask):
            resolved = self._tasks.get(task.campaign_task_id)
            if resolved != task:
                raise CampaignInvariantError("task is not planned by this campaign")
            return task
        try:
            return self._tasks[task]
        except KeyError as error:
            raise CampaignInvariantError(f"unknown campaign task {task!r}") from error

    def _record_failed_dispatch(self, task: CampaignTask, error: Exception) -> Observation:
        observation = Observation(
            task.target_id,
            task.campaign_task_id,
            Outcome.FAILED,
            operational_state=OperationalState.FAILED,
            input_refs=task.task.input_refs,
            parameters=task.provenance.parameters.to_dict(),
            source_refs=task.provenance.source_refs,
            details={"error": str(error), "error_type": type(error).__qualname__},
        )
        self._observe(observation, trusted_runtime=True)
        return observation

    @staticmethod
    def _checkpoint_custody_id(
        checkpoint: CheckpointRef,
        manifest: CheckpointManifest | None,
        receipts: Iterable[InterruptionReceipt] = (),
    ) -> str:
        payload = checkpoint.to_dict() if manifest is None else manifest.to_dict()
        receipt_values = sorted(
            (receipt.to_dict() for receipt in receipts),
            key=canonical_sha256,
        )
        custody = {
            "custody": payload,
            "producer_receipts": receipt_values,
            "schema": "arbogast.campaign.checkpoint-custody.v1",
        }
        return f"sha256:{canonical_sha256(custody)}"

    @staticmethod
    def _interruption_receipts_from_details(
        details: Mapping[str, object],
    ) -> tuple[InterruptionReceipt, ...]:
        raw_many = details.get("interruption_receipts")
        raw_single = details.get("interruption_receipt")
        try:
            if raw_many is not None:
                if not isinstance(raw_many, list) or any(
                    not isinstance(item, Mapping) for item in raw_many
                ):
                    raise ValueError("interruption_receipts must be an array of objects")
                receipts = tuple(InterruptionReceipt.from_dict(item) for item in raw_many)
                if raw_single is not None:
                    if not isinstance(raw_single, Mapping):
                        raise ValueError("interruption_receipt must be an object or null")
                    single = InterruptionReceipt.from_dict(raw_single)
                    if len(receipts) != 1 or receipts[0] != single:
                        raise ValueError("single and aggregate interruption receipts disagree")
                return receipts
            if raw_single is None:
                return ()
            if not isinstance(raw_single, Mapping):
                raise ValueError("interruption_receipt must be an object or null")
            return (InterruptionReceipt.from_dict(raw_single),)
        except (KeyError, TypeError, ValueError) as error:
            raise CampaignError("interruption receipt failed strict replay") from error

    def _checkpoint_custody_id_from_observation(
        self,
        observation: Observation,
    ) -> str:
        details = observation.details.to_dict()
        raw_checkpoint = details.get("checkpoint")
        raw_manifest = details.get("checkpoint_manifest")
        if not isinstance(raw_checkpoint, Mapping):
            raise CampaignError("checkpoint observation has no typed custody receipt")
        try:
            checkpoint = CheckpointRef.from_dict(raw_checkpoint)
            manifest = (
                CheckpointManifest.from_dict(raw_manifest)
                if isinstance(raw_manifest, Mapping)
                else None
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CampaignError("checkpoint observation failed strict custody replay") from error
        receipts = self._interruption_receipts_from_details(details)
        computed = self._checkpoint_custody_id(checkpoint, manifest, receipts)
        if details.get("checkpoint_custody_id") != computed:
            raise CampaignError("checkpoint observation custody ID does not match its receipt")
        return computed

    def _record_dispatch_error(
        self,
        task: CampaignTask,
        error: FleetDispatchError,
    ) -> Observation:
        manifest = error.checkpoint_manifest
        if manifest is not None and manifest.task_hash != task.task.task_hash:
            raise CampaignInvariantError(
                "fleet dispatch checkpoint manifest belongs to another task"
            )
        checkpoint = None if manifest is None else manifest.checkpoints[0]
        reasons = {item.interruption_reason for item in error.failures}
        homogeneous_reason = next(iter(reasons)) if len(reasons) == 1 else None
        if homogeneous_reason is InterruptionReason.PREEMPTED:
            outcome = Outcome.PREEMPTED
            operational_state = OperationalState.PREEMPTED
        elif homogeneous_reason is InterruptionReason.BUDGET_EXHAUSTED:
            outcome = Outcome.BUDGET_EXHAUSTED
            operational_state = OperationalState.BUDGET_EXHAUSTED
        else:
            outcome = Outcome.FAILED
            operational_state = OperationalState.FAILED
        receipts = tuple(
            item.interruption_receipt
            for item in error.failures
            if item.interruption_receipt is not None
        )
        custody_id = (
            None
            if checkpoint is None
            else self._checkpoint_custody_id(checkpoint, manifest, receipts)
        )
        resource_usage: Counter[str] = Counter()
        spent: Counter[str] = Counter()
        for receipt in receipts:
            for key, value in receipt.resources.to_dict().items():
                if isinstance(value, int) and not isinstance(value, bool):
                    resource_usage[key] += value
            for key, value in receipt.spent.to_dict().items():
                if isinstance(value, int) and not isinstance(value, bool):
                    spent[key] += value
        observation = Observation(
            task.target_id,
            task.campaign_task_id,
            outcome,
            operational_state=operational_state,
            checkpoint_ref=None if checkpoint is None else checkpoint.artifact,
            input_refs=task.task.input_refs,
            parameters=task.provenance.parameters.to_dict(),
            source_refs=task.provenance.source_refs,
            details={
                "checkpoint": None if checkpoint is None else checkpoint.to_dict(),
                "checkpoint_count": 0 if manifest is None else len(manifest.checkpoints),
                "checkpoint_custody_id": custody_id,
                "checkpoint_manifest": None if manifest is None else manifest.to_dict(),
                "checkpoint_scope": (
                    None
                    if manifest is None
                    else (
                        "single-shard-manifest"
                        if len(manifest.checkpoints) == 1
                        else "multi-shard-manifest"
                    )
                ),
                "dispatch_failures": [item.to_dict() for item in error.failures],
                "error": str(error),
                "error_type": type(error).__qualname__,
                "fleet_dispatch_error": error.to_dict(),
                "interruption_receipt": (receipts[0].to_dict() if len(receipts) == 1 else None),
                "interruption_receipts": [item.to_dict() for item in receipts],
                "multi_shard_resume_policy": (
                    "resume every checkpointed shard from the typed manifest; "
                    "uncached failed shards rerun"
                    if manifest is not None
                    else None
                ),
                "progress_completed": (
                    receipts[0].progress_completed if len(receipts) == 1 else None
                ),
                "progress_total": (receipts[0].progress_total if len(receipts) == 1 else None),
                "resource_usage": dict(resource_usage),
                "spent": dict(spent),
            },
        )
        self._observe(observation, trusted_runtime=True)
        return observation

    def _record_interruption(
        self,
        task: CampaignTask,
        interruption: FleetInterruption,
    ) -> Observation:
        mapping = {
            InterruptionReason.PREEMPTED: (
                Outcome.PREEMPTED,
                OperationalState.PREEMPTED,
            ),
            InterruptionReason.BUDGET_EXHAUSTED: (
                Outcome.BUDGET_EXHAUSTED,
                OperationalState.BUDGET_EXHAUSTED,
            ),
        }
        outcome, state = mapping[interruption.reason]
        checkpoint = interruption.checkpoint
        checkpoint_manifest: CheckpointManifest | None = None
        manifest_method = getattr(self.executor, "checkpoint_manifest", None)
        if callable(manifest_method):
            candidate_manifest = manifest_method(task.task.task_hash)
            if candidate_manifest is not None:
                if not isinstance(candidate_manifest, CheckpointManifest):
                    raise CampaignInvariantError(
                        "executor checkpoint_manifest returned an invalid value"
                    )
                checkpoint_manifest = candidate_manifest
                if checkpoint is None:
                    # Concurrent workers may publish typed checkpoints even
                    # when the deterministic first surfaced interruption has
                    # none.  Anchor the CampaignTask to the manifest's first
                    # canonical shard; dispatch still passes the full manifest.
                    checkpoint = checkpoint_manifest.checkpoints[0]
        checkpoint_count = (
            0 if checkpoint_manifest is None else len(checkpoint_manifest.checkpoints)
        )
        receipt = interruption.receipt
        if receipt is not None and not isinstance(receipt, InterruptionReceipt):
            raise CampaignInvariantError("executor interruption receipt has invalid type")
        receipts = () if receipt is None else (receipt,)
        custody_id = (
            None
            if checkpoint is None
            else self._checkpoint_custody_id(
                checkpoint,
                checkpoint_manifest,
                receipts,
            )
        )
        observation = Observation(
            task.target_id,
            task.campaign_task_id,
            outcome,
            operational_state=state,
            checkpoint_ref=None if checkpoint is None else checkpoint.artifact,
            input_refs=task.task.input_refs,
            parameters=task.provenance.parameters.to_dict(),
            source_refs=task.provenance.source_refs,
            details={
                "checkpoint": None if checkpoint is None else checkpoint.to_dict(),
                "checkpoint_count": checkpoint_count,
                "checkpoint_custody_id": custody_id,
                "checkpoint_manifest": (
                    None if checkpoint_manifest is None else checkpoint_manifest.to_dict()
                ),
                "checkpoint_scope": (
                    None
                    if checkpoint is None
                    else (
                        "single-shard"
                        if checkpoint_manifest is None
                        else (
                            "single-shard-manifest"
                            if checkpoint_count == 1
                            else "multi-shard-manifest"
                        )
                    )
                ),
                "detail": interruption.detail,
                "interruption_reason": interruption.reason.value,
                "interruption_receipt": (None if receipt is None else receipt.to_dict()),
                "multi_shard_resume_policy": (
                    "resume every checkpointed shard from the typed manifest; "
                    "other shards use verified cache or rerun"
                    if checkpoint_manifest is not None
                    else "the typed shard resumes; other shards use verified cache or rerun"
                    if checkpoint is not None
                    else None
                ),
                "progress_completed": (None if receipt is None else receipt.progress_completed),
                "progress_total": None if receipt is None else receipt.progress_total,
                "resource_usage": ({} if receipt is None else receipt.resources.to_dict()),
                "spent": {} if receipt is None else receipt.spent.to_dict(),
            },
        )
        self._observe(observation, trusted_runtime=True)
        return observation

    def _begin_attempt(
        self,
        task: CampaignTask,
        *,
        readiness_claim_id: str | None = None,
    ) -> AttemptRecord:
        prior = self.ledger.attempts_for_task(task.campaign_task_id)
        attempt_number = max((item.attempt for item in prior), default=0) + 1
        attempt = AttemptRecord(
            task.target_id,
            task.campaign_task_id,
            attempt_number,
            OperationalState.RUNNING,
            readiness_claim_id=readiness_claim_id,
        )
        event = self.ledger.record_attempt(attempt)
        self._active_attempts[task.campaign_task_id] = attempt
        if event is not None:
            self._emit_latest()
        return attempt

    def _record_dispatch_readiness_receipt(
        self,
        task: CampaignTask,
        receipt: DispatchReadinessReceipt,
    ) -> AttemptRecord:
        """Durably append operational lease authorization before work begins."""

        from arbogast.bootstrap import DispatchReadinessReceipt, readiness_receipt

        if not isinstance(receipt, DispatchReadinessReceipt) or not receipt.verify():
            raise CampaignReadinessError(
                "dispatch readiness receipt failed strict replay",
                code="READINESS_DISPATCH_RECEIPT_INVALID",
            )
        activation = self._active_readiness
        theorem_receipt = None if activation is None else readiness_receipt(activation.certificate)
        bindings = None if theorem_receipt is None else theorem_receipt.profile.bindings
        try:
            active_claim = None if activation is None else self.claim_graph.get(activation.claim_id)
        except Exception:
            active_claim = None
        if (
            activation is None
            or theorem_receipt is None
            or bindings is None
            or active_claim is None
            or receipt.environment_id != theorem_receipt.environment.environment_id
            or receipt.profile_id != theorem_receipt.profile.profile_id
            or receipt.readiness_receipt_id != theorem_receipt.receipt_id
            or receipt.campaign_id != self.campaign_id
            or receipt.campaign_plan_id != activation.plan.plan_id
            or receipt.campaign_task_id != task.campaign_task_id
            or receipt.campaign_target_id != task.target_id
            or receipt.fleet_task != task.task
            or receipt.readiness_certificate_id != activation.certificate.certificate_id
            or receipt.readiness_claim_id != activation.claim_id
            or receipt.readiness_certificate.to_dict() != activation.certificate.to_dict()
            or receipt.readiness_claim.to_dict() != active_claim.to_dict()
            or receipt.operation_registry_id != bindings["G"]
            or receipt.verifier_registry_id != bindings["V"]
            or receipt.executor_id != bindings["X"]
            or receipt.artifact_store_id != bindings["A"]
        ):
            raise CampaignReadinessError(
                "dispatch readiness receipt is outside the active campaign boundary",
                code="READINESS_DISPATCH_RECEIPT_MISMATCH",
            )
        with self._dispatch_readiness_lock:
            active = self._active_attempts.get(task.campaign_task_id)
            if active is None or not active.live:
                raise CampaignReadinessError(
                    "dispatch readiness receipt has no live campaign attempt",
                    code="READINESS_DISPATCH_ATTEMPT_MISSING",
                )
            if (
                receipt.campaign_attempt != active.attempt
                or receipt.campaign_attempt_id != active.attempt_id
            ):
                raise CampaignReadinessError(
                    "dispatch readiness receipt names a different campaign attempt",
                    code="READINESS_DISPATCH_RECEIPT_MISMATCH",
                )
            validate_context = getattr(
                self.executor,
                "validate_dispatch_context",
                None,
            )
            if not callable(validate_context):
                raise CampaignReadinessError(
                    "executor cannot replay active dispatch custody",
                    code="READINESS_LEASE_GUARD_UNSUPPORTED",
                )
            try:
                current_lease = validate_context(
                    task=receipt.fleet_task,
                    lease=receipt.lease,
                    dispatch_id=receipt.dispatch_id,
                    dispatch_ordinal=receipt.dispatch_ordinal,
                    dispatch_runtime_nonce=receipt.dispatch_runtime_nonce,
                    plan_hash=receipt.fleet_plan_hash,
                    worker_id=receipt.lease.worker_id,
                )
            except Exception as error:
                raise CampaignReadinessError(
                    "dispatch readiness receipt is not current scheduler authority",
                    code="READINESS_LEASE_STALE",
                    blockers=(str(error),),
                ) from error
            if current_lease != receipt.lease:
                raise CampaignReadinessError(
                    "dispatch readiness lease changed before provenance recording",
                    code="READINESS_LEASE_STALE",
                )
            if active.dispatch_readiness_receipt_id == receipt.receipt_id:
                return active
            updated = AttemptRecord(
                task.target_id,
                task.campaign_task_id,
                active.attempt,
                OperationalState.RUNNING,
                worker_id=active.worker_id,
                checkpoint_ref=active.checkpoint_ref,
                detail=active.detail,
                progress_completed=active.progress_completed,
                progress_total=active.progress_total,
                resources=active.resources,
                spent=active.spent,
                readiness_claim_id=active.readiness_claim_id,
                dispatch_readiness_receipt_id=receipt.receipt_id,
                dispatch_readiness_receipt=receipt.to_dict(),
            )
            self.ledger.record_attempt(updated)
            self._active_attempts[task.campaign_task_id] = updated
            # This is the final scheduler-to-run launch path.  Do not invoke
            # user sinks here: they are re-entrant and may block or mutate the
            # bound clock after custody was checked.  The next terminal attempt
            # event emits the complete history, including this receipt.
            return updated

    def _finish_attempt(
        self,
        task: CampaignTask,
        observation: Observation,
    ) -> None:
        active = self._active_attempts.pop(task.campaign_task_id, None)
        if active is None:
            return
        details = observation.details.to_dict()
        raw_resources = details.get("resource_usage", {})
        resources = raw_resources if isinstance(raw_resources, Mapping) else {}
        raw_spent = details.get("spent", {})
        spent = raw_spent if isinstance(raw_spent, Mapping) else {}
        completed = details.get("progress_completed")
        total = details.get("progress_total")
        if completed is not None and (
            isinstance(completed, bool) or not isinstance(completed, int)
        ):
            completed = None
        if total is not None and (isinstance(total, bool) or not isinstance(total, int)):
            total = None
        if total is not None and completed is not None and completed > total:
            completed = total
        detail = details.get("detail") or details.get("error")
        if detail is not None and not isinstance(detail, str):
            detail = None
        terminal_worker: str | None = None
        receipt = details.get("fleet_receipt")
        if isinstance(receipt, dict):
            worker_ids = receipt.get("worker_ids")
            if (
                isinstance(worker_ids, list)
                and len(worker_ids) == 1
                and isinstance(worker_ids[0], str)
            ):
                terminal_worker = worker_ids[0]
        interruption_receipt = details.get("interruption_receipt")
        if isinstance(interruption_receipt, Mapping):
            try:
                replayed_receipt = InterruptionReceipt.from_dict(interruption_receipt)
            except (KeyError, TypeError, ValueError) as error:
                raise CampaignInvariantError(
                    "campaign interruption receipt failed strict replay"
                ) from error
            terminal_worker = replayed_receipt.lease.worker_id
        terminal = AttemptRecord(
            task.target_id,
            task.campaign_task_id,
            active.attempt,
            observation.operational_state,
            worker_id=terminal_worker,
            checkpoint_ref=observation.checkpoint_ref,
            detail=detail,
            progress_completed=completed,
            progress_total=total,
            resources=resources,
            spent=spent,
            readiness_claim_id=active.readiness_claim_id,
            dispatch_readiness_receipt_id=active.dispatch_readiness_receipt_id,
            dispatch_readiness_receipt=(
                None
                if active.dispatch_readiness_receipt is None
                else active.dispatch_readiness_receipt.to_dict()
            ),
        )
        event = self.ledger.record_attempt(terminal)
        if event is not None:
            self._emit_latest()

    def _finish_readiness_refusal(self, task: CampaignTask) -> None:
        """Close an operational attempt without inventing an Observation."""

        active = self._active_attempts.pop(task.campaign_task_id, None)
        if active is None:
            return
        terminal = AttemptRecord(
            task.target_id,
            task.campaign_task_id,
            active.attempt,
            OperationalState.UNKNOWN,
            worker_id=active.worker_id,
            checkpoint_ref=active.checkpoint_ref,
            detail="dispatch readiness was refused before operation execution",
            progress_completed=active.progress_completed,
            progress_total=active.progress_total,
            resources=active.resources,
            spent=active.spent,
            readiness_claim_id=active.readiness_claim_id,
            dispatch_readiness_receipt_id=active.dispatch_readiness_receipt_id,
            dispatch_readiness_receipt=(
                None
                if active.dispatch_readiness_receipt is None
                else active.dispatch_readiness_receipt.to_dict()
            ),
        )
        event = self.ledger.record_attempt(terminal)
        if event is not None:
            self._emit_latest()

    def _typed_checkpoint_for_task(
        self,
        task: CampaignTask,
    ) -> CheckpointManifest | CheckpointRef:
        """Replay the exact checkpoint receipt named by an operational task."""

        if task.checkpoint_ref is None:
            raise CampaignInvariantError("campaign task is not checkpointed")
        if task.checkpoint_custody_id is None:
            raise CampaignError("campaign task has no typed checkpoint custody identity")
        observations_by_id = {
            observation.observation_id: observation for observation in self.ledger.observations
        }
        for observation_id in reversed(task.provenance.parent_observation_ids):
            observation = observations_by_id.get(observation_id)
            if observation is None or observation.checkpoint_ref != task.checkpoint_ref:
                continue
            details = observation.details.to_dict()
            raw_checkpoint = details.get("checkpoint")
            raw_manifest = details.get("checkpoint_manifest")
            receipts = self._interruption_receipts_from_details(details)
            if isinstance(raw_manifest, Mapping):
                try:
                    manifest = CheckpointManifest.from_dict(raw_manifest)
                except (KeyError, TypeError, ValueError) as error:
                    raise CampaignError("checkpoint manifest failed strict replay") from error
                if manifest.task_hash != task.task.task_hash or not any(
                    item.artifact.uri == task.checkpoint_ref for item in manifest.checkpoints
                ):
                    raise CampaignError("checkpoint manifest is not bound to this CampaignTask")
                anchor = next(
                    item
                    for item in manifest.checkpoints
                    if item.artifact.uri == task.checkpoint_ref
                )
                if (
                    self._checkpoint_custody_id(anchor, manifest, receipts)
                    != task.checkpoint_custody_id
                ):
                    continue
                return manifest
            if not isinstance(raw_checkpoint, Mapping):
                raise CampaignError("checkpoint has only a legacy URI and no typed custody receipt")
            try:
                checkpoint = CheckpointRef.from_dict(raw_checkpoint)
            except (KeyError, TypeError, ValueError) as error:
                raise CampaignError("checkpoint custody receipt failed strict replay") from error
            if checkpoint.artifact.uri != task.checkpoint_ref:
                raise CampaignError(
                    "checkpoint custody receipt does not match CampaignTask checkpoint_ref"
                )
            if (
                self._checkpoint_custody_id(checkpoint, None, receipts)
                != task.checkpoint_custody_id
            ):
                continue
            return checkpoint
        raise CampaignError(
            "checkpointed CampaignTask has no parent observation with typed custody"
        )

    def _checkpoint_resume_blocker(self, task: CampaignTask) -> str | None:
        if task.checkpoint_ref is None:
            return None
        if task.checkpoint_custody_id is None:
            return "checkpoint lacks typed custody identity; automatic resume is suspended"
        supports_resume = getattr(self.executor, "supports_checkpoint_resume", None)
        if callable(supports_resume):
            try:
                supported = supports_resume(task.task)
            except TypeError:
                supported = supports_resume()
            if supported is not True:
                return "configured executor cannot replay typed checkpoints; resume is suspended"
        elif not callable(getattr(self.executor, "execute_checkpointed", None)):
            return "configured executor cannot replay typed checkpoints; resume is suspended"
        return None

    def dispatch(
        self,
        task: CampaignTask | Recommendation | str | None = None,
        *,
        raise_errors: bool = False,
    ) -> Observation:
        if task is None and self._active_readiness is None and self.strict_readiness:
            # ``_resolve_task(None)`` records a newly computed plan, so reject
            # before calling it when no runtime theorem can authorize work.
            raise CampaignReadinessError(
                "campaign dispatch requires an active readiness theorem",
                code="READINESS_NOT_ACTIVE",
                blockers=("no readiness certificate is active",),
            )
        if task is None and self._active_readiness is not None:
            # An active theorem authorizes its recorded plan, not a newly
            # recomputed one.  Select the next untouched exact recommendation
            # without appending a replacement plan to the ledger.
            task = self._next_active_readiness_recommendation()
            if task is None:
                raise CampaignReadinessError(
                    "the active readiness plan has no untouched dispatchable recommendation",
                    code="READINESS_PLAN_EXHAUSTED",
                )
        recommendation = task if isinstance(task, Recommendation) else None
        selected = self._resolve_task(task)
        if self.ledger.status(selected.target_id).closed:
            raise CampaignInvariantError("cannot dispatch work for a closed target")
        # This check deliberately precedes mathematical preflight and every
        # ledger mutation.  Failure to authorize execution is not an
        # Observation about the campaign's mathematical target.
        readiness_claim_id = self._require_dispatch_readiness(
            selected,
            recommendation,
        )
        strategy = next(
            (item for item in self.spec.strategies if item.name == selected.strategy),
            None,
        )
        if strategy is not None and not self._preflight(
            selected.target,
            strategy,
            selected,
        ):
            if self.ledger.status(selected.target_id).closed:
                observations = self.ledger.observations_for_task(selected.campaign_task_id)
                if observations:
                    return observations[-1]
            raise CampaignError(
                f"campaign task {selected.campaign_task_id} is deferred by its exact gate"
            )
        missing = self._missing_capabilities(selected)
        if missing:
            raise CapabilityUnavailableError(f"missing task capabilities: {missing}")
        worker_reasons = self._worker_ineligibility(selected)
        if worker_reasons:
            raise CapabilityUnavailableError(f"no eligible worker: {' ; '.join(worker_reasons)}")
        operation: FleetOperation | None = None
        if self.operation_registry is not None:
            try:
                operation = self.operation_registry.resolve(selected.task.operation)
            except (KeyError, LookupError) as error:
                if selected.task.operation not in self.operations:
                    raise UnknownOperationError(selected.task.operation) from error
        if operation is None:
            operation = self.operations.get(selected.task.operation)
        if operation is None:
            raise UnknownOperationError(selected.task.operation)
        execute_checkpointed: object | None = None
        typed_checkpoint: CheckpointManifest | CheckpointRef | None = None
        if selected.checkpoint_ref is not None:
            resume_blocker = self._checkpoint_resume_blocker(selected)
            if resume_blocker is not None:
                raise CampaignError(resume_blocker)
            execute_checkpointed = getattr(
                self.executor,
                "execute_checkpointed",
                None,
            )
            if not callable(execute_checkpointed):
                raise CampaignError("executor does not support typed checkpoint resume")
            typed_checkpoint = self._typed_checkpoint_for_task(selected)
        readiness_context = self._lease_dispatch_readiness_context(
            selected,
            recommendation,
            operation,
        )
        event = self.ledger.start_task(selected.campaign_task_id)
        if event is not None:
            self._emit_latest()
        self._begin_attempt(
            selected,
            readiness_claim_id=readiness_claim_id,
        )
        try:
            with readiness_context:
                verify = False if strategy is None else strategy.verify_results
                if selected.checkpoint_ref is None:
                    run = self.executor.execute(selected.task, operation, verify=verify)
                else:
                    assert callable(execute_checkpointed)
                    assert typed_checkpoint is not None
                    run = execute_checkpointed(
                        selected.task,
                        operation,
                        checkpoint_ref=typed_checkpoint,
                        verify=verify,
                    )
            return self.harvest(selected, run)
        except FleetInterruption as interruption:
            observation = self._record_interruption(selected, interruption)
            self._finish_attempt(selected, observation)
            return observation
        except FleetDispatchError as error:
            observation = self._record_dispatch_error(selected, error)
            self._finish_attempt(selected, observation)
            if raise_errors:
                raise
            return observation
        except CampaignReadinessError:
            # The worker-pool guard can reject after a lease is active but
            # before its operation begins.  Never convert that environmental
            # refusal into a mathematical Observation.
            self._finish_readiness_refusal(selected)
            raise
        except Exception as error:
            observation = self._record_failed_dispatch(selected, error)
            self._finish_attempt(selected, observation)
            if raise_errors:
                raise
            return observation

    def _certificate_from_result(self, value: object) -> Certificate | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise CampaignInvariantError("result certificate must be an object")
        try:
            return certificate_from_dict(cast(Mapping[str, object], value))
        except (CertificateError, KeyError, TypeError, ValueError) as error:
            raise CampaignInvariantError("result certificate failed strict replay") from error

    def _observation_from_run(self, task: CampaignTask, run: FleetRun) -> Observation:
        if run.task.task_hash != task.task.task_hash:
            raise CampaignInvariantError("fleet run is not bound to the campaign task")
        value = self.executor.result_value(run)
        raw_outcome: object = None
        raw_outcome_scope: object = None
        # A successful FleetRun consumes any resume checkpoint.  Only a fresh,
        # typed FleetInterruption may establish new resumable custody.
        checkpoint_ref: object | None = None
        certificate_value: object = None
        execution_telemetry: ExecutionTelemetry | None = None
        details: dict[str, Any] = {
            "fleet_plan_hash": run.plan.plan_hash,
            "fleet_state": run.state.value,
            "fleet_task_hash": run.task.task_hash,
        }
        receipt_for = getattr(self.executor, "receipt_for", None)
        if callable(receipt_for):
            receipt = receipt_for(run)
            receipt_to_dict = getattr(receipt, "to_dict", None)
            if not callable(receipt_to_dict):
                raise CampaignInvariantError(
                    "executor receipt must provide a canonical to_dict projection"
                )
            details["fleet_receipt"] = receipt_to_dict()
        if isinstance(value, dict):
            raw_outcome = value.get("outcome")
            raw_outcome_scope = value.get("outcome_scope")
            reducer_checkpoint = value.get("checkpoint_ref")
            if reducer_checkpoint is not None and reducer_checkpoint != checkpoint_ref:
                details["rejected_untrusted_checkpoint_ref"] = reducer_checkpoint
            certificate_value = value.get("certificate")
            telemetry_value = value.get("execution_telemetry")
            if telemetry_value is not None:
                if not isinstance(telemetry_value, Mapping):
                    raise CampaignInvariantError("result execution_telemetry must be an object")
                try:
                    execution_telemetry = ExecutionTelemetry.from_dict(telemetry_value)
                except CampaignSerializationError as error:
                    raise CampaignInvariantError(
                        "result execution_telemetry failed strict replay"
                    ) from error
            details["result"] = value
        else:
            details["result"] = value
        outcome = Outcome.UNKNOWN
        if isinstance(raw_outcome, str):
            try:
                outcome = Outcome(raw_outcome)
            except ValueError:
                details["unrecognized_outcome"] = raw_outcome
        outcome_scope = OutcomeScope.TASK_LOCAL
        valid_outcome_scope = True
        if raw_outcome_scope is None:
            details["defaulted_outcome_scope"] = OutcomeScope.TASK_LOCAL.value
        elif isinstance(raw_outcome_scope, str):
            try:
                outcome_scope = OutcomeScope(raw_outcome_scope)
            except ValueError:
                valid_outcome_scope = False
                details["unrecognized_outcome_scope"] = raw_outcome_scope
        else:
            valid_outcome_scope = False
            details["unrecognized_outcome_scope"] = raw_outcome_scope
        certificate = self._certificate_from_result(certificate_value)
        if execution_telemetry is not None:
            details["execution_telemetry"] = execution_telemetry.to_dict()
            if execution_telemetry.progress_completed is not None:
                details["progress_completed"] = execution_telemetry.progress_completed
            if execution_telemetry.progress_total is not None:
                details["progress_total"] = execution_telemetry.progress_total
            details["resource_usage"] = execution_telemetry.resources.to_dict()
            details["spent"] = execution_telemetry.spent.to_dict()
        if not valid_outcome_scope and outcome in CLOSING_OUTCOMES:
            details["rejected_unscoped_outcome"] = outcome.value
            outcome = Outcome.UNKNOWN
            certificate = None
        if outcome in CLOSING_OUTCOMES and certificate is None:
            details["rejected_unverified_outcome"] = outcome.value
            outcome = Outcome.UNKNOWN
        state_map = {
            Outcome.BUDGET_EXHAUSTED: OperationalState.BUDGET_EXHAUSTED,
            Outcome.PREEMPTED: OperationalState.PREEMPTED,
            Outcome.FAILED: OperationalState.FAILED,
            Outcome.UNKNOWN: OperationalState.UNKNOWN,
        }
        operational_state = state_map.get(outcome, OperationalState.COMPLETED)
        try:
            observation = Observation(
                task.target_id,
                task.campaign_task_id,
                outcome,
                outcome_scope=outcome_scope,
                operational_state=operational_state,
                certificate=certificate,
                result_ref=run.result,
                checkpoint_ref=checkpoint_ref,
                input_refs=task.task.input_refs,
                parameters=task.provenance.parameters.to_dict(),
                source_refs=task.provenance.source_refs,
                details=details,
            )
            if outcome in CLOSING_OUTCOMES and not observation.verify(self.verifier_registry):
                details["rejected_unverified_outcome"] = outcome.value
                return Observation(
                    task.target_id,
                    task.campaign_task_id,
                    Outcome.UNKNOWN,
                    operational_state=OperationalState.UNKNOWN,
                    result_ref=run.result,
                    checkpoint_ref=checkpoint_ref,
                    input_refs=task.task.input_refs,
                    parameters=task.provenance.parameters.to_dict(),
                    source_refs=task.provenance.source_refs,
                    details=details,
                )
            return observation
        except CampaignInvariantError as error:
            details["rejected_closure"] = str(error)
            return Observation(
                task.target_id,
                task.campaign_task_id,
                Outcome.UNKNOWN,
                operational_state=OperationalState.UNKNOWN,
                result_ref=run.result,
                checkpoint_ref=checkpoint_ref,
                input_refs=task.task.input_refs,
                parameters=task.provenance.parameters.to_dict(),
                source_refs=task.provenance.source_refs,
                details=details,
            )

    def harvest(self, task: CampaignTask | str, run: FleetRun) -> Observation:
        selected = self._resolve_task(task)
        if selected.campaign_task_id not in self._active_attempts:
            self._begin_attempt(selected)
        observation = self._observation_from_run(selected, run)
        self._observe(observation, trusted_runtime=True)
        self._finish_attempt(selected, observation)
        return observation

    def _certificate_witness_value(
        self,
        observation: Observation,
        key: str,
    ) -> JSONValue | None:
        if observation.certificate_payload is None:
            return None
        payload = observation.certificate_payload.to_dict()
        witness = payload.get("witness")
        if not isinstance(witness, dict):
            return None
        return witness.get(key)

    def _validate_observation_custody(
        self,
        observation: Observation,
        task: CampaignTask,
        *,
        trusted_runtime: bool,
        gate_closure: bool,
    ) -> None:
        if observation.input_refs != task.task.input_refs:
            raise CampaignInvariantError(
                "observation input_refs do not match the planned campaign task"
            )
        if observation.parameters.to_dict() != task.provenance.parameters.to_dict():
            raise CampaignInvariantError(
                "observation parameters do not match the planned task provenance"
            )
        if observation.source_refs != task.provenance.source_refs:
            raise CampaignInvariantError(
                "observation source_refs do not match the planned task provenance"
            )
        if not trusted_runtime:
            if observation.result_ref is not None and (
                not observation.verify(self.verifier_registry)
                or self._certificate_witness_value(observation, "result_ref")
                != observation.result_ref
            ):
                raise CampaignInvariantError(
                    "an external result_ref must be bound by its verified certificate witness"
                )
            if (
                observation.checkpoint_ref is not None
                and observation.checkpoint_ref != task.checkpoint_ref
                and (
                    not observation.verify(self.verifier_registry)
                    or self._certificate_witness_value(observation, "checkpoint_ref")
                    != observation.checkpoint_ref
                )
            ):
                raise CampaignInvariantError(
                    "an external checkpoint_ref must be bound by its verified certificate witness"
                )
        if observation.outcome in CLOSING_OUTCOMES:
            if not observation.verify(self.verifier_registry):
                raise CampaignInvariantError(
                    "mathematical closure failed its registered independent verifier"
                )
            activation = self._active_readiness
            if activation is not None:
                payload = observation.certificate_payload
                verifier_name = None if payload is None else payload.get("verifier")
                if verifier_name not in activation.required_verifiers:
                    raise CampaignInvariantError(
                        "mathematical closure certificate verifier is absent from "
                        "the active readiness profile's certified required V roster"
                    )
            if (
                not gate_closure
                and self._certificate_witness_value(observation, "task_hash") != task.task.task_hash
            ):
                raise CampaignInvariantError(
                    "closure certificate is not bound to the planned fleet task hash"
                )

    def _candidate_records_from_observation(
        self,
        observation: Observation,
    ) -> tuple[CandidateRecord, ...]:
        """Decode the narrow, data-only candidate result contract.

        Candidate artifacts and provenance are bound to the already validated
        observation.  Operations may describe mathematical canonical keys,
        invariants, evidence level, and integer quality; they cannot introduce
        a second unverified artifact or lineage edge through this surface.
        """

        result = observation.details.to_dict().get("result")
        if not isinstance(result, dict) or "candidates" not in result:
            return ()
        raw_candidates = result["candidates"]
        if not isinstance(raw_candidates, list):
            raise CampaignInvariantError("result candidates must be an array of objects")
        candidate_values: list[dict[str, JSONValue]] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                raise CampaignInvariantError("result candidates must be an array of objects")
            candidate_values.append(item)
        allowed = {
            "artifact_ref",
            "canonical_key",
            "canonicalizer",
            "certificate_ref",
            "evidence",
            "equivalence_scope",
            "invariants",
            "quality",
            "quality_metric",
            "source_refs",
        }
        records: list[CandidateRecord] = []
        for raw in candidate_values:
            required = {
                "canonical_key",
                "canonicalizer",
                "equivalence_scope",
                "evidence",
            }
            if set(raw) - allowed or not required <= set(raw):
                raise CampaignInvariantError("result candidate has missing or unknown fields")
            canonical_key = raw["canonical_key"]
            canonicalizer = raw["canonicalizer"]
            equivalence_scope_value = raw["equivalence_scope"]
            evidence_value = raw["evidence"]
            if (
                not isinstance(canonical_key, str)
                or not isinstance(canonicalizer, str)
                or not isinstance(equivalence_scope_value, str)
                or not isinstance(evidence_value, str)
            ):
                raise CampaignInvariantError(
                    "candidate identity and evidence fields must be strings"
                )
            try:
                evidence = CandidateEvidence(evidence_value)
                equivalence_scope = CandidateScope(equivalence_scope_value)
            except ValueError as error:
                raise CampaignInvariantError(
                    "unsupported candidate evidence level or equivalence scope"
                ) from error
            invariants = raw.get("invariants", {})
            if not isinstance(invariants, Mapping):
                raise CampaignInvariantError("candidate invariants must be an object")
            quality = raw.get("quality", 0)
            if isinstance(quality, bool) or not isinstance(quality, int):
                raise CampaignInvariantError("candidate quality must be an integer")
            quality_metric = raw.get("quality_metric", "campaign-quality")
            if not isinstance(quality_metric, str):
                raise CampaignInvariantError("candidate quality_metric must be a string")
            artifact_ref = raw.get("artifact_ref", observation.result_ref)
            if artifact_ref is None or artifact_ref != observation.result_ref:
                raise CampaignInvariantError(
                    "candidate artifact_ref must match its observed fleet result"
                )
            raw_sources = raw.get("source_refs", list(observation.source_refs))
            if not isinstance(raw_sources, list) or any(
                not isinstance(item, str) for item in raw_sources
            ):
                raise CampaignInvariantError("candidate source_refs must be strings")
            if tuple(raw_sources) != observation.source_refs:
                raise CampaignInvariantError(
                    "candidate source_refs must match observation provenance"
                )
            observed_certificate = (
                None
                if observation.certificate_ref is None
                else observation.certificate_ref.certificate_id
            )
            certificate_ref = raw.get("certificate_ref")
            if evidence is CandidateEvidence.VERIFIED and certificate_ref is None:
                certificate_ref = observed_certificate
            if certificate_ref is not None and certificate_ref != observed_certificate:
                raise CampaignInvariantError(
                    "candidate certificate_ref must match observation evidence"
                )
            records.append(
                CandidateRecord(
                    observation.target_id,
                    observation.task_id,
                    observation.observation_id,
                    canonical_key,
                    artifact_ref,
                    canonicalizer=canonicalizer,
                    equivalence_scope=equivalence_scope,
                    invariants=invariants,
                    evidence=evidence,
                    quality=quality,
                    quality_metric=quality_metric,
                    certificate_ref=certificate_ref,
                    source_refs=observation.source_refs,
                )
            )
        return tuple(records)

    def record_candidate(self, candidate: CandidateRecord) -> CandidateRecord:
        """Append one observation-bound mathematical candidate idempotently."""

        event = self.ledger.record_candidate(candidate)
        if event is not None:
            self._emit_latest()
        return candidate

    def _observe(
        self,
        observation: Observation,
        *,
        trusted_runtime: bool = False,
        gate_closure: bool = False,
    ) -> tuple[CampaignTask, ...]:
        observation = observation.with_verifier_registry(self.verifier_registry)
        task = self._tasks.get(observation.task_id)
        if task is None:
            raise CampaignInvariantError("observation task was not planned by this campaign")
        if task.target_id != observation.target_id:
            raise CampaignInvariantError("observation target does not match its planned task")
        for existing in self.ledger.observations_for_task(observation.task_id):
            if existing.observation_id != observation.observation_id:
                continue
            if existing != observation:
                raise CampaignInvariantError("observation ID collision")
            return ()
        self._validate_observation_custody(
            observation,
            task,
            trusted_runtime=trusted_runtime,
            gate_closure=gate_closure,
        )
        candidate_records = self._candidate_records_from_observation(observation)
        claim = (
            claim_for_observation(self.campaign_id, self.name, task, observation)
            if observation.closes_target_with(self.verifier_registry)
            else None
        )
        if (
            claim is not None
            and claim.id in self.claim_graph
            and self.claim_graph.get(claim.id) != claim
        ):
            raise CampaignInvariantError(
                "campaign claim graph conflicts with authoritative observation"
            )
        event = self.ledger.record(observation)
        if event is None:
            return ()
        self._emit_latest()
        for candidate_record in candidate_records:
            self.record_candidate(candidate_record)
        if claim is not None:
            if claim.id not in self.claim_graph:
                self.claim_graph.add_claim(claim)
            claim_event = self.ledger.bind_claim(
                claim_id=claim.id,
                claim_digest=claim.digest,
                observation_id=observation.observation_id,
                target_id=observation.target_id,
            )
            if claim_event is not None:
                self._emit_latest()
        derived: list[CampaignTask] = []
        for rule in self.derivations:
            for candidate in rule.apply(observation, self.ledger):
                derived.append(self.add_task(candidate))
        return tuple(derived)

    def observe(self, observation: Observation) -> tuple[CampaignTask, ...]:
        """Record externally supplied evidence after strict custody validation."""

        return self._observe(observation)

    def run(self, limit: int | None = None) -> tuple[Observation, ...]:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise CampaignInvariantError("run limit must be a non-negative integer")
        if limit != 0 and self.strict_readiness and self._active_readiness is None:
            raise CampaignReadinessError(
                "campaign run requires an active readiness theorem",
                code="READINESS_NOT_ACTIVE",
                blockers=("no readiness certificate is active",),
            )
        results: list[Observation] = []
        while limit is None or len(results) < limit:
            if self._active_readiness is not None:
                recommendation = self._next_active_readiness_recommendation()
                if recommendation is None:
                    break
                results.append(self.dispatch(recommendation))
                continue
            plan = self.recommend(limit=1)
            if not plan.recommendations:
                break
            # Dispatch the exact recommendation just planned.  Calling
            # dispatch() without it would invoke recommend() a second time and
            # lose the plan identity certified by readiness.
            results.append(self.dispatch(plan.recommendations[0]))
        return tuple(results)

    def export_claims(self) -> dict[str, JSONValue]:
        """Return a canonical, directly replayable semantic ClaimGraph."""

        value = normalize_json(self.claim_graph.to_dict())
        if not isinstance(value, dict):
            raise CampaignInvariantError("claim graph serialization must produce an object")
        return value

    def export_claim_candidates(self) -> tuple[dict[str, JSONValue], ...]:
        """Return lower-level closure receipts for compatibility and auditing."""

        candidates: list[dict[str, JSONValue]] = []
        for observation in self.ledger.observations:
            if not observation.closes_target_with(self.verifier_registry):
                continue
            result_is_evidence = (
                observation.result_ref is not None
                and self._certificate_witness_value(observation, "result_ref")
                == observation.result_ref
            )
            candidates.append(
                {
                    "certificate_payload": (
                        None
                        if observation.certificate_payload is None
                        else observation.certificate_payload.to_dict()
                    ),
                    "certificate_ref": (
                        None
                        if observation.certificate_ref is None
                        else normalize_json(observation.certificate_ref.to_dict())
                    ),
                    "evidence_result_ref": (observation.result_ref if result_is_evidence else None),
                    "execution_receipt_ref": observation.result_ref,
                    "observation_id": observation.observation_id,
                    "outcome": observation.outcome.value,
                    "provenance": {
                        "input_refs": list(observation.input_refs),
                        "parameters": observation.parameters.to_dict(),
                        "source_refs": list(observation.source_refs),
                    },
                    "result_ref_is_evidence": result_is_evidence,
                    "schema": "arbogast.campaign.claim-candidate.v1",
                    "target_id": observation.target_id,
                    "task_id": observation.task_id,
                }
            )
        return tuple(candidates)

    def to_dict(self) -> dict[str, JSONValue]:
        claims = normalize_json(self.claim_graph.to_dict())
        if not isinstance(claims, dict):
            raise CampaignInvariantError("claim graph serialization must produce an object")
        return {
            "campaign_id": self.campaign_id,
            "claims": claims,
            "ledger": self.ledger.to_dict(),
            "schema": self.schema,
            "spec": self.spec.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    def save(self, path: str | os.PathLike[str]) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(self.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def export(self, path: str | os.PathLike[str] | None = None) -> dict[str, JSONValue] | Path:
        return self.to_dict() if path is None else self.save(path)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        executor: LocalExecutor | None = None,
        operations: Mapping[str, FleetOperation] | None = None,
        operation_registry: _OperationRegistry | None = None,
        verifier_registry: VerifierRegistry | None = None,
        strict_readiness: bool = False,
        gates: Mapping[str, ExactGate] | None = None,
        task_factories: Mapping[str, TaskFactory] | None = None,
        derivations: Iterable[DerivationRule] | None = None,
        capabilities: Iterable[str] | None = (),
        sinks: Iterable[_Sink] = (),
    ) -> Campaign:
        required = {"campaign_id", "claims", "ledger", "schema", "spec"}
        if set(value) != required:
            raise CampaignSerializationError("campaign has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise CampaignSerializationError("unsupported campaign schema")
        spec_value = value["spec"]
        ledger_value = value["ledger"]
        claims_value = value["claims"]
        if (
            not isinstance(spec_value, Mapping)
            or not isinstance(ledger_value, Mapping)
            or not isinstance(claims_value, Mapping)
        ):
            raise CampaignSerializationError("campaign spec, ledger, and claims must be objects")
        spec = CampaignSpec.from_dict(spec_value)
        if value["campaign_id"] != spec.campaign_id:
            raise CampaignSerializationError("campaign_id does not match campaign spec")
        try:
            claim_graph = ClaimGraph.from_dict(claims_value)
        except ClaimGraphError as error:
            raise CampaignSerializationError("campaign claim graph failed replay") from error
        if verifier_registry is not None and not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry or None")
        resolved_verifiers = default_verifiers if verifier_registry is None else verifier_registry
        return cls(
            spec,
            ledger=TargetLedger.from_dict(
                ledger_value,
                verifier_registry=resolved_verifiers,
            ),
            executor=executor,
            operations=operations,
            operation_registry=operation_registry,
            verifier_registry=verifier_registry,
            strict_readiness=strict_readiness,
            gates=gates,
            task_factories=task_factories,
            derivations=derivations,
            claims=claim_graph,
            capabilities=capabilities,
            sinks=sinks,
        )

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
        **runtime: Any,
    ) -> Campaign:
        parsed = loads(value)
        if not isinstance(parsed, dict):
            raise CampaignSerializationError("campaign JSON must be an object")
        return cls.from_dict(parsed, **runtime)

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        **runtime: Any,
    ) -> Campaign:
        return cls.from_json(Path(path).read_bytes(), **runtime)


__all__ = ["Campaign", "CampaignStatus", "TargetExplanation"]
