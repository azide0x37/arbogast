"""Theorem-level source registry and mathematical provenance."""

from .records import (
    LiteratureClaim,
    ProvenanceRecord,
    Reference,
    ReferenceKind,
    SourceDocument,
    SourceError,
)
from .registry import SourceRegistry, default_sources

__all__ = [
    "LiteratureClaim",
    "ProvenanceRecord",
    "Reference",
    "ReferenceKind",
    "SourceDocument",
    "SourceError",
    "SourceRegistry",
    "default_sources",
]
