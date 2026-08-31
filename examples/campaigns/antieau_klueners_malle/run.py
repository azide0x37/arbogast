"""Run a deterministic local campaign and emit its replayable claim artifacts."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path

from arbogast.campaign import (
    Campaign,
    CampaignSerializationError,
    CampaignSpec,
    CampaignTask,
    ExecutionTelemetry,
    Outcome,
    OutcomeScope,
    Strategy,
    TargetSpec,
    TaskProvenance,
    closure_subject,
)
from arbogast.cert import (
    CertificateError,
    CertificateVerificationError,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    verifier,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.export import export_json
from arbogast.fleet import FunctionalOperation, LocalExecutor, ShardSpec, TaskSpec
from arbogast.formats import JSONValue, normalize_json
from arbogast.sinks import FilesystemSink

MODULUS = 17
TARGET_RESIDUE = 3
OPERATION = "examples.exhaust_residue_squares"
STRATEGY = "complete-residue-scan"
CAPABILITY = "small-exact-computations"
VERIFIER = "examples.campaign.residue-scan.v1"
CATALOGUE_SOURCE = "https://galoisdb.math.uni-paderborn.de/"
PRIOR_CLAIM_ID = "demo.catalogue.mod17_residue3_absent"
CLOSURE_CLAIM_ID = "demo.certificate.mod17_residue3_nonsquare"
RESULT_STATEMENT = FormalStatement(
    "No canonical residue modulo 17 has square congruent to 3 modulo 17."
)
RESULT_STATEMENT_HASH = RESULT_STATEMENT.statement_hash
RESULT_BOUNDARY_HASH = claim_boundary_hash(
    CLOSURE_CLAIM_ID,
    RESULT_STATEMENT,
    kind=ClaimKind.COMPUTED,
    status=EpistemicStatus.EXACT,
)


def require_integer(value: object, name: str) -> int:
    """Return a strict integer, excluding booleans at the evidence boundary."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateVerificationError(f"{name} must be an integer")
    return value


def require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CertificateVerificationError(f"{name} must be a nonempty string")
    return value


@verifier(VERIFIER, certificate_type=VerificationCertificate)
def verify_residue_scan(certificate: VerificationCertificate) -> VerificationReport:
    """Verify completeness and every modular square without trusting campaign scheduling."""

    witness = certificate.witness.to_dict()
    target_id = require_string(witness.get("target_id"), "target_id")
    task_hash = require_string(witness.get("task_hash"), "task_hash")
    outcome = Outcome(require_string(witness.get("outcome"), "outcome"))
    outcome_scope = OutcomeScope(require_string(witness.get("outcome_scope"), "outcome_scope"))
    modulus = require_integer(witness.get("modulus"), "modulus")
    target = require_integer(witness.get("target"), "target")
    rows = witness.get("rows")

    if modulus <= 1 or not 0 <= target < modulus:
        raise CertificateVerificationError("modulus or target is outside canonical range")
    if not isinstance(rows, list):
        raise CertificateVerificationError("rows must be an array")

    expected_rows = [
        {"residue": residue, "square": residue * residue % modulus} for residue in range(modulus)
    ]
    if rows != expected_rows:
        raise CertificateVerificationError(
            "residue table is not the complete canonical modular domain"
        )

    roots = [row["residue"] for row in expected_rows if row["square"] == target]
    if outcome is Outcome.SEARCH_EXHAUSTED and roots:
        raise CertificateVerificationError("SEARCH_EXHAUSTED certificate contains a root")
    if outcome is Outcome.FOUND and not roots:
        raise CertificateVerificationError("FOUND certificate contains no root")
    if outcome not in {Outcome.FOUND, Outcome.SEARCH_EXHAUSTED}:
        raise CertificateVerificationError("residue scan cannot certify this campaign outcome")
    if outcome_scope is not OutcomeScope.TARGET_GLOBAL:
        raise CertificateVerificationError("residue scan claims only target-global closure")
    if certificate.subject != closure_subject(target_id, outcome, outcome_scope):
        raise CertificateVerificationError(
            "certificate is not bound to its target, outcome, and scope"
        )
    if certificate.claim_id != CLOSURE_CLAIM_ID:
        raise CertificateVerificationError("certificate is bound to another closure claim")
    if certificate.statement_hash != RESULT_STATEMENT_HASH:
        raise CertificateVerificationError("certificate is bound to another result statement")
    if certificate.claim_boundary_hash != RESULT_BOUNDARY_HASH:
        raise CertificateVerificationError("certificate has the wrong semantic claim boundary")
    if certificate.claim_dependencies:
        raise CertificateVerificationError("closure certificate cannot bind claim dependencies")
    if len(task_hash) != 64 or any(character not in "0123456789abcdef" for character in task_hash):
        raise CertificateVerificationError("certificate has no canonical planned-task hash")

    return VerificationReport(
        valid=True,
        verifier=VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=("canonical-domain", "modular-squares", "outcome-binding"),
        details=FrozenMap({"checked": modulus, "roots": roots}),
    )


def plan_residues(task: TaskSpec) -> tuple[ShardSpec, ...]:
    modulus = require_integer(task.parameters.get("modulus"), "modulus")
    return tuple(
        ShardSpec(
            task.task_hash,
            f"residue-{residue:02d}",
            {"residue": residue},
            ordinal=residue,
        )
        for residue in range(modulus)
    )


def evaluate_residue(task: TaskSpec, shard: ShardSpec) -> dict[str, int]:
    modulus = require_integer(task.parameters.get("modulus"), "modulus")
    residue = require_integer(shard.payload.get("residue"), "residue")
    return {"residue": residue, "square": residue * residue % modulus}


def reduce_residues(task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, JSONValue]:
    modulus = require_integer(task.parameters.get("modulus"), "modulus")
    target = require_integer(task.parameters.get("target"), "target")
    target_id = require_string(task.parameters.get("target_id"), "target_id")
    rows: list[dict[str, int]] = []
    for index, partial in enumerate(partials):
        if not isinstance(partial, dict):
            raise ValueError(f"partial {index} is not an object")
        rows.append(
            {
                "residue": require_integer(partial.get("residue"), "residue"),
                "square": require_integer(partial.get("square"), "square"),
            }
        )
    rows.sort(key=lambda row: row["residue"])
    roots = [row["residue"] for row in rows if row["square"] == target]
    root_values: list[JSONValue] = list(roots)
    outcome = Outcome.FOUND if roots else Outcome.SEARCH_EXHAUSTED
    certificate = VerificationCertificate.create(
        closure_subject(target_id, outcome, OutcomeScope.TARGET_GLOBAL),
        VERIFIER,
        claim_id=CLOSURE_CLAIM_ID,
        statement_hash=RESULT_STATEMENT_HASH,
        claim_boundary_hash=RESULT_BOUNDARY_HASH,
        witness={
            "modulus": modulus,
            "outcome": outcome.value,
            "outcome_scope": OutcomeScope.TARGET_GLOBAL.value,
            "rows": rows,
            "target": target,
            "target_id": target_id,
            "task_hash": task.task_hash,
        },
        checks=("canonical-domain", "modular-squares", "outcome-binding"),
        guarantees=(
            "the target has an explicit root in the declared finite domain"
            if roots
            else "the complete declared finite domain contains no root",
        ),
    )
    candidate_invariants: dict[str, JSONValue] = {
        "checked": len(rows),
        "modulus": modulus,
        "roots": root_values,
        "target": target,
    }
    candidate: dict[str, JSONValue] = {
        "canonical_key": f"residue-square-table:{modulus}:{target}",
        "canonicalizer": "examples.modular-residue-table.v1",
        "equivalence_scope": "TARGET",
        "evidence": "VERIFIED",
        "invariants": candidate_invariants,
        "quality": len(rows),
        "quality_metric": "checked-residues",
    }
    candidates: list[JSONValue] = [candidate]
    return {
        "candidates": candidates,
        "certificate": normalize_json(certificate.to_dict()),
        "checked": len(rows),
        "execution_telemetry": ExecutionTelemetry(
            progress_completed=len(rows),
            progress_total=modulus,
        ).to_dict(),
        "outcome": outcome.value,
        "outcome_scope": OutcomeScope.TARGET_GLOBAL.value,
        "roots": root_values,
    }


def verify_reduced_result(task: TaskSpec, result: JSONValue) -> bool:
    """Fleet verification gate: literal True is required before campaign closure."""

    try:
        from arbogast.cert import certificate_from_dict

        if not isinstance(result, dict):
            return False
        encoded_certificate = result.get("certificate")
        if not isinstance(encoded_certificate, Mapping):
            return False
        certificate = certificate_from_dict(encoded_certificate)
        if not isinstance(certificate, VerificationCertificate):
            return False
        telemetry_value = result.get("execution_telemetry")
        if not isinstance(telemetry_value, Mapping):
            return False
        telemetry = ExecutionTelemetry.from_dict(telemetry_value)
        report = verify_residue_scan(certificate)
        if not isinstance(report, VerificationReport):
            return False
        return (
            report.valid
            and telemetry.progress_completed == task.parameters["modulus"]
            and telemetry.progress_total == task.parameters["modulus"]
            and result.get("outcome") == certificate.witness["outcome"]
            and result.get("outcome_scope") == certificate.witness["outcome_scope"]
            and certificate.witness["target_id"] == task.parameters["target_id"]
        )
    except (
        CampaignSerializationError,
        CertificateError,
        CertificateVerificationError,
        KeyError,
        LookupError,
        ValueError,
    ):
        return False


RESIDUE_OPERATION = FunctionalOperation(
    planner=plan_residues,
    runner=evaluate_residue,
    reducer=reduce_residues,
    verifier=verify_reduced_result,
    closure_verifiers=(VERIFIER,),
)


def imported_prior_claim() -> Claim:
    """Record prior catalogue knowledge without treating absence as a theorem."""

    return Claim(
        id=PRIOR_CLAIM_ID,
        statement=FormalStatement(
            "The toy prior-work catalogue contains no example for residue 3 modulo 17."
        ),
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("supplied-interview:antieau-klueners-malle-workflow", CATALOGUE_SOURCE),
        metadata={
            "scope": "teaching analogue only",
            "warning": "catalogue absence is not mathematical nonexistence",
        },
    )


def build_campaign(output: Path, prior: Claim) -> tuple[Campaign, FilesystemSink]:
    target_spec = TargetSpec(
        "mod17-residue3",
        {"modulus": MODULUS, "target": TARGET_RESIDUE},
        importance=3,
        label="Is 3 a square modulo 17?",
    )
    planning_graph: ClaimGraph | None = None

    def build_task(
        target: TargetSpec,
        provenance: TaskProvenance,
        checkpoint_ref: str | None,
    ) -> CampaignTask:
        if planning_graph is None:
            raise RuntimeError("campaign claim graph is not initialized")
        planning_provenance = provenance.merge(
            TaskProvenance(
                input_refs=(f"claim-graph:{planning_graph.digest}",),
                source_refs=(CATALOGUE_SOURCE,),
            )
        )
        return CampaignTask(
            TaskSpec(
                operation=OPERATION,
                input_refs=(f"claim-graph:{planning_graph.digest}",),
                parameters={
                    "modulus": MODULUS,
                    "target": TARGET_RESIDUE,
                    "target_id": target.target_id,
                },
            ),
            target,
            STRATEGY,
            "Replace catalogue absence with a complete finite check.",
            provenance=planning_provenance,
            checkpoint_ref=checkpoint_ref,
            capability_requirements=(CAPABILITY,),
            usefulness=5,
            information_gain=5,
            estimated_cost=17,
        )

    strategy = Strategy(
        STRATEGY,
        OPERATION,
        "Replace catalogue absence with a complete finite check.",
        capability_requirements=(CAPABILITY,),
        task_factory=build_task,
        verify_results=True,
        usefulness=5,
        information_gain=5,
        estimated_cost=17,
    )
    spec = CampaignSpec(
        "antieau-klueners-malle-local-analogue",
        objective="Replace a catalogue absence with a verified bounded mathematical outcome.",
        targets=(target_spec,),
        strategies=(strategy,),
        metadata={"scope": "local deterministic teaching analogue"},
    )
    planning_graph = ClaimGraph(
        (prior,),
        graph_id=f"campaign:{spec.campaign_id}",
    )
    sink = FilesystemSink(output / "ledger-sink")
    campaign = Campaign(
        spec,
        executor=LocalExecutor(output / "artifacts", max_workers=2),
        operations={OPERATION: RESIDUE_OPERATION},
        claims=planning_graph,
        capabilities=(CAPABILITY,),
        sinks=(sink,),
    )
    return campaign, sink


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="campaign state directory")
    return parser.parse_args()


def main() -> int:
    from arbogast.cert import certificate_from_dict, verify_certificate

    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    prior = imported_prior_claim()
    campaign, sink = build_campaign(args.output, prior)
    plan = campaign.recommend(limit=1)
    if not plan.recommendations:
        raise RuntimeError("campaign produced no capability-compatible task")
    recommendation = plan.recommendations[0]
    observation = campaign.dispatch(recommendation, raise_errors=True)
    if observation.outcome is not Outcome.SEARCH_EXHAUSTED or not observation.closes_target:
        raise RuntimeError("expected a verified exhaustive finite-domain result")
    if observation.certificate_payload is None:
        raise RuntimeError("closing observation has no replayable certificate")
    certificate = certificate_from_dict(observation.certificate_payload.to_dict())
    if not isinstance(certificate, VerificationCertificate):
        raise RuntimeError("campaign closure did not retain a verification certificate")
    closure_report = verify_certificate(certificate)
    if not closure_report.valid:
        raise RuntimeError("registered residue verifier rejected the closure certificate")

    computed_claims = tuple(
        claim
        for claim in campaign.claims
        if claim.kind is ClaimKind.COMPUTED
        and claim.metadata.get("target_id") == observation.target_id
    )
    if len(computed_claims) != 1:
        raise RuntimeError("campaign did not bind exactly one computed claim to the target")
    result_claim = computed_claims[0]
    claim_report = result_claim.verify()
    if not claim_report.verified:
        raise RuntimeError(f"campaign claim-envelope replay failed: {claim_report.error}")

    snapshot = campaign.save(args.output / "campaign.json")
    (args.output / "ledger.json").write_text(campaign.ledger.to_json() + "\n", encoding="utf-8")
    (args.output / "claims.json").write_text(
        export_json(campaign.export_claims(), pretty=True),
        encoding="utf-8",
    )
    # The sink is attached after the ledger's initial target event. Replaying the current
    # canonical events is idempotent and makes that complete event stream available there.
    for event in campaign.ledger.events:
        sink.write(
            event.to_dict(),
            kind="campaign.event",
            metadata={
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.name,
            },
        )

    replayed = Campaign.load(
        snapshot,
        executor=LocalExecutor(args.output / "artifacts", max_workers=2),
        operations={OPERATION: RESIDUE_OPERATION},
        capabilities=(CAPABILITY,),
        sinks=(sink,),
    )
    status = replayed.status()
    if status.closed_targets != 1 or status.open_targets != 0:
        raise RuntimeError("saved campaign did not replay its authoritative closed state")
    if replayed.export_claims() != campaign.export_claims():
        raise RuntimeError("saved campaign did not replay its campaign-owned claim graph")
    best_known = dict(replayed.ledger.best_known_by_metric(observation.target_id))
    candidate = best_known.get("checked-residues")
    if candidate is None:
        raise RuntimeError("campaign did not retain the per-metric best-known candidate")
    attempts = replayed.ledger.attempts_for_task(observation.task_id)
    if not attempts or attempts[-1].progress_completed != MODULUS:
        raise RuntimeError("campaign did not retain operation-reported successful progress")

    print(f"recommended strategy: {recommendation.task.strategy}")
    print(
        f"priority score: {recommendation.priority.numerator}/{recommendation.priority.denominator}"
    )
    print(f"capability matched: {CAPABILITY}")
    print(f"mathematical outcome: {observation.mathematical_outcome.value}")
    print(f"operational state: {observation.operational_state.value}")
    print(f"target closed: {observation.closes_target}")
    print(f"claim kinds: imported={prior.kind.value}, computed={result_claim.kind.value}")
    print(f"claim graph: {len(replayed.claims)} nodes, campaign-owned and replayed")
    print(f"closure verifier: {closure_report.verifier}")
    print("claim envelope: verified through campaign.claim-closure.v1")
    print(
        "best known: "
        f"{candidate.quality_metric}={candidate.quality}, "
        f"canonicalizer={candidate.canonicalizer}, "
        f"scope={candidate.equivalence_scope.value}"
    )
    print(
        f"plans/attempts: {status.recorded_plans}/{status.terminal_attempts}; "
        f"progress={attempts[-1].progress_completed}/{attempts[-1].progress_total}; "
        f"resources={dict(status.resource_usage)}"
    )
    print(f"sink records: {len(sink.records())}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
