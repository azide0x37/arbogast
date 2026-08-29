"""Verified-observation derivation rules and task provenance."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from arbogast.fleet import TaskSpec
from arbogast.formats import FrozenMapping, JSONValue

from .errors import CampaignInvariantError, CampaignSerializationError
from .events import Observation, Outcome

if TYPE_CHECKING:
    from .ledger import TargetLedger
    from .planner import CampaignTask


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(values))
    if any(not item.strip() for item in result):
        raise CampaignInvariantError("provenance references cannot be blank")
    return result


@dataclass(frozen=True, slots=True, init=False)
class TaskProvenance:
    """Lineage material deliberately usable by the next fleet task."""

    input_refs: tuple[str, ...]
    parameters: FrozenMapping
    parent_observation_ids: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __init__(
        self,
        input_refs: Iterable[str] = (),
        parameters: Mapping[str, Any] | None = None,
        parent_observation_ids: Iterable[str] = (),
        source_refs: Iterable[str] = (),
    ) -> None:
        object.__setattr__(self, "input_refs", _deduplicate(input_refs))
        object.__setattr__(self, "parameters", FrozenMapping(parameters))
        object.__setattr__(
            self,
            "parent_observation_ids",
            _deduplicate(parent_observation_ids),
        )
        object.__setattr__(self, "source_refs", _deduplicate(source_refs))

    @classmethod
    def from_observation(cls, observation: Observation) -> TaskProvenance:
        refs = list(observation.input_refs)
        if observation.result_ref is not None:
            refs.append(observation.result_ref)
        if observation.certificate_ref is not None:
            refs.append(observation.certificate_ref.certificate_id)
        return cls(
            input_refs=refs,
            parameters={
                **observation.parameters.to_dict(),
                "source_outcome": observation.outcome.value,
                "source_target_id": observation.target_id,
                "source_task_id": observation.task_id,
            },
            parent_observation_ids=(observation.observation_id,),
            source_refs=observation.source_refs,
        )

    def merge(self, other: TaskProvenance) -> TaskProvenance:
        parameters = self.parameters.to_dict()
        for key, value in other.parameters.to_dict().items():
            if key in parameters and parameters[key] != value:
                raise CampaignInvariantError(f"conflicting derived provenance parameter {key!r}")
            parameters[key] = value
        return TaskProvenance(
            input_refs=(*self.input_refs, *other.input_refs),
            parameters=parameters,
            parent_observation_ids=(
                *self.parent_observation_ids,
                *other.parent_observation_ids,
            ),
            source_refs=(*self.source_refs, *other.source_refs),
        )

    def apply(self, task: TaskSpec) -> TaskSpec:
        """Materialize lineage in fleet input references and parameters."""

        parameters = task.parameters.to_dict()
        existing = parameters.get("campaign_provenance")
        if existing is not None and existing != self.to_dict():
            raise CampaignInvariantError("fleet task contains conflicting campaign provenance")
        parameters["campaign_provenance"] = self.to_dict()
        return TaskSpec(
            operation=task.operation,
            input_refs=tuple(dict.fromkeys((*task.input_refs, *self.input_refs))),
            parameters=parameters,
            backend=task.backend,
            resources=task.resources,
            seed=task.seed,
            schema_version=task.schema_version,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "input_refs": list(self.input_refs),
            "parameters": self.parameters.to_dict(),
            "parent_observation_ids": list(self.parent_observation_ids),
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskProvenance:
        _require_keys(
            value,
            required={
                "input_refs",
                "parameters",
                "parent_observation_ids",
                "source_refs",
            },
            context="task provenance",
        )
        return cls(
            input_refs=_strict_strings(value.get("input_refs", []), "input_refs"),
            parameters=_strict_mapping(value.get("parameters", {}), "parameters"),
            parent_observation_ids=_strict_strings(
                value.get("parent_observation_ids", []),
                "parent_observation_ids",
            ),
            source_refs=_strict_strings(value.get("source_refs", []), "source_refs"),
        )


DeriveFunction = Callable[[Observation, "TargetLedger"], Iterable["CampaignTask"]]


@dataclass(frozen=True, slots=True)
class DerivationRule:
    """A named runtime rule that can consume only verified observations.

    The callable is deliberately excluded from serialization.  Replay restores
    the rule descriptor and requires an explicit trusted callable injection.
    """

    name: str
    derive: DeriveFunction | None = field(default=None, compare=False, repr=False)
    outcomes: tuple[Outcome, ...] = (Outcome.FOUND,)
    rationale: str = "verified result implies further mathematical work"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.rationale.strip():
            raise CampaignInvariantError("derivation name and rationale cannot be blank")
        outcomes = tuple(Outcome(item) for item in self.outcomes)
        if not outcomes:
            raise CampaignInvariantError("derivation rule requires at least one outcome")
        object.__setattr__(self, "outcomes", outcomes)

    @property
    def bound(self) -> bool:
        return self.derive is not None

    def apply(
        self,
        observation: Observation,
        ledger: TargetLedger,
    ) -> tuple[CampaignTask, ...]:
        if observation.outcome not in self.outcomes:
            return ()
        if not observation.verified:
            return ()
        if self.derive is None:
            raise CampaignInvariantError(
                f"derivation rule {self.name!r} has no injected implementation"
            )
        derived_provenance = TaskProvenance.from_observation(observation)
        tasks = tuple(self.derive(observation, ledger))
        return tuple(
            task.with_provenance(derived_provenance, derivation=self.name) for task in tasks
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "outcomes": [outcome.value for outcome in self.outcomes],
            "rationale": self.rationale,
            "schema": "arbogast.campaign.derivation-rule.v1",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DerivationRule:
        _require_keys(
            value,
            required={"name", "outcomes", "rationale", "schema"},
            context="derivation rule",
        )
        if value["schema"] != "arbogast.campaign.derivation-rule.v1":
            raise CampaignSerializationError("unsupported derivation-rule schema")
        name = value["name"]
        rationale = value["rationale"]
        if not isinstance(name, str) or not isinstance(rationale, str):
            raise CampaignSerializationError("derivation name and rationale must be strings")
        raw_outcomes = _strict_strings(value["outcomes"], "outcomes")
        return cls(
            name=name,
            outcomes=tuple(Outcome(item) for item in raw_outcomes),
            rationale=rationale,
        )


def _strict_strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CampaignSerializationError(f"{field_name} must be an array of strings")
    return tuple(value)


def _strict_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CampaignSerializationError(f"{field_name} must be a string-keyed object")
    return value


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    context: str,
) -> None:
    allowed = required | (optional or set())
    keys = set(value)
    if keys != required and not (required <= keys <= allowed):
        missing = sorted(required - keys)
        unknown = sorted(keys - allowed)
        raise CampaignSerializationError(
            f"invalid {context} keys; missing={missing}, unknown={unknown}"
        )


__all__ = ["DerivationRule", "TaskProvenance"]
