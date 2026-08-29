"""Campaign tasks and deterministic exact-priority plans."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from arbogast.fleet import TaskSpec
from arbogast.formats import JSONValue, canonical_sha256

from .derive import TaskProvenance
from .errors import CampaignInvariantError, CampaignSerializationError
from .policy import PriorityScore
from .targets import TargetSpec

_CONTENT_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _content_ref(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        result = value
    else:
        uri = getattr(value, "uri", None)
        content_id = getattr(value, "content_id", None)
        if isinstance(uri, str):
            result = uri
        elif isinstance(content_id, str):
            result = content_id
        else:
            raise CampaignInvariantError("checkpoint must be a stable content reference")
    if not result.strip():
        raise CampaignInvariantError("checkpoint reference cannot be blank")
    if not _CONTENT_REF_RE.fullmatch(result):
        raise CampaignInvariantError(
            "checkpoint reference must be a canonical sha256 content reference"
        )
    return result


@dataclass(frozen=True, slots=True, init=False)
class CampaignTask:
    """A fleet task plus the campaign-level reason it exists."""

    task: TaskSpec
    target: TargetSpec
    strategy: str
    rationale: str
    provenance: TaskProvenance
    derivation: str | None
    capability_requirements: tuple[str, ...]
    checkpoint_ref: str | None
    checkpoint_custody_id: str | None
    usefulness: int
    information_gain: int
    estimated_cost: int

    def __init__(
        self,
        task: TaskSpec | None = None,
        target: TargetSpec | None = None,
        strategy: str = "",
        rationale: str = "",
        *,
        task_spec: TaskSpec | None = None,
        provenance: TaskProvenance | None = None,
        derivation: str | None = None,
        capability_requirements: Iterable[str] = (),
        checkpoint_ref: object | None = None,
        checkpoint_custody_id: object | None = None,
        usefulness: int = 1,
        information_gain: int = 1,
        estimated_cost: int = 1,
        _task_is_materialized: bool = False,
    ) -> None:
        if task is not None and task_spec is not None:
            raise CampaignInvariantError("provide task or task_spec, not both")
        resolved_task = task if task is not None else task_spec
        if resolved_task is None or target is None:
            raise CampaignInvariantError("campaign task requires a fleet task and target")
        if not strategy.strip() or not rationale.strip():
            raise CampaignInvariantError("campaign task strategy and rationale cannot be blank")
        requirements = tuple(sorted(set(capability_requirements)))
        if any(not item.strip() for item in requirements):
            raise CampaignInvariantError("capability requirements cannot be blank")
        for name, value in {
            "usefulness": usefulness,
            "information_gain": information_gain,
            "estimated_cost": estimated_cost,
        }.items():
            minimum = 1 if name == "estimated_cost" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise CampaignInvariantError(f"{name} must be an integer >= {minimum}")
        resolved_checkpoint = _content_ref(checkpoint_ref)
        resolved_custody = _content_ref(checkpoint_custody_id)
        if resolved_checkpoint is None and resolved_custody is not None:
            raise CampaignInvariantError("checkpoint_custody_id requires a checkpoint_ref")
        resolved_provenance = TaskProvenance() if provenance is None else provenance
        materialized_task = (
            resolved_task if _task_is_materialized else resolved_provenance.apply(resolved_task)
        )
        object.__setattr__(self, "task", materialized_task)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "provenance", resolved_provenance)
        object.__setattr__(self, "derivation", derivation)
        object.__setattr__(self, "capability_requirements", requirements)
        object.__setattr__(self, "checkpoint_ref", resolved_checkpoint)
        object.__setattr__(self, "checkpoint_custody_id", resolved_custody)
        object.__setattr__(self, "usefulness", usefulness)
        object.__setattr__(self, "information_gain", information_gain)
        object.__setattr__(self, "estimated_cost", estimated_cost)

    @property
    def target_id(self) -> str:
        return self.target.target_id

    @property
    def task_spec(self) -> TaskSpec:
        return self.task

    @property
    def fleet_task(self) -> TaskSpec:
        return self.task

    @property
    def campaign_task_id(self) -> str:
        return f"sha256:{canonical_sha256(self.identity_dict())}"

    @property
    def task_id(self) -> str:
        return self.campaign_task_id

    @property
    def content_id(self) -> str:
        return self.campaign_task_id

    def identity_dict(self) -> dict[str, JSONValue]:
        return {
            "capability_requirements": list(self.capability_requirements),
            "checkpoint_ref": self.checkpoint_ref,
            "checkpoint_custody_id": self.checkpoint_custody_id,
            "derivation": self.derivation,
            "estimated_cost": self.estimated_cost,
            "information_gain": self.information_gain,
            "provenance": self.provenance.to_dict(),
            "rationale": self.rationale,
            "schema": "arbogast.campaign.task.v1",
            "strategy": self.strategy,
            "target_id": self.target_id,
            "task": self.task.to_dict(),
            "usefulness": self.usefulness,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self.identity_dict(),
            "campaign_task_id": self.campaign_task_id,
            "target": self.target.to_dict(),
        }

    def with_provenance(
        self,
        provenance: TaskProvenance,
        *,
        derivation: str | None = None,
    ) -> CampaignTask:
        base_task = TaskSpec(
            operation=self.task.operation,
            input_refs=tuple(
                ref for ref in self.task.input_refs if ref not in self.provenance.input_refs
            ),
            parameters={
                key: value
                for key, value in self.task.parameters.to_dict().items()
                if key != "campaign_provenance"
            },
            backend=self.task.backend,
            resources=self.task.resources,
            seed=self.task.seed,
            schema_version=self.task.schema_version,
        )
        return CampaignTask(
            base_task,
            self.target,
            self.strategy,
            self.rationale,
            provenance=self.provenance.merge(provenance),
            derivation=derivation or self.derivation,
            capability_requirements=self.capability_requirements,
            checkpoint_ref=self.checkpoint_ref,
            checkpoint_custody_id=self.checkpoint_custody_id,
            usefulness=self.usefulness,
            information_gain=self.information_gain,
            estimated_cost=self.estimated_cost,
        )

    def resume(
        self,
        checkpoint_ref: object,
        *,
        checkpoint_custody_id: object | None = None,
        observation_id: str | None = None,
    ) -> CampaignTask:
        resolved_checkpoint = _content_ref(checkpoint_ref)
        assert resolved_checkpoint is not None
        resolved_custody = _content_ref(checkpoint_custody_id)
        if resolved_custody is None:
            raise CampaignInvariantError(
                "resume requires the content identity of typed checkpoint custody"
            )
        if (
            resolved_checkpoint == self.checkpoint_ref
            and resolved_custody == self.checkpoint_custody_id
        ):
            return self
        rationale = (
            self.rationale
            if self.rationale.startswith("resume from checkpoint: ")
            else f"resume from checkpoint: {self.rationale}"
        )
        provenance_parameters = self.provenance.parameters.to_dict()
        previous_checkpoint = self.checkpoint_ref
        prior_checkpoints = provenance_parameters.get("prior_checkpoint_refs", [])
        if not isinstance(prior_checkpoints, list):
            raise CampaignInvariantError("prior_checkpoint_refs provenance must be an array")
        if isinstance(previous_checkpoint, str) and previous_checkpoint not in prior_checkpoints:
            provenance_parameters["prior_checkpoint_refs"] = [
                *prior_checkpoints,
                previous_checkpoint,
            ]
        previous_custody = self.checkpoint_custody_id
        prior_custody = provenance_parameters.get("prior_checkpoint_custody_ids", [])
        if not isinstance(prior_custody, list):
            raise CampaignInvariantError("prior_checkpoint_custody_ids provenance must be an array")
        if isinstance(previous_custody, str) and previous_custody not in prior_custody:
            provenance_parameters["prior_checkpoint_custody_ids"] = [
                *prior_custody,
                previous_custody,
            ]
        resume_provenance = TaskProvenance(
            input_refs=self.provenance.input_refs,
            parameters=provenance_parameters,
            parent_observation_ids=(
                self.provenance.parent_observation_ids
                if observation_id is None
                else (*self.provenance.parent_observation_ids, observation_id)
            ),
            source_refs=self.provenance.source_refs,
        )
        return CampaignTask(
            self.task,
            self.target,
            self.strategy,
            rationale,
            provenance=resume_provenance,
            derivation=self.derivation,
            capability_requirements=self.capability_requirements,
            checkpoint_ref=resolved_checkpoint,
            checkpoint_custody_id=resolved_custody,
            usefulness=self.usefulness,
            information_gain=self.information_gain,
            estimated_cost=self.estimated_cost,
            _task_is_materialized=True,
        )

    def retry(self, observation_id: str, retry_index: int) -> CampaignTask:
        """Create one explicit no-checkpoint retry with auditable lineage."""

        if not _CONTENT_REF_RE.fullmatch(observation_id):
            raise CampaignInvariantError(
                "retry observation_id must be a canonical sha256 content reference"
            )
        if isinstance(retry_index, bool) or not isinstance(retry_index, int) or retry_index < 1:
            raise CampaignInvariantError("retry_index must be a positive integer")
        provenance_parameters = self.provenance.parameters.to_dict()
        previous_retry = provenance_parameters.pop("retry_index", None)
        prior_retries = provenance_parameters.get("prior_retry_indices", [])
        if not isinstance(prior_retries, list):
            raise CampaignInvariantError("prior_retry_indices provenance must be an array")
        if isinstance(previous_retry, int) and previous_retry not in prior_retries:
            provenance_parameters["prior_retry_indices"] = [
                *prior_retries,
                previous_retry,
            ]
        provenance_parameters["retry_index"] = retry_index
        retry_provenance = TaskProvenance(
            input_refs=self.provenance.input_refs,
            parameters=provenance_parameters,
            parent_observation_ids=(
                *self.provenance.parent_observation_ids,
                observation_id,
            ),
            source_refs=self.provenance.source_refs,
        )
        rationale = (
            self.rationale
            if self.rationale.startswith("retry after interruption: ")
            else f"retry after interruption: {self.rationale}"
        )
        return CampaignTask(
            self.task,
            self.target,
            self.strategy,
            rationale,
            provenance=retry_provenance,
            derivation=self.derivation,
            capability_requirements=self.capability_requirements,
            usefulness=self.usefulness,
            information_gain=self.information_gain,
            estimated_cost=self.estimated_cost,
            _task_is_materialized=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CampaignTask:
        required = {
            "campaign_task_id",
            "capability_requirements",
            "checkpoint_ref",
            "checkpoint_custody_id",
            "derivation",
            "estimated_cost",
            "information_gain",
            "provenance",
            "rationale",
            "schema",
            "strategy",
            "target",
            "target_id",
            "task",
            "usefulness",
        }
        if set(value) != required:
            raise CampaignSerializationError("campaign task has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.task.v1":
            raise CampaignSerializationError("unsupported campaign-task schema")
        task_value = value["task"]
        target_value = value["target"]
        provenance_value = value["provenance"]
        if not isinstance(task_value, Mapping):
            raise CampaignSerializationError("campaign task fleet task must be an object")
        _validate_fleet_task(task_value)
        if not isinstance(target_value, Mapping):
            raise CampaignSerializationError("campaign task target must be an object")
        if not isinstance(provenance_value, Mapping):
            raise CampaignSerializationError("campaign task provenance must be an object")
        strategy = value["strategy"]
        rationale = value["rationale"]
        derivation = value["derivation"]
        checkpoint = value["checkpoint_ref"]
        checkpoint_custody_id = value["checkpoint_custody_id"]
        if not isinstance(strategy, str) or not isinstance(rationale, str):
            raise CampaignSerializationError("task strategy and rationale must be strings")
        if derivation is not None and not isinstance(derivation, str):
            raise CampaignSerializationError("task derivation must be a string or null")
        if checkpoint is not None and not isinstance(checkpoint, str):
            raise CampaignSerializationError("checkpoint_ref must be a string or null")
        if checkpoint_custody_id is not None and not isinstance(checkpoint_custody_id, str):
            raise CampaignSerializationError("checkpoint_custody_id must be a string or null")
        requirements_value = value["capability_requirements"]
        if not isinstance(requirements_value, list) or any(
            not isinstance(item, str) for item in requirements_value
        ):
            raise CampaignSerializationError("capability requirements must be an array of strings")
        integer_values: dict[str, int] = {}
        for field_name in ("usefulness", "information_gain", "estimated_cost"):
            raw = value[field_name]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise CampaignSerializationError(f"{field_name} must be an integer")
            integer_values[field_name] = raw
        campaign_task = cls(
            task=TaskSpec.from_dict(task_value),
            target=TargetSpec.from_dict(target_value),
            strategy=strategy,
            rationale=rationale,
            provenance=TaskProvenance.from_dict(provenance_value),
            derivation=derivation,
            capability_requirements=tuple(requirements_value),
            checkpoint_ref=checkpoint,
            checkpoint_custody_id=checkpoint_custody_id,
            usefulness=integer_values["usefulness"],
            information_gain=integer_values["information_gain"],
            estimated_cost=integer_values["estimated_cost"],
            _task_is_materialized=True,
        )
        if value["target_id"] != campaign_task.target_id:
            raise CampaignSerializationError("campaign task target_id mismatch")
        if value["campaign_task_id"] != campaign_task.campaign_task_id:
            raise CampaignSerializationError("campaign_task_id mismatch")
        return campaign_task


def _validate_fleet_task(value: Mapping[str, Any]) -> None:
    required = {
        "backend",
        "input_refs",
        "operation",
        "parameters",
        "resources",
        "schema",
        "schema_version",
        "task_hash",
    }
    allowed = required | {"seed"}
    if not required <= set(value) <= allowed:
        raise CampaignSerializationError("fleet task has missing or unknown fields")
    for field_name in ("operation", "schema", "schema_version", "task_hash"):
        if not isinstance(value[field_name], str):
            raise CampaignSerializationError(f"fleet task {field_name} must be a string")
    refs = value["input_refs"]
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise CampaignSerializationError("fleet task input_refs must be an array of strings")
    if not isinstance(value["parameters"], Mapping):
        raise CampaignSerializationError("fleet task parameters must be an object")
    backend = value["backend"]
    resources = value["resources"]
    if not isinstance(backend, Mapping) or set(backend) != {
        "capabilities",
        "name",
        "version",
    }:
        raise CampaignSerializationError("fleet task backend is invalid")
    capabilities = backend["capabilities"]
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) for item in capabilities
    ):
        raise CampaignSerializationError("fleet backend capabilities must be strings")
    if not isinstance(backend["name"], str) or (
        backend["version"] is not None and not isinstance(backend["version"], str)
    ):
        raise CampaignSerializationError("fleet backend name/version is invalid")
    resource_keys = {
        "cpu_cores",
        "gpu_count",
        "memory_bytes",
        "scratch_bytes",
        "wall_time_seconds",
    }
    if not isinstance(resources, Mapping) or set(resources) != resource_keys:
        raise CampaignSerializationError("fleet task resources are invalid")
    for field_name in resource_keys:
        resource_value = resources[field_name]
        if resource_value is not None and (
            isinstance(resource_value, bool) or not isinstance(resource_value, int)
        ):
            raise CampaignSerializationError(
                f"fleet resource {field_name} must be an integer or null"
            )
    if "seed" in value and (isinstance(value["seed"], bool) or not isinstance(value["seed"], int)):
        raise CampaignSerializationError("fleet task seed must be an integer")


class RecommendationAction(StrEnum):
    DISPATCH = "DISPATCH"
    RESUME = "RESUME"
    SUSPEND = "SUSPEND"
    STOP = "STOP"
    EXPAND = "EXPAND"


@dataclass(frozen=True, slots=True)
class Recommendation:
    task: CampaignTask
    priority: PriorityScore
    action: RecommendationAction = RecommendationAction.DISPATCH
    reason: str = "highest exact value-over-cost score"

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise CampaignInvariantError("recommendation reason cannot be blank")
        if isinstance(self.action, str):
            object.__setattr__(self, "action", RecommendationAction(self.action))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action": self.action.value,
            "priority": self.priority.to_dict(),
            "reason": self.reason,
            "task": self.task.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Recommendation:
        if set(value) != {"action", "priority", "reason", "task"}:
            raise CampaignSerializationError("recommendation has missing or unknown fields")
        action = value["action"]
        reason = value["reason"]
        priority = value["priority"]
        task = value["task"]
        if not isinstance(action, str) or not isinstance(reason, str):
            raise CampaignSerializationError("recommendation action and reason must be strings")
        if not isinstance(priority, Mapping) or not isinstance(task, Mapping):
            raise CampaignSerializationError("recommendation priority and task must be objects")
        return cls(
            task=CampaignTask.from_dict(task),
            priority=PriorityScore.from_dict(priority),
            action=RecommendationAction(action),
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    recommendations: tuple[Recommendation, ...]
    advisories: tuple[Recommendation, ...]
    policy_name: str
    schema: str = field(default="arbogast.campaign.plan.v1", init=False, compare=False)

    def __init__(
        self,
        recommendations: Iterable[Recommendation],
        policy_name: str = "value-over-cost",
        *,
        advisories: Iterable[Recommendation] = (),
    ) -> None:
        if not isinstance(policy_name, str) or not policy_name.strip():
            raise CampaignInvariantError("campaign plan policy_name cannot be blank")
        ordered = tuple(
            sorted(
                recommendations,
                key=lambda item: (
                    -item.priority.value,
                    item.task.campaign_task_id,
                ),
            )
        )
        ordered_advisories = tuple(
            sorted(
                advisories,
                key=lambda item: (
                    item.action.value,
                    -item.priority.value,
                    item.task.campaign_task_id,
                ),
            )
        )
        if any(
            item.action in {RecommendationAction.DISPATCH, RecommendationAction.RESUME}
            for item in ordered_advisories
        ):
            raise CampaignInvariantError(
                "dispatch and resume actions belong in plan recommendations"
            )
        if any(
            item.action not in {RecommendationAction.DISPATCH, RecommendationAction.RESUME}
            for item in ordered
        ):
            raise CampaignInvariantError(
                "suspend, stop, and expand actions belong in plan advisories"
            )
        object.__setattr__(self, "recommendations", ordered)
        object.__setattr__(self, "advisories", ordered_advisories)
        object.__setattr__(self, "policy_name", policy_name)
        object.__setattr__(self, "schema", "arbogast.campaign.plan.v1")

    def __len__(self) -> int:
        return len(self.recommendations)

    def __iter__(self) -> Iterator[Recommendation]:
        return iter(self.recommendations)

    @property
    def tasks(self) -> tuple[CampaignTask, ...]:
        return tuple(item.task for item in self.recommendations)

    @property
    def plan_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    @property
    def content_id(self) -> str:
        return self.plan_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "advisories": [item.to_dict() for item in self.advisories],
            "policy_name": self.policy_name,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "schema": self.schema,
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CampaignPlan:
        if set(value) != {
            "advisories",
            "plan_id",
            "policy_name",
            "recommendations",
            "schema",
        }:
            raise CampaignSerializationError("campaign plan has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.plan.v1":
            raise CampaignSerializationError("unsupported campaign-plan schema")
        policy_name = value["policy_name"]
        if not isinstance(policy_name, str):
            raise CampaignSerializationError("campaign plan policy_name must be a string")
        parsed: dict[str, tuple[Recommendation, ...]] = {}
        for field_name in ("recommendations", "advisories"):
            raw = value[field_name]
            if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
                raise CampaignSerializationError(
                    f"campaign plan {field_name} must be an array of objects"
                )
            parsed[field_name] = tuple(Recommendation.from_dict(item) for item in raw)
        plan = cls(
            parsed["recommendations"],
            policy_name,
            advisories=parsed["advisories"],
        )
        if not isinstance(value["plan_id"], str) or value["plan_id"] != plan.plan_id:
            raise CampaignSerializationError("plan_id does not match canonical contents")
        return plan


__all__ = [
    "CampaignPlan",
    "CampaignTask",
    "Recommendation",
    "RecommendationAction",
]
