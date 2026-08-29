"""Theorem-level source and mathematical provenance records."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from arbogast.cert.canonical import FrozenMap, freeze_mapping, validate_content_address
from arbogast.claims.statement import FormalStatement


class SourceError(ValueError):
    """Raised for incomplete source or provenance records."""


class ReferenceKind(StrEnum):
    THEOREM = "theorem"
    PROPOSITION = "proposition"
    LEMMA = "lemma"
    COROLLARY = "corollary"
    TABLE_ENTRY = "table_entry"
    DEFINITION = "definition"
    DATASET = "dataset"
    OTHER = "other"


@dataclass(frozen=True)
class SourceDocument:
    """A specific immutable edition or snapshot of a source document."""

    key: str
    citation: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    year: str | None = None
    url: str | None = None
    source_hash: str | None = None
    identifiers: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        _validate_key(self.key)
        if not isinstance(self.citation, str):
            raise SourceError("source citation must be a string")
        if not self.citation.strip():
            raise SourceError("source citation cannot be blank")
        object.__setattr__(self, "authors", tuple(self.authors))
        object.__setattr__(self, "identifiers", freeze_mapping(self.identifiers))
        if self.source_hash is not None:
            if not isinstance(self.source_hash, str):
                raise SourceError("source_hash must be a string or null")
            validate_content_address(self.source_hash)
        for name in ("title", "year", "url"):
            item = getattr(self, name)
            if item is not None and (not isinstance(item, str) or not item.strip()):
                raise SourceError(f"source {name} must be a non-blank string or null")
        if any(not isinstance(author, str) or not author.strip() for author in self.authors):
            raise SourceError("source authors must be non-blank strings")

    def to_canonical(self) -> dict[str, object]:
        return {
            "key": self.key,
            "citation": self.citation,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "url": self.url,
            "source_hash": self.source_hash,
            "identifiers": self.identifiers,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SourceDocument:
        _require_fields(
            value,
            required={"key", "citation"},
            allowed={
                "key",
                "citation",
                "title",
                "authors",
                "year",
                "url",
                "source_hash",
                "identifiers",
            },
            record="source document",
        )
        identifiers = value.get("identifiers")
        return cls(
            key=_required_string(value, "key"),
            citation=_required_string(value, "citation"),
            title=_optional_string(value.get("title"), "title"),
            authors=_strings(value.get("authors", ())),
            year=_optional_string(value.get("year"), "year"),
            url=_optional_string(value.get("url"), "url"),
            source_hash=_optional_string(value.get("source_hash"), "source_hash"),
            identifiers=freeze_mapping(_mapping(identifiers)),
        )


@dataclass(frozen=True)
class Reference:
    """An exact theorem/table/definition proposition consumed from a source."""

    key: str
    document_key: str
    statement: FormalStatement
    locator: str
    kind: ReferenceKind = ReferenceKind.THEOREM
    theorem_id: str | None = None
    page: str | None = None
    source_hash: str | None = None
    imported_as: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        _validate_key(self.key)
        _validate_key(self.document_key)
        if isinstance(self.statement, str):
            object.__setattr__(self, "statement", FormalStatement(self.statement))
        elif not isinstance(self.statement, FormalStatement):
            raise SourceError("reference statement must be a FormalStatement or string")
        if isinstance(self.kind, str):
            try:
                object.__setattr__(self, "kind", ReferenceKind(self.kind))
            except ValueError as exc:
                raise SourceError(f"invalid reference kind: {self.kind!r}") from exc
        elif not isinstance(self.kind, ReferenceKind):
            raise SourceError("reference kind must be a ReferenceKind")
        if not isinstance(self.locator, str):
            raise SourceError("reference locator must be a string")
        if not self.locator.strip():
            raise SourceError("reference locator cannot be blank")
        if self.source_hash is not None:
            if not isinstance(self.source_hash, str):
                raise SourceError("reference source_hash must be a string or null")
            validate_content_address(self.source_hash)
        object.__setattr__(self, "imported_as", tuple(self.imported_as))
        if any(not isinstance(item, str) or not item.strip() for item in self.imported_as):
            raise SourceError("imported claim IDs must be non-blank strings")
        for name in ("theorem_id", "page", "notes"):
            item = getattr(self, name)
            if item is not None and (not isinstance(item, str) or not item.strip()):
                raise SourceError(f"reference {name} must be a non-blank string or null")

    @classmethod
    def create(
        cls,
        key: str,
        document_key: str,
        statement: FormalStatement | str,
        *,
        locator: str | None = None,
        theorem_id: str | None = None,
        page: str | int | None = None,
        kind: ReferenceKind = ReferenceKind.THEOREM,
        source_hash: str | None = None,
        imported_as: Sequence[str] = (),
        notes: str | None = None,
    ) -> Reference:
        resolved_locator = locator or theorem_id or (f"page {page}" if page is not None else None)
        if resolved_locator is None:
            raise SourceError("theorem-level reference requires locator, theorem_id, or page")
        return cls(
            key=key,
            document_key=document_key,
            statement=(
                statement if isinstance(statement, FormalStatement) else FormalStatement(statement)
            ),
            locator=resolved_locator,
            kind=kind,
            theorem_id=theorem_id,
            page=str(page) if page is not None else None,
            source_hash=source_hash,
            imported_as=tuple(imported_as),
            notes=notes,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "key": self.key,
            "document_key": self.document_key,
            "statement": self.statement,
            "locator": self.locator,
            "kind": self.kind.value,
            "theorem_id": self.theorem_id,
            "page": self.page,
            "source_hash": self.source_hash,
            "imported_as": self.imported_as,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Reference:
        _require_fields(
            value,
            required={"key", "document_key", "statement", "locator"},
            allowed={
                "key",
                "document_key",
                "statement",
                "locator",
                "kind",
                "theorem_id",
                "page",
                "source_hash",
                "imported_as",
                "notes",
            },
            record="source reference",
        )
        statement_raw = value["statement"]
        if isinstance(statement_raw, Mapping):
            statement = FormalStatement.from_dict(statement_raw)
        elif isinstance(statement_raw, str):
            statement = FormalStatement(statement_raw)
        else:
            raise SourceError("reference statement must be a mapping or string")
        raw_kind = value.get("kind", ReferenceKind.THEOREM.value)
        if not isinstance(raw_kind, str):
            raise SourceError("reference kind must be a string")
        return cls(
            key=_required_string(value, "key"),
            document_key=_required_string(value, "document_key"),
            statement=statement,
            locator=_required_string(value, "locator"),
            kind=ReferenceKind(raw_kind),
            theorem_id=_optional_string(value.get("theorem_id"), "theorem_id"),
            page=_optional_string(value.get("page"), "page"),
            source_hash=_optional_string(value.get("source_hash"), "source_hash"),
            imported_as=_strings(value.get("imported_as", ())),
            notes=_optional_string(value.get("notes"), "notes"),
        )


LiteratureClaim = Reference


@dataclass(frozen=True)
class ProvenanceRecord:
    """A content-level lineage record from sources and inputs to outputs."""

    id: str
    operation: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    source_references: tuple[str, ...] = ()
    parent_records: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    parameters: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        _validate_key(self.id)
        if not isinstance(self.operation, str):
            raise SourceError("provenance operation must be a string")
        if not self.operation.strip():
            raise SourceError("provenance operation cannot be blank")
        for field_name in (
            "inputs",
            "outputs",
            "source_references",
            "parent_records",
            "artifacts",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise SourceError(
                    f"provenance {field_name} must contain non-blank string references"
                )
            object.__setattr__(self, field_name, values)
        if not self.outputs:
            raise SourceError("provenance record requires at least one output")
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))

    def to_canonical(self) -> dict[str, object]:
        return {
            "id": self.id,
            "operation": self.operation,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "source_references": self.source_references,
            "parent_records": self.parent_records,
            "artifacts": self.artifacts,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProvenanceRecord:
        _require_fields(
            value,
            required={"id", "operation", "outputs"},
            allowed={
                "id",
                "operation",
                "inputs",
                "outputs",
                "source_references",
                "parent_records",
                "artifacts",
                "parameters",
            },
            record="provenance record",
        )
        return cls(
            id=_required_string(value, "id"),
            operation=_required_string(value, "operation"),
            inputs=_strings(value.get("inputs", ())),
            outputs=_strings(value["outputs"]),
            source_references=_strings(value.get("source_references", ())),
            parent_records=_strings(value.get("parent_records", ())),
            artifacts=_strings(value.get("artifacts", ())),
            parameters=freeze_mapping(_mapping(value.get("parameters"))),
        )


_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")


def _validate_key(value: str) -> None:
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise SourceError(f"invalid source/provenance key: {value!r}")


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SourceError("expected a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise SourceError("expected a sequence of strings")
    return tuple(value)


def _mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise SourceError("expected a string-keyed mapping")
    return value


def _required_string(value: Mapping[str, object], field: str) -> str:
    raw = value.get(field)
    if not isinstance(raw, str):
        raise SourceError(f"{field} must be a string")
    return raw


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceError(f"{field} must be a string or null")
    return value


def _require_fields(
    value: Mapping[str, object],
    *,
    required: set[str],
    allowed: set[str],
    record: str,
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise SourceError(f"unexpected {record} fields: {', '.join(unexpected)}")
    missing = sorted(required - set(value))
    if missing:
        raise SourceError(f"{record} is missing required fields: {', '.join(missing)}")


__all__ = [
    "LiteratureClaim",
    "ProvenanceRecord",
    "Reference",
    "ReferenceKind",
    "SourceDocument",
    "SourceError",
]
