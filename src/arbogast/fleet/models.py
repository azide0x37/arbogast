"""Immutable fleet protocol objects.

These objects describe mathematical work; they do not describe a particular
scheduler.  Every identity-bearing field is canonical and deeply immutable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from arbogast.formats import (
    ARTIFACT_SCHEMA,
    PLAN_SCHEMA,
    RUN_SCHEMA,
    SHARD_SCHEMA,
    TASK_SCHEMA,
    FrozenMapping,
    JSONValue,
    canonical_sha256,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FleetSpecError(ValueError):
    """Raised when a fleet protocol object violates an invariant."""


class EvidenceState(StrEnum):
    """The proof boundary of an artifact.

    Discovery artifacts are candidates or computed outputs.  Verification
    artifacts have passed the named local operation verifier.  This is a cache
    receipt, not a theorem certificate or campaign-closing mathematical state.
    There is no implicit promotion between these states.
    """

    DISCOVERY = "discovery"
    VERIFICATION = "verification"

    def satisfies(self, required: EvidenceState) -> bool:
        if required is EvidenceState.DISCOVERY:
            return True
        return self is EvidenceState.VERIFICATION


@dataclass(frozen=True, slots=True, init=False)
class ResourceHint:
    """Non-semantic scheduling hints.

    Resource hints do not contribute to :attr:`TaskSpec.task_hash`; moving an
    identical task between machines must not create a new mathematical task.
    """

    cpu_cores: int
    memory_bytes: int | None
    wall_time_seconds: int | None
    scratch_bytes: int | None
    gpu_count: int

    def __init__(
        self,
        cpu_cores: int = 1,
        memory_bytes: int | None = None,
        wall_time_seconds: int | None = None,
        scratch_bytes: int | None = None,
        gpu_count: int = 0,
        *,
        memory_mb: int | None = None,
        scratch_mb: int | None = None,
    ) -> None:
        if memory_bytes is not None and memory_mb is not None:
            raise FleetSpecError("provide memory_bytes or memory_mb, not both")
        if scratch_bytes is not None and scratch_mb is not None:
            raise FleetSpecError("provide scratch_bytes or scratch_mb, not both")
        if memory_mb is not None:
            if isinstance(memory_mb, bool) or not isinstance(memory_mb, int):
                raise FleetSpecError("memory_mb must be a non-negative integer or None")
            memory_bytes = memory_mb * 1024 * 1024
        if scratch_mb is not None:
            if isinstance(scratch_mb, bool) or not isinstance(scratch_mb, int):
                raise FleetSpecError("scratch_mb must be a non-negative integer or None")
            scratch_bytes = scratch_mb * 1024 * 1024
        integer_fields = {
            "cpu_cores": cpu_cores,
            "gpu_count": gpu_count,
        }
        optional_fields = {
            "memory_bytes": memory_bytes,
            "wall_time_seconds": wall_time_seconds,
            "scratch_bytes": scratch_bytes,
        }
        for name, value in integer_fields.items():
            minimum = 1 if name == "cpu_cores" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise FleetSpecError(f"{name} must be an integer >= {minimum}")
        for name, optional_value in optional_fields.items():
            if optional_value is not None and (
                isinstance(optional_value, bool)
                or not isinstance(optional_value, int)
                or optional_value < 0
            ):
                raise FleetSpecError(f"{name} must be a non-negative integer or None")
        object.__setattr__(self, "cpu_cores", cpu_cores)
        object.__setattr__(self, "memory_bytes", memory_bytes)
        object.__setattr__(self, "wall_time_seconds", wall_time_seconds)
        object.__setattr__(self, "scratch_bytes", scratch_bytes)
        object.__setattr__(self, "gpu_count", gpu_count)

    @property
    def memory_mb(self) -> int | None:
        return None if self.memory_bytes is None else self.memory_bytes // (1024 * 1024)

    @property
    def scratch_mb(self) -> int | None:
        return None if self.scratch_bytes is None else self.scratch_bytes // (1024 * 1024)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "cpu_cores": self.cpu_cores,
            "gpu_count": self.gpu_count,
            "memory_bytes": self.memory_bytes,
            "scratch_bytes": self.scratch_bytes,
            "wall_time_seconds": self.wall_time_seconds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceHint:
        required = {
            "cpu_cores",
            "gpu_count",
            "memory_bytes",
            "scratch_bytes",
            "wall_time_seconds",
        }
        if set(value) != required:
            raise FleetSpecError("resource hint has missing or unknown fields")
        cpu_cores = value["cpu_cores"]
        gpu_count = value["gpu_count"]
        memory_bytes = value["memory_bytes"]
        scratch_bytes = value["scratch_bytes"]
        wall_time_seconds = value["wall_time_seconds"]
        if isinstance(cpu_cores, bool) or not isinstance(cpu_cores, int):
            raise FleetSpecError("resource cpu_cores must be an integer")
        if isinstance(gpu_count, bool) or not isinstance(gpu_count, int):
            raise FleetSpecError("resource gpu_count must be an integer")
        for resource_name, resource_value in (
            ("memory_bytes", memory_bytes),
            ("wall_time_seconds", wall_time_seconds),
            ("scratch_bytes", scratch_bytes),
        ):
            if resource_value is not None and (
                isinstance(resource_value, bool) or not isinstance(resource_value, int)
            ):
                raise FleetSpecError(f"resource {resource_name} must be an integer or null")
        return cls(
            cpu_cores=cpu_cores,
            memory_bytes=memory_bytes,
            wall_time_seconds=wall_time_seconds,
            scratch_bytes=scratch_bytes,
            gpu_count=gpu_count,
        )


@dataclass(frozen=True, slots=True)
class BackendRequirement:
    """An exact, honest backend requirement for a task."""

    name: str = "python"
    version: str | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise FleetSpecError("backend name must be a string")
        if self.version is not None and not isinstance(self.version, str):
            raise FleetSpecError("backend version must be a string or None")
        if self.version == "":
            raise FleetSpecError("backend version cannot be blank")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(item, str) for item in self.capabilities
        ):
            raise FleetSpecError("backend capabilities must be a tuple of strings")
        name = self.name.strip().lower()
        if not name:
            raise FleetSpecError("backend name must not be empty")
        capabilities = tuple(sorted(set(self.capabilities)))
        if any(not item or item != item.strip() for item in capabilities):
            raise FleetSpecError("backend capabilities must be non-empty strings")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "capabilities", capabilities)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "capabilities": list(self.capabilities),
            "name": self.name,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BackendRequirement:
        if set(value) != {"capabilities", "name", "version"}:
            raise FleetSpecError("backend requirement has missing or unknown fields")
        name = value["name"]
        version = value["version"]
        capabilities = value["capabilities"]
        if not isinstance(name, str):
            raise FleetSpecError("backend name must be a string")
        if version is not None and not isinstance(version, str):
            raise FleetSpecError("backend version must be a string or null")
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            raise FleetSpecError("backend capabilities must be an array of strings")
        if name != name.strip().lower() or not name:
            raise FleetSpecError("backend name is not in canonical lowercase form")
        if version == "":
            raise FleetSpecError("backend version cannot be blank")
        if capabilities != sorted(set(capabilities)) or any(not item for item in capabilities):
            raise FleetSpecError("backend capabilities are not canonical and unique")
        return cls(name=name, version=version, capabilities=tuple(capabilities))


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """A content-addressed artifact reference."""

    digest: str
    size: int
    media_type: str = "application/octet-stream"
    algorithm: str = "sha256"
    schema: str = field(default=ARTIFACT_SCHEMA, init=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, str) or not isinstance(self.digest, str):
            raise FleetSpecError("artifact algorithm and digest must be strings")
        if not isinstance(self.media_type, str):
            raise FleetSpecError("artifact media type must be a string")
        algorithm = self.algorithm.lower()
        digest = self.digest.lower()
        if algorithm != "sha256":
            raise FleetSpecError(f"unsupported artifact hash algorithm: {algorithm}")
        if not _SHA256_RE.fullmatch(digest):
            raise FleetSpecError("artifact digest must be 64 lowercase hexadecimal characters")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise FleetSpecError("artifact size must be a non-negative integer")
        if not self.media_type:
            raise FleetSpecError("artifact media type must not be empty")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "digest", digest)

    @property
    def uri(self) -> str:
        return f"{self.algorithm}:{self.digest}"

    def __str__(self) -> str:
        return self.uri

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "media_type": self.media_type,
            "schema": self.schema,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArtifactRef:
        required = {"algorithm", "digest", "media_type", "schema", "size"}
        if set(value) != required:
            raise FleetSpecError("artifact reference has missing or unknown fields")
        if value["schema"] != ARTIFACT_SCHEMA:
            raise FleetSpecError("unsupported artifact-reference schema")
        digest = value["digest"]
        size = value["size"]
        media_type = value["media_type"]
        algorithm = value["algorithm"]
        if not isinstance(digest, str):
            raise FleetSpecError("artifact digest must be a string")
        if isinstance(size, bool) or not isinstance(size, int):
            raise FleetSpecError("artifact size must be an integer")
        if not isinstance(media_type, str) or not isinstance(algorithm, str):
            raise FleetSpecError("artifact media_type and algorithm must be strings")
        if algorithm != "sha256" or digest != digest.lower():
            raise FleetSpecError("artifact hash fields are not canonically encoded")
        return cls(
            digest=digest,
            size=size,
            media_type=media_type,
            algorithm=algorithm,
        )


def _input_ref(value: object) -> str:
    if isinstance(value, ArtifactRef):
        return value.uri
    if isinstance(value, str) and value:
        return value
    uri = getattr(value, "uri", None)
    if isinstance(uri, str) and uri:
        return uri
    digest = getattr(value, "digest", None)
    if isinstance(digest, str) and digest:
        algorithm = getattr(value, "algorithm", "sha256")
        return f"{algorithm}:{digest}"
    raise FleetSpecError("input references must be strings or content-addressed references")


@dataclass(frozen=True, slots=True, init=False)
class TaskSpec:
    """A scheduler-independent mathematical task identity."""

    operation: str
    input_refs: tuple[str, ...]
    parameters: FrozenMapping
    backend: BackendRequirement
    resources: ResourceHint
    seed: int | None
    schema_version: str
    schema: str

    def __init__(
        self,
        operation: str,
        input_refs: Iterable[object] = (),
        parameters: Mapping[str, Any] | None = None,
        backend: BackendRequirement | None = None,
        resources: ResourceHint | None = None,
        seed: int | None = None,
        schema_version: str = "1",
    ) -> None:
        if not isinstance(operation, str):
            raise FleetSpecError("task operation must be a string")
        operation = operation.strip()
        if not operation:
            raise FleetSpecError("task operation must not be empty")
        refs = tuple(_input_ref(item) for item in input_refs)
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise FleetSpecError("task seed must be an integer or None")
        if not isinstance(schema_version, str) or not schema_version:
            raise FleetSpecError("task schema_version must be a non-empty string")
        if backend is not None and not isinstance(backend, BackendRequirement):
            raise FleetSpecError("task backend must be a BackendRequirement")
        if resources is not None and not isinstance(resources, ResourceHint):
            raise FleetSpecError("task resources must be a ResourceHint")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "input_refs", refs)
        object.__setattr__(self, "parameters", FrozenMapping(parameters))
        object.__setattr__(self, "backend", BackendRequirement() if backend is None else backend)
        object.__setattr__(self, "resources", ResourceHint() if resources is None else resources)
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "schema", TASK_SCHEMA)

    def identity_dict(self) -> dict[str, JSONValue]:
        """Return exactly the fields that define mathematical task identity."""

        identity: dict[str, JSONValue] = {
            "backend": self.backend.to_dict(),
            "input_refs": list(self.input_refs),
            "operation": self.operation,
            "parameters": self.parameters.to_dict(),
            "schema": self.schema,
            "schema_version": self.schema_version,
        }
        if self.seed is not None:
            # A pseudorandom seed is semantically a parameter, not a scheduling
            # hint.  Omitting it would make distinct discoveries share a cache.
            identity["seed"] = self.seed
        return identity

    @property
    def task_hash(self) -> str:
        return canonical_sha256(self.identity_dict())

    @property
    def hash(self) -> str:
        """Alias for clients that use ``spec.hash``."""

        return self.task_hash

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self.identity_dict(),
            "resources": self.resources.to_dict(),
            "task_hash": self.task_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskSpec:
        required = {
            "backend",
            "input_refs",
            "operation",
            "parameters",
            "resources",
            "schema",
            "schema_version",
            "task_hash",
        }
        allowed = required | {"seed"}
        if set(value) not in (required, allowed):
            raise FleetSpecError("task has missing or unknown fields")
        if value["schema"] != TASK_SCHEMA:
            raise FleetSpecError("unsupported task schema")
        operation = value["operation"]
        input_refs = value["input_refs"]
        parameters = value["parameters"]
        backend_value = value["backend"]
        resource_value = value["resources"]
        if not isinstance(operation, str):
            raise FleetSpecError("task operation must be a string")
        if not isinstance(input_refs, list) or any(
            not isinstance(item, str) for item in input_refs
        ):
            raise FleetSpecError("task input_refs must be an array of strings")
        if not isinstance(parameters, Mapping):
            raise FleetSpecError("task parameters must be an object")
        if not isinstance(backend_value, Mapping) or not isinstance(resource_value, Mapping):
            raise FleetSpecError("task backend and resources must be objects")
        backend = BackendRequirement.from_dict(backend_value)
        resources = ResourceHint.from_dict(resource_value)
        schema_version = value["schema_version"]
        seed = value.get("seed")
        if not isinstance(schema_version, str):
            raise FleetSpecError("task schema_version must be a string")
        if operation != operation.strip() or not schema_version:
            raise FleetSpecError("task operation/schema_version are not canonical")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise FleetSpecError("task seed must be an integer or null")
        spec = cls(
            operation=operation,
            input_refs=input_refs,
            parameters=parameters,
            backend=backend,
            resources=resources,
            seed=seed,
            schema_version=schema_version,
        )
        supplied_hash = value["task_hash"]
        if not isinstance(supplied_hash, str):
            raise FleetSpecError("task_hash must be a string")
        if supplied_hash != spec.task_hash:
            raise FleetSpecError("task_hash does not match canonical task contents")
        return spec


@dataclass(frozen=True, slots=True, init=False)
class ShardSpec:
    """One deterministic unit of a :class:`TaskSpec`."""

    task_hash: str
    key: str
    payload: FrozenMapping
    ordinal: int | None
    schema: str

    def __init__(
        self,
        task_hash: str,
        key: str,
        payload: Mapping[str, Any] | None = None,
        ordinal: int | None = None,
    ) -> None:
        if not isinstance(task_hash, str) or not task_hash:
            raise FleetSpecError("shard task_hash must be a non-empty string")
        if not isinstance(key, str) or not key:
            raise FleetSpecError("shard key must be an explicit non-empty string")
        if ordinal is not None and (
            isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0
        ):
            raise FleetSpecError("shard ordinal must be a non-negative integer or None")
        object.__setattr__(self, "task_hash", task_hash)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "payload", FrozenMapping(payload))
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "schema", SHARD_SCHEMA)

    @property
    def shard_key(self) -> str:
        return self.key

    @property
    def shard_hash(self) -> str:
        return canonical_sha256(
            {
                "key": self.key,
                "payload": self.payload.to_dict(),
                "schema": self.schema,
                "task_hash": self.task_hash,
            }
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "key": self.key,
            "ordinal": self.ordinal,
            "payload": self.payload.to_dict(),
            "schema": self.schema,
            "shard_hash": self.shard_hash,
            "task_hash": self.task_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ShardSpec:
        required = {"key", "ordinal", "payload", "schema", "shard_hash", "task_hash"}
        if set(value) != required:
            raise FleetSpecError("shard has missing or unknown fields")
        if value["schema"] != SHARD_SCHEMA:
            raise FleetSpecError("unsupported shard schema")
        task_hash = value["task_hash"]
        key = value["key"]
        payload = value["payload"]
        ordinal = value["ordinal"]
        if not isinstance(task_hash, str) or not isinstance(key, str):
            raise FleetSpecError("shard task_hash and key must be strings")
        if not isinstance(payload, Mapping):
            raise FleetSpecError("shard payload must be an object")
        if ordinal is not None and (isinstance(ordinal, bool) or not isinstance(ordinal, int)):
            raise FleetSpecError("shard ordinal must be an integer or null")
        shard = cls(
            task_hash=task_hash,
            key=key,
            payload=payload,
            ordinal=ordinal,
        )
        supplied_hash = value["shard_hash"]
        if not isinstance(supplied_hash, str):
            raise FleetSpecError("shard_hash must be a string")
        if supplied_hash != shard.shard_hash:
            raise FleetSpecError("shard_hash does not match canonical shard contents")
        return shard


@dataclass(frozen=True, slots=True, init=False)
class FleetPlan:
    """A key-sorted, duplicate-free collection of task shards."""

    task: TaskSpec
    shards: tuple[ShardSpec, ...]
    schema: str

    def __init__(self, task: TaskSpec, shards: Iterable[ShardSpec]) -> None:
        ordered = tuple(sorted(shards, key=lambda shard: (shard.key, shard.shard_hash)))
        keys = tuple(shard.key for shard in ordered)
        if len(keys) != len(set(keys)):
            raise FleetSpecError("shard keys must be unique within a plan")
        if any(shard.task_hash != task.task_hash for shard in ordered):
            raise FleetSpecError("every shard must be bound to the plan's task hash")
        normalized = tuple(
            ShardSpec(
                task_hash=shard.task_hash,
                key=shard.key,
                payload=shard.payload,
                ordinal=ordinal,
            )
            for ordinal, shard in enumerate(ordered)
        )
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "shards", normalized)
        object.__setattr__(self, "schema", PLAN_SCHEMA)

    @classmethod
    def from_keys(
        cls,
        task: TaskSpec,
        keys: Iterable[str],
        payloads: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> FleetPlan:
        payload_map = {} if payloads is None else payloads
        shards = (ShardSpec(task.task_hash, key, payload_map.get(key, {})) for key in keys)
        return cls(task, shards)

    @property
    def plan_hash(self) -> str:
        return canonical_sha256(
            {
                "schema": self.schema,
                "shards": [shard.shard_hash for shard in self.shards],
                "task_hash": self.task.task_hash,
            }
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "plan_hash": self.plan_hash,
            "schema": self.schema,
            "shards": [shard.to_dict() for shard in self.shards],
            "task": self.task.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ShardResult:
    """The immutable receipt for one shard artifact."""

    shard: ShardSpec
    artifact: ArtifactRef
    state: EvidenceState = EvidenceState.DISCOVERY
    resumed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.shard, ShardSpec):
            raise FleetSpecError("shard result shard must be a ShardSpec")
        if not isinstance(self.artifact, ArtifactRef):
            raise FleetSpecError("shard result artifact must be an ArtifactRef")
        if not isinstance(self.state, EvidenceState):
            raise FleetSpecError("shard result state must be an EvidenceState")
        if not isinstance(self.resumed, bool):
            raise FleetSpecError("shard result resumed must be boolean")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifact": self.artifact.to_dict(),
            "resumed": self.resumed,
            "shard": self.shard.to_dict(),
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class FleetRun:
    """A reduced fleet result and the receipts from which it was built."""

    task: TaskSpec
    plan: FleetPlan
    shards: tuple[ShardResult, ...]
    result: ArtifactRef
    state: EvidenceState
    resumed: bool = False
    schema: str = field(default=RUN_SCHEMA, init=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskSpec) or not isinstance(self.plan, FleetPlan):
            raise FleetSpecError("run task/plan have invalid types")
        if not isinstance(self.shards, tuple) or any(
            not isinstance(item, ShardResult) for item in self.shards
        ):
            raise FleetSpecError("run shards must be a tuple of ShardResult values")
        if not isinstance(self.result, ArtifactRef):
            raise FleetSpecError("run result must be an ArtifactRef")
        if not isinstance(self.state, EvidenceState):
            raise FleetSpecError("run state must be an EvidenceState")
        if not isinstance(self.resumed, bool):
            raise FleetSpecError("run resumed must be boolean")
        if self.plan.task != self.task:
            raise FleetSpecError("run plan is not bound to run task")
        if tuple(item.shard for item in self.shards) != self.plan.shards:
            raise FleetSpecError("run shard receipts must follow deterministic plan order")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "plan_hash": self.plan.plan_hash,
            "result": self.result.to_dict(),
            "resumed": self.resumed,
            "schema": self.schema,
            "shards": [shard.to_dict() for shard in self.shards],
            "state": self.state.value,
            "task": self.task.to_dict(),
        }


def deterministic_plan(
    task: TaskSpec,
    shard_keys: Sequence[str] | Iterable[str],
    *,
    payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> FleetPlan:
    """Build a deterministic plan from explicit shard keys."""

    return FleetPlan.from_keys(task, shard_keys, payloads)
