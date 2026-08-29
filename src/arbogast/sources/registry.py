"""Deterministic registry for source documents, propositions, and provenance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TypeVar, cast

from arbogast.cert.canonical import canonicalize, content_address

from .records import ProvenanceRecord, Reference, SourceDocument, SourceError

T = TypeVar("T")


class SourceRegistry:
    schema_version = "arbogast.sources/v1"

    def __init__(self) -> None:
        self._documents: dict[str, SourceDocument] = {}
        self._references: dict[str, Reference] = {}
        self._provenance: dict[str, ProvenanceRecord] = {}

    @property
    def digest(self) -> str:
        return content_address(self.to_canonical())

    def register_document(self, document: SourceDocument) -> SourceDocument:
        self._register(self._documents, document.key, document)
        return document

    def register_reference(self, reference: Reference) -> Reference:
        if reference.document_key not in self._documents:
            raise SourceError(
                f"reference {reference.key} names unknown document {reference.document_key}"
            )
        document = self._documents[reference.document_key]
        if (
            reference.source_hash is not None
            and document.source_hash is not None
            and reference.source_hash != document.source_hash
        ):
            raise SourceError("reference and document source hashes disagree")
        self._register(self._references, reference.key, reference)
        return reference

    def register_provenance(self, record: ProvenanceRecord) -> ProvenanceRecord:
        missing_sources = sorted(set(record.source_references) - self._references.keys())
        if missing_sources:
            raise SourceError(
                f"provenance {record.id} has unknown sources: {', '.join(missing_sources)}"
            )
        missing_parents = sorted(set(record.parent_records) - self._provenance.keys())
        if missing_parents:
            raise SourceError(
                f"provenance {record.id} has unknown parents: {', '.join(missing_parents)}"
            )
        self._register(self._provenance, record.id, record)
        return record

    @staticmethod
    def _register(store: dict[str, T], key: str, value: T) -> None:
        existing = store.get(key)
        if existing is not None and existing != value:
            raise SourceError(f"registry key already has different content: {key}")
        store[key] = value

    def document(self, key: str) -> SourceDocument:
        try:
            return self._documents[key]
        except KeyError as exc:
            raise SourceError(f"unknown source document: {key}") from exc

    def reference(self, key: str) -> Reference:
        try:
            return self._references[key]
        except KeyError as exc:
            raise SourceError(f"unknown theorem-level reference: {key}") from exc

    def provenance(self, key: str) -> ProvenanceRecord:
        try:
            return self._provenance[key]
        except KeyError as exc:
            raise SourceError(f"unknown provenance record: {key}") from exc

    def documents(self) -> tuple[SourceDocument, ...]:
        return tuple(self._documents[key] for key in sorted(self._documents))

    def references(self) -> tuple[Reference, ...]:
        return tuple(self._references[key] for key in sorted(self._references))

    def provenance_records(self) -> tuple[ProvenanceRecord, ...]:
        return tuple(self._provenance[key] for key in sorted(self._provenance))

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "documents": self.documents(),
            "references": self.references(),
            "provenance": self.provenance_records(),
        }

    def to_dict(self) -> dict[str, object]:
        plain = canonicalize(self.to_canonical())
        if not isinstance(plain, dict):
            raise SourceError("source registry canonical form must be an object")
        return cast(dict[str, object], plain)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SourceRegistry:
        allowed = {"schema_version", "documents", "references", "provenance"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise SourceError(f"unexpected source registry fields: {', '.join(unexpected)}")
        if value.get("schema_version") != cls.schema_version:
            raise SourceError(
                f"unsupported source registry schema: {value.get('schema_version')!r}"
            )
        registry = cls()
        documents = tuple(
            SourceDocument.from_dict(raw)
            for raw in _records(value.get("documents", ()), "documents")
        )
        references = tuple(
            Reference.from_dict(raw) for raw in _records(value.get("references", ()), "references")
        )
        pending = [
            ProvenanceRecord.from_dict(raw)
            for raw in _records(value.get("provenance", ()), "provenance")
        ]
        _require_unique_keys((item.key for item in documents), "source document")
        _require_unique_keys((item.key for item in references), "source reference")
        _require_unique_keys((item.id for item in pending), "provenance record")
        for document in documents:
            registry.register_document(document)
        for reference in references:
            registry.register_reference(reference)
        while pending:
            progress = False
            for record in tuple(pending):
                if set(record.parent_records).issubset(registry._provenance):
                    registry.register_provenance(record)
                    pending.remove(record)
                    progress = True
            if not progress:
                unresolved = ", ".join(sorted(record.id for record in pending))
                raise SourceError(f"cyclic or missing provenance parents: {unresolved}")
        return registry


def _records(value: object, field: str) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SourceError(f"{field} must be a sequence")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item):
            raise SourceError(f"{field} entries must be string-keyed objects")
        result.append(item)
    return tuple(result)


def _require_unique_keys(keys: Iterable[str], record: str) -> None:
    values = tuple(keys)
    if len(set(values)) != len(values):
        raise SourceError(f"duplicate {record} key in source registry transport")


default_sources = SourceRegistry()


__all__ = ["SourceRegistry", "default_sources"]
