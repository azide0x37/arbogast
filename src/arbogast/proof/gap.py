"""Proof-gap summaries and a transparent formalization-distance metric."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from os import PathLike
from typing import cast

from arbogast.cert.canonical import canonicalize, content_address

from .obligations import ObligationClass, ProofObligation, ProofObligationError


@dataclass(frozen=True)
class FormalizationDistance:
    """A decomposed metric; components remain more important than the scalar score."""

    decidable_steps: int = 0
    certificate_steps: int = 0
    existing_lemmas: int = 0
    missing_elementary_lemmas: int = 0
    external_theorems: int = 0
    open_obligations: int = 0
    analytic_dependencies: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.components.values()):
            raise ProofObligationError("formalization-distance counts cannot be negative")

    @property
    def components(self) -> dict[str, int]:
        return {
            "decidable_steps": self.decidable_steps,
            "certificate_steps": self.certificate_steps,
            "existing_lemmas": self.existing_lemmas,
            "missing_elementary_lemmas": self.missing_elementary_lemmas,
            "external_theorems": self.external_theorems,
            "open_obligations": self.open_obligations,
            "analytic_dependencies": self.analytic_dependencies,
        }

    @property
    def score(self) -> int:
        """Return a documented prioritization score, not a theorem-quality measure."""

        return (
            self.decidable_steps
            + 2 * self.certificate_steps
            + self.existing_lemmas
            + 5 * self.missing_elementary_lemmas
            + 8 * self.external_theorems
            + 13 * self.open_obligations
            + 13 * self.analytic_dependencies
        )

    @classmethod
    def from_obligations(
        cls,
        obligations: Iterable[ProofObligation],
        *,
        analytic_dependencies: int = 0,
    ) -> FormalizationDistance:
        counts = Counter(
            obligation.classification for obligation in obligations if not obligation.is_discharged
        )
        return cls(
            decidable_steps=counts[ObligationClass.DECIDABLE],
            certificate_steps=counts[ObligationClass.CERTIFICATE],
            existing_lemmas=counts[ObligationClass.LIBRARY_THEOREM],
            missing_elementary_lemmas=counts[ObligationClass.MISSING_LEMMA],
            external_theorems=counts[ObligationClass.EXTERNAL_THEOREM],
            open_obligations=counts[ObligationClass.OPEN],
            analytic_dependencies=analytic_dependencies,
        )

    def to_canonical(self) -> dict[str, object]:
        return {**self.components, "score": self.score}


class ProofGap:
    """A validated obligation DAG and its unresolved formalization frontier."""

    schema_version = "arbogast.proof-gap/v1"

    def __init__(
        self,
        claim_id: str,
        obligations: Iterable[ProofObligation],
        *,
        analytic_dependencies: int = 0,
    ) -> None:
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise ProofObligationError("proof gap claim_id must be a non-blank string")
        if (
            isinstance(analytic_dependencies, bool)
            or not isinstance(analytic_dependencies, int)
            or analytic_dependencies < 0
        ):
            raise ProofObligationError("analytic_dependencies must be a non-negative integer")
        self.claim_id = claim_id
        self.analytic_dependencies = analytic_dependencies
        self._obligations: dict[str, ProofObligation] = {}
        for obligation in obligations:
            existing = self._obligations.get(obligation.id)
            if existing is not None and existing != obligation:
                raise ProofObligationError(f"duplicate obligation id: {obligation.id}")
            self._obligations[obligation.id] = obligation
        self.validate()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProofGap):
            return NotImplemented
        return self.to_canonical() == other.to_canonical()

    def __hash__(self) -> int:
        return hash(self.digest)

    @property
    def digest(self) -> str:
        return content_address(self.to_canonical())

    @property
    def obligations(self) -> tuple[ProofObligation, ...]:
        return tuple(self._obligations[item] for item in self.topological_ids())

    @property
    def unresolved(self) -> tuple[ProofObligation, ...]:
        return tuple(item for item in self.obligations if not item.is_discharged)

    @property
    def blockers(self) -> tuple[ProofObligation, ...]:
        return tuple(item for item in self.unresolved if item.is_gap)

    @property
    def distance(self) -> FormalizationDistance:
        return FormalizationDistance.from_obligations(
            self.obligations,
            analytic_dependencies=self.analytic_dependencies,
        )

    @property
    def complete(self) -> bool:
        return not self.unresolved

    def counts(self) -> dict[str, int]:
        counts = Counter(item.classification.value for item in self.obligations)
        return {key: counts[key] for key in sorted(counts)}

    def validate(self) -> ProofGap:
        missing: dict[str, list[str]] = {}
        for item in self._obligations.values():
            absent = sorted(set(item.dependencies) - self._obligations.keys())
            if absent:
                missing[item.id] = absent
        if missing:
            details = "; ".join(
                f"{key}: {','.join(value)}" for key, value in sorted(missing.items())
            )
            raise ProofObligationError(f"missing proof obligation dependencies: {details}")
        self.topological_ids()
        return self

    def topological_ids(self) -> tuple[str, ...]:
        indegree = {item: 0 for item in self._obligations}
        dependents: dict[str, set[str]] = {item: set() for item in self._obligations}
        for obligation in self._obligations.values():
            for dependency in obligation.dependencies:
                indegree[obligation.id] += 1
                dependents[dependency].add(obligation.id)
        ready = deque(sorted(item for item, degree in indegree.items() if degree == 0))
        result: list[str] = []
        while ready:
            current = ready.popleft()
            result.append(current)
            for dependent in sorted(dependents[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            if len(ready) > 1:
                ready = deque(sorted(ready))
        if len(result) != len(self._obligations):
            cycle = sorted(item for item, degree in indegree.items() if degree)
            raise ProofObligationError(f"proof obligation cycle: {', '.join(cycle)}")
        return tuple(result)

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "obligations": self.obligations,
            "analytic_dependencies": self.analytic_dependencies,
            "distance": self.distance,
        }

    def to_dict(self) -> dict[str, object]:
        plain = canonicalize(self.to_canonical())
        if not isinstance(plain, dict):
            raise ProofObligationError("proof gap canonical form must be an object")
        return cast(dict[str, object], plain)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProofGap:
        allowed = {
            "schema_version",
            "claim_id",
            "obligations",
            "analytic_dependencies",
            "distance",
        }
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ProofObligationError(f"unexpected proof-gap fields: {', '.join(unexpected)}")
        if value.get("schema_version") != cls.schema_version:
            raise ProofObligationError("missing or unsupported proof-gap schema")
        raw = value.get("obligations")
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise ProofObligationError("proof gap obligations must be a sequence")
        obligations: list[ProofObligation] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise ProofObligationError("proof obligation must be an object")
            obligations.append(ProofObligation.from_dict(item))
        ids = tuple(item.id for item in obligations)
        if len(set(ids)) != len(ids):
            raise ProofObligationError("duplicate obligation id in proof-gap transport")
        analytic = value.get("analytic_dependencies", 0)
        if isinstance(analytic, bool) or not isinstance(analytic, int):
            raise ProofObligationError("analytic_dependencies must be an integer")
        claim_id = value.get("claim_id")
        if not isinstance(claim_id, str):
            raise ProofObligationError("proof gap claim_id must be a string")
        result = cls(claim_id, obligations, analytic_dependencies=analytic)
        distance = value.get("distance")
        if distance is not None:
            if not isinstance(distance, Mapping):
                raise ProofObligationError("proof-gap distance must be an object")
            if canonicalize(distance) != canonicalize(result.distance.to_canonical()):
                raise ProofObligationError("proof-gap distance does not match its obligations")
        return result

    def export(
        self,
        format: str,
        destination: str | PathLike[str] | None = None,
        **options: object,
    ) -> str:
        from arbogast.export import export

        return export(self, format, destination=destination, **options)


def proof_gap(
    claim_id: str,
    obligations: Iterable[ProofObligation],
    *,
    analytic_dependencies: int = 0,
) -> ProofGap:
    return ProofGap(
        claim_id,
        obligations,
        analytic_dependencies=analytic_dependencies,
    )


__all__ = ["FormalizationDistance", "ProofGap", "proof_gap"]
