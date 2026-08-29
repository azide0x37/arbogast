"""Immutable content-addressed JSON artifacts.

An :class:`Artifact` stores the exact canonical JSON text that is hashed.  Its
reference binds the artifact kind and schema version as well as the payload,
preventing the same bytes from being reinterpreted under another schema.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .canonical import CanonicalJSON, CanonicalObject, canonical_json, require_canonical_json
from .errors import ValidationError, VerificationError

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _validate_nonempty_label(value: str, field_name: str) -> None:
    if not value or value.strip() != value or any(ord(char) < 0x20 for char in value):
        raise ValidationError(f"{field_name} must be a nonempty, trimmed printable string")


@dataclass(frozen=True, slots=True)
class ArtifactRef(CanonicalObject):
    """A typed reference to immutable content."""

    kind: str
    schema_version: str
    digest: str

    def __post_init__(self) -> None:
        _validate_nonempty_label(self.kind, "kind")
        _validate_nonempty_label(self.schema_version, "schema_version")
        if _DIGEST_RE.fullmatch(self.digest) is None:
            raise ValidationError("digest must have form sha256:<64 lowercase hexadecimal digits>")

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the stable artifact-reference encoding."""

        return {
            "digest": self.digest,
            "kind": self.kind,
            "schema_version": self.schema_version,
            "type": "arbogast.artifact_ref",
        }


@dataclass(frozen=True, slots=True, init=False)
class Artifact(CanonicalObject):
    """A hashable canonical JSON artifact with a self-verifying reference."""

    kind: str
    schema_version: str
    payload_json: str
    ref: ArtifactRef

    def __init__(self, kind: str, schema_version: str, payload: object) -> None:
        _validate_nonempty_label(kind, "kind")
        _validate_nonempty_label(schema_version, "schema_version")
        encoded = canonical_json(payload)
        digest_input = canonical_json(
            {
                "kind": kind,
                "payload": require_canonical_json(encoded),
                "schema_version": schema_version,
                "type": "arbogast.artifact",
            }
        ).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(digest_input).hexdigest()}"
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "payload_json", encoded)
        object.__setattr__(self, "ref", ArtifactRef(kind, schema_version, digest))

    @classmethod
    def from_canonical_json(
        cls,
        kind: str,
        schema_version: str,
        payload_json: str,
        *,
        expected_ref: ArtifactRef | None = None,
    ) -> Artifact:
        """Load canonical payload text and optionally bind it to an expected ref."""

        payload = require_canonical_json(payload_json)
        artifact = cls(kind, schema_version, payload)
        if expected_ref is not None and artifact.ref != expected_ref:
            raise VerificationError("artifact content does not match the expected reference")
        return artifact

    @property
    def payload(self) -> CanonicalJSON:
        """Return a freshly parsed payload, never mutable internal state."""

        return require_canonical_json(self.payload_json)

    def verify(self, expected_ref: ArtifactRef | None = None) -> bool:
        """Recompute all bindings, raising on any mismatch."""

        rebuilt = Artifact(self.kind, self.schema_version, self.payload)
        if rebuilt.ref != self.ref:
            raise VerificationError("artifact reference does not match its canonical payload")
        if expected_ref is not None and self.ref != expected_ref:
            raise VerificationError("artifact reference does not match the expected reference")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the full self-contained artifact encoding."""

        return {
            "kind": self.kind,
            "payload": self.payload,
            "ref": self.ref.to_canonical_data(),
            "schema_version": self.schema_version,
            "type": "arbogast.artifact",
        }
