"""Scope-labelled generated manifests for machine collaborators."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arbogast.formats import AGENT_MANIFEST_SCHEMA, JSONValue, canonical_dumps, loads

from .code_dependencies import DEFAULT_CODE_DEPENDENCIES, CodeDependencyRegistry
from .operations import (
    OperationDescription,
    default_semantic_registry,
    operation_descriptions,
    registry_names,
)


def _strings(values: Iterable[str], label: str) -> tuple[str, ...]:
    materialized = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise ValueError(f"agent manifest {label} must contain non-blank strings")
    return tuple(sorted(set(materialized)))


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"agent manifest {label} must be an array of non-blank strings")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class AgentManifest:
    """Generated equivalent of a compact, scope-specific ``AGENT.md``."""

    package: str
    version: str
    operations: tuple[str, ...]
    primary_types: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    do_not: tuple[str, ...] = ()
    schema: str = AGENT_MANIFEST_SCHEMA
    scope: str = ""
    purpose: str = ""
    code_dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.package, str) or not self.package.strip():
            raise ValueError("agent manifest package must not be empty")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("agent manifest version must not be empty")
        if not isinstance(self.scope, str):
            raise ValueError("agent manifest scope must be a string")
        scope = self.scope or self.package
        if not scope.strip():
            raise ValueError("agent manifest scope must not be empty")
        if not isinstance(self.purpose, str) or (self.purpose and not self.purpose.strip()):
            raise ValueError("agent manifest purpose must be empty or non-blank")
        if self.schema != AGENT_MANIFEST_SCHEMA:
            raise ValueError("unsupported agent-manifest schema")
        object.__setattr__(self, "scope", scope)
        for name in (
            "operations",
            "primary_types",
            "invariants",
            "do_not",
            "code_dependencies",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))

    @classmethod
    def from_operations(
        cls,
        operations: Iterable[OperationDescription],
        *,
        package: str = "arbogast",
        version: str | None = None,
        scope: str | None = None,
        purpose: str = "",
        primary_types: Iterable[str] = (),
        invariants: Iterable[str] = (),
        do_not: Iterable[str] = (),
        code_dependencies: Iterable[str] = (),
    ) -> AgentManifest:
        descriptions = tuple(operations)
        if version is None:
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = "0+unknown"
        types = set(primary_types)
        types.update(
            type_name
            for operation in descriptions
            for type_name in (*operation.inputs, *operation.outputs)
        )
        return cls(
            package=package,
            version=version,
            operations=tuple(operation.name for operation in descriptions),
            primary_types=tuple(types),
            invariants=tuple(invariants),
            do_not=tuple(do_not),
            scope=package if scope is None else scope,
            purpose=purpose,
            code_dependencies=tuple(code_dependencies),
        )

    @classmethod
    def from_registry(
        cls,
        registry: object | None = None,
        *,
        package: str = "arbogast",
        version: str | None = None,
        scope: str | None = None,
        purpose: str = "",
        primary_types: Iterable[str] = (),
        invariants: Iterable[str] = (),
        do_not: Iterable[str] = (),
        code_dependencies: Iterable[str] = (),
    ) -> AgentManifest:
        return cls.from_operations(
            operation_descriptions(registry),
            package=package,
            version=version,
            scope=scope,
            purpose=purpose,
            primary_types=primary_types,
            invariants=invariants,
            do_not=do_not,
            code_dependencies=code_dependencies,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "code_dependencies": list(self.code_dependencies),
            "do_not": list(self.do_not),
            "invariants": list(self.invariants),
            "operations": list(self.operations),
            "package": self.package,
            "primary_types": list(self.primary_types),
            "purpose": self.purpose,
            "schema": self.schema,
            "scope": self.scope,
            "version": self.version,
        }

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> AgentManifest:
        decoded = loads(value)
        if not isinstance(decoded, Mapping):
            raise ValueError("agent manifest JSON must contain an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentManifest:
        expected = {
            "code_dependencies",
            "do_not",
            "invariants",
            "operations",
            "package",
            "primary_types",
            "purpose",
            "schema",
            "scope",
            "version",
        }
        if set(value) != expected:
            raise ValueError("agent manifest has missing or unknown fields")
        if value["schema"] != AGENT_MANIFEST_SCHEMA:
            raise ValueError("unsupported agent-manifest schema")
        package = value["package"]
        version = value["version"]
        scope = value["scope"]
        purpose = value["purpose"]
        if any(not isinstance(item, str) for item in (package, version, scope, purpose)):
            raise ValueError("agent manifest scalar fields must be strings")
        return cls(
            package=package,
            version=version,
            operations=_string_array(value["operations"], "operations"),
            primary_types=_string_array(value["primary_types"], "primary_types"),
            invariants=_string_array(value["invariants"], "invariants"),
            do_not=_string_array(value["do_not"], "do_not"),
            scope=scope,
            purpose=purpose,
            code_dependencies=_string_array(value["code_dependencies"], "code_dependencies"),
        )


@dataclass(frozen=True, slots=True)
class _ModuleProfile:
    purpose: str
    primary_types: tuple[str, ...]
    invariants: tuple[str, ...]
    do_not: tuple[str, ...]


_MODULE_PROFILES = {
    "arbogast.core": _ModuleProfile(
        "Canonical finite objects, immutable artifacts, and stable identities.",
        ("Artifact", "ArtifactRef", "CanonicalObject"),
        ("Canonical encodings are deterministic and use the strict JSON subset.",),
        ("Do not use repr, memory addresses, floats, or raw bytes as canonical identity.",),
    ),
    "arbogast.linalg": _ModuleProfile(
        "Exact dense and sparse finite-field linear algebra.",
        ("DenseMatrix", "LinearSubspace", "PrimeField", "SparseMatrix"),
        ("An m by n matrix acts from F^n to F^m.",),
        ("Do not promote floating-point rank or recognition to an exact result.",),
    ),
    "arbogast.rep": _ModuleProfile(
        "Concrete finite groups, representations, characters, and invariant decompositions.",
        ("Character", "CyclicGroup", "PermutationGroup", "Representation"),
        ("Representation matrices satisfy rho(gh) = rho(g) rho(h) on columns.",),
        ("Do not change a pinned concrete group embedding without an explicit transport.",),
    ),
    "arbogast.cohom": _ModuleProfile(
        "Explicit low-degree cohomology of finite group actions.",
        ("CohomologyCertificate", "H0Result", "H1Result", "H2Result"),
        ("Cohomology results retain cocycles, coboundaries, quotient maps, and evidence.",),
        ("Do not treat a dimension or backend transcript as a cohomology certificate.",),
    ),
    "arbogast.hurwitz": _ModuleProfile(
        "Finite Nielsen classes, braid actions, real structures, and component invariants.",
        ("BraidAction", "HurwitzComponent", "NielsenClass", "NielsenTuple"),
        ("Nielsen tuples use the declared product and right-Hurwitz conventions.",),
        (
            "Do not confuse source genus with Hurwitz-component genus.",
            "Do not promote imported or context-bound receipts without complete portable evidence.",
        ),
    ),
    "arbogast.claims": _ModuleProfile(
        "Typed mathematical claims and their theorem dependency DAG.",
        ("Claim", "ClaimGraph", "FormalStatement"),
        ("Claim kind and epistemic status are independent classifications.",),
        ("Do not infer theorem dependencies from code imports or task completion.",),
    ),
    "arbogast.cert": _ModuleProfile(
        "Discovery, verification, and theorem-level certificate boundaries.",
        ("DiscoveryReceipt", "TheoremCertificate", "VerificationCertificate"),
        ("Verification evidence must replay through its registered verifier.",),
        ("Do not promote a discovery receipt or a matching hash into mathematical proof.",),
    ),
    "arbogast.fleet": _ModuleProfile(
        "Deterministic mathematical task planning, sharding, execution, and reduction.",
        ("FleetRun", "ShardSpec", "TaskSpec"),
        ("Task and shard identities bind canonical inputs and parameters.",),
        ("Do not treat dispatch, process exit, or an execution receipt as proof.",),
    ),
    "arbogast.agent": _ModuleProfile(
        "Compact declared contracts and work packets for machine collaborators.",
        ("AgentContext", "AgentManifest", "AgentTask", "CodeDependencyGraph"),
        ("Theorem, capability, code, and task dependency graphs remain distinct.",),
        ("Do not infer code dependencies by scanning Python imports.",),
    ),
    "arbogast.backends": _ModuleProfile(
        "Honest probes for separately installed optional algebra systems.",
        ("BackendRequirement", "BackendStatus"),
        ("A capability status is a point-in-time observation.",),
        ("Do not download, emulate, or silently substitute a missing backend.",),
    ),
    "arbogast.export": _ModuleProfile(
        "Stable projections for JSON, paper, agent, and Lean-facing consumers.",
        ("Claim", "ClaimGraph", "ProofGap"),
        ("An export preserves the source claim classification.",),
        ("Do not strengthen a claim or imply that generated Lean axioms were proved.",),
    ),
    "arbogast.formats": _ModuleProfile(
        "Versioned canonical interchange schemas.",
        ("FrozenMapping", "JSONValue"),
        ("Unknown schema versions fail closed.",),
        ("Do not guess a schema from payload fields.",),
    ),
}


def _public_module(module: str) -> str:
    pieces = module.split(".")
    return ".".join(pieces[:2]) if len(pieces) >= 2 else module


def _operation_public_module(operation_name: str) -> str:
    prefix = operation_name.split(".", 1)[0]
    return f"arbogast.{prefix}"


def module_manifest(
    module: str,
    *,
    registry: object | None = None,
    code_dependencies: CodeDependencyRegistry = DEFAULT_CODE_DEPENDENCIES,
) -> AgentManifest:
    """Return the generated compact manifest for one declared public module."""

    public_module = _public_module(module)
    try:
        profile = _MODULE_PROFILES[public_module]
    except KeyError as error:
        raise LookupError(f"no agent module profile for {public_module!r}") from error
    selected_registry = default_semantic_registry() if registry is None else registry
    operation_names = {
        name
        for name in registry_names(selected_registry)
        if _operation_public_module(name) == public_module
    }
    descriptions = tuple(
        description
        for description in operation_descriptions(selected_registry)
        if description.name in operation_names
    )
    declared, _ = code_dependencies.select(operation_names)
    dependency_ids = {f"module:{declaration.implementation_module}" for declaration in declared}
    dependency_ids.update(
        {
            f"module:{dependency}"
            for declaration in declared
            for dependency in declaration.module_dependencies
        }
    )
    dependency_ids.update(
        f"backend:{backend}"
        for declaration in declared
        for backend in (*declaration.required_backends, *declaration.optional_backends)
    )
    return AgentManifest.from_operations(
        descriptions,
        scope=public_module,
        purpose=profile.purpose,
        primary_types=profile.primary_types,
        invariants=profile.invariants,
        do_not=profile.do_not,
        code_dependencies=dependency_ids,
    )


def manifest_for_operations(
    operations: Iterable[OperationDescription],
    *,
    code_dependencies: CodeDependencyRegistry = DEFAULT_CODE_DEPENDENCIES,
    invariants: Iterable[str] = (),
    do_not: Iterable[str] = (),
) -> AgentManifest:
    """Build one coherent manifest from selected operation contracts."""

    descriptions = tuple(operations)
    declarations, _ = code_dependencies.select(description.name for description in descriptions)
    public_modules = tuple(
        sorted(
            {
                _operation_public_module(description.name)
                for description in descriptions
                if _operation_public_module(description.name) in _MODULE_PROFILES
            }
        )
    )
    profiles = tuple(_MODULE_PROFILES[module] for module in public_modules)
    if len(public_modules) == 1:
        scope = public_modules[0]
        purpose = profiles[0].purpose
    else:
        scope = "arbogast"
        purpose = "Cross-module context for " + ", ".join(public_modules) if public_modules else ""
    dependencies = {f"module:{declaration.implementation_module}" for declaration in declarations}
    dependencies.update(
        {
            f"module:{dependency}"
            for declaration in declarations
            for dependency in declaration.module_dependencies
        }
    )
    dependencies.update(
        f"backend:{backend}"
        for declaration in declarations
        for backend in (*declaration.required_backends, *declaration.optional_backends)
    )
    return AgentManifest.from_operations(
        descriptions,
        scope=scope,
        purpose=purpose,
        primary_types=(item for profile in profiles for item in profile.primary_types),
        invariants=(*invariants, *(item for profile in profiles for item in profile.invariants)),
        do_not=(*do_not, *(item for profile in profiles for item in profile.do_not)),
        code_dependencies=dependencies,
    )


__all__ = ["AgentManifest", "manifest_for_operations", "module_manifest"]
