"""Serializable campaign objectives and specifications."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256

from .derive import DerivationRule
from .errors import CampaignInvariantError, CampaignSerializationError
from .policy import PriorityPolicy
from .strategy import Strategy
from .targets import TargetSpec


@dataclass(frozen=True, slots=True, init=False)
class Objective:
    """A human-readable mathematical goal with explicit success criteria."""

    statement: str
    success_criteria: tuple[str, ...]
    metadata: FrozenMapping

    def __init__(
        self,
        statement: str,
        success_criteria: Iterable[str] = (),
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not statement.strip():
            raise CampaignInvariantError("campaign objective cannot be blank")
        criteria = tuple(success_criteria)
        if any(not item.strip() for item in criteria):
            raise CampaignInvariantError("objective success criteria cannot be blank")
        object.__setattr__(self, "statement", statement)
        object.__setattr__(self, "success_criteria", criteria)
        object.__setattr__(self, "metadata", FrozenMapping(metadata))

    @property
    def objective_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    @property
    def content_id(self) -> str:
        return self.objective_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "metadata": self.metadata.to_dict(),
            "schema": "arbogast.campaign.objective.v1",
            "statement": self.statement,
            "success_criteria": list(self.success_criteria),
        }
        if include_id:
            payload["objective_id"] = self.objective_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Objective:
        required = {"metadata", "objective_id", "schema", "statement", "success_criteria"}
        if set(value) != required:
            raise CampaignSerializationError("objective has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.objective.v1":
            raise CampaignSerializationError("unsupported objective schema")
        statement = value["statement"]
        criteria = value["success_criteria"]
        metadata = value["metadata"]
        if not isinstance(statement, str):
            raise CampaignSerializationError("objective statement must be a string")
        if not isinstance(criteria, list) or any(not isinstance(item, str) for item in criteria):
            raise CampaignSerializationError("success_criteria must be an array of strings")
        if not isinstance(metadata, Mapping):
            raise CampaignSerializationError("objective metadata must be an object")
        objective = cls(statement, criteria, metadata=metadata)
        if value["objective_id"] != objective.objective_id:
            raise CampaignSerializationError("objective_id does not match canonical contents")
        return objective


@dataclass(frozen=True, slots=True, init=False)
class CampaignSpec:
    """Portable mathematical campaign definition without executable callables."""

    name: str
    objective: Objective
    targets: tuple[TargetSpec, ...]
    strategies: tuple[Strategy, ...]
    derivations: tuple[DerivationRule, ...]
    policy: PriorityPolicy
    metadata: FrozenMapping

    def __init__(
        self,
        name: str,
        objective: Objective | str,
        targets: Iterable[TargetSpec] = (),
        strategies: Iterable[Strategy] = (),
        derivations: Iterable[DerivationRule] = (),
        policy: PriorityPolicy | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not name.strip():
            raise CampaignInvariantError("campaign name cannot be blank")
        resolved_objective = Objective(objective) if isinstance(objective, str) else objective
        target_map: dict[str, TargetSpec] = {}
        for target in targets:
            existing_target = target_map.get(target.target_id)
            if existing_target is not None and existing_target != target:
                raise CampaignInvariantError(
                    "campaign targets with the same mathematical identity "
                    "must have identical planning metadata"
                )
            target_map[target.target_id] = target
        strategy_tuple = tuple(strategies)
        strategy_names = tuple(strategy.name for strategy in strategy_tuple)
        if len(strategy_names) != len(set(strategy_names)):
            raise CampaignInvariantError("campaign strategy names must be unique")
        derivation_tuple = tuple(derivations)
        derivation_names = tuple(rule.name for rule in derivation_tuple)
        if len(derivation_names) != len(set(derivation_names)):
            raise CampaignInvariantError("campaign derivation names must be unique")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "objective", resolved_objective)
        object.__setattr__(
            self,
            "targets",
            tuple(target_map[key] for key in sorted(target_map)),
        )
        object.__setattr__(self, "strategies", strategy_tuple)
        object.__setattr__(self, "derivations", derivation_tuple)
        object.__setattr__(self, "policy", PriorityPolicy() if policy is None else policy)
        object.__setattr__(self, "metadata", FrozenMapping(metadata))

    @property
    def campaign_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    @property
    def content_id(self) -> str:
        return self.campaign_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "derivations": [rule.to_dict() for rule in self.derivations],
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "objective": self.objective.to_dict(),
            "policy": self.policy.to_dict(),
            "schema": "arbogast.campaign.spec.v1",
            "strategies": [strategy.to_dict() for strategy in self.strategies],
            "targets": [target.to_dict() for target in self.targets],
        }
        if include_id:
            payload["campaign_id"] = self.campaign_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CampaignSpec:
        required = {
            "campaign_id",
            "derivations",
            "metadata",
            "name",
            "objective",
            "policy",
            "schema",
            "strategies",
            "targets",
        }
        if set(value) != required:
            raise CampaignSerializationError("campaign spec has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.spec.v1":
            raise CampaignSerializationError("unsupported campaign-spec schema")
        name = value["name"]
        if not isinstance(name, str):
            raise CampaignSerializationError("campaign name must be a string")
        objective_value = value["objective"]
        policy_value = value["policy"]
        metadata = value["metadata"]
        if not isinstance(objective_value, Mapping) or not isinstance(policy_value, Mapping):
            raise CampaignSerializationError("objective and policy must be objects")
        if not isinstance(metadata, Mapping):
            raise CampaignSerializationError("campaign metadata must be an object")
        collections: dict[str, list[Mapping[str, Any]]] = {}
        for field_name in ("targets", "strategies", "derivations"):
            raw = value[field_name]
            if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
                raise CampaignSerializationError(
                    f"campaign {field_name} must be an array of objects"
                )
            collections[field_name] = raw
        spec = cls(
            name=name,
            objective=Objective.from_dict(objective_value),
            targets=(TargetSpec.from_dict(item) for item in collections["targets"]),
            strategies=(Strategy.from_dict(item) for item in collections["strategies"]),
            derivations=(DerivationRule.from_dict(item) for item in collections["derivations"]),
            policy=PriorityPolicy.from_dict(policy_value),
            metadata=metadata,
        )
        if value["campaign_id"] != spec.campaign_id:
            raise CampaignSerializationError("campaign_id does not match canonical contents")
        return spec


__all__ = ["CampaignSpec", "Objective"]
