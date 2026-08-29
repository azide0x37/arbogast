"""Compatibility module for the primary campaign engine types."""

from .engine import Campaign, CampaignStatus, TargetExplanation
from .spec import CampaignSpec, Objective

__all__ = ["Campaign", "CampaignSpec", "CampaignStatus", "Objective", "TargetExplanation"]
