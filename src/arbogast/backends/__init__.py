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
from .pari import (
    PARI,
    PARI_CAPABILITIES,
    PARI_SUPPORTED_RANGE,
    PariBackend,
    normalize_pari_version,
)
from .pari_certificate import PARI_OPERATIONAL_VERIFIER_ID, PARI_VERIFIER_ID, pari_payload_id
from .pari_protocol import (
    PariBackendError,
    PariOperationError,
    PariOutputLimitError,
    PariProtocolError,
    PariTimeoutError,
)
from .pari_results import (
    PariArithmeticResult,
    PariCompleteness,
    PariOutcome,
    PariProbeResult,
    PariVerificationRequirement,
    decode_pari_arithmetic_result,
)
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
    "PARI_CAPABILITIES",
    "PARI_OPERATIONAL_VERIFIER_ID",
    "PARI_SUPPORTED_RANGE",
    "PARI_VERIFIER_ID",
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
    "PariArithmeticResult",
    "PariBackend",
    "PariBackendError",
    "PariCompleteness",
    "PariOperationError",
    "PariOutcome",
    "PariOutputLimitError",
    "PariProbeResult",
    "PariProtocolError",
    "PariTimeoutError",
    "PariVerificationRequirement",
    "PythonBackend",
    "PythonModuleBackend",
    "RequirementLike",
    "SageBackend",
    "backend_statuses",
    "decode_pari_arithmetic_result",
    "normalize_pari_version",
    "pari_payload_id",
    "require_backend",
]
