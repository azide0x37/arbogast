"""The zeroth theorem: finite, replayable campaign readiness."""

from .capture import capture_environment
from .dispatch import (
    DISPATCH_READINESS_CHECKS,
    DispatchReadinessError,
    DispatchReadinessReceipt,
)
from .models import (
    READINESS_OBLIGATIONS,
    BootstrapError,
    EnvironmentSnapshot,
    FileIdentity,
    ObligationStatus,
    ReadinessObligation,
    ReadinessProfile,
    ReadinessReceipt,
    ReadinessScope,
    ReadinessVerdict,
    RuntimeBinding,
)
from .readiness import (
    READINESS_VERIFIER,
    CertifiedBlocked,
    CertifiedReady,
    Partial,
    ReadinessActivationReport,
    ReadinessResult,
    Unknown,
    Unsupported,
    certify_campaign_readiness,
    readiness_receipt,
    validate_readiness_activation,
    verify_readiness_certificate,
)
from .report import BootstrapReport, EnvironmentPreflightReport, environment_preflight
from .semantic import register_readiness_verifier

__all__ = [
    "DISPATCH_READINESS_CHECKS",
    "READINESS_OBLIGATIONS",
    "READINESS_VERIFIER",
    "BootstrapError",
    "BootstrapReport",
    "CertifiedBlocked",
    "CertifiedReady",
    "DispatchReadinessError",
    "DispatchReadinessReceipt",
    "EnvironmentPreflightReport",
    "EnvironmentSnapshot",
    "FileIdentity",
    "ObligationStatus",
    "Partial",
    "ReadinessActivationReport",
    "ReadinessObligation",
    "ReadinessProfile",
    "ReadinessReceipt",
    "ReadinessResult",
    "ReadinessScope",
    "ReadinessVerdict",
    "RuntimeBinding",
    "Unknown",
    "Unsupported",
    "capture_environment",
    "certify_campaign_readiness",
    "environment_preflight",
    "readiness_receipt",
    "register_readiness_verifier",
    "validate_readiness_activation",
    "verify_readiness_certificate",
]
