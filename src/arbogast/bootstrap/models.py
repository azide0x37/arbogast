"""Canonical subjects and profiles for the campaign-readiness theorem.

The records in this module contain data only.  In particular, a serialized
profile never contains an import path that is later executed.  Runtime objects
are retained privately by :meth:`ReadinessProfile.from_plan` solely so the
same process can perform the artifact-store and fresh-process probes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, cast

from arbogast.cert import FrozenMap, canonicalize, content_address, freeze_mapping
from arbogast.formats import (
    ENVIRONMENT_READINESS_RECEIPT_SCHEMA,
    ENVIRONMENT_SNAPSHOT_SCHEMA,
    READINESS_OBLIGATION_SCHEMA,
    READINESS_PROFILE_SCHEMA,
    RUNTIME_BINDING_SCHEMA,
    canonical_sha256,
)


class BootstrapError(ValueError):
    """Raised when a readiness subject or profile is malformed."""


class ReadinessScope(StrEnum):
    """The volatility boundary covered by one readiness theorem."""

    STATIC = "STATIC"
    PLAN = "PLAN"
    DISPATCH = "DISPATCH"


class ObligationStatus(StrEnum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    UNCHECKED = "UNCHECKED"


class ReadinessVerdict(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


READINESS_OBLIGATIONS: tuple[str, ...] = (
    "python.supported",
    "arbogast.identity-bound",
    "lock.consistent",
    "operation-registry.covers-plan",
    "capabilities.cover-plan",
    "verifier-registry.covers-plan",
    "executor.supports-shard-policies",
    "artifact-store.roundtrip",
    "fresh-process.fixture-replays",
)


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BootstrapError(f"{label} must be a non-blank string")
    return value


def _content_id(value: object, label: str) -> str:
    result = _nonblank(value, label)
    if not result.startswith("sha256:") or len(result) != 71:
        raise BootstrapError(f"{label} must be a canonical sha256 content address")
    try:
        int(result[7:], 16)
    except ValueError as error:
        raise BootstrapError(f"{label} must be a canonical sha256 content address") from error
    if result.lower() != result:
        raise BootstrapError(f"{label} must be lowercase")
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise BootstrapError(f"{label} must be an array of strings")
    items = tuple(_nonblank(item, f"{label} entry") for item in value)
    if items != tuple(sorted(set(items))):
        raise BootstrapError(f"{label} must be sorted and unique")
    return items


def _unique_strings(value: object, label: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise BootstrapError(f"{label} must be an array of strings")
    items = tuple(_nonblank(item, f"{label} entry") for item in value)
    if len(items) != len(set(items)):
        raise BootstrapError(f"{label} must contain unique strings")
    return items


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise BootstrapError(f"{label} must be a string-keyed object")
    return cast(Mapping[str, object], value)


def _strict_fields(
    value: Mapping[str, object],
    *,
    required: set[str],
    allowed: set[str] | None = None,
    label: str,
) -> None:
    permitted = required if allowed is None else allowed
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - permitted)
    if missing or unexpected:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if unexpected:
            parts.append(f"unknown {', '.join(unexpected)}")
        raise BootstrapError(f"{label} has {'; '.join(parts)}")


def _manifest_digest(value: Mapping[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "digest"}
    return f"sha256:{canonical_sha256(payload)}"


def _registry_binding_error(
    binding: RuntimeBinding,
    *,
    expected_requested: tuple[str, ...],
    entries_key: str,
) -> str | None:
    """Return why a registry binding is not a canonical fixed manifest."""

    wrapper = binding.manifest
    expected_wrapper_schema = {
        "operations": "arbogast.bootstrap.operation-registry-manifest/v1",
        "verifiers": "arbogast.bootstrap.verifier-registry-manifest/v1",
    }[entries_key]
    expected_nested_schema = {
        "operations": "arbogast.fleet.operation-registry-manifest.v1",
        "verifiers": "arbogast.cert.verifier-registry-manifest.v1",
    }[entries_key]
    expected_fields = {
        "schema",
        "requested_names",
        "interface_supported",
        "registered_names",
        "manifest",
        "manifest_digest",
        "missing",
        "uncertifiable",
        "registry_error",
    }
    if set(wrapper) != expected_fields or wrapper.get("schema") != expected_wrapper_schema:
        return "registry binding wrapper fields or schema are not canonical"
    try:
        requested = _strings(wrapper.get("requested_names"), "requested registry names")
        registered = _strings(wrapper.get("registered_names"), "registered registry names")
        missing = _strings(wrapper.get("missing"), "missing registry names")
        uncertifiable = _strings(wrapper.get("uncertifiable"), "uncertifiable registry names")
    except BootstrapError as error:
        return str(error)
    if requested != expected_requested:
        return "registry requested names differ from the readiness profile"
    if missing != tuple(sorted(set(requested) - set(registered))):
        return "registry missing names are not derived from requested/registered names"
    interface_supported = wrapper.get("interface_supported")
    if not isinstance(interface_supported, bool):
        return "registry interface_supported must be boolean"
    registry_error = wrapper.get("registry_error")
    if registry_error is not None:
        if not isinstance(registry_error, str) or not registry_error:
            return "registry_error must be a non-empty string or null"
        if wrapper.get("manifest") is not None or wrapper.get("manifest_digest") is not None:
            return "a failed registry probe cannot retain a manifest"
        return None
    if not interface_supported:
        return "an unsupported registry interface must carry registry_error"
    nested = wrapper.get("manifest")
    if not isinstance(nested, Mapping) or any(not isinstance(key, str) for key in nested):
        return "registry manifest must be an object"
    if set(nested) != {"schema", entries_key, "digest"}:
        return "registry manifest fields are not canonical"
    if nested.get("schema") != expected_nested_schema:
        return "registry manifest schema is not canonical"
    computed_digest = _manifest_digest(cast(Mapping[str, object], nested))
    if nested.get("digest") != computed_digest or wrapper.get("manifest_digest") != computed_digest:
        return "registry manifest digest does not match canonical contents"
    raw_entries = nested.get(entries_key)
    if isinstance(raw_entries, str) or not isinstance(raw_entries, Sequence):
        return "registry manifest entries must be an array"
    entries = tuple(raw_entries)
    if any(not isinstance(item, Mapping) for item in entries):
        return "registry manifest entries must be objects"
    names: list[str] = []
    derived_uncertifiable: list[str] = []
    for raw_entry in entries:
        entry = cast(Mapping[str, object], raw_entry)
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            return "registry manifest entry name is invalid"
        names.append(name)
        certifiable = entry.get("certifiable")
        if not isinstance(certifiable, bool):
            return "registry manifest certifiable flag is invalid"
        reason = entry.get("reason")
        if (certifiable and reason is not None) or (
            not certifiable and (not isinstance(reason, str) or not reason)
        ):
            return "registry manifest certifiability reason is invalid"
        implementation = entry.get("implementation")
        if not isinstance(implementation, Mapping):
            return "registry implementation manifest is invalid"
        if entry.get("implementation_digest") != f"sha256:{canonical_sha256(implementation)}":
            return "registry implementation digest does not match canonical contents"
        certificate_type = entry.get("certificate_type")
        if entries_key == "operations":
            expected_entry_fields = {
                "name",
                "contract",
                "contract_digest",
                "implementation",
                "implementation_digest",
                "certifiable",
                "reason",
            }
            contract = entry.get("contract")
            if not isinstance(contract, Mapping):
                return "operation contract is invalid"
            if set(contract) != {
                "schema",
                "required_methods",
                "optional_methods",
                "closure_verifiers",
            }:
                return "operation contract fields are not canonical"
            if contract.get("schema") != "arbogast.fleet.operation-contract.v1":
                return "operation contract schema is not canonical"
            required_methods = contract.get("required_methods")
            optional_methods = contract.get("optional_methods")
            closure_verifiers = contract.get("closure_verifiers")
            if (
                isinstance(required_methods, str)
                or not isinstance(required_methods, Sequence)
                or tuple(required_methods) != ("plan", "run", "reduce")
            ):
                return "operation required methods are not canonical"
            if isinstance(optional_methods, str) or not isinstance(optional_methods, Sequence):
                return "operation optional methods are malformed"
            optional_tuple = tuple(optional_methods)
            if any(not isinstance(item, str) for item in optional_tuple):
                return "operation optional methods are malformed"
            if optional_tuple != tuple(
                method for method in ("verify", "resume") if method in set(optional_tuple)
            ):
                return "operation optional methods are not canonical"
            if isinstance(closure_verifiers, str) or not isinstance(closure_verifiers, Sequence):
                return "operation closure verifiers are malformed"
            closure_tuple = tuple(closure_verifiers)
            if closure_tuple != tuple(sorted(set(closure_tuple))) or any(
                not isinstance(item, str) or not item for item in closure_tuple
            ):
                return "operation closure verifiers are not canonical"
        else:
            expected_entry_fields = {
                "name",
                "certificate_type",
                "contract_digest",
                "implementation",
                "implementation_digest",
                "certifiable",
                "reason",
            }
            if not isinstance(certificate_type, str) or not certificate_type:
                return "verifier certificate type is invalid"
            contract = {
                "schema": "arbogast.cert.verifier-contract.v1",
                "certificate_type": certificate_type,
            }
        if set(entry) != expected_entry_fields:
            return "registry manifest entry fields are not canonical"
        if entry.get("contract_digest") != f"sha256:{canonical_sha256(contract)}":
            return "registry contract digest does not match canonical contents"
        if not certifiable:
            derived_uncertifiable.append(name)
    canonical_names = tuple(names)
    if canonical_names != tuple(sorted(set(canonical_names))):
        return "registry manifest entry names are not sorted and unique"
    if canonical_names != tuple(sorted(set(requested) - set(missing))):
        return "registry manifest entries do not exactly cover bound requested names"
    if tuple(derived_uncertifiable) != uncertifiable:
        return "registry uncertifiable names are not derived from manifest entries"
    return None


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Exact identity of one file used by a readiness decision."""

    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _nonblank(self.path, "file path")
        _content_id(self.sha256, "file sha256")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise BootstrapError("file size must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    to_canonical = to_dict

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FileIdentity:
        _strict_fields(value, required={"path", "sha256", "size"}, label="file identity")
        path = _nonblank(value["path"], "file path")
        digest = _content_id(value["sha256"], "file sha256")
        size = value["size"]
        if isinstance(size, bool) or not isinstance(size, int):
            raise BootstrapError("file size must be an integer")
        return cls(path, digest, size)


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    """A content-addressed, non-executable description of one runtime input."""

    kind: str
    manifest: FrozenMap = field(default_factory=FrozenMap)

    schema_version: ClassVar[str] = RUNTIME_BINDING_SCHEMA

    def __post_init__(self) -> None:
        _nonblank(self.kind, "runtime binding kind")
        object.__setattr__(self, "manifest", freeze_mapping(self.manifest))

    @property
    def runtime_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "manifest": self.manifest,
        }

    def to_dict(self) -> dict[str, object]:
        result = cast(dict[str, object], canonicalize(self.to_canonical()))
        result["runtime_id"] = self.runtime_id
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RuntimeBinding:
        required = {"schema_version", "kind", "manifest", "runtime_id"}
        _strict_fields(value, required=required, label="runtime binding")
        if value["schema_version"] != cls.schema_version:
            raise BootstrapError("unsupported runtime-binding schema")
        binding = cls(
            kind=_nonblank(value["kind"], "runtime binding kind"),
            manifest=freeze_mapping(_mapping(value["manifest"], "runtime manifest")),
        )
        if _content_id(value["runtime_id"], "runtime_id") != binding.runtime_id:
            raise BootstrapError("runtime_id does not match canonical contents")
        return binding


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """Finite identity of the interpreter and installed Arbogast environment."""

    python_implementation: str
    python_version: str
    python_executable: str
    python_executable_identity: FileIdentity | None
    platform: str
    arbogast_version: str
    arbogast_location: str
    arbogast_tree_sha256: str
    project_root: str | None
    lockfiles: tuple[FileIdentity, ...]
    lock_consistent: bool | None
    lock_detail: str
    packages: FrozenMap
    backends: FrozenMap
    capabilities: tuple[str, ...]
    declared_capabilities: tuple[str, ...] = ()
    probed_capabilities: tuple[str, ...] = ()
    capture_options: FrozenMap = field(default_factory=FrozenMap)
    probe_errors: FrozenMap = field(default_factory=FrozenMap)

    schema_version: ClassVar[str] = ENVIRONMENT_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.python_implementation, "Python implementation"),
            (self.python_version, "Python version"),
            (self.python_executable, "Python executable"),
            (self.platform, "platform"),
            (self.arbogast_version, "Arbogast version"),
            (self.arbogast_location, "Arbogast location"),
            (self.lock_detail, "lock detail"),
        ):
            _nonblank(value, label)
        _content_id(self.arbogast_tree_sha256, "Arbogast tree hash")
        if self.project_root is not None:
            _nonblank(self.project_root, "project root")
        if self.python_executable_identity is not None and not isinstance(
            self.python_executable_identity, FileIdentity
        ):
            raise BootstrapError("python executable identity must be FileIdentity or null")
        object.__setattr__(self, "lockfiles", tuple(self.lockfiles))
        if any(not isinstance(item, FileIdentity) for item in self.lockfiles):
            raise BootstrapError("lockfiles must contain FileIdentity values")
        if tuple(item.path for item in self.lockfiles) != tuple(
            sorted({item.path for item in self.lockfiles})
        ):
            raise BootstrapError("lockfiles must be sorted by unique path")
        if self.lock_consistent is not None and not isinstance(self.lock_consistent, bool):
            raise BootstrapError("lock_consistent must be boolean or null")
        object.__setattr__(self, "packages", freeze_mapping(self.packages))
        object.__setattr__(self, "backends", freeze_mapping(self.backends))
        object.__setattr__(self, "capture_options", freeze_mapping(self.capture_options))
        object.__setattr__(self, "probe_errors", freeze_mapping(self.probe_errors))
        for name in ("capabilities", "declared_capabilities", "probed_capabilities"):
            capabilities = tuple(getattr(self, name))
            if capabilities != tuple(sorted(set(capabilities))) or any(
                not isinstance(item, str) or not item for item in capabilities
            ):
                raise BootstrapError(f"environment {name} must be sorted, unique strings")
            object.__setattr__(self, name, capabilities)
        if set(self.declared_capabilities) | set(self.probed_capabilities) != set(
            self.capabilities
        ):
            raise BootstrapError(
                "environment capabilities must be exactly the declared/probed union"
            )

    @property
    def environment_id(self) -> str:
        return content_address(self.to_canonical())

    @property
    def content_id(self) -> str:
        return self.environment_id

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "python_executable_identity": self.python_executable_identity,
            "platform": self.platform,
            "arbogast_version": self.arbogast_version,
            "arbogast_location": self.arbogast_location,
            "arbogast_tree_sha256": self.arbogast_tree_sha256,
            "project_root": self.project_root,
            "lockfiles": self.lockfiles,
            "lock_consistent": self.lock_consistent,
            "lock_detail": self.lock_detail,
            "packages": self.packages,
            "backends": self.backends,
            "capabilities": self.capabilities,
            "declared_capabilities": self.declared_capabilities,
            "probed_capabilities": self.probed_capabilities,
            "capture_options": self.capture_options,
            "probe_errors": self.probe_errors,
        }

    def to_dict(self) -> dict[str, object]:
        result = cast(dict[str, object], canonicalize(self.to_canonical()))
        result["environment_id"] = self.environment_id
        return result

    @classmethod
    def capture(
        cls,
        *,
        project_root: str | Path | None = None,
        package_hashes: bool = True,
        lockfile: bool = True,
        backends: bool = False,
        capabilities: Iterable[str] = (),
        probe_external: bool = False,
    ) -> EnvironmentSnapshot:
        """Capture through the fixed, non-extensible bootstrap probe set."""

        from .capture import capture_environment

        return capture_environment(
            project_root=project_root,
            package_hashes=package_hashes,
            lockfile=lockfile,
            backends=backends,
            capabilities=capabilities,
            probe_external=probe_external,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EnvironmentSnapshot:
        required = {
            "schema_version",
            "environment_id",
            "python_implementation",
            "python_version",
            "python_executable",
            "python_executable_identity",
            "platform",
            "arbogast_version",
            "arbogast_location",
            "arbogast_tree_sha256",
            "project_root",
            "lockfiles",
            "lock_consistent",
            "lock_detail",
            "packages",
            "backends",
            "capabilities",
            "declared_capabilities",
            "probed_capabilities",
            "capture_options",
            "probe_errors",
        }
        _strict_fields(value, required=required, label="environment snapshot")
        if value["schema_version"] != cls.schema_version:
            raise BootstrapError("unsupported environment-snapshot schema")
        raw_executable = value["python_executable_identity"]
        if raw_executable is not None and not isinstance(raw_executable, Mapping):
            raise BootstrapError("python_executable_identity must be an object or null")
        raw_lockfiles = value["lockfiles"]
        if isinstance(raw_lockfiles, str) or not isinstance(raw_lockfiles, Sequence):
            raise BootstrapError("lockfiles must be an array")
        if any(not isinstance(item, Mapping) for item in raw_lockfiles):
            raise BootstrapError("lockfile identities must be objects")
        raw_root = value["project_root"]
        raw_consistent = value["lock_consistent"]
        if raw_root is not None and not isinstance(raw_root, str):
            raise BootstrapError("project_root must be a string or null")
        if raw_consistent is not None and not isinstance(raw_consistent, bool):
            raise BootstrapError("lock_consistent must be boolean or null")
        snapshot = cls(
            python_implementation=_nonblank(
                value["python_implementation"], "Python implementation"
            ),
            python_version=_nonblank(value["python_version"], "Python version"),
            python_executable=_nonblank(value["python_executable"], "Python executable"),
            python_executable_identity=(
                None
                if raw_executable is None
                else FileIdentity.from_dict(cast(Mapping[str, object], raw_executable))
            ),
            platform=_nonblank(value["platform"], "platform"),
            arbogast_version=_nonblank(value["arbogast_version"], "Arbogast version"),
            arbogast_location=_nonblank(value["arbogast_location"], "Arbogast location"),
            arbogast_tree_sha256=_content_id(value["arbogast_tree_sha256"], "Arbogast tree hash"),
            project_root=raw_root,
            lockfiles=tuple(
                FileIdentity.from_dict(cast(Mapping[str, object], item)) for item in raw_lockfiles
            ),
            lock_consistent=raw_consistent,
            lock_detail=_nonblank(value["lock_detail"], "lock detail"),
            packages=freeze_mapping(_mapping(value["packages"], "packages")),
            backends=freeze_mapping(_mapping(value["backends"], "backends")),
            capabilities=_strings(value["capabilities"], "capabilities"),
            declared_capabilities=_strings(value["declared_capabilities"], "declared_capabilities"),
            probed_capabilities=_strings(value["probed_capabilities"], "probed_capabilities"),
            capture_options=freeze_mapping(_mapping(value["capture_options"], "capture options")),
            probe_errors=freeze_mapping(_mapping(value["probe_errors"], "probe errors")),
        )
        if _content_id(value["environment_id"], "environment_id") != snapshot.environment_id:
            raise BootstrapError("environment_id does not match canonical contents")
        return snapshot


@dataclass(frozen=True, slots=True)
class ReadinessProfile:
    """Complete obligation set and exact ``C,P,G,V,X,A`` runtime bindings."""

    scope: ReadinessScope
    campaign_id: str
    plan_id: str
    task_ids: tuple[str, ...]
    required_operations: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    required_backends: FrozenMap
    optional_backends: FrozenMap
    required_verifiers: tuple[str, ...]
    optional_verifiers: tuple[str, ...]
    shard_policies: tuple[str, ...]
    operation_registry: RuntimeBinding
    verifier_registry: RuntimeBinding
    executor: RuntimeBinding
    artifact_store: RuntimeBinding
    expected_arbogast_version: str
    expected_arbogast_tree_sha256: str
    minimum_python: tuple[int, int]
    maximum_python_exclusive: tuple[int, int]
    require_lock_consistency: bool
    require_persistent_custody: bool
    required_obligation_ids: tuple[str, ...] = READINESS_OBLIGATIONS
    optional_obligation_ids: tuple[str, ...] = ()
    _runtime_artifact_store: object | None = field(
        default=None, repr=False, compare=False, hash=False
    )

    schema_version: ClassVar[str] = READINESS_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.scope, str):
            object.__setattr__(self, "scope", ReadinessScope(self.scope))
        for value, label in (
            (self.campaign_id, "campaign_id"),
            (self.plan_id, "plan_id"),
        ):
            _content_id(value, label)
        for name in (
            "task_ids",
            "required_operations",
            "required_capabilities",
            "optional_capabilities",
            "required_verifiers",
            "optional_verifiers",
            "shard_policies",
        ):
            items = tuple(getattr(self, name))
            if items != tuple(sorted(set(items))) or any(
                not isinstance(item, str) or not item for item in items
            ):
                raise BootstrapError(f"{name} must be sorted, unique strings")
            object.__setattr__(self, name, items)
        if any(not item.startswith("sha256:") for item in self.task_ids):
            raise BootstrapError("task_ids must contain canonical content addresses")
        object.__setattr__(self, "required_backends", freeze_mapping(self.required_backends))
        object.__setattr__(self, "optional_backends", freeze_mapping(self.optional_backends))
        if set(self.required_capabilities) & set(self.optional_capabilities):
            raise BootstrapError("a capability cannot be both required and optional")
        if set(self.required_backends) & set(self.optional_backends):
            raise BootstrapError("a backend cannot be both required and optional")
        if set(self.required_verifiers) & set(self.optional_verifiers):
            raise BootstrapError("a verifier cannot be both required and optional")
        for binding, kind in (
            (self.operation_registry, "operation-registry"),
            (self.verifier_registry, "verifier-registry"),
            (self.executor, "executor"),
            (self.artifact_store, "artifact-store"),
        ):
            if not isinstance(binding, RuntimeBinding) or binding.kind != kind:
                raise BootstrapError(f"profile {kind} binding is invalid")
        operation_binding_error = _registry_binding_error(
            self.operation_registry,
            expected_requested=self.required_operations,
            entries_key="operations",
        )
        if operation_binding_error is not None:
            raise BootstrapError(
                f"operation registry binding is invalid: {operation_binding_error}"
            )
        expected_verifiers = tuple(
            sorted(set(self.required_verifiers) | set(self.optional_verifiers))
        )
        verifier_binding_error = _registry_binding_error(
            self.verifier_registry,
            expected_requested=expected_verifiers,
            entries_key="verifiers",
        )
        if verifier_binding_error is not None:
            raise BootstrapError(f"verifier registry binding is invalid: {verifier_binding_error}")
        _nonblank(self.expected_arbogast_version, "expected Arbogast version")
        _content_id(self.expected_arbogast_tree_sha256, "expected Arbogast tree hash")
        for version, label in (
            (self.minimum_python, "minimum Python"),
            (self.maximum_python_exclusive, "maximum Python"),
        ):
            if (
                not isinstance(version, tuple)
                or len(version) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in version)
            ):
                raise BootstrapError(f"{label} must be a two-integer tuple")
        if self.minimum_python >= self.maximum_python_exclusive:
            raise BootstrapError("Python support interval must be nonempty")
        if not isinstance(self.require_lock_consistency, bool):
            raise BootstrapError("require_lock_consistency must be boolean")
        if self.scope in {ReadinessScope.PLAN, ReadinessScope.DISPATCH} and not (
            self.require_lock_consistency
        ):
            raise BootstrapError("PLAN and DISPATCH readiness require lock consistency")
        if not isinstance(self.require_persistent_custody, bool):
            raise BootstrapError("require_persistent_custody must be boolean")
        required_obligations = tuple(self.required_obligation_ids)
        optional_obligations = tuple(self.optional_obligation_ids)
        if required_obligations != tuple(
            item for item in READINESS_OBLIGATIONS if item in set(required_obligations)
        ):
            raise BootstrapError("required obligation IDs must use canonical v1 order")
        if optional_obligations != tuple(
            item for item in READINESS_OBLIGATIONS if item in set(optional_obligations)
        ):
            raise BootstrapError("optional obligation IDs must use canonical v1 order")
        if set(required_obligations) & set(optional_obligations):
            raise BootstrapError("an obligation cannot be both required and optional")
        if set(required_obligations) | set(optional_obligations) != set(READINESS_OBLIGATIONS):
            raise BootstrapError("readiness profile must classify every v1 obligation")
        if self.scope in {ReadinessScope.PLAN, ReadinessScope.DISPATCH} and optional_obligations:
            raise BootstrapError("PLAN and DISPATCH readiness require every formula obligation")
        object.__setattr__(self, "required_obligation_ids", required_obligations)
        object.__setattr__(self, "optional_obligation_ids", optional_obligations)

    @property
    def obligation_ids(self) -> tuple[str, ...]:
        """Return all obligations in canonical theorem order."""

        declared = set(self.required_obligation_ids) | set(self.optional_obligation_ids)
        return tuple(item for item in READINESS_OBLIGATIONS if item in declared)

    @property
    def profile_id(self) -> str:
        return content_address(self.to_canonical())

    @property
    def content_id(self) -> str:
        return self.profile_id

    @property
    def bindings(self) -> dict[str, str]:
        return {
            "C": self.campaign_id,
            "P": self.plan_id,
            "G": self.operation_registry.runtime_id,
            "V": self.verifier_registry.runtime_id,
            "X": self.executor.runtime_id,
            "A": self.artifact_store.runtime_id,
        }

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope.value,
            "campaign_id": self.campaign_id,
            "plan_id": self.plan_id,
            "task_ids": self.task_ids,
            "required_operations": self.required_operations,
            "required_capabilities": self.required_capabilities,
            "optional_capabilities": self.optional_capabilities,
            "required_backends": self.required_backends,
            "optional_backends": self.optional_backends,
            "required_verifiers": self.required_verifiers,
            "optional_verifiers": self.optional_verifiers,
            "shard_policies": self.shard_policies,
            "operation_registry": self.operation_registry.to_dict(),
            "verifier_registry": self.verifier_registry.to_dict(),
            "executor": self.executor.to_dict(),
            "artifact_store": self.artifact_store.to_dict(),
            "expected_arbogast_version": self.expected_arbogast_version,
            "expected_arbogast_tree_sha256": self.expected_arbogast_tree_sha256,
            "minimum_python": self.minimum_python,
            "maximum_python_exclusive": self.maximum_python_exclusive,
            "require_lock_consistency": self.require_lock_consistency,
            "require_persistent_custody": self.require_persistent_custody,
            "required_obligation_ids": self.required_obligation_ids,
            "optional_obligation_ids": self.optional_obligation_ids,
        }

    def to_dict(self) -> dict[str, object]:
        result = cast(dict[str, object], canonicalize(self.to_canonical()))
        result["profile_id"] = self.profile_id
        return result

    @classmethod
    def from_plan(
        cls,
        campaign: object,
        plan: object,
        operation_registry: object,
        verifier_registry: object,
        executor: object,
        *,
        required_verifiers: Iterable[str] = (),
        optional_capabilities: Iterable[str] = (),
        optional_backends: Mapping[str, object] | None = None,
        optional_verifiers: Iterable[str] = (),
        optional_obligations: Iterable[str] = (),
        expected_arbogast_version: str | None = None,
        expected_arbogast_tree_sha256: str | None = None,
        require_lock_consistency: bool = True,
        require_persistent_custody: bool | None = None,
        scope: ReadinessScope = ReadinessScope.PLAN,
    ) -> ReadinessProfile:
        """Construct a profile from already-trusted live runtime objects.

        The function inspects only fixed attributes and methods.  It never
        resolves an import path from campaign or plan data.
        """

        from .runtime import profile_from_plan

        return profile_from_plan(
            cls,
            campaign,
            plan,
            operation_registry,
            verifier_registry,
            executor,
            required_verifiers=required_verifiers,
            optional_capabilities=optional_capabilities,
            optional_backends=optional_backends,
            optional_verifiers=optional_verifiers,
            optional_obligations=optional_obligations,
            expected_arbogast_version=expected_arbogast_version,
            expected_arbogast_tree_sha256=expected_arbogast_tree_sha256,
            require_lock_consistency=require_lock_consistency,
            require_persistent_custody=require_persistent_custody,
            scope=scope,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReadinessProfile:
        required = {
            "schema_version",
            "profile_id",
            "scope",
            "campaign_id",
            "plan_id",
            "task_ids",
            "required_operations",
            "required_capabilities",
            "optional_capabilities",
            "required_backends",
            "optional_backends",
            "required_verifiers",
            "optional_verifiers",
            "shard_policies",
            "operation_registry",
            "verifier_registry",
            "executor",
            "artifact_store",
            "expected_arbogast_version",
            "expected_arbogast_tree_sha256",
            "minimum_python",
            "maximum_python_exclusive",
            "require_lock_consistency",
            "require_persistent_custody",
            "required_obligation_ids",
            "optional_obligation_ids",
        }
        _strict_fields(value, required=required, label="readiness profile")
        if value["schema_version"] != cls.schema_version:
            raise BootstrapError("unsupported readiness-profile schema")
        bindings: dict[str, RuntimeBinding] = {}
        for name in ("operation_registry", "verifier_registry", "executor", "artifact_store"):
            raw = value[name]
            if not isinstance(raw, Mapping):
                raise BootstrapError(f"{name} must be an object")
            bindings[name] = RuntimeBinding.from_dict(cast(Mapping[str, object], raw))
        minimum = value["minimum_python"]
        maximum = value["maximum_python_exclusive"]
        if (
            isinstance(minimum, str)
            or not isinstance(minimum, Sequence)
            or isinstance(maximum, str)
            or not isinstance(maximum, Sequence)
        ):
            raise BootstrapError("Python version bounds must be arrays")
        if any(
            isinstance(item, bool) or not isinstance(item, int) for item in (*minimum, *maximum)
        ):
            raise BootstrapError("Python version bounds must contain integers")
        raw_lock = value["require_lock_consistency"]
        raw_custody = value["require_persistent_custody"]
        if not isinstance(raw_lock, bool):
            raise BootstrapError("require_lock_consistency must be boolean")
        if not isinstance(raw_custody, bool):
            raise BootstrapError("require_persistent_custody must be boolean")
        profile = cls(
            scope=ReadinessScope(_nonblank(value["scope"], "readiness scope")),
            campaign_id=_content_id(value["campaign_id"], "campaign_id"),
            plan_id=_content_id(value["plan_id"], "plan_id"),
            task_ids=_strings(value["task_ids"], "task_ids"),
            required_operations=_strings(value["required_operations"], "required_operations"),
            required_capabilities=_strings(value["required_capabilities"], "required_capabilities"),
            optional_capabilities=_strings(value["optional_capabilities"], "optional_capabilities"),
            required_backends=freeze_mapping(
                _mapping(value["required_backends"], "required_backends")
            ),
            optional_backends=freeze_mapping(
                _mapping(value["optional_backends"], "optional_backends")
            ),
            required_verifiers=_strings(value["required_verifiers"], "required_verifiers"),
            optional_verifiers=_strings(value["optional_verifiers"], "optional_verifiers"),
            shard_policies=_strings(value["shard_policies"], "shard_policies"),
            operation_registry=bindings["operation_registry"],
            verifier_registry=bindings["verifier_registry"],
            executor=bindings["executor"],
            artifact_store=bindings["artifact_store"],
            expected_arbogast_version=_nonblank(
                value["expected_arbogast_version"], "expected Arbogast version"
            ),
            expected_arbogast_tree_sha256=_content_id(
                value["expected_arbogast_tree_sha256"], "expected Arbogast tree hash"
            ),
            minimum_python=tuple(minimum),
            maximum_python_exclusive=tuple(maximum),
            require_lock_consistency=raw_lock,
            require_persistent_custody=raw_custody,
            required_obligation_ids=_unique_strings(
                value["required_obligation_ids"], "required_obligation_ids"
            ),
            optional_obligation_ids=_unique_strings(
                value["optional_obligation_ids"], "optional_obligation_ids"
            ),
        )
        if _content_id(value["profile_id"], "profile_id") != profile.profile_id:
            raise BootstrapError("profile_id does not match canonical contents")
        return profile


@dataclass(frozen=True, slots=True)
class ReadinessObligation:
    id: str
    required: bool
    status: ObligationStatus
    detail: str
    evidence: FrozenMap = field(default_factory=FrozenMap)

    schema_version: ClassVar[str] = READINESS_OBLIGATION_SCHEMA

    def __post_init__(self) -> None:
        _nonblank(self.id, "obligation id")
        if not isinstance(self.required, bool):
            raise BootstrapError("obligation required must be boolean")
        if isinstance(self.status, str):
            object.__setattr__(self, "status", ObligationStatus(self.status))
        _nonblank(self.detail, "obligation detail")
        object.__setattr__(self, "evidence", freeze_mapping(self.evidence))

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            canonicalize(
                {
                    "schema_version": self.schema_version,
                    "id": self.id,
                    "required": self.required,
                    "status": self.status.value,
                    "detail": self.detail,
                    "evidence": self.evidence,
                }
            ),
        )

    to_canonical = to_dict

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReadinessObligation:
        required = {"schema_version", "id", "required", "status", "detail", "evidence"}
        _strict_fields(value, required=required, label="readiness obligation")
        if value["schema_version"] != cls.schema_version:
            raise BootstrapError("unsupported readiness-obligation schema")
        raw_required = value["required"]
        if not isinstance(raw_required, bool):
            raise BootstrapError("obligation required must be boolean")
        return cls(
            id=_nonblank(value["id"], "obligation id"),
            required=raw_required,
            status=ObligationStatus(_nonblank(value["status"], "obligation status")),
            detail=_nonblank(value["detail"], "obligation detail"),
            evidence=freeze_mapping(_mapping(value["evidence"], "obligation evidence")),
        )


@dataclass(frozen=True, slots=True)
class ReadinessReceipt:
    """Strict receipt nested inside the central verification certificate."""

    environment: EnvironmentSnapshot
    profile: ReadinessProfile
    subject: FrozenMap
    verdict: ReadinessVerdict
    obligations: tuple[ReadinessObligation, ...]

    schema_version: ClassVar[str] = ENVIRONMENT_READINESS_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.environment, EnvironmentSnapshot):
            raise BootstrapError("readiness receipt environment is invalid")
        if not isinstance(self.profile, ReadinessProfile):
            raise BootstrapError("readiness receipt profile is invalid")
        object.__setattr__(self, "subject", freeze_mapping(self.subject))
        if isinstance(self.verdict, str):
            object.__setattr__(self, "verdict", ReadinessVerdict(self.verdict))
        object.__setattr__(self, "obligations", tuple(self.obligations))
        ids = tuple(item.id for item in self.obligations)
        if ids != self.profile.obligation_ids:
            raise BootstrapError("readiness receipt does not cover the profile obligations exactly")
        if any(not isinstance(item, ReadinessObligation) for item in self.obligations):
            raise BootstrapError("readiness receipt obligations are invalid")
        expected_subject = {
            "E": self.environment.environment_id,
            **self.profile.bindings,
            "R": self.profile.profile_id,
        }
        if self.subject.to_dict() != expected_subject:
            raise BootstrapError("readiness subject does not bind exact E,C,P,G,V,X,A,R identities")
        required = set(self.profile.required_obligation_ids)
        if any(item.required != (item.id in required) for item in self.obligations):
            raise BootstrapError("obligation required flags disagree with the readiness profile")
        if self.verdict is not verdict_for(self.obligations):
            raise BootstrapError("readiness verdict does not match obligation statuses")

    @property
    def receipt_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "environment": self.environment.to_dict(),
            "profile": self.profile.to_dict(),
            "subject": self.subject,
            "verdict": self.verdict.value,
            "obligations": tuple(item.to_dict() for item in self.obligations),
        }

    def to_dict(self) -> dict[str, object]:
        result = cast(dict[str, object], canonicalize(self.to_canonical()))
        result["receipt_id"] = self.receipt_id
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReadinessReceipt:
        required = {
            "schema_version",
            "receipt_id",
            "environment",
            "profile",
            "subject",
            "verdict",
            "obligations",
        }
        _strict_fields(value, required=required, label="readiness receipt")
        if value["schema_version"] != cls.schema_version:
            raise BootstrapError("unsupported readiness-receipt schema")
        raw_environment = _mapping(value["environment"], "receipt environment")
        raw_profile = _mapping(value["profile"], "receipt profile")
        raw_obligations = value["obligations"]
        if isinstance(raw_obligations, str) or not isinstance(raw_obligations, Sequence):
            raise BootstrapError("receipt obligations must be an array")
        if any(not isinstance(item, Mapping) for item in raw_obligations):
            raise BootstrapError("receipt obligations must be objects")
        receipt = cls(
            environment=EnvironmentSnapshot.from_dict(raw_environment),
            profile=ReadinessProfile.from_dict(raw_profile),
            subject=freeze_mapping(_mapping(value["subject"], "readiness subject")),
            verdict=ReadinessVerdict(_nonblank(value["verdict"], "readiness verdict")),
            obligations=tuple(
                ReadinessObligation.from_dict(cast(Mapping[str, object], item))
                for item in raw_obligations
            ),
        )
        if _content_id(value["receipt_id"], "receipt_id") != receipt.receipt_id:
            raise BootstrapError("receipt_id does not match canonical contents")
        return receipt


def verdict_for(obligations: Iterable[ReadinessObligation]) -> ReadinessVerdict:
    records = tuple(obligations)
    statuses = {item.status for item in records if item.required}
    if ObligationStatus.UNSATISFIED in statuses:
        return ReadinessVerdict.BLOCKED
    if ObligationStatus.UNKNOWN in statuses:
        return ReadinessVerdict.UNKNOWN
    if ObligationStatus.UNSUPPORTED in statuses:
        return ReadinessVerdict.UNSUPPORTED
    if ObligationStatus.UNCHECKED in statuses:
        return ReadinessVerdict.PARTIAL
    if statuses <= {ObligationStatus.SATISFIED}:
        return ReadinessVerdict.READY
    raise BootstrapError("cannot classify an empty or malformed obligation set")


__all__ = [
    "READINESS_OBLIGATIONS",
    "BootstrapError",
    "EnvironmentSnapshot",
    "FileIdentity",
    "ObligationStatus",
    "ReadinessObligation",
    "ReadinessProfile",
    "ReadinessReceipt",
    "ReadinessScope",
    "ReadinessVerdict",
    "RuntimeBinding",
    "verdict_for",
]
