"""Research campaigns: why mathematical fleet tasks are being run."""

from .claims import register_campaign_claim_verifier
from .derive import DerivationRule, TaskProvenance
from .engine import Campaign, CampaignStatus, TargetExplanation
from .errors import (
    CampaignError,
    CampaignInvariantError,
    CampaignReadinessError,
    CampaignSerializationError,
    CapabilityUnavailableError,
    UnknownOperationError,
    UnknownTargetError,
)
from .events import (
    CLOSING_OUTCOMES,
    CampaignOutcome,
    EventKind,
    LedgerEvent,
    MathematicalOutcome,
    Observation,
    OperationalState,
    Outcome,
    OutcomeScope,
    closure_certificate,
    closure_subject,
)
from .ledger import TargetLedger
from .planner import (
    CampaignPlan,
    CampaignTask,
    Recommendation,
    RecommendationAction,
)
from .policy import PriorityPolicy, PriorityScore
from .results import (
    AttemptRecord,
    CandidateEvidence,
    CandidateRecord,
    CandidateScope,
    ExecutionTelemetry,
)
from .spec import CampaignSpec, Objective
from .strategy import (
    ExactGate,
    FunctionalGate,
    GateDecision,
    GateDisposition,
    PreflightDecision,
    PreflightGate,
    Strategy,
    TaskFactory,
)
from .targets import TargetSpec, TargetState, TargetStatus

__all__ = [
    "CLOSING_OUTCOMES",
    "AttemptRecord",
    "Campaign",
    "CampaignError",
    "CampaignInvariantError",
    "CampaignOutcome",
    "CampaignPlan",
    "CampaignReadinessError",
    "CampaignSerializationError",
    "CampaignSpec",
    "CampaignStatus",
    "CampaignTask",
    "CandidateEvidence",
    "CandidateRecord",
    "CandidateScope",
    "CapabilityUnavailableError",
    "DerivationRule",
    "EventKind",
    "ExactGate",
    "ExecutionTelemetry",
    "FunctionalGate",
    "GateDecision",
    "GateDisposition",
    "LedgerEvent",
    "MathematicalOutcome",
    "Objective",
    "Observation",
    "OperationalState",
    "Outcome",
    "OutcomeScope",
    "PreflightDecision",
    "PreflightGate",
    "PriorityPolicy",
    "PriorityScore",
    "Recommendation",
    "RecommendationAction",
    "Strategy",
    "TargetExplanation",
    "TargetLedger",
    "TargetSpec",
    "TargetState",
    "TargetStatus",
    "TaskFactory",
    "TaskProvenance",
    "UnknownOperationError",
    "UnknownTargetError",
    "closure_certificate",
    "closure_subject",
    "register_campaign_claim_verifier",
]
