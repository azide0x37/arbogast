"""Campaign-layer exceptions."""

from __future__ import annotations


class CampaignError(RuntimeError):
    """Base class for campaign failures."""


class CampaignInvariantError(CampaignError, ValueError):
    """Raised when an event would cross a mathematical proof boundary."""


class CampaignSerializationError(CampaignError, ValueError):
    """Raised when canonical campaign replay data is invalid."""


class UnknownTargetError(CampaignError, KeyError):
    """Raised when a target is absent from the authoritative ledger."""


class UnknownOperationError(CampaignError, KeyError):
    """Raised when a task names no injected operation implementation."""


class CapabilityUnavailableError(CampaignError):
    """Raised when no local capability set can execute a campaign task."""


class CampaignReadinessError(CampaignError):
    """Raised when no current environmental theorem authorizes dispatch."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "READINESS_REJECTED",
        blockers: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("campaign readiness error code must be non-blank")
        resolved = tuple(blockers)
        if any(not isinstance(item, str) or not item.strip() for item in resolved):
            raise ValueError("campaign readiness blockers must be non-blank strings")
        self.code = code
        self.blockers = resolved
        super().__init__(message)


__all__ = [
    "CampaignError",
    "CampaignInvariantError",
    "CampaignReadinessError",
    "CampaignSerializationError",
    "CapabilityUnavailableError",
    "UnknownOperationError",
    "UnknownTargetError",
]
