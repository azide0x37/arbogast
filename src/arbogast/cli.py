"""The stable, dependency-free Arbogast command-line interface."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from arbogast.agent import (
    CapabilityGraph,
    CapabilityRouteError,
    OperationLookupError,
    describe_operation,
    operation_descriptions,
)
from arbogast.claims import Claim, ClaimGraph
from arbogast.fleet import (
    FleetExecutionError,
    FleetOperationRegistryError,
    LeaseCustodyError,
    NoEligibleWorkerError,
    WorkerPoolExecutor,
    automatic_local_worker_pool,
    default_fleet_operation_registry,
)
from arbogast.formats import (
    CLI_BACKENDS_SCHEMA,
    CLI_CAMPAIGN_SCHEMA,
    CLI_CLAIMS_SCHEMA,
    CLI_DESCRIBE_SCHEMA,
    CLI_PROOF_GAP_SCHEMA,
    CLI_ROUTE_SCHEMA,
    CLI_VERIFY_SCHEMA,
    CLI_VERSION_SCHEMA,
    CanonicalJSONError,
    JSONValue,
    canonical_dumps,
    loads,
    normalize_json,
)
from arbogast.proof import ProofGap, ProofObligation


class CLIError(RuntimeError):
    """A user-actionable command failure."""


def _version() -> str:
    try:
        return importlib.metadata.version("arbogast")
    except importlib.metadata.PackageNotFoundError:
        module = importlib.import_module("arbogast")
        return str(getattr(module, "__version__", "0+unknown"))


def _jsonable(value: object) -> JSONValue:
    """Project semantic records without weakening strict canonical JSON."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # Delegating to normalize_json produces the shared exact-boundary error.
        return normalize_json(value)
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CLIError("stable JSON objects require string keys")
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    for method_name in ("to_dict", "to_canonical", "to_canonical_data"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _jsonable(method())
    raise CLIError(f"cannot serialize {type(value).__qualname__} to stable JSON")


def _emit_json(value: object) -> None:
    print(canonical_dumps(_jsonable(value)))


def _read_json(path: str) -> Mapping[str, object]:
    try:
        decoded = loads(Path(path).read_bytes())
    except OSError as error:
        raise CLIError(f"cannot read {path!r}: {error}") from error
    except CanonicalJSONError as error:
        raise CLIError(f"invalid JSON in {path!r}: {error}") from error
    if not isinstance(decoded, dict):
        raise CLIError(f"{path!r} must contain a JSON object")
    return decoded


def _cmd_version(args: argparse.Namespace) -> int:
    version = _version()
    if args.json:
        _emit_json({"schema": CLI_VERSION_SCHEMA, "version": version})
    else:
        print(version)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Emit one bounded, non-authoritative environment diagnostic."""

    from arbogast.bootstrap import environment_preflight

    try:
        report = environment_preflight(args.mode)
        payload = report.to_dict()
    except Exception as error:
        raise CLIError(f"doctor diagnostic failed: {type(error).__name__}: {error}") from error
    _emit_json(payload)
    return 0 if report.ready else 1


def _cmd_backends(args: argparse.Namespace) -> int:
    """Report a backend status, using its explicit detailed probe when available."""

    from arbogast.backends import DEFAULT_BACKENDS

    if args.name is not None:
        try:
            backend = DEFAULT_BACKENDS.get(args.name)
        except KeyError as error:
            raise CLIError(str(error)) from error
        probe = getattr(backend, "probe", None)
        try:
            result = probe() if callable(probe) else backend.status()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise CLIError(f"backend {args.name!r} probe failed: {error}") from error
        payload = {"backend": _jsonable(result), "schema": CLI_BACKENDS_SCHEMA}
        if args.json:
            _emit_json(payload)
        else:
            status = getattr(result, "status", result)
            available = bool(getattr(status, "available", False))
            version = getattr(status, "version", None)
            summary = "available" if available else "unavailable"
            print(f"{args.name.lower()}: {summary}" + (f" ({version})" if version else ""))
        return 0

    statuses = tuple(DEFAULT_BACKENDS.statuses())
    payload = {
        "backend": [_jsonable(status) for status in statuses],
        "schema": CLI_BACKENDS_SCHEMA,
    }
    if args.json:
        _emit_json(payload)
    else:
        for status in statuses:
            summary = "available" if status.available else "unavailable"
            print(f"{status.name}: {summary}" + (f" ({status.version})" if status.version else ""))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    # Keep non-describe CLI startup independent of the mathematical registry imports.
    from arbogast.specs import OperationSpecError

    try:
        description = describe_operation(args.operation)
    except (OperationLookupError, OperationSpecError) as error:
        raise CLIError(f"unknown operation: {args.operation}") from error
    if args.json:
        _emit_json(
            {
                "operation": description.to_dict(),
                "schema": CLI_DESCRIBE_SCHEMA,
            }
        )
        return 0
    print(description.name)
    if description.summary:
        print(f"  {description.summary}")
    if description.inputs:
        print(f"  inputs: {', '.join(description.inputs)}")
    if description.outputs:
        print(f"  outputs: {', '.join(description.outputs)}")
    if description.preconditions:
        print("  preconditions:")
        for item in description.preconditions:
            print(f"    - {item}")
    if description.guarantees:
        print("  mathematical guarantees:")
        for item in description.guarantees:
            print(f"    - {item}")
    if description.failure_modes:
        print("  failure modes:")
        for item in description.failure_modes:
            print(f"    - {item}")
    return 0


def _load_builtin_verifiers() -> None:
    """Import lightweight certificate modules that explicitly self-register."""

    for module_name in (
        "arbogast.arithmetic.semantic",
        "arbogast.backends.pari_certificate",
        "arbogast.cohom.five_term",
        "arbogast.cohom.map_certificate",
        "arbogast.cohom.semantic",
        "arbogast.galois.groups",
        "arbogast.galois.modules",
        "arbogast.galois.proof",
        "arbogast.galois.semantic",
        "arbogast.hurwitz.claims",
    ):
        try:
            importlib.import_module(module_name)
        except ImportError:
            continue


def _cmd_verify(args: argparse.Namespace) -> int:
    from arbogast.cert import (
        CertificateError,
        CertificateVerificationError,
        UnknownVerifierError,
        certificate_from_dict,
        verify_certificate,
    )

    try:
        encoded = Path(args.certificate).read_bytes()
    except OSError as error:
        raise CLIError(f"cannot read {args.certificate!r}: {error}") from error
    _load_builtin_verifiers()
    try:
        decoded = loads(encoded)
    except CanonicalJSONError as error:
        payload = {
            "certificate": args.certificate,
            "error": str(error),
            "schema": CLI_VERIFY_SCHEMA,
            "valid": False,
        }
        if args.json:
            _emit_json(payload)
        else:
            print(f"INVALID: {error}")
        return 1
    if isinstance(decoded, dict) and decoded.get("schema_version") == "arbogast.cohomology.v1":
        from arbogast.cohom import CohomologyCertificate

        try:
            domain_certificate = CohomologyCertificate.from_dict(decoded)
            domain_report = domain_certificate.verify(raise_on_error=False)
        except (TypeError, ValueError) as error:
            payload = {
                "certificate": args.certificate,
                "error": str(error),
                "schema": CLI_VERIFY_SCHEMA,
                "valid": False,
            }
            if args.json:
                _emit_json(payload)
            else:
                print(f"INVALID: {error}")
            return 1
        payload = {
            "certificate_id": f"sha256:{domain_certificate.content_hash}",
            "checks": list(domain_report.checks),
            "details": {
                "degree": domain_certificate.degree,
                "dimension": domain_certificate.dimension,
            },
            "error": domain_report.error,
            "schema": CLI_VERIFY_SCHEMA,
            "valid": domain_report.ok,
            "verifier": "arbogast.cohom.CohomologyCertificate.verify",
        }
        if args.json:
            _emit_json(payload)
        elif domain_report.ok:
            print(f"VALID sha256:{domain_certificate.content_hash} (cohomology)")
        else:
            print(f"INVALID sha256:{domain_certificate.content_hash}: {domain_report.error}")
        return 0 if domain_report.ok else 1
    try:
        if not isinstance(decoded, dict):
            raise CertificateError("certificate JSON must contain an object")
        certificate = certificate_from_dict(decoded)
        report = verify_certificate(
            certificate,
            verifier_name=args.verifier,
            raise_on_failure=False,
        )
    except (CertificateError, CertificateVerificationError, UnknownVerifierError) as error:
        payload = {
            "certificate": args.certificate,
            "error": str(error),
            "schema": CLI_VERIFY_SCHEMA,
            "valid": False,
        }
        if args.json:
            _emit_json(payload)
        else:
            print(f"INVALID: {error}")
        return 1
    payload = {
        "certificate_id": report.certificate_id,
        "checks": list(report.checks),
        "details": _jsonable(report.details),
        "error": report.error,
        "schema": CLI_VERIFY_SCHEMA,
        "valid": report.valid,
        "verifier": report.verifier,
    }
    if args.json:
        _emit_json(payload)
    elif report.valid:
        print(f"VALID {report.certificate_id} ({report.verifier})")
    else:
        print(f"INVALID {report.certificate_id}: {report.error}")
    return 0 if report.valid else 1


def _load_claims(path: str) -> tuple[object, ...]:
    document = _read_json(path)
    schema = document.get("schema_version")
    try:
        from arbogast.claims import ClaimGraph

        return tuple(ClaimGraph.from_dict(document).claims)
    except ImportError as error:
        if schema is not None:
            raise CLIError(f"cannot load schema-bearing claim graph: {error}") from error
    except (KeyError, TypeError, ValueError) as error:
        if schema is not None:
            raise CLIError(f"invalid {schema} claim graph: {error}") from error
    if schema is None:
        raw = document.get("claims")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise CLIError("claim document must contain a 'claims' array") from None
        if any(not isinstance(item, Mapping) for item in raw):
            raise CLIError("every claim must be a JSON object") from None
        return tuple(raw)
    raise CLIError(f"unsupported claim graph schema: {schema}")


def _claim_field(claim: object, name: str) -> str | None:
    value = claim.get(name) if isinstance(claim, Mapping) else getattr(claim, name, None)
    if isinstance(value, Enum):
        value = value.value
    return None if value is None else str(value)


def _cmd_claims(args: argparse.Namespace) -> int:
    claims = _load_claims(args.file)
    statuses = set(args.status or ())
    kinds = set(args.kind or ())
    selected = tuple(
        claim
        for claim in claims
        if (
            not statuses
            or _claim_field(claim, "status") in statuses
            or _claim_field(claim, "kind") in statuses
        )
        and (not kinds or _claim_field(claim, "kind") in kinds)
    )
    payload = {
        "claims": [_jsonable(claim) for claim in selected],
        "count": len(selected),
        "filters": {
            "kind": sorted(kinds),
            "status": sorted(statuses),
        },
        "schema": CLI_CLAIMS_SCHEMA,
    }
    if args.json:
        _emit_json(payload)
    else:
        for claim in selected:
            claim_id = _claim_field(claim, "id") or "<unnamed>"
            kind = _claim_field(claim, "kind") or "unknown"
            status = _claim_field(claim, "status") or "unknown"
            print(f"{claim_id}\t{kind}\t{status}")
    return 0


def _proof_gaps(document: Mapping[str, object], claim_id: str | None) -> tuple[ProofGap, ...]:
    """Decode only canonical theorem-boundary schemas; never guess from field names."""

    schema = document.get("schema_version")
    try:
        if schema == ClaimGraph.schema_version:
            graph = ClaimGraph.from_dict(document)
            if claim_id is not None:
                if claim_id not in graph:
                    raise CLIError(f"unknown claim in proof document: {claim_id}")
                claim = graph.get(claim_id)
                return (claim.formalization,) if claim.formalization is not None else ()
            return tuple(
                claim.formalization for claim in graph.claims if claim.formalization is not None
            )
        from arbogast.claims import CLAIM_SCHEMA_V1, CLAIM_SCHEMA_V2

        if schema in {CLAIM_SCHEMA_V1, CLAIM_SCHEMA_V2}:
            claim = Claim.from_dict(document)
            if claim_id is not None and claim_id != claim.id:
                raise CLIError(f"unknown claim in proof document: {claim_id}")
            return (claim.formalization,) if claim.formalization is not None else ()
        if schema == ProofGap.schema_version:
            gap = ProofGap.from_dict(document)
            if claim_id is not None and claim_id != gap.claim_id:
                raise CLIError(
                    f"proof gap is bound to {gap.claim_id!r}, not requested claim {claim_id!r}"
                )
            return (gap,)
    except CLIError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CLIError(f"invalid {schema or 'unknown'} proof document: {error}") from error
    raise CLIError(
        "proof-gap expects an arbogast.claim-graph/v1, arbogast.claim/v1, "
        "arbogast.claim/v2, or arbogast.proof-gap/v1 document"
    )


def _proof_obligation_payload(claim_id: str, obligation: ProofObligation) -> dict[str, object]:
    return {"claim_id": claim_id, **obligation.to_dict()}


def _cmd_proof_gap(args: argparse.Namespace) -> int:
    document = _read_json(args.file)
    gaps = _proof_gaps(document, args.claim)
    obligations = tuple(
        (gap.claim_id, obligation) for gap in gaps for obligation in gap.obligations
    )
    counts = Counter(obligation.classification.value.upper() for _, obligation in obligations)
    summary = {name: counts[name] for name in sorted(counts)}
    selected_claim = args.claim
    if selected_claim is None and len(gaps) == 1:
        selected_claim = gaps[0].claim_id
    payload = {
        "claim": selected_claim,
        "obligations": [
            _proof_obligation_payload(owner, obligation) for owner, obligation in obligations
        ],
        "schema": CLI_PROOF_GAP_SCHEMA,
        "summary": {
            "by_class": summary,
            "total": len(obligations),
        },
    }
    if args.json:
        _emit_json(payload)
    else:
        print(f"{len(obligations)} obligations total")
        for name, count in summary.items():
            print(f"{count:>4} {name}")
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    graph = CapabilityGraph.from_operations(operation_descriptions())
    try:
        route = graph.route(
            args.source,
            args.target,
            include_unimplemented=args.include_unimplemented,
        )
    except CapabilityRouteError as error:
        raise CLIError(str(error)) from error
    if args.json:
        _emit_json({"route": route.to_dict(), "schema": CLI_ROUTE_SCHEMA})
    else:
        print(route.source)
        for step in route.steps:
            suffix = " [UNIMPLEMENTED]" if not step.implemented else ""
            print(f"  -> {step.operation} -> {step.target}{suffix}")
    return 0


def _campaign_api() -> tuple[Any, Any, type[Exception], Any]:
    """Load the campaign surface only when a campaign command is requested."""

    try:
        campaign_module = importlib.import_module("arbogast.campaign")
        campaign_type = campaign_module.Campaign
        objective_type = campaign_module.Objective
        campaign_error = campaign_module.CampaignError
        observation_type = campaign_module.Observation
    except (ImportError, AttributeError) as error:
        raise CLIError("campaign support is not installed or is incomplete") from error
    return campaign_type, objective_type, campaign_error, observation_type


def _load_campaign(path: str, *, fleet: str = "off") -> Any:
    campaign_type, _, campaign_error, _ = _campaign_api()
    runtime: dict[str, object] = {}
    if fleet == "auto":
        registry = default_fleet_operation_registry()
        runtime["executor"] = WorkerPoolExecutor(
            automatic_local_worker_pool(),
            f"{path}.fleet",
            operation_registry=registry,
        )
    elif fleet != "off":
        raise CLIError(f"unsupported fleet mode: {fleet!r}")
    try:
        return campaign_type.load(path, **runtime)
    except (OSError, CanonicalJSONError, campaign_error) as error:
        raise CLIError(f"cannot load campaign {path!r}: {error}") from error


def _campaign_payload(command: str, campaign: Any, result: object) -> dict[str, object]:
    return {
        "campaign_id": campaign.campaign_id,
        "command": command,
        "result": result,
        "schema": CLI_CAMPAIGN_SCHEMA,
    }


def _cmd_campaign_init(args: argparse.Namespace) -> int:
    campaign_type, objective_type, campaign_error, _ = _campaign_api()
    statement = args.objective or args.name
    try:
        objective = objective_type(statement, tuple(args.success_criterion or ()))
        campaign = campaign_type(args.name, objective=objective)
        campaign.save(args.file)
    except (OSError, campaign_error, TypeError, ValueError) as error:
        raise CLIError(f"cannot initialize campaign: {error}") from error
    payload = _campaign_payload("campaign.init", campaign, campaign.status().to_dict())
    if args.json:
        _emit_json(payload)
    else:
        print(f"initialized {campaign.name} at {args.file}")
    return 0


def _cmd_campaign_plan(args: argparse.Namespace) -> int:
    campaign = _load_campaign(args.file)
    _, _, campaign_error, _ = _campaign_api()
    try:
        plan = campaign.recommend(limit=args.limit)
        # Planning appends canonical task-planned events; persist them.
        campaign.save(args.file)
    except (OSError, campaign_error) as error:
        raise CLIError(f"cannot plan campaign: {error}") from error
    payload = _campaign_payload("plan", campaign, plan.to_dict())
    if args.json:
        _emit_json(payload)
    else:
        print(f"{len(plan.recommendations)} recommendations")
        for recommendation in plan.recommendations:
            print(
                f"{recommendation.action.value}\t"
                f"{recommendation.task.target.key}\t"
                f"{recommendation.task.strategy}"
            )
    return 0


def _cmd_campaign_status(args: argparse.Namespace) -> int:
    campaign = _load_campaign(args.file)
    status = campaign.status()
    payload = _campaign_payload("status", campaign, status.to_dict())
    if args.json:
        _emit_json(payload)
    else:
        print(f"{status.name}: {status.closed_targets}/{status.target_count} targets closed")
        print(f"tasks: {status.task_count} total, {status.pending_tasks} pending")
    return 0


def _cmd_campaign_target(args: argparse.Namespace) -> int:
    campaign = _load_campaign(args.file)
    _, _, campaign_error, _ = _campaign_api()
    try:
        explanation = campaign.explain(args.target)
        # Explanation includes recommendations and can materialize planned tasks.
        campaign.save(args.file)
    except (OSError, campaign_error) as error:
        raise CLIError(f"cannot explain target {args.target!r}: {error}") from error
    payload = _campaign_payload("target.explain", campaign, explanation.to_dict())
    if args.json:
        _emit_json(payload)
    else:
        state = explanation.state
        print(f"{state.target.key}: {state.status.value} ({state.mathematical_outcome.value})")
        print(f"observations: {len(explanation.observations)}")
        print(f"recommendations: {len(explanation.recommendations)}")
    return 0


def _cmd_campaign_run(args: argparse.Namespace) -> int:
    campaign = _load_campaign(args.file, fleet=args.fleet)
    _, _, campaign_error, _ = _campaign_api()
    try:
        runs = campaign.run(limit=args.limit)
        campaign.save(args.file)
    except (
        OSError,
        campaign_error,
        FleetExecutionError,
        FleetOperationRegistryError,
        LeaseCustodyError,
        NoEligibleWorkerError,
    ) as error:
        raise CLIError(
            "campaign run is unavailable without locally injected fleet operations "
            f"(or a trusted runtime registry) and eligible workers: {error}"
        ) from error
    payload = _campaign_payload("run", campaign, [run.to_dict() for run in runs])
    if args.json:
        _emit_json(payload)
    else:
        print(f"completed {len(runs)} local fleet runs")
    return 0


def _cmd_campaign_harvest(args: argparse.Namespace) -> int:
    if args.observation is None:
        raise CLIError(
            "CLI harvest cannot reconstruct a live FleetRun; provide --observation "
            "with a strict, certificate-bearing Observation document"
        )
    campaign = _load_campaign(args.file)
    _, _, campaign_error, observation_type = _campaign_api()
    document = _read_json(args.observation)
    try:
        observation = observation_type.from_dict(document)
        campaign.observe(observation)
        campaign.save(args.file)
    except (OSError, campaign_error, TypeError, ValueError) as error:
        raise CLIError(f"cannot harvest observation: {error}") from error
    payload = _campaign_payload("harvest", campaign, observation.to_dict())
    if args.json:
        _emit_json(payload)
    else:
        print(f"recorded observation {observation.observation_id}")
    return 0


def _cmd_campaign_export(args: argparse.Namespace) -> int:
    campaign = _load_campaign(args.file)
    if args.kind != "claims":
        raise CLIError(f"unsupported campaign export kind: {args.kind}")
    result = campaign.export_claims()
    if args.output is not None:
        try:
            Path(args.output).write_text(canonical_dumps(result), encoding="utf-8")
        except OSError as error:
            raise CLIError(f"cannot write claim export {args.output!r}: {error}") from error
    if args.json or args.output is None:
        _emit_json(result)
    else:
        claims = result.get("claims", [])
        count = len(claims) if isinstance(claims, list) else 0
        print(f"exported {count} verified claims to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbogast",
        description="Certificate-first finite exact computational mathematics",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    version = commands.add_parser("version", help="show the Arbogast release version")
    version.add_argument("--json", action="store_true", help="emit stable JSON")
    version.set_defaults(handler=_cmd_version)

    doctor = commands.add_parser("doctor", help="diagnose bounded environment readiness")
    doctor.add_argument("--mode", choices=("campaign", "core", "replay"), required=True)
    doctor.add_argument("--json", action="store_true", required=True, help="emit stable JSON")
    doctor.set_defaults(handler=_cmd_doctor)

    backends = commands.add_parser("backends", help="probe optional algebra backends")
    backends.add_argument("--name", help="probe one backend by name")
    backends.add_argument("--json", action="store_true", help="emit stable JSON")
    backends.set_defaults(handler=_cmd_backends)

    describe = commands.add_parser("describe", help="describe a semantic operation")
    describe.add_argument("operation")
    describe.add_argument("--json", action="store_true", help="emit stable JSON")
    describe.set_defaults(handler=_cmd_describe)

    verify = commands.add_parser("verify", help="independently verify a certificate")
    verify.add_argument("certificate")
    verify.add_argument("--verifier", help="select an explicitly registered verifier")
    verify.add_argument("--json", action="store_true", help="emit stable JSON")
    verify.set_defaults(handler=_cmd_verify)

    claims = commands.add_parser("claims", help="filter a serialized claim graph")
    claims.add_argument("file")
    claims.add_argument("--status", action="append", help="filter epistemic status or claim kind")
    claims.add_argument("--kind", action="append", help="filter claim kind")
    claims.add_argument("--json", action="store_true", help="emit stable JSON")
    claims.set_defaults(handler=_cmd_claims)

    proof_gap = commands.add_parser("proof-gap", help="summarize finite proof obligations")
    proof_gap.add_argument("file")
    proof_gap.add_argument("--claim", help="restrict to one claim id")
    proof_gap.add_argument("--json", action="store_true", help="emit stable JSON")
    proof_gap.set_defaults(handler=_cmd_proof_gap)

    route = commands.add_parser("route", help="find a semantic capability route")
    route.add_argument("--from", dest="source", required=True, help="source semantic type")
    route.add_argument("--to", dest="target", required=True, help="target semantic type")
    route.add_argument("--include-unimplemented", action="store_true")
    route.add_argument("--json", action="store_true", help="emit stable JSON")
    route.set_defaults(handler=_cmd_route)

    campaign = commands.add_parser("campaign", help="manage persisted research campaigns")
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True)
    campaign_init = campaign_commands.add_parser("init", help="initialize a campaign file")
    campaign_init.add_argument("name")
    campaign_init.add_argument("file")
    campaign_init.add_argument("--objective", help="mathematical objective statement")
    campaign_init.add_argument(
        "--success-criterion",
        action="append",
        help="explicit objective success criterion (repeatable)",
    )
    campaign_init.add_argument("--json", action="store_true", help="emit stable JSON")
    campaign_init.set_defaults(handler=_cmd_campaign_init)

    plan = commands.add_parser("plan", help="recommend deterministic campaign tasks")
    plan.add_argument("file", help="persisted campaign JSON")
    plan.add_argument("--limit", type=int)
    plan.add_argument("--json", action="store_true", help="emit stable JSON")
    plan.set_defaults(handler=_cmd_campaign_plan)

    run = commands.add_parser("run", help="run a campaign through trusted local operations")
    run.add_argument("file", help="persisted campaign JSON")
    run.add_argument(
        "--fleet",
        choices=("off", "auto"),
        default="off",
        help="use the audited automatic local worker/operation registry",
    )
    run.add_argument("--limit", type=int)
    run.add_argument("--json", action="store_true", help="emit stable JSON")
    run.set_defaults(handler=_cmd_campaign_run)

    status = commands.add_parser("status", help="show authoritative campaign status")
    status.add_argument("file", help="persisted campaign JSON")
    status.add_argument("--json", action="store_true", help="emit stable JSON")
    status.set_defaults(handler=_cmd_campaign_status)

    target = commands.add_parser("target", help="inspect one campaign target")
    target.add_argument("file", help="persisted campaign JSON")
    target.add_argument("target", help="target content id or unique key")
    target.add_argument("--explain", action="store_true", required=True)
    target.add_argument("--json", action="store_true", help="emit stable JSON")
    target.set_defaults(handler=_cmd_campaign_target)

    harvest = commands.add_parser("harvest", help="record a strict external observation")
    harvest.add_argument("file", help="persisted campaign JSON")
    harvest.add_argument("--observation", help="strict Observation JSON document")
    harvest.add_argument("--json", action="store_true", help="emit stable JSON")
    harvest.set_defaults(handler=_cmd_campaign_harvest)

    export = commands.add_parser("export", help="export campaign products")
    export.add_argument("kind", choices=("claims",))
    export.add_argument("file", help="persisted campaign JSON")
    export.add_argument("output", nargs="?", help="optional output file")
    export.add_argument("--json", action="store_true", help="emit stable JSON")
    export.set_defaults(handler=_cmd_campaign_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except CLIError as error:
        print(f"arbogast: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
