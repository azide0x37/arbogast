"""Compact semantic surfaces for coding, paper, and proof agents."""

from .code_dependencies import (
    DEFAULT_CODE_DEPENDENCIES,
    CodeDependencyEdge,
    CodeDependencyError,
    CodeDependencyGraph,
    CodeDependencyKind,
    CodeDependencyLookupError,
    CodeDependencyRegistry,
    CodeNode,
    CodeNodeKind,
    OperationCodeDependencies,
)
from .context import AgentContext, compact_context
from .hazards import DEFAULT_HAZARDS, Hazard, HazardRegistry, HazardSeverity
from .manifest import AgentManifest, manifest_for_operations, module_manifest
from .operations import (
    InMemorySemanticRegistry,
    OperationDescription,
    OperationLookupError,
    SemanticRegistry,
    default_semantic_registry,
    describe_operation,
    operation_descriptions,
    registry_names,
)
from .routes import CapabilityEdge, CapabilityGraph, CapabilityRoute, CapabilityRouteError
from .tasks import AgentTask

__all__ = [
    "DEFAULT_CODE_DEPENDENCIES",
    "DEFAULT_HAZARDS",
    "AgentContext",
    "AgentManifest",
    "AgentTask",
    "CapabilityEdge",
    "CapabilityGraph",
    "CapabilityRoute",
    "CapabilityRouteError",
    "CodeDependencyEdge",
    "CodeDependencyError",
    "CodeDependencyGraph",
    "CodeDependencyKind",
    "CodeDependencyLookupError",
    "CodeDependencyRegistry",
    "CodeNode",
    "CodeNodeKind",
    "Hazard",
    "HazardRegistry",
    "HazardSeverity",
    "InMemorySemanticRegistry",
    "OperationCodeDependencies",
    "OperationDescription",
    "OperationLookupError",
    "SemanticRegistry",
    "compact_context",
    "default_semantic_registry",
    "describe_operation",
    "manifest_for_operations",
    "module_manifest",
    "operation_descriptions",
    "registry_names",
]
