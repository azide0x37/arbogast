"""Append-only authoritative target ledger."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from arbogast.cert import VerifierRegistry, default_verifiers
from arbogast.formats import FrozenMapping, JSONValue, canonical_dumps, loads, thaw_json

from .errors import CampaignInvariantError, CampaignSerializationError, UnknownTargetError
from .events import EventKind, LedgerEvent, MathematicalOutcome, Observation
from .results import AttemptRecord, CandidateRecord
from .targets import TargetSpec, TargetState, TargetStatus

_CONTENT_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class _CampaignTaskLike(Protocol):
    @property
    def campaign_task_id(self) -> str: ...

    @property
    def target_id(self) -> str: ...

    def to_dict(self) -> dict[str, JSONValue]: ...


class TargetLedger:
    """Canonical target deduplication backed by a hash-chained event log.

    Derived indexes are rebuilt from events during replay.  They are never
    serialized as an independently mutable source of mathematical state.
    """

    schema = "arbogast.campaign.ledger.v1"

    def __init__(
        self,
        targets: Iterable[TargetSpec] = (),
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> None:
        if not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry")
        self._verifier_registry = verifier_registry
        self._events: list[LedgerEvent] = []
        self._targets: dict[str, TargetSpec] = {}
        self._observations: dict[str, list[Observation]] = {}
        self._tasks: dict[str, FrozenMapping] = {}
        self._task_observations: dict[str, list[Observation]] = {}
        self._observations_by_id: dict[str, Observation] = {}
        self._candidate_records: dict[str, CandidateRecord] = {}
        self._candidate_history: dict[str, list[CandidateRecord]] = {}
        self._attempts: dict[str, list[AttemptRecord]] = {}
        self._plans: dict[str, FrozenMapping] = {}
        self._claim_bindings: dict[str, FrozenMapping] = {}
        for target in targets:
            self.add(target)

    def use_verifier_registry(self, verifier_registry: VerifierRegistry) -> None:
        """Bind runtime-only verification context without changing ledger bytes."""

        if not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry")
        self._verifier_registry = verifier_registry

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    @property
    def targets(self) -> tuple[TargetSpec, ...]:
        return tuple(self._targets[key] for key in sorted(self._targets))

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tasks))

    @property
    def observations(self) -> tuple[Observation, ...]:
        result: list[Observation] = []
        for event in self._events:
            if event.kind is not EventKind.OBSERVATION_RECORDED:
                continue
            raw = thaw_json(event.payload["observation"])
            if not isinstance(raw, dict):
                raise CampaignSerializationError("observation payload must be an object")
            result.append(Observation.from_dict(raw, verifier_registry=self._verifier_registry))
        return tuple(result)

    @property
    def candidates(self) -> tuple[CandidateRecord, ...]:
        return tuple(self._candidate_records[key] for key in sorted(self._candidate_records))

    @property
    def canonical_candidates(self) -> tuple[CandidateRecord, ...]:
        result: list[CandidateRecord] = []
        for candidate_id in sorted(self._candidate_history):
            history = self._candidate_history[candidate_id]
            metrics = sorted({candidate.quality_metric for candidate in history})
            for metric in metrics:
                comparable = tuple(
                    candidate for candidate in history if candidate.quality_metric == metric
                )
                best = comparable[0]
                for candidate in comparable[1:]:
                    if candidate.better_than(best):
                        best = candidate
                result.append(best)
        return tuple(result)

    @property
    def attempts(self) -> tuple[AttemptRecord, ...]:
        return tuple(
            record for attempt_id in sorted(self._attempts) for record in self._attempts[attempt_id]
        )

    @property
    def live_attempts(self) -> tuple[AttemptRecord, ...]:
        return tuple(
            history[-1] for _, history in sorted(self._attempts.items()) if history[-1].live
        )

    @property
    def latest_attempts(self) -> tuple[AttemptRecord, ...]:
        return tuple(history[-1] for _, history in sorted(self._attempts.items()))

    @property
    def plan_documents(self) -> tuple[dict[str, JSONValue], ...]:
        return tuple(self._plans[key].to_dict() for key in sorted(self._plans))

    @property
    def latest_plan_document(self) -> dict[str, JSONValue] | None:
        for event in reversed(self._events):
            if event.kind is not EventKind.PLAN_RECORDED:
                continue
            value = thaw_json(event.payload["plan"])
            if not isinstance(value, dict):
                raise CampaignSerializationError("plan payload must be an object")
            return value
        return None

    @property
    def claim_bindings(self) -> tuple[dict[str, JSONValue], ...]:
        return tuple(self._claim_bindings[key].to_dict() for key in sorted(self._claim_bindings))

    def __len__(self) -> int:
        return len(self._targets)

    def __contains__(self, target: object) -> bool:
        if isinstance(target, TargetSpec):
            return target.target_id in self._targets
        if isinstance(target, str):
            return target in self._targets or any(
                item.key == target for item in self._targets.values()
            )
        return False

    def _append(self, kind: EventKind, payload: Mapping[str, Any]) -> LedgerEvent:
        previous = None if not self._events else self._events[-1].event_id
        event = LedgerEvent(
            sequence=len(self._events),
            kind=kind,
            payload=FrozenMapping(payload),
            previous_event_id=previous,
        )
        self._apply(event)
        self._events.append(event)
        return event

    def add(self, target: TargetSpec) -> TargetSpec:
        """Add a target or return the canonical existing representative."""

        existing = self._targets.get(target.target_id)
        if existing is not None:
            return existing
        self._append(EventKind.TARGET_ADDED, {"target": target.to_dict()})
        return target

    add_target = add

    def get(self, target: TargetSpec | str) -> TargetSpec:
        if isinstance(target, TargetSpec):
            target_id = target.target_id
        elif target in self._targets:
            target_id = target
        else:
            matches = tuple(item for item in self._targets.values() if item.key == target)
            if len(matches) != 1:
                raise UnknownTargetError(target)
            return matches[0]
        try:
            return self._targets[target_id]
        except KeyError as error:
            raise UnknownTargetError(target_id) from error

    def plan_task(self, task: _CampaignTaskLike) -> LedgerEvent | None:
        if task.target_id not in self._targets:
            raise UnknownTargetError(task.target_id)
        if task.campaign_task_id in self._tasks:
            return None
        return self._append(EventKind.TASK_PLANNED, {"task": task.to_dict()})

    def start_task(self, task_id: str) -> LedgerEvent:
        if task_id not in self._tasks:
            raise CampaignInvariantError(f"cannot start unknown campaign task {task_id!r}")
        return self._append(EventKind.TASK_STARTED, {"task_id": task_id})

    def record_attempt(self, attempt: AttemptRecord) -> LedgerEvent | None:
        if attempt.target_id not in self._targets:
            raise UnknownTargetError(attempt.target_id)
        task_document = self._tasks.get(attempt.task_id)
        if task_document is None:
            raise CampaignInvariantError("attempt refers to an unplanned campaign task")
        if task_document["target_id"] != attempt.target_id:
            raise CampaignInvariantError("attempt target does not match its planned task")
        history = self._attempts.get(attempt.attempt_id, [])
        if any(existing.record_id == attempt.record_id for existing in history):
            return None
        if history:
            previous = history[-1]
            if not previous.live:
                raise CampaignInvariantError("a terminal attempt cannot receive another state")
            if previous.worker_id is not None and previous.worker_id != attempt.worker_id:
                raise CampaignInvariantError("attempt worker assignment cannot change")
        elif not attempt.live:
            raise CampaignInvariantError("the first attempt state must be RUNNING")
        return self._append(EventKind.ATTEMPT_RECORDED, {"attempt": attempt.to_dict()})

    def record_candidate(self, candidate: CandidateRecord) -> LedgerEvent | None:
        if candidate.target_id not in self._targets:
            raise UnknownTargetError(candidate.target_id)
        task_document = self._tasks.get(candidate.task_id)
        if task_document is None or task_document["target_id"] != candidate.target_id:
            raise CampaignInvariantError("candidate does not match a planned campaign task")
        observation = self._observations_by_id.get(candidate.observation_id)
        if observation is None:
            raise CampaignInvariantError("candidate refers to an unknown observation")
        if observation.task_id != candidate.task_id:
            raise CampaignInvariantError("candidate observation belongs to another task")
        if candidate.artifact_ref != observation.result_ref:
            raise CampaignInvariantError(
                "candidate artifact does not match its observed fleet result"
            )
        if candidate.source_refs != observation.source_refs:
            raise CampaignInvariantError(
                "candidate source_refs do not match observation provenance"
            )
        if candidate.evidence.value == "VERIFIED":
            if (
                not observation.verify(self._verifier_registry)
                or observation.certificate_ref is None
            ):
                raise CampaignInvariantError(
                    "VERIFIED candidate requires its observation's verified certificate"
                )
            if candidate.certificate_ref != observation.certificate_ref.certificate_id:
                raise CampaignInvariantError(
                    "candidate certificate does not match its verified observation"
                )
        if candidate.record_id in self._candidate_records:
            return None
        return self._append(
            EventKind.CANDIDATE_RECORDED,
            {"candidate": candidate.to_dict()},
        )

    def record_plan(self, plan: object) -> LedgerEvent | None:
        from .planner import CampaignPlan

        if not isinstance(plan, CampaignPlan):
            raise CampaignInvariantError("campaign ledger plans must be CampaignPlan values")
        if plan.plan_id in self._plans:
            return None
        for recommendation in (*plan.recommendations, *plan.advisories):
            document = self._tasks.get(recommendation.task.campaign_task_id)
            if document is None or document.to_dict() != recommendation.task.to_dict():
                raise CampaignInvariantError(
                    "campaign plan recommendation refers to an unplanned task"
                )
        return self._append(EventKind.PLAN_RECORDED, {"plan": plan.to_dict()})

    def bind_claim(
        self,
        *,
        claim_id: str,
        claim_digest: str,
        observation_id: str,
        target_id: str,
    ) -> LedgerEvent | None:
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise CampaignInvariantError("claim_id cannot be blank")
        if not isinstance(claim_digest, str) or not _CONTENT_REF_RE.fullmatch(claim_digest):
            raise CampaignInvariantError("claim_digest must be content-addressed")
        if not isinstance(observation_id, str) or not _CONTENT_REF_RE.fullmatch(observation_id):
            raise CampaignInvariantError("claim observation_id must be content-addressed")
        if not isinstance(target_id, str) or not _CONTENT_REF_RE.fullmatch(target_id):
            raise CampaignInvariantError("claim target_id must be content-addressed")
        observation = self._observations_by_id.get(observation_id)
        if observation is None or observation.target_id != target_id:
            raise CampaignInvariantError("claim binding refers to unknown campaign evidence")
        binding = FrozenMapping(
            {
                "claim_digest": claim_digest,
                "claim_id": claim_id,
                "observation_id": observation_id,
                "target_id": target_id,
            }
        )
        existing = self._claim_bindings.get(claim_id)
        if existing is not None:
            if existing != binding:
                raise CampaignInvariantError("claim ID is already bound to different evidence")
            return None
        return self._append(EventKind.CLAIM_BOUND, {"binding": binding})

    def record(self, observation: Observation) -> LedgerEvent | None:
        if observation.target_id not in self._targets:
            raise UnknownTargetError(observation.target_id)
        task_document = self._tasks.get(observation.task_id)
        if task_document is None:
            raise CampaignInvariantError(
                "an observation must refer to a task planned by this campaign"
            )
        if task_document["target_id"] != observation.target_id:
            raise CampaignInvariantError(
                "an observation target must match its planned campaign task"
            )
        existing = self._observations_by_id.get(observation.observation_id)
        if existing is not None:
            if existing != observation:
                raise CampaignInvariantError("observation ID collision")
            return None
        state = self.status(observation.target_id)
        if state.closed and observation.closes_target_with(self._verifier_registry):
            assert state.closing_observation is not None
            if state.closing_observation.outcome is not observation.outcome:
                raise CampaignInvariantError(
                    "a closed target cannot receive a contradictory mathematical closure"
                )
        return self._append(
            EventKind.OBSERVATION_RECORDED,
            {"observation": observation.to_dict()},
        )

    observe = record

    def observations_for(self, target: TargetSpec | str) -> tuple[Observation, ...]:
        target_id = self.get(target).target_id
        return tuple(self._observations.get(target_id, ()))

    def observations_for_task(self, task_id: str) -> tuple[Observation, ...]:
        return tuple(self._task_observations.get(task_id, ()))

    def candidates_for(self, target: TargetSpec | str) -> tuple[CandidateRecord, ...]:
        target_id = self.get(target).target_id
        grouped: dict[tuple[str, str], list[CandidateRecord]] = {}
        for candidate in self._candidate_records.values():
            if candidate.target_id == target_id:
                grouped.setdefault((candidate.candidate_id, candidate.quality_metric), []).append(
                    candidate
                )
        result: list[CandidateRecord] = []
        for key in sorted(grouped):
            best = grouped[key][0]
            for candidate in grouped[key][1:]:
                if candidate.better_than(best):
                    best = candidate
            result.append(best)
        return tuple(result)

    def best_known_by_metric(
        self,
        target: TargetSpec | str,
    ) -> tuple[tuple[str, CandidateRecord], ...]:
        """Return one deterministic best candidate for each explicit metric."""

        by_metric: dict[str, CandidateRecord] = {}
        for candidate in self.candidates_for(target):
            best = by_metric.get(candidate.quality_metric)
            if best is None or candidate.better_than(best):
                by_metric[candidate.quality_metric] = candidate
        return tuple(sorted(by_metric.items()))

    def best_known(
        self,
        target: TargetSpec | str,
        *,
        quality_metric: str | None = None,
    ) -> CandidateRecord | None:
        candidates = self.candidates_for(target)
        if quality_metric is not None:
            candidates = tuple(
                candidate for candidate in candidates if candidate.quality_metric == quality_metric
            )
        if not candidates:
            return None
        metrics = {candidate.quality_metric for candidate in candidates}
        if quality_metric is None and len(metrics) > 1:
            raise CampaignInvariantError(
                "best_known requires an explicit quality_metric when metrics differ"
            )
        best = candidates[0]
        for candidate in candidates[1:]:
            if candidate.better_than(best):
                best = candidate
        return best

    def attempts_for_task(self, task_id: str) -> tuple[AttemptRecord, ...]:
        histories = tuple(
            history for history in self._attempts.values() if history[0].task_id == task_id
        )
        ordered = sorted(histories, key=lambda history: history[0].attempt)
        return tuple(record for history in ordered for record in history)

    def task_document(self, task_id: str) -> dict[str, JSONValue]:
        try:
            return self._tasks[task_id].to_dict()
        except KeyError as error:
            raise CampaignInvariantError(f"unknown campaign task {task_id!r}") from error

    def task_documents(self) -> tuple[dict[str, JSONValue], ...]:
        return tuple(self._tasks[key].to_dict() for key in sorted(self._tasks))

    def latest_checkpoint(self, target: TargetSpec | str) -> str | None:
        for observation in reversed(self.observations_for(target)):
            if observation.checkpoint_ref is not None:
                return observation.checkpoint_ref
        return None

    def status(self, target: TargetSpec | str) -> TargetState:
        spec = self.get(target)
        observations = self._observations.get(spec.target_id, ())
        closing = next(
            (item for item in observations if item.closes_target_with(self._verifier_registry)),
            None,
        )
        if closing is None:
            status = TargetStatus.OPEN
            outcome = MathematicalOutcome.UNKNOWN
        else:
            status = TargetStatus.CLOSED
            outcome = MathematicalOutcome(closing.outcome.value)
        checkpoint = next(
            (
                item.checkpoint_ref
                for item in reversed(observations)
                if item.checkpoint_ref is not None
            ),
            None,
        )
        return TargetState(
            target=spec,
            status=status,
            mathematical_outcome=outcome,
            closing_observation=closing,
            observation_count=len(observations),
            checkpoint_ref=checkpoint,
        )

    def unresolved(self) -> tuple[TargetSpec, ...]:
        return tuple(target for target in self.targets if self.status(target).open)

    def _apply(self, event: LedgerEvent) -> None:
        if event.kind is EventKind.TARGET_ADDED:
            if set(event.payload) != {"target"}:
                raise CampaignSerializationError(
                    "target-added event has missing or unknown payload fields"
                )
            target_value = thaw_json(event.payload["target"])
            if not isinstance(target_value, dict):
                raise CampaignSerializationError("target event payload must be an object")
            target = TargetSpec.from_dict(target_value)
            existing = self._targets.get(target.target_id)
            if existing is not None:
                raise CampaignSerializationError("duplicate target-added event in ledger")
            self._targets[target.target_id] = target
            self._observations.setdefault(target.target_id, [])
            return
        if event.kind is EventKind.TASK_PLANNED:
            if set(event.payload) != {"task"}:
                raise CampaignSerializationError(
                    "task-planned event has missing or unknown payload fields"
                )
            task_value = thaw_json(event.payload["task"])
            if not isinstance(task_value, dict):
                raise CampaignSerializationError("task event payload must be an object")
            # Import lazily to keep the ledger/model dependency acyclic while
            # still making standalone ledger replay a strict trust boundary.
            from .planner import CampaignTask

            task = CampaignTask.from_dict(task_value)
            task_id = task.campaign_task_id
            target_id = task.target_id
            if target_id not in self._targets:
                raise CampaignSerializationError("planned task refers to an unknown target")
            if task.target != self._targets[target_id]:
                raise CampaignSerializationError(
                    "planned task target differs from the authoritative ledger target"
                )
            if task_id in self._tasks:
                raise CampaignSerializationError("duplicate task-planned event in ledger")
            frozen = FrozenMapping(task.to_dict())
            self._tasks[task_id] = frozen
            self._task_observations.setdefault(task_id, [])
            return
        if event.kind is EventKind.TASK_STARTED:
            if set(event.payload) != {"task_id"}:
                raise CampaignSerializationError(
                    "task-started event has missing or unknown payload fields"
                )
            started_task_id = event.payload["task_id"]
            if not isinstance(started_task_id, str) or started_task_id not in self._tasks:
                raise CampaignSerializationError("task-start event refers to an unknown task")
            return
        if event.kind is EventKind.OBSERVATION_RECORDED:
            if set(event.payload) != {"observation"}:
                raise CampaignSerializationError(
                    "observation event has missing or unknown payload fields"
                )
            observation_value = thaw_json(event.payload["observation"])
            if not isinstance(observation_value, dict):
                raise CampaignSerializationError("observation payload must be an object")
            observation = Observation.from_dict(
                observation_value,
                verifier_registry=self._verifier_registry,
            )
            if observation.target_id not in self._targets:
                raise CampaignSerializationError("observation refers to an unknown target")
            task_document = self._tasks.get(observation.task_id)
            if task_document is None:
                raise CampaignSerializationError("observation refers to an unknown campaign task")
            if task_document["target_id"] != observation.target_id:
                raise CampaignSerializationError(
                    "observation target does not match its planned campaign task"
                )
            if observation.observation_id in self._observations_by_id:
                raise CampaignSerializationError("duplicate observation event")
            self._observations.setdefault(observation.target_id, []).append(observation)
            self._task_observations.setdefault(observation.task_id, []).append(observation)
            self._observations_by_id[observation.observation_id] = observation
            return
        if event.kind is EventKind.ATTEMPT_RECORDED:
            if set(event.payload) != {"attempt"}:
                raise CampaignSerializationError(
                    "attempt event has missing or unknown payload fields"
                )
            attempt_value = thaw_json(event.payload["attempt"])
            if not isinstance(attempt_value, dict):
                raise CampaignSerializationError("attempt payload must be an object")
            attempt = AttemptRecord.from_dict(attempt_value)
            task_document = self._tasks.get(attempt.task_id)
            if task_document is None or task_document["target_id"] != attempt.target_id:
                raise CampaignSerializationError("attempt does not match a planned task")
            history = self._attempts.setdefault(attempt.attempt_id, [])
            if any(existing.record_id == attempt.record_id for existing in history):
                raise CampaignSerializationError("duplicate attempt state event")
            if history:
                previous = history[-1]
                if not previous.live or (
                    previous.worker_id is not None and previous.worker_id != attempt.worker_id
                ):
                    raise CampaignSerializationError("invalid attempt state transition")
            elif not attempt.live:
                raise CampaignSerializationError("first attempt state is not RUNNING")
            history.append(attempt)
            return
        if event.kind is EventKind.CANDIDATE_RECORDED:
            if set(event.payload) != {"candidate"}:
                raise CampaignSerializationError(
                    "candidate event has missing or unknown payload fields"
                )
            candidate_value = thaw_json(event.payload["candidate"])
            if not isinstance(candidate_value, dict):
                raise CampaignSerializationError("candidate payload must be an object")
            candidate = CandidateRecord.from_dict(candidate_value)
            if candidate.record_id in self._candidate_records:
                raise CampaignSerializationError("duplicate candidate record event")
            task_document = self._tasks.get(candidate.task_id)
            candidate_observation = self._observations_by_id.get(candidate.observation_id)
            if (
                task_document is None
                or task_document["target_id"] != candidate.target_id
                or candidate_observation is None
                or candidate_observation.task_id != candidate.task_id
            ):
                raise CampaignSerializationError(
                    "candidate provenance does not match campaign history"
                )
            if candidate.evidence.value == "VERIFIED" and (
                not candidate_observation.verify(self._verifier_registry)
                or candidate_observation.certificate_ref is None
                or candidate.certificate_ref != candidate_observation.certificate_ref.certificate_id
            ):
                raise CampaignSerializationError(
                    "verified candidate is not bound to verified observation evidence"
                )
            if candidate.artifact_ref != candidate_observation.result_ref:
                raise CampaignSerializationError(
                    "candidate artifact does not match its observed fleet result"
                )
            if candidate.source_refs != candidate_observation.source_refs:
                raise CampaignSerializationError(
                    "candidate source_refs do not match observation provenance"
                )
            self._candidate_records[candidate.record_id] = candidate
            self._candidate_history.setdefault(candidate.candidate_id, []).append(candidate)
            return
        if event.kind is EventKind.PLAN_RECORDED:
            if set(event.payload) != {"plan"}:
                raise CampaignSerializationError("plan event has missing or unknown payload fields")
            plan_value = thaw_json(event.payload["plan"])
            if not isinstance(plan_value, dict):
                raise CampaignSerializationError("plan payload must be an object")
            from .planner import CampaignPlan

            plan = CampaignPlan.from_dict(plan_value)
            if plan.plan_id in self._plans:
                raise CampaignSerializationError("duplicate campaign plan event")
            for recommendation in (*plan.recommendations, *plan.advisories):
                document = self._tasks.get(recommendation.task.campaign_task_id)
                if document is None or document.to_dict() != recommendation.task.to_dict():
                    raise CampaignSerializationError("campaign plan refers to an unplanned task")
            self._plans[plan.plan_id] = FrozenMapping(plan.to_dict())
            return
        if event.kind is EventKind.CLAIM_BOUND:
            if set(event.payload) != {"binding"}:
                raise CampaignSerializationError(
                    "claim-binding event has missing or unknown payload fields"
                )
            binding_value = thaw_json(event.payload["binding"])
            if not isinstance(binding_value, dict) or set(binding_value) != {
                "claim_digest",
                "claim_id",
                "observation_id",
                "target_id",
            }:
                raise CampaignSerializationError("claim binding is invalid")
            if any(not isinstance(item, str) for item in binding_value.values()):
                raise CampaignSerializationError("claim binding fields must be strings")
            observation_id_value = binding_value["observation_id"]
            target_id_value = binding_value["target_id"]
            claim_id_value = binding_value["claim_id"]
            claim_digest_value = binding_value["claim_digest"]
            assert isinstance(observation_id_value, str)
            assert isinstance(target_id_value, str)
            assert isinstance(claim_id_value, str)
            assert isinstance(claim_digest_value, str)
            observation_id = observation_id_value
            target_id = target_id_value
            claim_id = claim_id_value
            claim_digest = claim_digest_value
            bound_observation = self._observations_by_id.get(observation_id)
            if bound_observation is None or bound_observation.target_id != target_id:
                raise CampaignSerializationError(
                    "claim binding refers to unknown campaign evidence"
                )
            if not _CONTENT_REF_RE.fullmatch(claim_digest):
                raise CampaignSerializationError("claim digest is not content-addressed")
            if not _CONTENT_REF_RE.fullmatch(observation_id) or not _CONTENT_REF_RE.fullmatch(
                target_id
            ):
                raise CampaignSerializationError("claim binding IDs are not content-addressed")
            if claim_id in self._claim_bindings:
                raise CampaignSerializationError("duplicate claim-binding event")
            self._claim_bindings[claim_id] = FrozenMapping(binding_value)
            return
        raise CampaignSerializationError(f"unsupported event kind {event.kind!r}")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "events": [event.to_dict() for event in self._events],
            "schema": self.schema,
        }

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    @classmethod
    def replay(
        cls,
        events: Iterable[LedgerEvent | Mapping[str, Any]],
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> TargetLedger:
        ledger = cls(verifier_registry=verifier_registry)
        for expected_sequence, raw_event in enumerate(events):
            event = (
                raw_event
                if isinstance(raw_event, LedgerEvent)
                else LedgerEvent.from_dict(raw_event)
            )
            if event.sequence != expected_sequence:
                raise CampaignSerializationError("campaign event sequence is not contiguous")
            expected_previous = None if not ledger._events else ledger._events[-1].event_id
            if event.previous_event_id != expected_previous:
                raise CampaignSerializationError("campaign event hash chain is broken")
            ledger._apply(event)
            ledger._events.append(event)
        return ledger

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> TargetLedger:
        if set(value) != {"events", "schema"}:
            raise CampaignSerializationError("ledger has missing or unknown fields")
        if value.get("schema") != cls.schema:
            raise CampaignSerializationError("unsupported target ledger schema")
        raw_events = value.get("events")
        if not isinstance(raw_events, list):
            raise CampaignSerializationError("ledger events must be a JSON array")
        if any(not isinstance(event, Mapping) for event in raw_events):
            raise CampaignSerializationError("ledger event must be a JSON object")
        return cls.replay(raw_events, verifier_registry=verifier_registry)

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> TargetLedger:
        parsed = loads(value)
        if not isinstance(parsed, dict):
            raise CampaignSerializationError("campaign ledger JSON must be an object")
        return cls.from_dict(parsed, verifier_registry=verifier_registry)


__all__ = ["TargetLedger"]
