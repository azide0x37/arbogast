"""Machine-readable mathematical and implementation hazards."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbogast.formats import HAZARD_SCHEMA, JSONValue


class HazardSeverity(StrEnum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Hazard:
    """A regression lesson attached to relevant operations or types."""

    id: str
    message: str
    triggered_by: tuple[str, ...]
    severity: HazardSeverity = HazardSeverity.WARNING
    remediation: str | None = None
    schema: str = HAZARD_SCHEMA

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or not isinstance(self.message, str)
            or not self.message.strip()
        ):
            raise ValueError("hazard id and message must not be empty")
        triggers = tuple(self.triggered_by)
        if not triggers or any(
            not isinstance(trigger, str) or not trigger.strip() for trigger in triggers
        ):
            raise ValueError("hazards require at least one non-empty trigger")
        if not isinstance(self.severity, HazardSeverity):
            raise ValueError("hazard severity is invalid")
        if self.remediation is not None and not isinstance(self.remediation, str):
            raise ValueError("hazard remediation must be a string or null")
        if self.schema != HAZARD_SCHEMA:
            raise ValueError("unsupported hazard schema")
        object.__setattr__(self, "triggered_by", tuple(sorted(set(triggers))))

    def relevant_to(self, values: Iterable[str]) -> bool:
        candidates = set(values)
        return bool(candidates.intersection(self.triggered_by))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "message": self.message,
            "remediation": self.remediation,
            "schema": self.schema,
            "severity": self.severity.value,
            "triggered_by": list(self.triggered_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Hazard:
        expected = {"id", "message", "remediation", "schema", "severity", "triggered_by"}
        if set(value) != expected:
            raise ValueError("hazard has missing or unknown fields")
        if value["schema"] != HAZARD_SCHEMA:
            raise ValueError("unsupported hazard schema")
        hazard_id = value["id"]
        message = value["message"]
        remediation = value["remediation"]
        triggers = value["triggered_by"]
        if not isinstance(hazard_id, str) or not isinstance(message, str):
            raise ValueError("hazard id and message must be strings")
        if remediation is not None and not isinstance(remediation, str):
            raise ValueError("hazard remediation must be a string or null")
        if not isinstance(triggers, list) or any(not isinstance(item, str) for item in triggers):
            raise ValueError("hazard triggered_by must be an array of strings")
        try:
            severity = HazardSeverity(value["severity"])
        except (TypeError, ValueError) as error:
            raise ValueError("hazard severity is invalid") from error
        return cls(hazard_id, message, tuple(triggers), severity, remediation)


class HazardRegistry:
    def __init__(self, hazards: Iterable[Hazard] = ()) -> None:
        self._hazards: dict[str, Hazard] = {}
        for hazard in hazards:
            self.register(hazard)

    def register(self, hazard: Hazard, *, replace: bool = False) -> None:
        if hazard.id in self._hazards and not replace:
            raise ValueError(f"hazard {hazard.id!r} is already registered")
        self._hazards[hazard.id] = hazard

    def all(self) -> tuple[Hazard, ...]:
        return tuple(self._hazards[key] for key in sorted(self._hazards))

    def get(self, hazard_id: str) -> Hazard:
        try:
            return self._hazards[hazard_id]
        except KeyError as error:
            raise LookupError(f"unknown hazard: {hazard_id}") from error

    def resolve(self, hazard_ids: Iterable[str]) -> tuple[Hazard, ...]:
        return tuple(self.get(hazard_id) for hazard_id in sorted(set(hazard_ids)))

    def relevant(
        self,
        values: Iterable[str],
        *,
        declared_ids: Iterable[str] = (),
    ) -> tuple[Hazard, ...]:
        materialized = tuple(values)
        selected = {hazard.id: hazard for hazard in self.all() if hazard.relevant_to(materialized)}
        for hazard in self.resolve(declared_ids):
            selected[hazard.id] = hazard
        return tuple(selected[key] for key in sorted(selected))


DEFAULT_HAZARDS = HazardRegistry(
    (
        Hazard(
            id="hurwitz.source-vs-parameter-genus",
            triggered_by=("hurwitz.source_genus", "hurwitz.hurwitz_genus"),
            message="Source genus and Hurwitz-parameter genus are different invariants.",
            remediation="Compute and name each genus separately.",
        ),
        Hazard(
            id="groups.concrete-vs-abstract-embedding",
            triggered_by=(
                "CanonicalGroupElement",
                "ConcreteGroupElement",
                "NielsenClass",
                "hurwitz.nielsen_class",
            ),
            message="Canonical ambient conjugates need not lie in a pinned concrete embedding.",
            remediation="Use an explicit transport map and preserve its provenance.",
        ),
        Hazard(
            id="arithmetic.moduli-vs-definition",
            triggered_by=("field_of_moduli", "field_of_definition"),
            message="A field of moduli is not automatically a field of definition.",
            remediation="Require and verify effective descent data.",
        ),
        Hazard(
            id="numeric.real-input-vs-real-model",
            triggered_by=("numeric.exactify", "hurwitz.real_points"),
            message="Real branch coordinates do not imply real normalized coefficients.",
            remediation="Verify the real structure on the exactified model.",
        ),
        Hazard(
            id="cohom.full-shift-quotient-descent",
            triggered_by=("QuotientModule", "cohom.h0", "cohom.h1", "cohom.h2"),
            message="A full-shift quotient need not descend through the intended action.",
            remediation="Verify the quotient action and descent maps explicitly.",
        ),
        Hazard(
            id="backends.gap-reserved-identifier",
            triggered_by=("GAP", "gap"),
            message="EI is a reserved identifier in GAP and cannot be used as a local name.",
            remediation="Generate backend-safe identifiers instead of forwarding Python names.",
        ),
        Hazard(
            id="arithmetic.class-rationality-vs-component-field",
            triggered_by=("ComponentField", "RationalityField", "hurwitz.components"),
            message="A class rationality field does not determine the component field.",
            remediation="Compute component descent and Galois action separately.",
        ),
        Hazard(
            id="hurwitz.orbit-length-vs-order",
            triggered_by=("BraidAction", "hurwitz.braid_action", "hurwitz.components"),
            message="An orbit length does not by itself determine an acting element's order.",
            remediation="Verify the permutation action and element order explicitly.",
        ),
    )
)
