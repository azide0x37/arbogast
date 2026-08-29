"""Typed loader for precomputed Nielsen representatives.

Loading and validating representatives is not a proof that the imported list is
complete.  The returned object makes that boundary explicit and never creates a
``NielsenEnumerationCertificate`` from a cardinality assertion in JSON.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from arbogast.formats import CanonicalJSONError, loads

from ._group import ConcreteGroupContext, Element
from .errors import CertificateVerificationError, ImportedBoundaryError
from .nielsen import (
    ImportedNielsenBoundary,
    NielsenClass,
    NielsenTuple,
    _explicit_classes,
)

PRECOMPUTED_NIELSEN_SCHEMA = "arbogast.hurwitz.precomputed-nielsen.v1"


@dataclass(frozen=True)
class ImportedNielsenDataset:
    """Validated imported representatives with an intentionally open completeness claim."""

    nielsen_class: NielsenClass
    boundary: ImportedNielsenBoundary
    metadata: Mapping[str, Any]

    @property
    def status(self) -> str:
        return "IMPORTED"

    @property
    def representatives_verified(self) -> bool:
        return True

    @property
    def completeness_certified(self) -> bool:
        return False

    def verify_representatives(self) -> bool:
        return self.nielsen_class.verify(require_complete=False)

    def verify_complete(self) -> bool:
        raise CertificateVerificationError(
            "an imported representative list is not a completeness certificate; "
            "run exact enumeration or attach a separately verifiable exhaustive receipt"
        )


def _decoder_for_group(
    group: object, decoder: Callable[[Any], Element] | None
) -> Callable[[Any], Element]:
    if decoder is not None:
        return decoder
    for name in ("element_from_json", "decode_element"):
        method = getattr(group, name, None)
        if callable(method):
            return cast(Callable[[Any], Element], method)
    raise ImportedBoundaryError(
        "loading a precomputed dataset requires decode_element=... or "
        "group.element_from_json(); no element transport is inferred"
    )


def load_precomputed_nielsen_class(
    path: str | Path,
    group: object,
    classes: Sequence[object],
    *,
    decode_element: Callable[[Any], Element] | None = None,
) -> ImportedNielsenDataset:
    """Load and exactly validate a typed imported Nielsen representative list."""

    source_path = Path(path).expanduser().resolve()
    payload_bytes = source_path.read_bytes()
    digest = hashlib.sha256(payload_bytes).hexdigest()
    try:
        payload = loads(payload_bytes)
    except CanonicalJSONError as exc:
        raise ImportedBoundaryError("precomputed Nielsen dataset is not strict exact JSON") from exc
    if not isinstance(payload, dict):
        raise ImportedBoundaryError("precomputed Nielsen dataset must be a JSON object")
    allowed = {
        "schema",
        "group_fingerprint",
        "class_fingerprints",
        "representatives",
        "declared_cardinality",
        "metadata",
    }
    required = {"schema", "group_fingerprint", "class_fingerprints", "representatives"}
    missing = sorted(required - payload.keys())
    unexpected = sorted(payload.keys() - allowed)
    if missing or unexpected:
        raise ImportedBoundaryError(
            f"precomputed Nielsen dataset fields mismatch; missing={missing}, "
            f"unexpected={unexpected}"
        )
    if payload.get("schema") != PRECOMPUTED_NIELSEN_SCHEMA:
        raise ImportedBoundaryError(
            f"unsupported dataset schema {payload.get('schema')!r}; "
            f"expected {PRECOMPUTED_NIELSEN_SCHEMA!r}"
        )
    context = ConcreteGroupContext.build(group)
    explicit = _explicit_classes(context, classes)
    if payload.get("group_fingerprint") != context.fingerprint:
        raise ImportedBoundaryError("dataset concrete-group fingerprint mismatch")
    class_fingerprints = tuple(conjugacy_class.fingerprint for conjugacy_class in explicit)
    raw_class_fingerprints = payload["class_fingerprints"]
    if not isinstance(raw_class_fingerprints, list) or any(
        not isinstance(item, str) for item in raw_class_fingerprints
    ):
        raise ImportedBoundaryError("dataset class_fingerprints must be an array of strings")
    if tuple(raw_class_fingerprints) != class_fingerprints:
        raise ImportedBoundaryError("dataset ordered class-vector fingerprint mismatch")
    raw_representatives = payload.get("representatives")
    if not isinstance(raw_representatives, list):
        raise ImportedBoundaryError("dataset representatives must be a JSON array")
    decoder = _decoder_for_group(group, decode_element)
    representatives: list[NielsenTuple] = []
    for position, encoded_entries in enumerate(raw_representatives):
        if not isinstance(encoded_entries, list):
            raise ImportedBoundaryError(f"representative {position} is not an array")
        try:
            entries = tuple(decoder(encoded) for encoded in encoded_entries)
        except Exception as exc:
            raise ImportedBoundaryError(
                f"failed to decode representative {position} in the pinned embedding"
            ) from exc
        value = NielsenTuple._from_context(context, entries, explicit, validate=True)
        canonical, _ = value.canonical_inner()
        if canonical.entries != value.entries:
            raise ImportedBoundaryError(
                f"representative {position} is not canonical under inner conjugacy"
            )
        representatives.append(value)
    declared = payload.get("declared_cardinality", len(representatives))
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        raise ImportedBoundaryError("declared_cardinality must be a nonnegative integer")
    if declared != len(representatives):
        raise ImportedBoundaryError(
            "declared_cardinality does not match the materialized representative list"
        )
    boundary = ImportedNielsenBoundary(
        str(source_path), digest, PRECOMPUTED_NIELSEN_SCHEMA, declared
    )
    nielsen = NielsenClass(
        context,
        explicit,
        representatives,
        certificate=None,
        imported_boundary=boundary,
    )
    nielsen.verify(require_complete=False)
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ImportedBoundaryError("dataset metadata must be a JSON object")
    return ImportedNielsenDataset(nielsen, boundary, metadata)
