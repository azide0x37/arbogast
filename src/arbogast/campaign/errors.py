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


__all__ = [
    "CampaignError",
    "CampaignInvariantError",
    "CampaignSerializationError",
    "CapabilityUnavailableError",
    "UnknownOperationError",
    "UnknownTargetError",
]
