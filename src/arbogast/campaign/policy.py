"""Inspectable exact campaign priority policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from arbogast.formats import JSONValue

from .errors import CampaignInvariantError, CampaignSerializationError


def _factor(name: str, value: int, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CampaignInvariantError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class PriorityScore:
    """The recorded factors behind one exact rational priority."""

    importance: int
    usefulness: int
    information_gain: int
    estimated_cost: int

    def __post_init__(self) -> None:
        _factor("importance", self.importance)
        _factor("usefulness", self.usefulness)
        _factor("information_gain", self.information_gain)
        _factor("estimated_cost", self.estimated_cost, positive=True)

    @property
    def value(self) -> Fraction:
        return Fraction(
            self.importance * self.usefulness * self.information_gain,
            self.estimated_cost,
        )

    @property
    def numerator(self) -> int:
        return self.value.numerator

    @property
    def denominator(self) -> int:
        return self.value.denominator

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "estimated_cost": self.estimated_cost,
            "importance": self.importance,
            "information_gain": self.information_gain,
            "score": {
                "denominator": self.denominator,
                "numerator": self.numerator,
            },
            "usefulness": self.usefulness,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PriorityScore:
        required = {
            "estimated_cost",
            "importance",
            "information_gain",
            "score",
            "usefulness",
        }
        if set(value) != required:
            raise CampaignSerializationError("priority score has missing or unknown fields")
        factors: dict[str, int] = {}
        for field_name in (
            "estimated_cost",
            "importance",
            "information_gain",
            "usefulness",
        ):
            raw = value[field_name]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise CampaignSerializationError(f"priority score {field_name} must be an integer")
            factors[field_name] = raw
        score = value["score"]
        if not isinstance(score, Mapping) or set(score) != {"denominator", "numerator"}:
            raise CampaignSerializationError("priority score rational value is invalid")
        if any(
            isinstance(score[name], bool) or not isinstance(score[name], int)
            for name in ("denominator", "numerator")
        ):
            raise CampaignSerializationError("priority rational fields must be integers")
        result = cls(
            importance=factors["importance"],
            usefulness=factors["usefulness"],
            information_gain=factors["information_gain"],
            estimated_cost=factors["estimated_cost"],
        )
        if score["numerator"] != result.numerator or score["denominator"] != result.denominator:
            raise CampaignSerializationError("priority rational value does not match its factors")
        return result


@dataclass(frozen=True, slots=True)
class PriorityPolicy:
    """Exact ``importance * usefulness * information_gain / cost`` policy."""

    name: str = "value-over-cost"
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise CampaignInvariantError("priority policy name cannot be blank")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise CampaignInvariantError("max_retries must be a non-negative integer")

    def assess(
        self,
        *,
        importance: int,
        usefulness: int,
        information_gain: int,
        estimated_cost: int,
    ) -> PriorityScore:
        return PriorityScore(importance, usefulness, information_gain, estimated_cost)

    def score(
        self,
        *,
        importance: int,
        usefulness: int,
        information_gain: int,
        estimated_cost: int,
    ) -> Fraction:
        return self.assess(
            importance=importance,
            usefulness=usefulness,
            information_gain=information_gain,
            estimated_cost=estimated_cost,
        ).value

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "formula": "importance*usefulness*information_gain/estimated_cost",
            "max_retries": self.max_retries,
            "name": self.name,
            "schema": "arbogast.campaign.priority-policy.v1",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PriorityPolicy:
        expected = {"formula", "max_retries", "name", "schema"}
        if set(value) != expected:
            raise CampaignSerializationError("priority policy has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.priority-policy.v1":
            raise CampaignSerializationError("unsupported priority-policy schema")
        if value["formula"] != "importance*usefulness*information_gain/estimated_cost":
            raise CampaignSerializationError("unsupported priority formula")
        if not isinstance(value["name"], str):
            raise CampaignSerializationError("priority policy name must be a string")
        max_retries = value["max_retries"]
        if isinstance(max_retries, bool) or not isinstance(max_retries, int):
            raise CampaignSerializationError("max_retries must be an integer")
        return cls(name=value["name"], max_retries=max_retries)


__all__ = ["PriorityPolicy", "PriorityScore"]
