"""Machine-readable novelty ledger with paper-writing guardrails."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class NoveltyError(ValueError):
    """Raised when a novelty claim exceeds its recorded literature audit."""


class NoveltyStatus(StrEnum):
    KNOWN = "known"
    REPRODUCED = "reproduced"
    STRENGTHENED = "strengthened"
    APPARENTLY_NEW = "apparently_new"
    NEW = "new"


@dataclass(frozen=True)
class LiteratureSearch:
    """One reproducible literature-search action."""

    query: str
    sources: tuple[str, ...]
    performed_on: str
    performed_by: str
    summary: str
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        required = {
            "query": self.query,
            "performed_on": self.performed_on,
            "performed_by": self.performed_by,
            "summary": self.summary,
        }
        if any(not isinstance(value, str) for value in required.values()):
            raise NoveltyError("literature search text fields must be strings")
        blank = [name for name, value in required.items() if not value.strip()]
        if blank:
            raise NoveltyError(f"literature search fields cannot be blank: {', '.join(blank)}")
        if not self.sources or any(
            not isinstance(source, str) or not source.strip() for source in self.sources
        ):
            raise NoveltyError("literature search requires named sources")
        if any(
            not isinstance(reference, str) or not reference.strip()
            for reference in self.artifact_refs
        ):
            raise NoveltyError("literature-search artifact references must be non-blank strings")

    def to_canonical(self) -> dict[str, object]:
        return {
            "query": self.query,
            "sources": self.sources,
            "performed_on": self.performed_on,
            "performed_by": self.performed_by,
            "summary": self.summary,
            "artifact_refs": self.artifact_refs,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> LiteratureSearch:
        allowed = {
            "query",
            "sources",
            "performed_on",
            "performed_by",
            "summary",
            "artifact_refs",
        }
        required = {"query", "sources", "performed_on", "performed_by", "summary"}
        _require_fields(value, required=required, allowed=allowed, record="literature search")
        return cls(
            query=_required_string(value, "query"),
            sources=_strings(value["sources"]),
            performed_on=_required_string(value, "performed_on"),
            performed_by=_required_string(value, "performed_by"),
            summary=_required_string(value, "summary"),
            artifact_refs=_strings(value.get("artifact_refs", ())),
        )


@dataclass(frozen=True)
class NoveltyRecord:
    """Novelty status tied to audit evidence rather than computational surprise."""

    claim_id: str
    status: NoveltyStatus
    literature_searches: tuple[LiteratureSearch, ...] = ()
    nearest_results: tuple[str, ...] = ()
    promotion_note: str | None = None
    confirmed_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise NoveltyError("claim_id must be a non-blank string")
        if isinstance(self.status, str):
            try:
                object.__setattr__(self, "status", NoveltyStatus(self.status))
            except ValueError as exc:
                raise NoveltyError(f"invalid novelty status: {self.status!r}") from exc
        elif not isinstance(self.status, NoveltyStatus):
            raise NoveltyError("novelty status must be a NoveltyStatus")
        object.__setattr__(self, "literature_searches", tuple(self.literature_searches))
        object.__setattr__(self, "nearest_results", tuple(self.nearest_results))
        object.__setattr__(self, "confirmed_by", tuple(self.confirmed_by))
        if any(not isinstance(item, LiteratureSearch) for item in self.literature_searches):
            raise NoveltyError("literature_searches must contain LiteratureSearch records")
        if any(not isinstance(item, str) or not item.strip() for item in self.nearest_results):
            raise NoveltyError("nearest_results must contain non-blank strings")
        if self.promotion_note is not None and (
            not isinstance(self.promotion_note, str) or not self.promotion_note.strip()
        ):
            raise NoveltyError("promotion_note must be a non-blank string or null")
        if any(
            not isinstance(reviewer, str) or not reviewer.strip() for reviewer in self.confirmed_by
        ):
            raise NoveltyError("confirmed_by must contain non-blank strings")
        if (
            self.status in {NoveltyStatus.APPARENTLY_NEW, NoveltyStatus.NEW}
            and not self.literature_searches
        ):
            raise NoveltyError(f"{self.status.value} requires a recorded literature search")
        if self.status is NoveltyStatus.STRENGTHENED and not self.nearest_results:
            raise NoveltyError("strengthened claims must identify the nearest prior result")
        if self.status is NoveltyStatus.NEW:
            if not self.promotion_note or not self.promotion_note.strip():
                raise NoveltyError("NEW status requires an explicit post-audit promotion note")
            if not self.confirmed_by or any(not reviewer.strip() for reviewer in self.confirmed_by):
                raise NoveltyError("NEW status requires named confirmation")

    @property
    def may_say_new(self) -> bool:
        """Only fully promoted ``NEW`` records authorize an unqualified novelty claim."""

        return self.status is NoveltyStatus.NEW

    @property
    def paper_wording(self) -> str:
        return {
            NoveltyStatus.KNOWN: "known",
            NoveltyStatus.REPRODUCED: "reproduced here",
            NoveltyStatus.STRENGTHENED: "strengthens a known result",
            NoveltyStatus.APPARENTLY_NEW: "apparently new",
            NoveltyStatus.NEW: "new",
        }[self.status]

    def to_canonical(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "literature_searches": self.literature_searches,
            "nearest_results": self.nearest_results,
            "promotion_note": self.promotion_note,
            "confirmed_by": self.confirmed_by,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> NoveltyRecord:
        allowed = {
            "claim_id",
            "status",
            "literature_searches",
            "nearest_results",
            "promotion_note",
            "confirmed_by",
        }
        _require_fields(
            value,
            required={"claim_id", "status"},
            allowed=allowed,
            record="novelty record",
        )
        searches_raw = value.get("literature_searches", ())
        if isinstance(searches_raw, str) or not isinstance(searches_raw, Sequence):
            raise NoveltyError("literature_searches must be a sequence")
        searches: list[LiteratureSearch] = []
        for item in searches_raw:
            if not isinstance(item, Mapping):
                raise NoveltyError("literature search must be an object")
            searches.append(LiteratureSearch.from_dict(item))
        raw_status = value.get("status")
        promotion_note = value.get("promotion_note")
        if not isinstance(raw_status, str):
            raise NoveltyError("novelty status must be a string")
        if promotion_note is not None and not isinstance(promotion_note, str):
            raise NoveltyError("promotion_note must be a string or null")
        return cls(
            claim_id=_required_string(value, "claim_id"),
            status=NoveltyStatus(raw_status),
            literature_searches=tuple(searches),
            nearest_results=_strings(value.get("nearest_results", ())),
            promotion_note=promotion_note,
            confirmed_by=_strings(value.get("confirmed_by", ())),
        )


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise NoveltyError("expected a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise NoveltyError("expected a sequence of strings")
    return tuple(value)


def _required_string(value: Mapping[str, object], field: str) -> str:
    raw = value.get(field)
    if not isinstance(raw, str):
        raise NoveltyError(f"{field} must be a string")
    return raw


def _require_fields(
    value: Mapping[str, object],
    *,
    required: set[str],
    allowed: set[str],
    record: str,
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise NoveltyError(f"unexpected {record} fields: {', '.join(unexpected)}")
    missing = sorted(required - set(value))
    if missing:
        raise NoveltyError(f"{record} is missing required fields: {', '.join(missing)}")


__all__ = [
    "LiteratureSearch",
    "NoveltyError",
    "NoveltyRecord",
    "NoveltyStatus",
]
