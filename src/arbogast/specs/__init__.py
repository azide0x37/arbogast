"""Machine-readable mathematical contracts for public operations."""

from .catalog import (
    BUILTIN_IMPLEMENTATIONS,
    BUILTIN_OPERATION_SPECS,
    OPERATION_CONTRACT_MODULES,
    PUBLIC_FUNCTION_OPERATIONS,
    PUBLIC_NON_OPERATION_HELPERS,
    SHARD_PLANNERS,
    bind_builtin_implementations,
    register_builtin_operations,
)
from .operations import (
    FailureMode,
    OperationExample,
    OperationRegistry,
    OperationSpec,
    OperationSpecError,
    RegisteredOperation,
    default_operations,
    default_registry,
    get_operation_spec,
    operation,
    operation_registry,
)

register_builtin_operations()
bind_builtin_implementations()

__all__ = [
    "BUILTIN_IMPLEMENTATIONS",
    "BUILTIN_OPERATION_SPECS",
    "OPERATION_CONTRACT_MODULES",
    "PUBLIC_FUNCTION_OPERATIONS",
    "PUBLIC_NON_OPERATION_HELPERS",
    "SHARD_PLANNERS",
    "FailureMode",
    "OperationExample",
    "OperationRegistry",
    "OperationSpec",
    "OperationSpecError",
    "RegisteredOperation",
    "bind_builtin_implementations",
    "default_operations",
    "default_registry",
    "get_operation_spec",
    "operation",
    "operation_registry",
    "register_builtin_operations",
]
