"""Canonical campaign targets and their derived state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256

from .errors import CampaignInvariantError, CampaignSerializationError
from .events import MathematicalOutcome, Observation


@dataclass(frozen=True, slots=True, init=False)
class TargetSpec:
    """A canonical mathematical case, independent of scheduling metadata."""

    key: str
    parameters: FrozenMapping
    importance: int
    label: str | None
    metadata: FrozenMapping

    def __init__(
        self,
        key: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        importance: int = 1,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not key.strip():
            raise CampaignInvariantError("target key cannot be blank")
        if isinstance(importance, bool) or not isinstance(importance, int) or importance < 0:
            raise CampaignInvariantError("target importance must be a non-negative integer")
        if label is not None and not label.strip():
            raise CampaignInvariantError("target label cannot be blank")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "parameters", FrozenMapping(parameters))
        object.__setattr__(self, "importance", importance)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "metadata", FrozenMapping(metadata))

    def identity_dict(self) -> dict[str, JSONValue]:
        return {
            "key": self.key,
            "parameters": self.parameters.to_dict(),
            "schema": "arbogast.campaign.target.v1",
        }

    @property
    def target_id(self) -> str:
        return f"sha256:{canonical_sha256(self.identity_dict())}"

    @property
    def content_id(self) -> str:
        return self.target_id

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self.identity_dict(),
            "importance": self.importance,
            "label": self.label,
            "metadata": self.metadata.to_dict(),
            "target_id": self.target_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TargetSpec:
        required = {
            "importance",
            "key",
            "label",
            "metadata",
            "parameters",
            "schema",
            "target_id",
        }
        if set(value) != required:
            raise CampaignSerializationError("target has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.target.v1":
            raise CampaignSerializationError("unsupported target schema")
        key = value["key"]
        importance = value["importance"]
        label = value["label"]
        parameters = value["parameters"]
        metadata = value["metadata"]
        if not isinstance(key, str):
            raise CampaignSerializationError("target key must be a string")
        if isinstance(importance, bool) or not isinstance(importance, int):
            raise CampaignSerializationError("target importance must be an integer")
        if label is not None and not isinstance(label, str):
            raise CampaignSerializationError("target label must be a string or null")
        if not isinstance(parameters, Mapping) or not isinstance(metadata, Mapping):
            raise CampaignSerializationError("target parameters and metadata must be objects")
        target = cls(
            key=key,
            parameters=parameters,
            importance=importance,
            label=label,
            metadata=metadata,
        )
        expected = value["target_id"]
        if not isinstance(expected, str):
            raise CampaignSerializationError("target_id must be a string")
        if expected != target.target_id:
            raise CampaignSerializationError("target_id does not match canonical contents")
        return target


class TargetStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class TargetState:
    """A projection of event history, never an independent source of truth."""

    target: TargetSpec
    status: TargetStatus
    mathematical_outcome: MathematicalOutcome = MathematicalOutcome.UNKNOWN
    closing_observation: Observation | None = None
    observation_count: int = 0
    checkpoint_ref: str | None = None

    @property
    def closed(self) -> bool:
        return self.status is TargetStatus.CLOSED

    @property
    def open(self) -> bool:
        return not self.closed

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "checkpoint_ref": self.checkpoint_ref,
            "closing_observation_id": (
                None
                if self.closing_observation is None
                else self.closing_observation.observation_id
            ),
            "mathematical_outcome": self.mathematical_outcome.value,
            "observation_count": self.observation_count,
            "status": self.status.value,
            "target": self.target.to_dict(),
        }


__all__ = ["TargetSpec", "TargetState", "TargetStatus"]
