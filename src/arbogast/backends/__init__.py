"""Optional algebra-backend capability declarations and status checks.

Importing this package never imports or impersonates a computer algebra
system.  A backend becomes usable only when its status probe says so.
"""

from .base import (
    Backend,
    BackendStatus,
    BackendUnavailableError,
    ExecutableBackend,
    PythonModuleBackend,
    RequirementLike,
)
from .flint import FLINT, FlintBackend
from .gap import GAP, GapBackend
from .magma import MAGMA, MagmaBackend
from .pari import PARI, PariBackend
from .python import PYTHON, PythonBackend
from .registry import DEFAULT_BACKENDS, BackendRegistry, backend_statuses, require_backend
from .results import FlintMatrixResult, GapGroupOrderResult
from .sage import SAGE, SageBackend

__all__ = [
    "DEFAULT_BACKENDS",
    "FLINT",
    "GAP",
    "MAGMA",
    "PARI",
    "PYTHON",
    "SAGE",
    "Backend",
    "BackendRegistry",
    "BackendStatus",
    "BackendUnavailableError",
    "ExecutableBackend",
    "FlintBackend",
    "FlintMatrixResult",
    "GapBackend",
    "GapGroupOrderResult",
    "MagmaBackend",
    "PariBackend",
    "PythonBackend",
    "PythonModuleBackend",
    "RequirementLike",
    "SageBackend",
    "backend_statuses",
    "require_backend",
]
