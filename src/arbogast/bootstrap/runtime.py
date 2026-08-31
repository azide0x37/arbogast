"""Fixed runtime projections used by readiness profiles.

These helpers inspect objects that the caller has already injected as trusted
runtime dependencies.  Persisted names are never converted into callables or
imported modules here.
"""

from __future__ import annotations

import hashlib
import inspect
import marshal
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import CodeType
from typing import TypeVar, cast

import arbogast
from arbogast import __version__
from arbogast.cert import FrozenMap, canonicalize, content_address, freeze_mapping

from .models import (
    READINESS_OBLIGATIONS,
    BootstrapError,
    ReadinessProfile,
    ReadinessScope,
    RuntimeBinding,
    _registry_binding_error,
)

ProfileT = TypeVar("ProfileT", bound=ReadinessProfile)


def _current_arbogast_tree_sha256() -> str:
    from .capture import _package_tree_identity

    package_root = Path(arbogast.__file__).resolve().parent
    return _package_tree_identity(package_root)


def _class_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _source_identity(value: object) -> dict[str, object]:
    """Describe loaded code without importing or executing a selected module."""

    result: dict[str, object] = {"class": _class_name(value)}
    try:
        source = inspect.getsourcefile(type(value))
    except (OSError, TypeError):
        source = None
    if source is None:
        result.update({"source_path": None, "source_sha256": None})
        return result
    path = Path(source).resolve()
    try:
        payload = path.read_bytes()
    except OSError as error:
        result.update(
            {
                "source_path": str(path),
                "source_sha256": None,
                "source_error": f"{type(error).__name__}: {error}",
            }
        )
    else:
        result.update(
            {
                "source_path": str(path),
                "source_sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "source_size": len(payload),
            }
        )
    return result


def _stable_code(code: CodeType) -> CodeType:
    constants = tuple(
        _stable_code(item) if isinstance(item, CodeType) else item for item in code.co_consts
    )
    return code.replace(co_consts=constants, co_filename="", co_firstlineno=1)


def _callable_identity(value: object) -> dict[str, object]:
    """Describe clock semantics without invoking or importing the callable."""

    target = value.__func__ if inspect.ismethod(value) else value
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    code = getattr(target, "__code__", None)
    result: dict[str, object] = {
        "module": module if isinstance(module, str) else None,
        "qualname": qualname if isinstance(qualname, str) else None,
        "code_sha256": None,
        "bound_values_digest": None,
        "identifiable": False,
        "reason": None,
    }
    if not isinstance(module, str) or not module or not isinstance(qualname, str) or not qualname:
        result["reason"] = "clock has no stable module and qualified name"
        return result
    if not isinstance(code, CodeType):
        result["reason"] = "clock has no inspectable Python code object"
        return result
    result["code_sha256"] = (
        "sha256:" + hashlib.sha256(marshal.dumps(_stable_code(code))).hexdigest()
    )
    bound_values: dict[str, object] = {}
    defaults = getattr(target, "__defaults__", None)
    if defaults:
        bound_values["defaults"] = defaults
    keyword_defaults = getattr(target, "__kwdefaults__", None)
    if keyword_defaults:
        bound_values["keyword_defaults"] = keyword_defaults
    closure = getattr(target, "__closure__", None)
    if closure:
        try:
            bound_values["closure"] = tuple(cell.cell_contents for cell in closure)
        except ValueError:
            result["reason"] = "clock contains an empty closure cell"
            return result
    try:
        result["bound_values_digest"] = content_address(canonicalize(bound_values))
    except (TypeError, ValueError) as error:
        result["reason"] = f"clock bound values are not canonical: {error}"
        return result
    result["identifiable"] = True
    return result


def _canonical_projection(value: object, label: str) -> tuple[object | None, str | None]:
    if value is None:
        return None, None
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        return None, f"{label} does not expose a fixed to_dict projection"
    try:
        projected = canonicalize(cast(Callable[[], object], to_dict)())
    except Exception as error:
        return None, f"{label} projection failed: {type(error).__name__}: {error}"
    if not isinstance(projected, Mapping):
        return None, f"{label} projection is not an object"
    return projected, None


def _registry_binding(
    kind: str,
    wrapper: dict[str, object],
    *,
    requested: tuple[str, ...],
    entries_key: str,
) -> RuntimeBinding:
    """Normalize a malformed third-party manifest into an UNKNOWN probe."""

    binding = RuntimeBinding(kind, freeze_mapping(wrapper))
    error = _registry_binding_error(
        binding,
        expected_requested=requested,
        entries_key=entries_key,
    )
    if error is None or wrapper.get("registry_error") is not None:
        return binding
    wrapper.update(
        {
            "manifest": None,
            "manifest_digest": None,
            "uncertifiable": (),
            "registry_error": f"malformed readiness manifest: {error}",
        }
    )
    return RuntimeBinding(kind, freeze_mapping(wrapper))


def operation_registry_binding(
    registry: object,
    required_operations: Iterable[str],
) -> RuntimeBinding:
    names_method = getattr(registry, "names", None)
    manifest_method = getattr(registry, "readiness_manifest", None)
    registered: tuple[str, ...] = ()
    registry_error: str | None = None
    manifest: object | None = None
    requested = tuple(sorted(set(required_operations)))
    interface_supported = callable(names_method) and callable(manifest_method)
    if not interface_supported:
        registry_error = "runtime does not expose fixed names/readiness_manifest methods"
    else:
        try:
            raw_names = cast(Callable[[], Iterable[str]], names_method)()
            registered = tuple(sorted(set(raw_names)))
        except Exception as error:  # diagnostic boundary: report, never promote
            registry_error = f"{type(error).__name__}: {error}"
        if registry_error is None:
            try:
                manifest = cast(Callable[[Iterable[str]], object], manifest_method)(
                    tuple(name for name in requested if name in set(registered))
                )
            except Exception as error:
                registry_error = f"{type(error).__name__}: {error}"
    if manifest is not None and not isinstance(manifest, Mapping):
        registry_error = "readiness_manifest did not return an object"
        manifest = None
    entries: tuple[object, ...] = ()
    if isinstance(manifest, Mapping):
        raw_entries = manifest.get("operations", ())
        if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, str):
            entries = tuple(raw_entries)
        else:
            registry_error = "operation manifest entries are malformed"
            manifest = None
    uncertifiable = tuple(
        cast(Mapping[str, object], entry).get("name")
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("certifiable") is not True
    )
    missing = tuple(sorted(set(requested) - set(registered)))
    return _registry_binding(
        "operation-registry",
        {
            "schema": "arbogast.bootstrap.operation-registry-manifest/v1",
            "requested_names": requested,
            "interface_supported": interface_supported,
            "registered_names": registered,
            "manifest": manifest,
            "manifest_digest": (manifest.get("digest") if isinstance(manifest, Mapping) else None),
            "missing": missing,
            "uncertifiable": uncertifiable,
            "registry_error": registry_error,
        },
        requested=requested,
        entries_key="operations",
    )


def verifier_registry_binding(
    registry: object,
    required_verifiers: Iterable[str],
) -> RuntimeBinding:
    names_method = getattr(registry, "names", None)
    manifest_method = getattr(registry, "readiness_manifest", None)
    registry_error: str | None = None
    registered: tuple[str, ...] = ()
    requested = tuple(sorted(set(required_verifiers)))
    manifest: object | None = None
    interface_supported = callable(names_method) and callable(manifest_method)
    if not interface_supported:
        registry_error = "runtime does not expose fixed names/readiness_manifest methods"
    else:
        try:
            registered = tuple(sorted(set(cast(Callable[[], Iterable[str]], names_method)())))
        except Exception as error:
            registry_error = f"{type(error).__name__}: {error}"
    if registry_error is None:
        try:
            manifest = cast(Callable[..., object], manifest_method)(
                tuple(name for name in requested if name in set(registered)),
                load_builtins=False,
            )
        except Exception as error:
            registry_error = f"{type(error).__name__}: {error}"
    if manifest is not None and not isinstance(manifest, Mapping):
        registry_error = "readiness_manifest did not return an object"
        manifest = None
    entries: tuple[object, ...] = ()
    if isinstance(manifest, Mapping):
        raw_entries = manifest.get("verifiers", ())
        if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, str):
            entries = tuple(raw_entries)
        else:
            registry_error = "verifier manifest entries are malformed"
            manifest = None
    uncertifiable = tuple(
        cast(Mapping[str, object], entry).get("name")
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("certifiable") is not True
    )
    missing = tuple(sorted(set(requested) - set(registered)))
    return _registry_binding(
        "verifier-registry",
        {
            "schema": "arbogast.bootstrap.verifier-registry-manifest/v1",
            "requested_names": requested,
            "interface_supported": interface_supported,
            "registered_names": registered,
            "manifest": manifest,
            "manifest_digest": (manifest.get("digest") if isinstance(manifest, Mapping) else None),
            "missing": missing,
            "uncertifiable": uncertifiable,
            "registry_error": registry_error,
        },
        requested=requested,
        entries_key="verifiers",
    )


def executor_binding(executor: object, shard_policies: Iterable[str]) -> RuntimeBinding:
    methods = {
        name: callable(getattr(executor, name, None))
        for name in (
            "plan",
            "run",
            "reduce",
            "execute",
            "execute_checkpointed",
            "supports_checkpoint_resume",
        )
    }
    checkpoint_support: bool | None
    checkpoint_error: str | None = None
    supports = getattr(executor, "supports_checkpoint_resume", None)
    if not callable(supports):
        checkpoint_support = None
    else:
        try:
            checkpoint_support = bool(supports())
        except Exception as error:
            checkpoint_support = None
            checkpoint_error = f"{type(error).__name__}: {error}"
    workers, workers_error = _canonical_projection(getattr(executor, "workers", None), "workers")
    retry_policy, retry_error = _canonical_projection(
        getattr(executor, "retry_policy", None), "retry policy"
    )
    custody = getattr(executor, "custody", None)
    custody_identity = None if custody is None else _source_identity(custody)
    clock = getattr(executor, "_clock", None)
    clock_identity = (
        {
            "identifiable": True,
            "kind": "not-applicable",
            "reason": None,
        }
        if clock is None
        else {"kind": "callable", **_callable_identity(clock)}
    )
    binding_errors = tuple(item for item in (workers_error, retry_error) if item is not None)
    manifest = {
        "schema": "arbogast.bootstrap.executor-manifest/v1",
        "interface_supported": all(methods[name] for name in ("plan", "run", "reduce", "execute")),
        "identity": _source_identity(executor),
        "methods": methods,
        "max_workers": getattr(executor, "max_workers", None),
        "workers": workers,
        "retry_policy": retry_policy,
        "custody": custody_identity,
        "clock": clock_identity,
        "binding_errors": binding_errors,
        "checkpoint_resume": checkpoint_support,
        "checkpoint_error": checkpoint_error,
        "required_shard_policies": tuple(sorted(set(shard_policies))),
    }
    return RuntimeBinding("executor", freeze_mapping(manifest))


def artifact_store_binding(
    store: object | None,
    *,
    ephemeral: bool | None = None,
) -> RuntimeBinding:
    if store is None:
        return RuntimeBinding(
            "artifact-store",
            freeze_mapping(
                {
                    "schema": "arbogast.bootstrap.artifact-store-manifest/v1",
                    "available": False,
                    "identity": None,
                    "root": None,
                    "ephemeral": ephemeral,
                    "methods": {},
                }
            ),
        )
    root = getattr(store, "root", None)
    manifest = {
        "schema": "arbogast.bootstrap.artifact-store-manifest/v1",
        "available": True,
        "identity": _source_identity(store),
        "root": str(Path(root).resolve()) if root is not None else None,
        "ephemeral": ephemeral,
        "methods": {
            name: callable(getattr(store, name, None))
            for name in ("put_bytes", "get_bytes", "put_json", "get_json")
        },
    }
    return RuntimeBinding("artifact-store", freeze_mapping(manifest))


def _stable_id(value: object, attributes: Sequence[str], label: str) -> str:
    for attribute in attributes:
        candidate = getattr(value, attribute, None)
        if isinstance(candidate, str) and candidate.startswith("sha256:"):
            return candidate
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return content_address(to_dict())
        except Exception as error:
            raise BootstrapError(f"cannot bind {label}: {error}") from error
    raise BootstrapError(f"{label} does not expose a canonical content identity")


def _tasks(plan: object) -> tuple[object, ...]:
    tasks = getattr(plan, "tasks", None)
    if tasks is None:
        recommendations = getattr(plan, "recommendations", None)
        if recommendations is not None:
            tasks = tuple(getattr(item, "task", None) for item in recommendations)
    if tasks is None or isinstance(tasks, str):
        raise BootstrapError("plan does not expose a finite task roster")
    try:
        result = tuple(tasks)
    except TypeError as error:
        raise BootstrapError("plan task roster is not iterable") from error
    if any(item is None for item in result):
        raise BootstrapError("plan task roster contains an invalid task")
    return result


def _task_operation(task: object) -> str:
    fleet_task = getattr(task, "task", task)
    operation = getattr(fleet_task, "operation", None)
    if not isinstance(operation, str) or not operation:
        raise BootstrapError("plan task does not name an operation")
    return operation


def _task_id(task: object) -> str:
    return _stable_id(task, ("campaign_task_id", "task_id", "content_id"), "campaign task")


def _requirements(tasks: Sequence[object]) -> tuple[tuple[str, ...], FrozenMap]:
    capabilities: set[str] = set()
    backends: dict[str, dict[str, object]] = {}
    for campaign_task in tasks:
        raw_caps = getattr(campaign_task, "capability_requirements", ())
        capabilities.update(raw_caps)
        fleet_task = getattr(campaign_task, "task", campaign_task)
        backend = getattr(fleet_task, "backend", None)
        if backend is None:
            continue
        name = getattr(backend, "name", None)
        if not isinstance(name, str) or not name:
            raise BootstrapError("task backend has no canonical name")
        backend_caps = tuple(getattr(backend, "capabilities", ()))
        capabilities.update(backend_caps)
        version = getattr(backend, "version", None)
        current = backends.get(name)
        record = {
            "capabilities": tuple(sorted(set(backend_caps))),
            "version": version,
        }
        if current is None:
            backends[name] = record
        elif current != record:
            versions = tuple(sorted({str(current["version"]), str(version)}))
            merged_caps = tuple(
                sorted(set(cast(Sequence[str], current["capabilities"])) | set(backend_caps))
            )
            backends[name] = {
                "capabilities": merged_caps,
                "version": None,
                "conflicting_versions": versions,
            }
    return tuple(sorted(capabilities)), freeze_mapping(backends)


def _strategy_map(campaign: object) -> dict[str, object]:
    """Return the live campaign's fixed strategy descriptors by name."""

    raw = getattr(campaign, "strategies", None)
    if raw is None:
        spec = getattr(campaign, "spec", None)
        raw = getattr(spec, "strategies", ())
    if raw is None:
        raw = ()
    if isinstance(raw, str):
        raise BootstrapError("campaign strategy roster is malformed")
    try:
        strategies = tuple(cast(Iterable[object], raw))
    except TypeError as error:
        raise BootstrapError("campaign strategy roster is not iterable") from error
    result: dict[str, object] = {}
    for strategy in strategies:
        name = getattr(strategy, "name", None)
        if not isinstance(name, str) or not name:
            raise BootstrapError("campaign strategy has no canonical name")
        if name in result:
            raise BootstrapError("campaign strategy roster contains duplicate names")
        result[name] = strategy
    return result


def _closure_verifiers(
    campaign: object,
    tasks: Sequence[object],
    operation_registry: object,
) -> tuple[str, ...]:
    """Derive ``Closures(P)`` from exact strategies and operation contracts.

    A caller may request additional verifiers, but cannot weaken this set.  A
    missing operation is left to the independently bound G obligation so a
    diagnostic blocked profile remains constructible.  If the operation is
    present, however, every verified strategy must declare at least one exact
    central certificate verifier.
    """

    strategies = _strategy_map(campaign)
    resolve = getattr(operation_registry, "resolve", None)
    required: set[str] = set()
    for task in tasks:
        operation_name = _task_operation(task)
        strategy_name = getattr(task, "strategy", None)
        strategy = strategies.get(strategy_name) if isinstance(strategy_name, str) else None
        verify_results = getattr(strategy, "verify_results", False) is True
        if not callable(resolve):
            if verify_results:
                # G cannot be complete without a fixed resolver.  Do not trust
                # a caller-supplied verifier list as a substitute.
                raise BootstrapError(
                    "verified campaign strategies require an operation registry resolver"
                )
            continue
        try:
            operation = cast(Callable[[str], object], resolve)(operation_name)
        except (KeyError, LookupError):
            # The operation-registry obligation records this exact absence and
            # prevents readiness promotion.
            continue
        names = getattr(operation, "closure_verifiers", ())
        if not isinstance(names, tuple) or any(
            not isinstance(name, str) or not name or name != name.strip() for name in names
        ):
            raise BootstrapError(
                f"operation {operation_name!r} has a malformed closure-verifier contract"
            )
        if names != tuple(sorted(set(names))):
            raise BootstrapError(
                f"operation {operation_name!r} closure verifiers are not sorted and unique"
            )
        if verify_results and not names:
            raise BootstrapError(
                f"verified strategy {strategy_name!r} operation {operation_name!r} "
                "declares no closure verifiers"
            )
        required.update(names)
    return tuple(sorted(required))


def profile_from_plan(
    profile_type: type[ProfileT],
    campaign: object,
    plan: object,
    operation_registry: object,
    verifier_registry: object,
    executor: object,
    *,
    required_verifiers: Iterable[str],
    optional_capabilities: Iterable[str],
    optional_backends: Mapping[str, object] | None,
    optional_verifiers: Iterable[str],
    optional_obligations: Iterable[str],
    expected_arbogast_version: str | None,
    expected_arbogast_tree_sha256: str | None,
    require_lock_consistency: bool,
    require_persistent_custody: bool | None,
    scope: ReadinessScope,
) -> ProfileT:
    tasks = _tasks(plan)
    operations = tuple(sorted({_task_operation(task) for task in tasks}))
    task_ids = tuple(sorted({_task_id(task) for task in tasks}))
    if len(task_ids) != len(tasks):
        raise BootstrapError("plan task roster contains duplicate task identities")
    capabilities, backends = _requirements(tasks)
    explicit_verifier_names = tuple(sorted(set(required_verifiers)))
    derived_verifier_names = _closure_verifiers(campaign, tasks, operation_registry)
    verifier_names = tuple(sorted(set(explicit_verifier_names) | set(derived_verifier_names)))
    optional_capability_names = tuple(sorted(set(optional_capabilities)))
    optional_verifier_names = tuple(sorted(set(optional_verifiers) - set(derived_verifier_names)))
    optional_obligation_names = set(optional_obligations)
    unknown_optional = optional_obligation_names - set(READINESS_OBLIGATIONS)
    if unknown_optional:
        raise BootstrapError(
            "unknown optional readiness obligations: " + ", ".join(sorted(unknown_optional))
        )
    policies = {"deterministic-sharding"}
    if any(getattr(task, "checkpoint_ref", None) is not None for task in tasks):
        policies.add("checkpoint-resume")
    operation_binding = operation_registry_binding(operation_registry, operations)
    verifier_binding = verifier_registry_binding(
        verifier_registry, (*verifier_names, *optional_verifier_names)
    )
    executor_manifest = executor_binding(executor, policies)
    store = getattr(executor, "store", None)
    ephemeral = getattr(executor, "_temporary", None) is not None
    artifact_manifest = artifact_store_binding(store, ephemeral=ephemeral)
    persistent_custody = (
        scope is ReadinessScope.PLAN
        if require_persistent_custody is None
        else require_persistent_custody
    )
    return profile_type(
        scope=scope,
        campaign_id=_stable_id(campaign, ("campaign_id", "content_id"), "campaign"),
        plan_id=_stable_id(plan, ("plan_id", "content_id"), "plan"),
        task_ids=task_ids,
        required_operations=operations,
        required_capabilities=capabilities,
        optional_capabilities=optional_capability_names,
        required_backends=backends,
        optional_backends=freeze_mapping(optional_backends or {}),
        required_verifiers=verifier_names,
        optional_verifiers=optional_verifier_names,
        shard_policies=tuple(sorted(policies)),
        operation_registry=operation_binding,
        verifier_registry=verifier_binding,
        executor=executor_manifest,
        artifact_store=artifact_manifest,
        expected_arbogast_version=expected_arbogast_version or __version__,
        expected_arbogast_tree_sha256=(
            expected_arbogast_tree_sha256 or _current_arbogast_tree_sha256()
        ),
        minimum_python=(3, 11),
        maximum_python_exclusive=(3, 15),
        require_lock_consistency=require_lock_consistency,
        require_persistent_custody=persistent_custody,
        required_obligation_ids=tuple(
            item for item in READINESS_OBLIGATIONS if item not in optional_obligation_names
        ),
        optional_obligation_ids=tuple(
            item for item in READINESS_OBLIGATIONS if item in optional_obligation_names
        ),
        _runtime_artifact_store=store,
    )


def diagnostic_profile(
    *,
    mode: str,
    operation_registry: object,
    verifier_registry: object,
    executor: object,
    require_lock_consistency: bool,
) -> ReadinessProfile:
    """Construct a finite empty-plan profile for the diagnostic projection."""

    if mode not in {"campaign", "core", "replay"}:
        raise BootstrapError("preflight mode must be campaign, core, or replay")
    campaign_id = content_address(
        {"schema": "arbogast.bootstrap.diagnostic-campaign/v1", "mode": mode}
    )
    plan_id = content_address(
        {"schema": "arbogast.bootstrap.diagnostic-plan/v1", "mode": mode, "tasks": ()}
    )
    capabilities = {
        "core": ("canonical-json", "small-exact-computations"),
        "replay": ("canonical-json", "certificate-verification"),
        "campaign": ("canonical-json", "certificate-verification", "control-plane"),
    }[mode]
    policies = ("deterministic-sharding",) if mode == "campaign" else ()
    store = getattr(executor, "store", None)
    return ReadinessProfile(
        scope=ReadinessScope.STATIC,
        campaign_id=campaign_id,
        plan_id=plan_id,
        task_ids=(),
        required_operations=(),
        required_capabilities=tuple(sorted(capabilities)),
        optional_capabilities=(),
        required_backends=freeze_mapping(
            {
                "python": {
                    "capabilities": tuple(sorted(capabilities)),
                    "version": None,
                }
            }
        ),
        optional_backends=freeze_mapping(),
        required_verifiers=(),
        optional_verifiers=(),
        shard_policies=policies,
        operation_registry=operation_registry_binding(operation_registry, ()),
        verifier_registry=verifier_registry_binding(verifier_registry, ()),
        executor=executor_binding(executor, policies),
        artifact_store=artifact_store_binding(
            store, ephemeral=getattr(executor, "_temporary", None) is not None
        ),
        expected_arbogast_version=__version__,
        expected_arbogast_tree_sha256=_current_arbogast_tree_sha256(),
        minimum_python=(3, 11),
        maximum_python_exclusive=(3, 15),
        require_lock_consistency=require_lock_consistency,
        require_persistent_custody=False,
        _runtime_artifact_store=store,
    )


__all__ = [
    "artifact_store_binding",
    "diagnostic_profile",
    "executor_binding",
    "operation_registry_binding",
    "profile_from_plan",
    "verifier_registry_binding",
]
