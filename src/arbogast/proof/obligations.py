"""Finite, typed proof obligations derived from claims and certificates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arbogast.cert.canonical import canonicalize
from arbogast.claims.statement import FormalStatement


class ProofObligationError(ValueError):
    """Raised for malformed or epistemically inconsistent obligations."""


class ObligationClass(StrEnum):
    DECIDABLE = "decidable"
    CERTIFICATE = "certificate"
    LIBRARY_THEOREM = "library_theorem"
    MISSING_LEMMA = "missing_lemma"
    EXTERNAL_THEOREM = "external_theorem"
    OPEN = "open"


@dataclass(frozen=True)
class ProofObligation:
    """One independently trackable step toward a formal theorem."""

    id: str
    statement: FormalStatement
    classification: ObligationClass
    context: tuple[FormalStatement, ...] = ()
    dependencies: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    discharged_by: tuple[str, ...] = ()
    notes: str | None = None

    schema_version = "arbogast.proof-obligation/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise ProofObligationError("proof obligation id must be a string")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", self.id):
            raise ProofObligationError(f"invalid proof obligation id: {self.id!r}")
        if isinstance(self.statement, str):
            object.__setattr__(self, "statement", FormalStatement(self.statement))
        elif not isinstance(self.statement, FormalStatement):
            raise ProofObligationError(
                "proof obligation statement must be a FormalStatement or string"
            )
        if isinstance(self.classification, str):
            try:
                object.__setattr__(self, "classification", ObligationClass(self.classification))
            except ValueError as exc:
                raise ProofObligationError(
                    f"invalid obligation classification: {self.classification!r}"
                ) from exc
        elif not isinstance(self.classification, ObligationClass):
            raise ProofObligationError("classification must be an ObligationClass")
        object.__setattr__(self, "context", tuple(self.context))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "discharged_by", tuple(self.discharged_by))
        if any(not isinstance(item, FormalStatement) for item in self.context):
            raise ProofObligationError("obligation context must contain FormalStatement values")
        for name in ("dependencies", "evidence", "discharged_by"):
            if any(not isinstance(item, str) or not item.strip() for item in getattr(self, name)):
                raise ProofObligationError(f"{name} must contain non-blank string references")
            if len(set(getattr(self, name))) != len(getattr(self, name)):
                raise ProofObligationError(f"{name} references must be unique")
        if self.notes is not None and (not isinstance(self.notes, str) or not self.notes.strip()):
            raise ProofObligationError("notes must be a non-blank string or null")
        if self.classification is ObligationClass.OPEN and self.discharged_by:
            raise ProofObligationError("an OPEN obligation cannot be marked discharged")
        if (
            self.classification is ObligationClass.CERTIFICATE
            and self.discharged_by
            and not self.evidence
        ):
            raise ProofObligationError(
                "a discharged certificate obligation must retain certificate evidence"
            )

    @classmethod
    def create(
        cls,
        id: str,
        statement: FormalStatement | str,
        classification: ObligationClass,
        *,
        context: Sequence[FormalStatement | str] = (),
        dependencies: Sequence[str] = (),
        evidence: Sequence[str] = (),
        discharged_by: Sequence[str] = (),
        notes: str | None = None,
    ) -> ProofObligation:
        return cls(
            id=id,
            statement=(
                statement if isinstance(statement, FormalStatement) else FormalStatement(statement)
            ),
            classification=classification,
            context=tuple(
                item if isinstance(item, FormalStatement) else FormalStatement(item)
                for item in context
            ),
            dependencies=tuple(dependencies),
            evidence=tuple(evidence),
            discharged_by=tuple(discharged_by),
            notes=notes,
        )

    @property
    def is_discharged(self) -> bool:
        return bool(self.discharged_by)

    @property
    def is_gap(self) -> bool:
        return not self.is_discharged and self.classification in {
            ObligationClass.MISSING_LEMMA,
            ObligationClass.EXTERNAL_THEOREM,
            ObligationClass.OPEN,
        }

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "statement": self.statement,
            "classification": self.classification.value,
            "context": self.context,
            "dependencies": self.dependencies,
            "evidence": self.evidence,
            "discharged_by": self.discharged_by,
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, object]:
        plain = canonicalize(self.to_canonical())
        if not isinstance(plain, dict):
            raise ProofObligationError("proof obligation canonical form must be an object")
        return cast(dict[str, object], plain)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProofObligation:
        allowed = {
            "schema_version",
            "id",
            "statement",
            "classification",
            "context",
            "dependencies",
            "evidence",
            "discharged_by",
            "notes",
        }
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ProofObligationError(
                f"unexpected proof obligation fields: {', '.join(unexpected)}"
            )
        if value.get("schema_version") != cls.schema_version:
            raise ProofObligationError("missing or unsupported proof obligation schema")
        statement_raw = value.get("statement")
        if isinstance(statement_raw, Mapping):
            statement = FormalStatement.from_dict(statement_raw)
        elif isinstance(statement_raw, str):
            statement = FormalStatement(statement_raw)
        else:
            raise ProofObligationError("obligation statement must be an object or string")
        context: list[FormalStatement] = []
        for item in _sequence(value.get("context", ()), "context"):
            if isinstance(item, Mapping):
                context.append(FormalStatement.from_dict(item))
            elif isinstance(item, str):
                context.append(FormalStatement(item))
            else:
                raise ProofObligationError("obligation context entries must be statements")
        raw_id = value.get("id")
        raw_classification = value.get("classification")
        notes = value.get("notes")
        if not isinstance(raw_id, str):
            raise ProofObligationError("obligation id must be a string")
        if not isinstance(raw_classification, str):
            raise ProofObligationError("obligation classification must be a string")
        if notes is not None and not isinstance(notes, str):
            raise ProofObligationError("obligation notes must be a string or null")
        return cls(
            id=raw_id,
            statement=statement,
            classification=ObligationClass(raw_classification),
            context=tuple(context),
            dependencies=_strings(value.get("dependencies", ())),
            evidence=_strings(value.get("evidence", ())),
            discharged_by=_strings(value.get("discharged_by", ())),
            notes=notes,
        )


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProofObligationError(f"{name} must be a sequence")
    return value


def _strings(value: object) -> tuple[str, ...]:
    sequence = _sequence(value, "string field")
    if any(not isinstance(item, str) for item in sequence):
        raise ProofObligationError("expected a sequence of strings")
    return tuple(sequence)  # type: ignore[arg-type]


__all__ = ["ObligationClass", "ProofObligation", "ProofObligationError"]
