"""Trusted runtime entry point for the template campaign."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from arbogast.bootstrap import (
    CertifiedReady,
    ReadinessProfile,
    capture_environment,
    certify_campaign_readiness,
)
from arbogast.campaign import Campaign, CampaignPlan, Outcome
from arbogast.cert import (
    VerificationCertificate,
    VerificationReport,
    VerifierRegistry,
    certificate_from_dict,
)
from arbogast.export import export_json
from arbogast.fleet import FleetOperationRegistry, LocalExecutor
from arbogast.formats import loads
from arbogast.sinks import FilesystemSink

from .specification import CAPABILITY, OPERATION, campaign_spec
from .verifiers import register_verifiers

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class CampaignRuntime:
    """Live dependencies that serialized campaign state cannot reconstruct."""

    campaign: Campaign
    operations: FleetOperationRegistry
    verifiers: VerifierRegistry
    executor: LocalExecutor
    sink: FilesystemSink


def operation_registry() -> FleetOperationRegistry:
    """Build the trusted executable registry without data-driven imports."""

    from .operations import TEMPLATE_OPERATION

    return FleetOperationRegistry({OPERATION: TEMPLATE_OPERATION})


def verifier_registry() -> VerifierRegistry:
    """Build the independent verifier registry for this campaign."""

    registry = VerifierRegistry()
    register_verifiers(registry)
    return registry


def build_runtime(output: Path) -> CampaignRuntime:
    """Construct a fresh runtime and its authoritative local custody roots."""

    operations = operation_registry()
    verifiers = verifier_registry()
    executor = LocalExecutor(output / "artifacts", operation_registry=operations)
    sink = FilesystemSink(output / "ledger-sink")
    campaign = Campaign(
        campaign_spec(),
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
        strict_readiness=True,
        capabilities=(CAPABILITY,),
        sinks=(sink,),
    )
    return CampaignRuntime(campaign, operations, verifiers, executor, sink)


def load_runtime(path: Path) -> CampaignRuntime:
    """Load campaign data only after rebuilding every trusted runtime dependency."""

    output = path.parent
    operations = operation_registry()
    verifiers = verifier_registry()
    executor = LocalExecutor(output / "artifacts", operation_registry=operations)
    sink = FilesystemSink(output / "ledger-sink")
    campaign = Campaign.load(
        path,
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
        strict_readiness=True,
        capabilities=(CAPABILITY,),
        sinks=(sink,),
    )
    return CampaignRuntime(campaign, operations, verifiers, executor, sink)


def certify_runtime(
    runtime: CampaignRuntime,
    output: Path,
) -> tuple[CertifiedReady, CampaignPlan]:
    """Certify, record, and activate readiness for one exact canonical plan."""

    plan = runtime.campaign.recommend(limit=1)
    if not plan.recommendations:
        raise RuntimeError("template campaign produced no capability-compatible plan")
    environment = capture_environment(
        project_root=PROJECT_ROOT,
        capabilities=runtime.campaign.capabilities or (),
    )
    profile = ReadinessProfile.from_plan(
        runtime.campaign,
        plan,
        runtime.operations,
        runtime.verifiers,
        runtime.executor,
    )
    result = certify_campaign_readiness(
        environment=environment,
        profile=profile,
    )
    result.verify()
    result.write_artifacts(output)
    runtime.campaign.record_environment_claim(result.claim())
    if not isinstance(result, CertifiedReady):
        raise RuntimeError(f"campaign readiness is {type(result).__name__}, not CertifiedReady")
    runtime.campaign.activate_readiness(result.certificate)
    return result, plan


def _write_campaign(runtime: CampaignRuntime, output: Path) -> Path:
    snapshot = runtime.campaign.save(output / "campaign.json")
    (output / "ledger.json").write_text(
        runtime.campaign.ledger.to_json() + "\n",
        encoding="utf-8",
    )
    (output / "claims.json").write_text(
        export_json(runtime.campaign.export_claims(), pretty=True),
        encoding="utf-8",
    )
    for event in runtime.campaign.ledger.events:
        runtime.sink.write(
            event.to_dict(),
            kind="campaign.event",
            metadata={"campaign_id": runtime.campaign.campaign_id},
        )
    return snapshot


def certify_command(output: Path) -> Path:
    """Write the readiness theorem and a campaign snapshot without dispatching work."""

    output.mkdir(parents=True, exist_ok=True)
    runtime = build_runtime(output)
    certify_runtime(runtime, output)
    return _write_campaign(runtime, output)


def run_campaign(output: Path) -> Path:
    """Certify the live runtime, dispatch the tiny plan, and preserve all evidence."""

    output.mkdir(parents=True, exist_ok=True)
    runtime = build_runtime(output)
    _, plan = certify_runtime(runtime, output)
    observation = runtime.campaign.dispatch(plan.recommendations[0], raise_errors=True)
    if observation.outcome is not Outcome.FOUND or observation.certificate_payload is None:
        raise RuntimeError("template campaign did not produce its certified positive fixture")
    certificate_path = output / "certificate.json"
    certificate_path.write_text(
        export_json(observation.certificate_payload.to_dict(), pretty=True),
        encoding="utf-8",
    )
    verify_certificate_path(certificate_path).require_valid()
    return _write_campaign(runtime, output)


def verify_certificate_path(path: Path) -> VerificationReport:
    """Replay a saved certificate without importing the discovery operation."""

    value = loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("certificate file must contain a JSON object")
    certificate = certificate_from_dict(value)
    if not isinstance(certificate, VerificationCertificate):
        raise ValueError("template verifier requires a verification certificate")
    return verifier_registry().verify(certificate)


def status(path: Path) -> dict[str, object]:
    """Return saved campaign status; runtime readiness is intentionally inactive after load."""

    return load_runtime(path).campaign.status().to_dict()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    certify = commands.add_parser("certify-readiness")
    certify.add_argument("--output", type=Path, required=True)

    run = commands.add_parser("run")
    run.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("certificate", type=Path)

    status_command = commands.add_parser("status")
    status_command.add_argument("campaign", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "certify-readiness":
        print(certify_command(args.output))
    elif args.command == "run":
        print(run_campaign(args.output))
    elif args.command == "verify":
        report = verify_certificate_path(args.certificate).require_valid()
        print(export_json(report.to_canonical(), pretty=True), end="")
    elif args.command == "status":
        print(export_json(status(args.campaign), pretty=True), end="")
    else:
        raise AssertionError(f"unhandled command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
