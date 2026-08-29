"""Discovery receipts: reproducibility data that is explicitly not a proof."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from .base import CertificateError, CertificateLayer, ContentAddressedCertificate
from .canonical import FrozenMap, freeze_mapping


@dataclass(frozen=True)
class DiscoveryReceipt(ContentAddressedCertificate):
    """Record what an expensive or heuristic discovery process did.

    Receipts may contain candidates and backend details, but theorem certificates are forbidden
    from treating them as verification evidence.
    """

    operation: str
    inputs: FrozenMap = field(default_factory=FrozenMap)
    parameters: FrozenMap = field(default_factory=FrozenMap)
    result: FrozenMap = field(default_factory=FrozenMap)
    artifacts: tuple[str, ...] = ()
    backend: str | None = None
    backend_version: str | None = None
    notes: tuple[str, ...] = ()

    layer: ClassVar[CertificateLayer] = CertificateLayer.DISCOVERY
    schema_version: ClassVar[str] = "arbogast.cert.discovery/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str):
            raise CertificateError("discovery operation must be a string")
        if not self.operation.strip():
            raise CertificateError("discovery operation cannot be blank")
        object.__setattr__(self, "inputs", freeze_mapping(self.inputs))
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        object.__setattr__(self, "result", freeze_mapping(self.result))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "notes", tuple(self.notes))
        if any(
            not isinstance(artifact, str) or not artifact.strip() for artifact in self.artifacts
        ):
            raise CertificateError("artifact references cannot be blank")
        if self.backend is not None and (
            not isinstance(self.backend, str) or not self.backend.strip()
        ):
            raise CertificateError("backend name must be a non-blank string")
        if self.backend is None and self.backend_version is not None:
            raise CertificateError("backend_version requires a backend name")
        if self.backend_version is not None and (
            not isinstance(self.backend_version, str) or not self.backend_version.strip()
        ):
            raise CertificateError("backend_version must be a non-blank string")
        if any(not isinstance(note, str) for note in self.notes):
            raise CertificateError("discovery notes must be strings")

    @classmethod
    def create(
        cls,
        operation: str,
        *,
        inputs: Mapping[str, object] | None = None,
        parameters: Mapping[str, object] | None = None,
        result: Mapping[str, object] | None = None,
        artifacts: Sequence[str] = (),
        backend: str | None = None,
        backend_version: str | None = None,
        notes: Sequence[str] = (),
    ) -> DiscoveryReceipt:
        return cls(
            operation=operation,
            inputs=freeze_mapping(inputs),
            parameters=freeze_mapping(parameters),
            result=freeze_mapping(result),
            artifacts=tuple(artifacts),
            backend=backend,
            backend_version=backend_version,
            notes=tuple(notes),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "operation": self.operation,
            "inputs": self.inputs,
            "parameters": self.parameters,
            "result": self.result,
            "artifacts": self.artifacts,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DiscoveryReceipt:
        _require_fields(
            value,
            required={"schema_version", "layer", "operation"},
            allowed={
                "schema_version",
                "layer",
                "operation",
                "inputs",
                "parameters",
                "result",
                "artifacts",
                "backend",
                "backend_version",
                "notes",
                "certificate_id",
            },
            record="discovery certificate",
        )
        if value.get("schema_version") != cls.schema_version:
            raise CertificateError("missing or unsupported discovery certificate schema")
        if value.get("layer") != cls.layer.value:
            raise CertificateError("discovery certificate has the wrong semantic layer")
        receipt = cls.create(
            _required_string(value, "operation"),
            inputs=_mapping(value.get("inputs")),
            parameters=_mapping(value.get("parameters")),
            result=_mapping(value.get("result")),
            artifacts=_strings(value.get("artifacts")),
            backend=_optional_string(value.get("backend")),
            backend_version=_optional_string(value.get("backend_version")),
            notes=_strings(value.get("notes")),
        )
        if "certificate_id" in value:
            expected = value["certificate_id"]
            if not isinstance(expected, str):
                raise CertificateError("certificate_id must be a string")
            receipt.verify_integrity(expected)
        return receipt


def _mapping(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CertificateError("expected a mapping")
    if any(not isinstance(key, str) for key in value):
        raise CertificateError("mapping keys must be strings")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise CertificateError("expected a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise CertificateError("expected a sequence of strings")
    return tuple(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CertificateError("expected a string or null")
    return value


def _required_string(value: Mapping[str, object], field: str) -> str:
    raw = value.get(field)
    if not isinstance(raw, str):
        raise CertificateError(f"{field} must be a string")
    return raw


def _require_fields(
    value: Mapping[str, object],
    *,
    required: set[str],
    allowed: set[str],
    record: str,
) -> None:
    if any(not isinstance(key, str) for key in value):
        raise CertificateError(f"{record} keys must be strings")
    missing = sorted(required - set(value))
    if missing:
        raise CertificateError(f"{record} is missing required fields: {', '.join(missing)}")
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise CertificateError(f"unexpected {record} fields: {', '.join(unexpected)}")


__all__ = ["DiscoveryReceipt"]
