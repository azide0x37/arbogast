"""Fixed registry hook for the environmental-readiness verifier."""

from __future__ import annotations

from arbogast.cert import VerificationCertificate, VerifierRegistry, default_verifiers

from .readiness import READINESS_VERIFIER, verify_readiness_certificate


def register_readiness_verifier(
    registry: VerifierRegistry = default_verifiers,
) -> VerifierRegistry:
    """Idempotently register the exact readiness verifier in ``registry``."""

    registry.register(
        READINESS_VERIFIER,
        VerificationCertificate,
        verify_readiness_certificate,
    )
    return registry


register_readiness_verifier()


__all__ = ["register_readiness_verifier"]
