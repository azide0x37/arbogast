"""Bind verified campaign closures into the semantic claim graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from arbogast.cert import (
    Certificate,
    CertificateVerificationError,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    VerifierRegistry,
    certificate_from_dict,
    default_verifiers,
)
from arbogast.claims import Claim, ClaimKind, Derivation, EpistemicStatus, FormalStatement
from arbogast.formats import canonical_sha256, thaw_json

from .errors import CampaignInvariantError
from .events import CLOSING_OUTCOMES, Observation, Outcome
from .planner import CampaignTask

_CLAIM_VERIFIER = "campaign.claim-closure.v1"
_CLAIM_WITNESS_SCHEMA = "arbogast.campaign.claim-witness.v1"
_CLAIM_CHECKS = (
    "campaign-observation-integrity",
    "campaign-closure-certificate-replay",
    "campaign-task-custody",
    "claim-statement-binding",
)
_CLAIM_GUARANTEES = ("verified campaign closure bound to this semantic claim",)
_REGISTERED: dict[
    VerifierRegistry,
    Callable[[VerificationCertificate], VerificationReport],
] = {}


def _certificate(observation: Observation) -> Certificate:
    if observation.certificate_payload is None:
        raise CampaignInvariantError("verified campaign claim requires embedded evidence")
    payload = thaw_json(observation.certificate_payload)
    if not isinstance(payload, dict):
        raise CampaignInvariantError("campaign claim certificate must be an object")
    return certificate_from_dict(payload)


def _statement(task: CampaignTask, observation: Observation) -> FormalStatement:
    target = task.target.label or task.target.key
    text = {
        Outcome.FOUND: f"Campaign target {target} has a verified witness.",
        Outcome.PROVED_IMPOSSIBLE: (
            f"Campaign target {target} is impossible under the recorded exact conditions."
        ),
        Outcome.SEARCH_EXHAUSTED: (
            f"The declared finite search space for campaign target {target} is exhausted."
        ),
    }[observation.outcome]
    return FormalStatement.create(
        text,
        parameters={
            "outcome": observation.outcome.value,
            "target": task.target.identity_dict(),
            "target_id": task.target_id,
        },
    )


def _claim_id(campaign_id: str, observation_id: str) -> str:
    digest = canonical_sha256(
        {
            "campaign_id": campaign_id,
            "observation_id": observation_id,
            "schema": "arbogast.campaign.claim-id.v1",
        }
    )
    return f"campaign:{digest}"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CertificateVerificationError(f"campaign claim {field} must be an object")
    return value


def _verify_campaign_claim(
    certificate: VerificationCertificate,
    registry: VerifierRegistry,
) -> VerificationReport:
    """Replay the embedded closure and recompute every semantic claim binding."""

    if certificate.verifier != _CLAIM_VERIFIER:
        raise CertificateVerificationError("campaign claim certificate names another verifier")
    if certificate.checks != _CLAIM_CHECKS:
        raise CertificateVerificationError("campaign claim certificate checks are incomplete")
    if certificate.guarantees != _CLAIM_GUARANTEES:
        raise CertificateVerificationError("campaign claim certificate guarantee is unsupported")
    witness = certificate.witness.to_dict()
    expected_fields = {"campaign_id", "observation", "schema", "task"}
    if set(witness) != expected_fields or witness.get("schema") != _CLAIM_WITNESS_SCHEMA:
        raise CertificateVerificationError(
            "campaign claim witness has missing, unknown, or unsupported fields"
        )
    campaign_id = witness.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise CertificateVerificationError("campaign claim campaign_id must be non-blank")
    try:
        task = CampaignTask.from_dict(_mapping(witness.get("task"), "task"))
        observation = Observation.from_dict(_mapping(witness.get("observation"), "observation"))
    except (CampaignInvariantError, KeyError, TypeError, ValueError) as error:
        raise CertificateVerificationError(
            "campaign claim task or observation failed strict replay"
        ) from error
    if observation.outcome not in CLOSING_OUTCOMES:
        raise CertificateVerificationError("campaign claim observation is not mathematical closure")
    if observation.task_id != task.campaign_task_id or observation.target_id != task.target_id:
        raise CertificateVerificationError(
            "campaign claim observation is bound to another task or target"
        )
    if observation.input_refs != task.task.input_refs:
        raise CertificateVerificationError("campaign claim input custody does not match its task")
    if observation.parameters.to_dict() != task.provenance.parameters.to_dict():
        raise CertificateVerificationError(
            "campaign claim parameter custody does not match its task"
        )
    if observation.source_refs != task.provenance.source_refs:
        raise CertificateVerificationError("campaign claim source custody does not match its task")

    closure = _certificate(observation)
    closure_report = registry.verify(closure)
    if not closure_report.valid:
        raise CertificateVerificationError("campaign closure certificate replay failed")

    statement = _statement(task, observation)
    expected_claim_id = _claim_id(campaign_id, observation.observation_id)
    if certificate.claim_id != expected_claim_id:
        raise CertificateVerificationError("campaign claim certificate has the wrong claim ID")
    if certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError(
            "campaign claim certificate has the wrong statement hash"
        )
    if certificate.subject != statement.text:
        raise CertificateVerificationError("campaign claim certificate has the wrong subject")
    return VerificationReport(
        valid=True,
        verifier=_CLAIM_VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=_CLAIM_CHECKS,
        details=FrozenMap(
            {
                "campaign_id": campaign_id,
                "closure_certificate_id": closure.certificate_id,
                "observation_id": observation.observation_id,
                "task_id": task.campaign_task_id,
            }
        ),
    )


def register_campaign_claim_verifier(
    registry: VerifierRegistry = default_verifiers,
) -> VerifierRegistry:
    """Register claim-envelope replay, including nested closure verification."""

    replay = _REGISTERED.get(registry)
    if replay is None:

        def replay(certificate: VerificationCertificate) -> VerificationReport:
            return _verify_campaign_claim(certificate, registry)

        registry.register(_CLAIM_VERIFIER, VerificationCertificate, replay)
        _REGISTERED[registry] = replay
    else:
        registry.register(_CLAIM_VERIFIER, VerificationCertificate, replay)
    return registry


def claim_for_observation(
    campaign_id: str,
    campaign_name: str,
    task: CampaignTask,
    observation: Observation,
) -> Claim:
    """Create a narrowly scoped computed claim from verified campaign closure."""

    if not observation.closes_target:
        raise CampaignInvariantError("only verified mathematical closure creates a claim")
    if observation.task_id != task.campaign_task_id:
        raise CampaignInvariantError("claim observation is bound to another campaign task")
    closure = _certificate(observation)
    result_ref = observation.result_ref
    certificate_witness = getattr(closure, "witness", None)
    bound_result: str | None = None
    if certificate_witness is not None:
        witness = certificate_witness.to_dict()
        if witness.get("result_ref") == result_ref:
            bound_result = result_ref
    is_gate = observation.details.get("preflight") == "PROVED_IMPOSSIBLE"
    operation = "campaign.exact-gate" if is_gate else task.task.operation
    method = (
        "Independent replay of an exact campaign preflight obstruction"
        if is_gate
        else "Independent replay of a campaign computation certificate"
    )
    statement = _statement(task, observation)
    claim_id = _claim_id(campaign_id, observation.observation_id)
    certificate = VerificationCertificate.create(
        statement.text,
        _CLAIM_VERIFIER,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        witness={
            "campaign_id": campaign_id,
            "observation": observation.to_dict(),
            "schema": _CLAIM_WITNESS_SCHEMA,
            "task": task.to_dict(),
        },
        checks=_CLAIM_CHECKS,
        guarantees=_CLAIM_GUARANTEES,
    )
    return Claim(
        id=claim_id,
        what=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        how=Derivation.computation(
            operation,
            method=method,
            inputs=task.task.input_refs,
            artifact=bound_result,
            parameters={
                "campaign_id": campaign_id,
                "campaign_task_id": task.campaign_task_id,
                "observation_id": observation.observation_id,
                "strategy": task.strategy,
                "target_id": task.target_id,
            },
        ),
        evidence=(certificate,),
        metadata={
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "campaign_task_id": task.campaign_task_id,
            "observation_id": observation.observation_id,
            "outcome": observation.outcome.value,
            "target_id": task.target_id,
        },
    )


register_campaign_claim_verifier()


__all__ = ["claim_for_observation", "register_campaign_claim_verifier"]
