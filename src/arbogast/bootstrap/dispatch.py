"""Canonical operational provenance for a post-acquisition readiness refresh."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, cast

from arbogast.backends import BackendStatus
from arbogast.cert import canonicalize, content_address
from arbogast.fleet import (
    ArtifactRef,
    LeaseRecord,
    LeaseState,
    ResourceHint,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerState,
)
from arbogast.formats import (
    DISPATCH_READINESS_RECEIPT_SCHEMA,
    PLAN_SCHEMA,
    FrozenMapping,
    canonical_bytes,
    canonical_sha256,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DISPATCH_ID = re.compile(r"^dispatch:[0-9a-f]{64}$")
_RUNTIME_NONCE = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACT_PROBE_SCHEMA = "arbogast.bootstrap.dispatch-artifact-probe/v1"
_ARTIFACT_PROBE_RECEIPT_SCHEMA = "arbogast.bootstrap.dispatch-artifact-probe-receipt/v1"

DISPATCH_READINESS_CHECKS: tuple[str, ...] = (
    "active-readiness-certificate-replayed",
    "live-environment-profile-bound",
    "campaign-plan-task-bound",
    "operation-verifier-registries-bound",
    "executor-artifact-custody-bound",
    "fleet-plan-shard-bound",
    "worker-capabilities-bound",
    "active-lease-custody-bound",
    "lease-bound-artifact-roundtrip",
    "final-active-lease-revalidated",
)


class DispatchReadinessError(ValueError):
    """Raised when a dispatch-readiness receipt fails strict replay."""


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DispatchReadinessError(f"{label} must be a non-blank string")
    return value


def _content_id(value: object, label: str) -> str:
    result = _nonblank(value, label)
    if not result.startswith("sha256:") or not _SHA256.fullmatch(result[7:]):
        raise DispatchReadinessError(f"{label} must be a canonical content address")
    return result


def _digest(value: object, label: str) -> str:
    result = _nonblank(value, label)
    if not _SHA256.fullmatch(result):
        raise DispatchReadinessError(f"{label} must be a canonical SHA-256 digest")
    return result


def _timestamp(value: object, label: str) -> str:
    result = _nonblank(value, label)
    try:
        parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise DispatchReadinessError(f"{label} must be a canonical UTC timestamp") from error
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != result:
        raise DispatchReadinessError(f"{label} must be a canonical UTC timestamp")
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DispatchReadinessError(f"{label} must be a string-keyed object")
    return cast(Mapping[str, object], value)


def _worker_from_document(value: Mapping[str, object]) -> Worker:
    required = {"backends", "id", "labels", "resources", "state"}
    if set(value) != required:
        raise DispatchReadinessError("worker document has missing or unknown fields")
    raw_backends = value["backends"]
    if isinstance(raw_backends, str) or not isinstance(raw_backends, Sequence):
        raise DispatchReadinessError("worker backends must be an array")
    backends: list[BackendStatus] = []
    for raw in raw_backends:
        backend = _mapping(raw, "worker backend")
        expected = {
            "available",
            "capabilities",
            "executable",
            "name",
            "reason",
            "schema",
            "version",
        }
        if set(backend) != expected:
            raise DispatchReadinessError("worker backend has missing or unknown fields")
        available = backend["available"]
        capabilities = backend["capabilities"]
        if not isinstance(available, bool):
            raise DispatchReadinessError("worker backend availability must be boolean")
        if (
            isinstance(capabilities, str)
            or not isinstance(capabilities, Sequence)
            or any(not isinstance(item, str) for item in capabilities)
        ):
            raise DispatchReadinessError("worker backend capabilities must be strings")
        optional: dict[str, str | None] = {}
        for name in ("executable", "reason", "version"):
            item = backend[name]
            if item is not None and not isinstance(item, str):
                raise DispatchReadinessError(f"worker backend {name} must be a string or null")
            optional[name] = item
        name = _nonblank(backend["name"], "worker backend name")
        schema = _nonblank(backend["schema"], "worker backend schema")
        backends.append(
            BackendStatus(
                name=name,
                available=available,
                capabilities=tuple(capabilities),
                version=optional["version"],
                executable=optional["executable"],
                reason=optional["reason"],
                schema=schema,
            )
        )
    resources = ResourceHint.from_dict(_mapping(value["resources"], "worker resources"))
    labels = FrozenMapping(_mapping(value["labels"], "worker labels"))
    state = _nonblank(value["state"], "worker state")
    worker = Worker(
        _nonblank(value["id"], "worker id"),
        tuple(backends),
        resources=resources,
        state=WorkerState(state),
        labels=labels,
    )
    if worker.to_dict() != value:
        raise DispatchReadinessError("worker document is not canonically encoded")
    return worker


def _readiness_material(
    certificate_value: Mapping[str, object],
    claim_value: Mapping[str, object],
    *,
    environment_id: str,
    profile_id: str,
    readiness_receipt_id: str,
    readiness_certificate_id: str,
    readiness_claim_id: str,
    campaign_id: str,
    campaign_plan_id: str,
    campaign_task_id: str,
    operation_registry_id: str,
    verifier_registry_id: str,
    executor_id: str,
    artifact_store_id: str,
) -> tuple[FrozenMapping, FrozenMapping]:
    from arbogast.cert import VerificationCertificate, certificate_from_dict
    from arbogast.claims import Claim, ClaimDomain, EvidenceKind

    from .models import ReadinessScope, ReadinessVerdict
    from .readiness import CertifiedReady, readiness_receipt

    try:
        decoded = certificate_from_dict(certificate_value)
        if not isinstance(decoded, VerificationCertificate):
            raise TypeError("readiness evidence is not a VerificationCertificate")
        theorem = readiness_receipt(decoded)
        claim = Claim.from_dict(claim_value)
        claim_report = claim.verify(raise_on_failure=False)
    except Exception as error:
        raise DispatchReadinessError(
            "embedded readiness certificate or claim failed independent replay"
        ) from error
    if decoded.certificate_id != readiness_certificate_id:
        raise DispatchReadinessError("embedded readiness certificate differs from its bound ID")
    if theorem.receipt_id != readiness_receipt_id:
        raise DispatchReadinessError("embedded readiness receipt differs from its bound ID")
    if theorem.verdict is not ReadinessVerdict.READY:
        raise DispatchReadinessError("embedded readiness theorem does not authorize dispatch")
    if theorem.profile.scope is not ReadinessScope.PLAN:
        raise DispatchReadinessError("embedded readiness theorem is not an exact PLAN theorem")
    expected_bindings = {
        "A": artifact_store_id,
        "C": campaign_id,
        "E": environment_id,
        "G": operation_registry_id,
        "P": campaign_plan_id,
        "R": profile_id,
        "V": verifier_registry_id,
        "X": executor_id,
    }
    if theorem.subject.to_dict() != expected_bindings:
        raise DispatchReadinessError(
            "embedded readiness theorem differs from the E,R,C,P,G,V,X,A boundary"
        )
    if campaign_task_id not in theorem.profile.task_ids:
        raise DispatchReadinessError("campaign task is absent from the embedded readiness theorem")
    if (
        claim.id != readiness_claim_id
        or claim.domain is not ClaimDomain.ENVIRONMENTAL
        or claim_report.verified is not True
    ):
        raise DispatchReadinessError(
            "embedded readiness claim is not the exact verified environmental claim"
        )
    expected_claim = CertifiedReady(
        theorem.environment,
        theorem.profile,
        theorem,
        decoded,
    ).claim()
    if claim.to_dict() != expected_claim.to_dict():
        raise DispatchReadinessError(
            "embedded readiness claim differs from the canonical certified-ready claim"
        )
    evidence_ids = tuple(
        item.ref for item in claim.evidence if item.kind is EvidenceKind.CERTIFICATE
    )
    attached = claim_value.get("attached_certificates")
    if (
        evidence_ids != (readiness_certificate_id,)
        or not isinstance(attached, Sequence)
        or isinstance(attached, str)
        or len(attached) != 1
        or attached[0] != decoded.to_dict()
    ):
        raise DispatchReadinessError(
            "embedded environmental claim does not carry the exact readiness certificate"
        )
    return FrozenMapping(decoded.to_dict()), FrozenMapping(claim.to_dict())


def _artifact_probe_receipt(
    value: Mapping[str, object],
    *,
    environment_id: str,
    profile_id: str,
    readiness_certificate_id: str,
    campaign_id: str,
    campaign_plan_id: str,
    campaign_task_id: str,
    campaign_target_id: str,
    campaign_attempt_id: str,
    dispatch_id: str,
    fleet_plan_hash: str,
    lease: LeaseRecord,
) -> FrozenMapping:
    if set(value) != {
        "payload",
        "read_bytes_hex",
        "read_outcome",
        "reference",
        "schema",
        "write_outcome",
    }:
        raise DispatchReadinessError("dispatch artifact probe has missing or unknown fields")
    if value["schema"] != _ARTIFACT_PROBE_RECEIPT_SCHEMA:
        raise DispatchReadinessError("unsupported dispatch artifact probe schema")
    if value["write_outcome"] != "completed" or value["read_outcome"] != "completed":
        raise DispatchReadinessError(
            "dispatch artifact probe did not record completed write and read outcomes"
        )
    payload = _mapping(value["payload"], "dispatch artifact probe payload")
    expected_payload = {
        "dispatch_id": dispatch_id,
        "environment_id": environment_id,
        "readiness_certificate_id": readiness_certificate_id,
        "campaign_id": campaign_id,
        "campaign_plan_id": campaign_plan_id,
        "campaign_task_id": campaign_task_id,
        "campaign_target_id": campaign_target_id,
        "campaign_attempt_id": campaign_attempt_id,
        "fleet_plan_hash": fleet_plan_hash,
        "lease_id": lease.id,
        "profile_id": profile_id,
        "schema": _ARTIFACT_PROBE_SCHEMA,
        "shard_hash": lease.shard_hash,
        "task_hash": lease.task_hash,
        "worker_id": lease.worker_id,
    }
    if dict(payload) != expected_payload:
        raise DispatchReadinessError(
            "dispatch artifact probe payload is outside the receipt boundary"
        )
    reference_value = _mapping(value["reference"], "dispatch artifact probe reference")
    try:
        reference = ArtifactRef.from_dict(reference_value)
    except (KeyError, TypeError, ValueError) as error:
        raise DispatchReadinessError(
            "dispatch artifact probe reference failed strict replay"
        ) from error
    encoded = canonical_bytes(expected_payload)
    raw_read = value["read_bytes_hex"]
    if not isinstance(raw_read, str):
        raise DispatchReadinessError("dispatch artifact probe read bytes must be hex")
    try:
        read_bytes = bytes.fromhex(raw_read)
    except ValueError as error:
        raise DispatchReadinessError("dispatch artifact probe read bytes are malformed") from error
    if (
        reference.digest != hashlib.sha256(encoded).hexdigest()
        or reference.size != len(encoded)
        or reference.media_type != "application/json"
        or read_bytes != encoded
    ):
        raise DispatchReadinessError(
            "dispatch artifact probe reference does not match its canonical bytes"
        )
    return FrozenMapping(
        {
            "payload": expected_payload,
            "read_bytes_hex": encoded.hex(),
            "read_outcome": "completed",
            "reference": reference.to_dict(),
            "schema": _ARTIFACT_PROBE_RECEIPT_SCHEMA,
            "write_outcome": "completed",
        }
    )


@dataclass(frozen=True, slots=True)
class DispatchReadinessReceipt:
    """A non-mathematical receipt emitted only after a live lease guard passes."""

    environment_id: str
    profile_id: str
    readiness_receipt_id: str
    readiness_certificate_id: str
    readiness_claim_id: str
    readiness_certificate: FrozenMapping
    readiness_claim: FrozenMapping
    campaign_id: str
    campaign_plan_id: str
    campaign_task_id: str
    campaign_target_id: str
    campaign_attempt: int
    campaign_attempt_id: str
    operation_registry_id: str
    verifier_registry_id: str
    executor_id: str
    artifact_store_id: str
    dispatch_id: str
    dispatch_ordinal: int
    dispatch_runtime_nonce: str
    fleet_task: TaskSpec
    fleet_plan_hash: str
    fleet_plan_shard_hashes: tuple[str, ...]
    shard: ShardSpec
    worker: FrozenMapping
    lease: LeaseRecord
    artifact_probe: FrozenMapping
    checked_at: str
    checks: tuple[str, ...] = DISPATCH_READINESS_CHECKS
    valid: bool = True

    schema_version: ClassVar[str] = DISPATCH_READINESS_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "environment_id",
            "profile_id",
            "readiness_receipt_id",
            "readiness_certificate_id",
            "campaign_id",
            "campaign_plan_id",
            "campaign_task_id",
            "campaign_target_id",
            "campaign_attempt_id",
            "operation_registry_id",
            "verifier_registry_id",
            "executor_id",
            "artifact_store_id",
        ):
            _content_id(getattr(self, name), name)
        _nonblank(self.readiness_claim_id, "readiness_claim_id")
        object.__setattr__(self, "readiness_certificate", FrozenMapping(self.readiness_certificate))
        object.__setattr__(self, "readiness_claim", FrozenMapping(self.readiness_claim))
        certificate, claim = _readiness_material(
            self.readiness_certificate,
            self.readiness_claim,
            environment_id=self.environment_id,
            profile_id=self.profile_id,
            readiness_receipt_id=self.readiness_receipt_id,
            readiness_certificate_id=self.readiness_certificate_id,
            readiness_claim_id=self.readiness_claim_id,
            campaign_id=self.campaign_id,
            campaign_plan_id=self.campaign_plan_id,
            campaign_task_id=self.campaign_task_id,
            operation_registry_id=self.operation_registry_id,
            verifier_registry_id=self.verifier_registry_id,
            executor_id=self.executor_id,
            artifact_store_id=self.artifact_store_id,
        )
        object.__setattr__(self, "readiness_certificate", certificate)
        object.__setattr__(self, "readiness_claim", claim)
        if (
            isinstance(self.campaign_attempt, bool)
            or not isinstance(self.campaign_attempt, int)
            or self.campaign_attempt < 1
        ):
            raise DispatchReadinessError("campaign_attempt must be a positive integer")
        expected_attempt_id = "sha256:" + canonical_sha256(
            {
                "attempt": self.campaign_attempt,
                "schema": "arbogast.campaign.attempt-identity.v1",
                "task_id": self.campaign_task_id,
            }
        )
        if self.campaign_attempt_id != expected_attempt_id:
            raise DispatchReadinessError(
                "campaign_attempt_id does not match its canonical identity"
            )
        if not _DISPATCH_ID.fullmatch(self.dispatch_id):
            raise DispatchReadinessError("dispatch_id must be dispatch:<64 lowercase hex>")
        if (
            isinstance(self.dispatch_ordinal, bool)
            or not isinstance(self.dispatch_ordinal, int)
            or self.dispatch_ordinal < 0
        ):
            raise DispatchReadinessError("dispatch_ordinal must be a non-negative integer")
        if not isinstance(self.dispatch_runtime_nonce, str) or not _RUNTIME_NONCE.fullmatch(
            self.dispatch_runtime_nonce
        ):
            raise DispatchReadinessError(
                "dispatch_runtime_nonce must be 32 lowercase hex characters"
            )
        if not isinstance(self.fleet_task, TaskSpec):
            raise DispatchReadinessError("fleet_task must be a TaskSpec")
        _digest(self.fleet_plan_hash, "fleet_plan_hash")
        hashes = tuple(self.fleet_plan_shard_hashes)
        if not hashes or len(hashes) != len(set(hashes)):
            raise DispatchReadinessError("fleet plan shard hashes must be nonempty and unique")
        for item in hashes:
            _digest(item, "fleet plan shard hash")
        object.__setattr__(self, "fleet_plan_shard_hashes", hashes)
        if not isinstance(self.shard, ShardSpec):
            raise DispatchReadinessError("shard must be a ShardSpec")
        if self.shard.task_hash != self.fleet_task.task_hash:
            raise DispatchReadinessError("shard is bound to a different fleet task")
        if self.shard.shard_hash not in hashes:
            raise DispatchReadinessError("shard is absent from the bound fleet plan")
        expected_plan_hash = canonical_sha256(
            {
                "schema": PLAN_SCHEMA,
                "shards": hashes,
                "task_hash": self.fleet_task.task_hash,
            }
        )
        if self.fleet_plan_hash != expected_plan_hash:
            raise DispatchReadinessError("fleet_plan_hash does not match its task and shards")
        expected_dispatch_id = "dispatch:" + canonical_sha256(
            {
                "ordinal": self.dispatch_ordinal,
                "plan_hash": self.fleet_plan_hash,
                "runtime_nonce": self.dispatch_runtime_nonce,
                "task_hash": self.fleet_task.task_hash,
            }
        )
        if self.dispatch_id != expected_dispatch_id:
            raise DispatchReadinessError(
                "dispatch_id does not match its canonical scheduler identity"
            )
        object.__setattr__(self, "worker", FrozenMapping(self.worker))
        worker = _worker_from_document(self.worker)
        if not worker.match(self.fleet_task).eligible:
            raise DispatchReadinessError("worker does not satisfy the exact fleet task")
        if not isinstance(self.lease, LeaseRecord) or self.lease.state is not LeaseState.ACTIVE:
            raise DispatchReadinessError("dispatch readiness requires an active LeaseRecord")
        if (
            self.lease.task_hash != self.fleet_task.task_hash
            or self.lease.shard_hash != self.shard.shard_hash
            or self.lease.worker_id != worker.id
        ):
            raise DispatchReadinessError("lease does not bind the task, shard, and worker")
        checked = _timestamp(self.checked_at, "checked_at")
        acquired = _timestamp(self.lease.acquired_at, "lease acquired_at")
        expires = _timestamp(self.lease.expires_at, "lease expires_at")
        if not acquired <= checked < expires:
            raise DispatchReadinessError("readiness check must occur during the active lease")
        object.__setattr__(
            self,
            "artifact_probe",
            _artifact_probe_receipt(
                self.artifact_probe,
                environment_id=self.environment_id,
                profile_id=self.profile_id,
                readiness_certificate_id=self.readiness_certificate_id,
                campaign_id=self.campaign_id,
                campaign_plan_id=self.campaign_plan_id,
                campaign_task_id=self.campaign_task_id,
                campaign_target_id=self.campaign_target_id,
                campaign_attempt_id=self.campaign_attempt_id,
                dispatch_id=self.dispatch_id,
                fleet_plan_hash=self.fleet_plan_hash,
                lease=self.lease,
            ),
        )
        if tuple(self.checks) != DISPATCH_READINESS_CHECKS:
            raise DispatchReadinessError("dispatch readiness checks are not canonical")
        object.__setattr__(self, "checks", tuple(self.checks))
        if self.valid is not True:
            raise DispatchReadinessError("a dispatch readiness receipt must record valid=true")

    @property
    def receipt_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "environment_id": self.environment_id,
            "profile_id": self.profile_id,
            "readiness_receipt_id": self.readiness_receipt_id,
            "readiness_certificate_id": self.readiness_certificate_id,
            "readiness_claim_id": self.readiness_claim_id,
            "readiness_certificate": self.readiness_certificate,
            "readiness_claim": self.readiness_claim,
            "campaign_id": self.campaign_id,
            "campaign_plan_id": self.campaign_plan_id,
            "campaign_task_id": self.campaign_task_id,
            "campaign_target_id": self.campaign_target_id,
            "campaign_attempt": self.campaign_attempt,
            "campaign_attempt_id": self.campaign_attempt_id,
            "operation_registry_id": self.operation_registry_id,
            "verifier_registry_id": self.verifier_registry_id,
            "executor_id": self.executor_id,
            "artifact_store_id": self.artifact_store_id,
            "dispatch_id": self.dispatch_id,
            "dispatch_ordinal": self.dispatch_ordinal,
            "dispatch_runtime_nonce": self.dispatch_runtime_nonce,
            "fleet_task": self.fleet_task.to_dict(),
            "fleet_plan_hash": self.fleet_plan_hash,
            "fleet_plan_shard_hashes": self.fleet_plan_shard_hashes,
            "shard": self.shard.to_dict(),
            "worker": self.worker,
            "lease": self.lease.to_dict(),
            "artifact_probe": self.artifact_probe,
            "checked_at": self.checked_at,
            "checks": self.checks,
            "valid": self.valid,
        }

    def to_dict(self) -> dict[str, object]:
        result = cast(dict[str, object], canonicalize(self.to_canonical()))
        result["receipt_id"] = self.receipt_id
        return result

    def verify(self) -> bool:
        try:
            return type(self).from_dict(self.to_dict()) == self
        except (DispatchReadinessError, KeyError, TypeError, ValueError):
            return False

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DispatchReadinessReceipt:
        required = {
            "schema_version",
            "receipt_id",
            "environment_id",
            "profile_id",
            "readiness_receipt_id",
            "readiness_certificate_id",
            "readiness_claim_id",
            "readiness_certificate",
            "readiness_claim",
            "campaign_id",
            "campaign_plan_id",
            "campaign_task_id",
            "campaign_target_id",
            "campaign_attempt",
            "campaign_attempt_id",
            "operation_registry_id",
            "verifier_registry_id",
            "executor_id",
            "artifact_store_id",
            "dispatch_id",
            "dispatch_ordinal",
            "dispatch_runtime_nonce",
            "fleet_task",
            "fleet_plan_hash",
            "fleet_plan_shard_hashes",
            "shard",
            "worker",
            "lease",
            "artifact_probe",
            "checked_at",
            "checks",
            "valid",
        }
        if set(value) != required:
            raise DispatchReadinessError("dispatch receipt has missing or unknown fields")
        if value["schema_version"] != cls.schema_version:
            raise DispatchReadinessError("unsupported dispatch-readiness receipt schema")
        hashes = value["fleet_plan_shard_hashes"]
        checks = value["checks"]
        if isinstance(hashes, str) or not isinstance(hashes, Sequence):
            raise DispatchReadinessError("fleet_plan_shard_hashes must be an array")
        if isinstance(checks, str) or not isinstance(checks, Sequence):
            raise DispatchReadinessError("checks must be an array")
        if any(not isinstance(item, str) for item in (*hashes, *checks)):
            raise DispatchReadinessError("hash and check arrays must contain strings")
        raw_valid = value["valid"]
        if not isinstance(raw_valid, bool):
            raise DispatchReadinessError("valid must be boolean")
        campaign_attempt = value["campaign_attempt"]
        dispatch_ordinal = value["dispatch_ordinal"]
        if isinstance(campaign_attempt, bool) or not isinstance(campaign_attempt, int):
            raise DispatchReadinessError("campaign_attempt must be an integer")
        if isinstance(dispatch_ordinal, bool) or not isinstance(dispatch_ordinal, int):
            raise DispatchReadinessError("dispatch_ordinal must be an integer")
        try:
            receipt = cls(
                environment_id=_nonblank(value["environment_id"], "environment_id"),
                profile_id=_nonblank(value["profile_id"], "profile_id"),
                readiness_receipt_id=_nonblank(
                    value["readiness_receipt_id"], "readiness_receipt_id"
                ),
                readiness_certificate_id=_nonblank(
                    value["readiness_certificate_id"], "readiness_certificate_id"
                ),
                readiness_claim_id=_nonblank(value["readiness_claim_id"], "readiness_claim_id"),
                readiness_certificate=FrozenMapping(
                    _mapping(value["readiness_certificate"], "readiness_certificate")
                ),
                readiness_claim=FrozenMapping(
                    _mapping(value["readiness_claim"], "readiness_claim")
                ),
                campaign_id=_nonblank(value["campaign_id"], "campaign_id"),
                campaign_plan_id=_nonblank(value["campaign_plan_id"], "campaign_plan_id"),
                campaign_task_id=_nonblank(value["campaign_task_id"], "campaign_task_id"),
                campaign_target_id=_nonblank(value["campaign_target_id"], "campaign_target_id"),
                campaign_attempt=campaign_attempt,
                campaign_attempt_id=_nonblank(value["campaign_attempt_id"], "campaign_attempt_id"),
                operation_registry_id=_nonblank(
                    value["operation_registry_id"], "operation_registry_id"
                ),
                verifier_registry_id=_nonblank(
                    value["verifier_registry_id"], "verifier_registry_id"
                ),
                executor_id=_nonblank(value["executor_id"], "executor_id"),
                artifact_store_id=_nonblank(value["artifact_store_id"], "artifact_store_id"),
                dispatch_id=_nonblank(value["dispatch_id"], "dispatch_id"),
                dispatch_ordinal=dispatch_ordinal,
                dispatch_runtime_nonce=_nonblank(
                    value["dispatch_runtime_nonce"], "dispatch_runtime_nonce"
                ),
                fleet_task=TaskSpec.from_dict(_mapping(value["fleet_task"], "fleet_task")),
                fleet_plan_hash=_nonblank(value["fleet_plan_hash"], "fleet_plan_hash"),
                fleet_plan_shard_hashes=tuple(cast(Sequence[str], hashes)),
                shard=ShardSpec.from_dict(_mapping(value["shard"], "shard")),
                worker=FrozenMapping(_mapping(value["worker"], "worker")),
                lease=LeaseRecord.from_dict(_mapping(value["lease"], "lease")),
                artifact_probe=FrozenMapping(_mapping(value["artifact_probe"], "artifact_probe")),
                checked_at=_nonblank(value["checked_at"], "checked_at"),
                checks=tuple(cast(Sequence[str], checks)),
                valid=raw_valid,
            )
        except DispatchReadinessError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise DispatchReadinessError(
                "dispatch receipt contains an invalid nested document"
            ) from error
        if _content_id(value["receipt_id"], "receipt_id") != receipt.receipt_id:
            raise DispatchReadinessError("receipt_id does not match canonical contents")
        return receipt


__all__ = [
    "DISPATCH_READINESS_CHECKS",
    "DispatchReadinessError",
    "DispatchReadinessReceipt",
]
