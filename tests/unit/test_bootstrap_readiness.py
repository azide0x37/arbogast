from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arbogast.backends import PYTHON
from arbogast.bootstrap import (
    READINESS_VERIFIER,
    BootstrapError,
    CertifiedBlocked,
    CertifiedReady,
    EnvironmentSnapshot,
    ObligationStatus,
    ReadinessProfile,
    ReadinessReceipt,
    ReadinessScope,
    ReadinessVerdict,
    RuntimeBinding,
    Unsupported,
    capture_environment,
    certify_campaign_readiness,
    validate_readiness_activation,
    verify_readiness_certificate,
)
from arbogast.cert import (
    CertificateVerificationError,
    VerificationCertificate,
    VerifierRegistry,
    certificate_from_dict,
    default_verifiers,
    freeze_mapping,
)
from arbogast.claims import ClaimDomain
from arbogast.fleet import (
    ArtifactStore,
    FleetOperationRegistry,
    FunctionalOperation,
    LocalExecutor,
    RetryPolicy,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerPool,
    WorkerPoolExecutor,
)
from arbogast.formats import JSONValue, canonical_sha256


def _planner(_task: TaskSpec) -> tuple[str, ...]:
    return ("only",)


def _runner(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
    return {"shard": shard.key}


def _reducer(_task: TaskSpec, partials: tuple[JSONValue, ...]) -> dict[str, object]:
    return {"count": len(partials)}


def _closure_verifier(_certificate: VerificationCertificate) -> bool:
    return True


def _content_id(label: str) -> str:
    return f"sha256:{canonical_sha256({'label': label})}"


@dataclass(frozen=True)
class _CampaignTask:
    task: TaskSpec
    campaign_task_id: str
    capability_requirements: tuple[str, ...] = ()
    checkpoint_ref: str | None = None


@dataclass(frozen=True)
class _Plan:
    tasks: tuple[_CampaignTask, ...]
    plan_id: str


@dataclass(frozen=True)
class _Campaign:
    campaign_id: str
    capabilities: frozenset[str]


@dataclass(frozen=True)
class _Bundle:
    campaign: _Campaign
    plan: _Plan
    operations: object
    verifiers: VerifierRegistry
    executor: LocalExecutor
    environment: EnvironmentSnapshot
    profile: ReadinessProfile


def _bundle(
    tmp_path: Path,
    *,
    operation_registry: object | None = None,
    optional_capabilities: tuple[str, ...] = (),
    required_capabilities: tuple[str, ...] = (),
) -> _Bundle:
    operation = FunctionalOperation(
        planner=_planner,
        runner=_runner,
        reducer=_reducer,
    )
    default_operations = FleetOperationRegistry({"tests.ready": operation})
    operations = default_operations if operation_registry is None else operation_registry
    executor = LocalExecutor(
        ArtifactStore(tmp_path / "artifacts"),
        operation_registry=default_operations,
    )
    verifiers = VerifierRegistry()
    verifiers.register("tests.closure", VerificationCertificate, _closure_verifier)
    task = _CampaignTask(
        TaskSpec("tests.ready"),
        _content_id("task"),
        capability_requirements=required_capabilities,
    )
    plan = _Plan((task,), _content_id("plan"))
    campaign = _Campaign(_content_id("campaign"), frozenset(required_capabilities))
    environment = capture_environment(
        project_root=Path(__file__).parents[2],
        capabilities=campaign.capabilities,
    )
    profile = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
        required_verifiers=("tests.closure",),
        optional_capabilities=optional_capabilities,
    )
    return _Bundle(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
        environment,
        profile,
    )


def test_ready_result_strict_roundtrips_claim_and_artifacts(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert isinstance(result, CertifiedReady)
    assert result.verify().valid
    assert EnvironmentSnapshot.from_dict(result.environment.to_dict()) == result.environment
    assert ReadinessProfile.from_dict(result.profile.to_dict()) == result.profile
    assert ReadinessReceipt.from_dict(result.receipt.to_dict()) == result.receipt
    decoded = certificate_from_dict(result.certificate.to_dict())
    assert decoded == result.certificate
    claim = result.claim()
    assert claim.domain is ClaimDomain.ENVIRONMENTAL
    assert claim.why == ()
    assert claim.verify().verified
    assert result.claim_graph().verify().verified

    paths = result.write_artifacts(tmp_path / "bootstrap")
    assert set(paths) == {
        "bootstrap-report.json",
        "environment-snapshot.json",
        "readiness-certificate.json",
        "readiness-claim.json",
        "readiness-profile.json",
    }
    assert all(path.is_file() for path in paths.values())

    manifest = default_verifiers.readiness_manifest(
        (READINESS_VERIFIER,),
        load_builtins=True,
    )
    assert manifest["verifiers"][0]["certifiable"] is True


def test_optional_missing_capability_does_not_block_ready(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, optional_capabilities=("optional.not-installed",))
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert isinstance(result, CertifiedReady)
    capability = next(
        item for item in result.receipt.obligations if item.id == "capabilities.cover-plan"
    )
    assert capability.status is ObligationStatus.SATISFIED
    assert capability.evidence["missing_optional_capabilities"] == ("optional.not-installed",)


def test_exact_missing_operation_is_certified_blocked(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, operation_registry=FleetOperationRegistry())
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert isinstance(result, CertifiedBlocked)
    assert result.verdict is ReadinessVerdict.BLOCKED
    assert {item.id for item in result.blockers} == {"operation-registry.covers-plan"}
    assert result.verify().valid


class _CrashingRegistry:
    def names(self) -> tuple[str, ...]:
        return ("tests.ready",)

    def readiness_manifest(self, _names: object) -> object:
        raise RuntimeError("manifest probe crashed")


class _UnsupportedRegistry:
    def names(self) -> tuple[str, ...]:
        return ("tests.ready",)


def test_manifest_probe_crash_is_unknown_not_blocked(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, operation_registry=_CrashingRegistry())
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert type(result).__name__ == "Unknown"
    assert result.verdict is ReadinessVerdict.UNKNOWN
    assert not result.blockers
    assert result.verify().valid


def test_missing_manifest_interface_is_unsupported(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, operation_registry=_UnsupportedRegistry())
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert isinstance(result, Unsupported)
    assert result.verdict is ReadinessVerdict.UNSUPPORTED
    assert result.verify().valid


def test_receipt_required_status_and_verdict_tampering_is_rejected(tmp_path: Path) -> None:
    result = certify_campaign_readiness(
        environment=(bundle := _bundle(tmp_path)).environment,
        profile=bundle.profile,
    )
    obligations = result.receipt.obligations

    with pytest.raises(BootstrapError, match="required flags"):
        replace(
            result.receipt,
            obligations=(replace(obligations[0], required=False), *obligations[1:]),
        )
    with pytest.raises(BootstrapError, match="verdict"):
        replace(
            result.receipt,
            obligations=(
                replace(obligations[0], status=ObligationStatus.UNSATISFIED),
                *obligations[1:],
            ),
        )
    with pytest.raises(BootstrapError, match="verdict"):
        replace(result.receipt, verdict=ReadinessVerdict.BLOCKED)


def test_result_variant_cannot_wrap_another_verdict(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    changed = replace(bundle.environment, arbogast_version="999.0")
    blocked = certify_campaign_readiness(environment=changed, profile=bundle.profile)
    assert isinstance(blocked, CertifiedBlocked)

    with pytest.raises(BootstrapError, match="requires verdict READY"):
        CertifiedReady(
            blocked.environment,
            blocked.profile,
            blocked.receipt,
            blocked.certificate,
        )


def test_activation_recomputes_live_bindings_and_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path)
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )
    report = validate_readiness_activation(
        result.certificate,
        campaign=bundle.campaign,
        plan=bundle.plan,
        operation_registry=bundle.operations,
        verifier_registry=bundle.verifiers,
        executor=bundle.executor,
    )
    assert report.valid

    changed = replace(
        bundle.environment,
        capabilities=tuple(sorted((*bundle.environment.capabilities, "environment.changed"))),
        declared_capabilities=tuple(
            sorted((*bundle.environment.declared_capabilities, "environment.changed"))
        ),
    )
    monkeypatch.setattr(
        "arbogast.bootstrap.capture.capture_environment",
        lambda **_kwargs: changed,
    )
    stale = validate_readiness_activation(
        result.certificate,
        campaign=bundle.campaign,
        plan=bundle.plan,
        operation_registry=bundle.operations,
        verifier_registry=bundle.verifiers,
        executor=bundle.executor,
    )
    assert not stale.valid
    assert "current environment identity" in stale.blockers[-1]


def test_claim_ids_distinguish_environments_for_same_profile(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    first = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )
    changed = replace(
        bundle.environment,
        capabilities=tuple(sorted((*bundle.environment.capabilities, "another-capability"))),
        declared_capabilities=tuple(
            sorted((*bundle.environment.declared_capabilities, "another-capability"))
        ),
    )
    second = certify_campaign_readiness(environment=changed, profile=bundle.profile)

    assert first.profile.profile_id == second.profile.profile_id
    assert first.claim().id != second.claim().id
    assert first.claim().what != second.claim().what


def test_fresh_process_evidence_tamper_rejects_certificate(tmp_path: Path) -> None:
    result = certify_campaign_readiness(
        environment=(bundle := _bundle(tmp_path)).environment,
        profile=bundle.profile,
    )
    receipt = result.receipt.to_dict()
    fresh = next(
        item for item in receipt["obligations"] if item["id"] == "fresh-process.fixture-replays"
    )
    fresh["evidence"]["python_executable"] = "/tampered/python"
    witness = result.certificate.witness.to_dict()
    witness["readiness_receipt"] = receipt
    tampered = VerificationCertificate.create(
        subject=result.certificate.subject,
        verifier=result.certificate.verifier,
        claim_id=result.certificate.claim_id,
        statement_hash=result.certificate.statement_hash,
        claim_boundary_hash=result.certificate.claim_boundary_hash,
        witness=witness,
        checks=result.certificate.checks,
        guarantees=result.certificate.guarantees,
    )

    with pytest.raises(CertificateVerificationError):
        from arbogast.bootstrap import verify_readiness_certificate

        verify_readiness_certificate(tampered)


def test_self_consistent_artifact_transcript_forgery_is_rejected(tmp_path: Path) -> None:
    from arbogast.bootstrap.readiness import _certificate_for

    result = certify_campaign_readiness(
        environment=(bundle := _bundle(tmp_path)).environment,
        profile=bundle.profile,
    )
    artifact = next(
        item for item in result.receipt.obligations if item.id == "artifact-store.roundtrip"
    )
    forged_bytes = b"self-consistent but foreign fixture"
    evidence = artifact.evidence.to_dict()
    evidence["input_hex"] = forged_bytes.hex()
    evidence["returned_hex"] = forged_bytes.hex()
    reference = evidence["reference"]
    reference["digest"] = hashlib.sha256(forged_bytes).hexdigest()
    reference["size"] = len(forged_bytes)
    forged_artifact = replace(artifact, evidence=freeze_mapping(evidence))
    forged_receipt = replace(
        result.receipt,
        obligations=tuple(
            forged_artifact if item.id == artifact.id else item
            for item in result.receipt.obligations
        ),
    )
    forged_certificate = _certificate_for(forged_receipt)

    with pytest.raises(CertificateVerificationError):
        verify_readiness_certificate(forged_certificate)


@pytest.mark.parametrize(
    ("binding_field", "entries_key", "kind"),
    (
        ("operation_registry", "operations", "operation-registry"),
        ("verifier_registry", "verifiers", "verifier-registry"),
    ),
)
def test_self_consistent_redundant_manifest_digest_forgery_is_rejected(
    tmp_path: Path,
    binding_field: str,
    entries_key: str,
    kind: str,
) -> None:
    result = certify_campaign_readiness(
        environment=(bundle := _bundle(tmp_path)).environment,
        profile=bundle.profile,
    )
    receipt = result.receipt.to_dict()
    profile = receipt["profile"]
    binding = profile[binding_field]
    bogus = "sha256:" + "0" * 64
    binding["manifest"]["manifest"]["digest"] = bogus
    binding["manifest"]["manifest_digest"] = bogus
    binding["runtime_id"] = RuntimeBinding(
        kind,
        freeze_mapping(binding["manifest"]),
    ).runtime_id
    witness = result.certificate.witness.to_dict()
    witness["readiness_receipt"] = receipt
    forged = VerificationCertificate.create(
        subject=result.certificate.subject,
        verifier=result.certificate.verifier,
        claim_id=result.certificate.claim_id,
        statement_hash=result.certificate.statement_hash,
        claim_boundary_hash=result.certificate.claim_boundary_hash,
        witness=witness,
        checks=result.certificate.checks,
        guarantees=result.certificate.guarantees,
    )

    with pytest.raises(CertificateVerificationError, match="invalid readiness receipt"):
        verify_readiness_certificate(forged)


def test_declared_custom_capability_cannot_satisfy_plan_coverage(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, required_capabilities=("caller.custom",))
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )

    assert result.verdict is ReadinessVerdict.UNKNOWN
    capability = next(
        item for item in result.receipt.obligations if item.id == "capabilities.cover-plan"
    )
    assert capability.status is ObligationStatus.UNKNOWN
    assert capability.evidence["declared_only_required_capabilities"] == ("caller.custom",)


def test_same_version_modified_arbogast_tree_is_blocked(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    changed = replace(
        bundle.environment,
        arbogast_tree_sha256=_content_id("modified-arbogast-tree"),
    )
    result = certify_campaign_readiness(environment=changed, profile=bundle.profile)

    assert isinstance(result, CertifiedBlocked)
    assert {item.id for item in result.blockers} == {"arbogast.identity-bound"}


def test_plan_formula_terms_cannot_be_demoted_to_optional(tmp_path: Path) -> None:
    profile = _bundle(tmp_path).profile
    demoted = "operation-registry.covers-plan"

    with pytest.raises(BootstrapError, match="every formula obligation"):
        replace(
            profile,
            required_obligation_ids=tuple(
                item for item in profile.required_obligation_ids if item != demoted
            ),
            optional_obligation_ids=(demoted,),
        )


def test_verifier_requirements_must_equal_binding_requested_names(tmp_path: Path) -> None:
    profile = _bundle(tmp_path).profile

    with pytest.raises(BootstrapError, match="requested names"):
        replace(profile, required_verifiers=("required-but-unbound",))


def test_activation_requires_plan_scope_and_exact_derived_profile(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, required_capabilities=("canonical-json",))
    ready = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )
    assert isinstance(ready, CertifiedReady)

    weakened_profile = replace(bundle.profile, required_capabilities=())
    weakened = certify_campaign_readiness(
        environment=bundle.environment,
        profile=weakened_profile,
    )
    assert isinstance(weakened, CertifiedReady)
    weakened_report = validate_readiness_activation(
        weakened.certificate,
        campaign=bundle.campaign,
        plan=bundle.plan,
        operation_registry=bundle.operations,
        verifier_registry=bundle.verifiers,
        executor=bundle.executor,
        environment=bundle.environment,
    )
    assert not weakened_report.valid
    assert any("profile identity" in item for item in weakened_report.blockers)

    static_profile = replace(bundle.profile, scope=ReadinessScope.STATIC)
    static = certify_campaign_readiness(
        environment=bundle.environment,
        profile=static_profile,
    )
    assert isinstance(static, CertifiedReady)
    static_report = validate_readiness_activation(
        static.certificate,
        campaign=bundle.campaign,
        plan=bundle.plan,
        operation_registry=bundle.operations,
        verifier_registry=bundle.verifiers,
        executor=bundle.executor,
        environment=bundle.environment,
    )
    assert not static_report.valid
    assert any("requires an exact PLAN" in item for item in static_report.blockers)


def test_activation_reruns_live_artifact_and_fresh_process_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path)
    result = certify_campaign_readiness(
        environment=bundle.environment,
        profile=bundle.profile,
    )
    assert result.verify().valid  # portable transcript replay is intentionally offline

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "arbogast.bootstrap.readiness._artifact_probe",
            lambda _environment, _profile: {"outcome": "error", "error": "live failure"},
        )
        artifact_report = validate_readiness_activation(
            result.certificate,
            campaign=bundle.campaign,
            plan=bundle.plan,
            operation_registry=bundle.operations,
            verifier_registry=bundle.verifiers,
            executor=bundle.executor,
            environment=bundle.environment,
        )
    assert not artifact_report.valid
    assert any("artifact-store.roundtrip" in item for item in artifact_report.blockers)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "arbogast.bootstrap.readiness._fresh_process_probe",
            lambda _environment: {"outcome": "error", "error": "live failure"},
        )
        fresh_report = validate_readiness_activation(
            result.certificate,
            campaign=bundle.campaign,
            plan=bundle.plan,
            operation_registry=bundle.operations,
            verifier_registry=bundle.verifiers,
            executor=bundle.executor,
            environment=bundle.environment,
        )
    assert not fresh_report.valid
    assert any("fresh-process.fixture-replays" in item for item in fresh_report.blockers)


def test_uv_lock_check_is_bounded_offline_and_errors_are_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "lock-probe"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("version = 1\nrevision = 1\n", encoding="utf-8")
    fake_uv = tmp_path / "uv"
    fake_uv.write_bytes(b"fixed uv fixture")
    monkeypatch.setattr("arbogast.bootstrap.capture.shutil.which", lambda _name: str(fake_uv))
    observed: dict[str, object] = {}

    def completed(command: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("arbogast.bootstrap.capture.subprocess.run", completed)
    captured = capture_environment(project_root=tmp_path, package_hashes=False)

    assert captured.lock_consistent is True
    assert tuple(observed["command"])[1:6] == (
        "--no-config",
        "--offline",
        "--no-progress",
        "--no-cache",
        "--no-python-downloads",
    )
    kwargs = observed["kwargs"]
    assert kwargs["timeout"] == 20
    assert "PYTHONSTARTUP" not in kwargs["env"]

    def timed_out(_command: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired("uv", 20)

    monkeypatch.setattr("arbogast.bootstrap.capture.subprocess.run", timed_out)
    unknown = capture_environment(project_root=tmp_path, package_hashes=False)
    assert unknown.lock_consistent is None
    assert "TimeoutExpired" in unknown.lock_detail


def _clock_one() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _clock_two() -> datetime:
    return datetime(2026, 1, 2, tzinfo=UTC)


def test_worker_pool_executor_binding_covers_workers_retry_custody_and_clock(
    tmp_path: Path,
) -> None:
    base = _bundle(tmp_path / "base")
    store = ArtifactStore(tmp_path / "pool-artifacts")
    first_worker = Worker("worker-a", (PYTHON.status(),))
    first = WorkerPoolExecutor(
        WorkerPool((first_worker,)),
        store,
        operation_registry=base.operations,
        retry_policy=RetryPolicy(max_attempts=1),
        clock=_clock_one,
    )
    profile = ReadinessProfile.from_plan(
        base.campaign,
        base.plan,
        base.operations,
        base.verifiers,
        first,
        required_verifiers=("tests.closure",),
    )
    environment = capture_environment(project_root=Path(__file__).parents[2])
    result = certify_campaign_readiness(environment=environment, profile=profile)
    assert isinstance(result, CertifiedReady)
    manifest = profile.executor.manifest
    assert manifest["workers"]["workers"][0]["id"] == "worker-a"
    assert manifest["retry_policy"]["max_attempts"] == 1
    assert manifest["custody"]["class"].endswith(".LeaseCustody")
    assert manifest["clock"]["identifiable"] is True

    variants = (
        WorkerPoolExecutor(
            WorkerPool((Worker("worker-b", (PYTHON.status(),)),)),
            store,
            operation_registry=base.operations,
            retry_policy=RetryPolicy(max_attempts=1),
            clock=_clock_one,
        ),
        WorkerPoolExecutor(
            WorkerPool((first_worker,)),
            store,
            operation_registry=base.operations,
            retry_policy=RetryPolicy(max_attempts=2),
            clock=_clock_one,
        ),
        WorkerPoolExecutor(
            WorkerPool((first_worker,)),
            store,
            operation_registry=base.operations,
            retry_policy=RetryPolicy(max_attempts=1),
            clock=_clock_two,
        ),
    )
    for changed_executor in variants:
        report = validate_readiness_activation(
            result.certificate,
            campaign=base.campaign,
            plan=base.plan,
            operation_registry=base.operations,
            verifier_registry=base.verifiers,
            executor=changed_executor,
            artifact_store=store,
            environment=environment,
        )
        assert not report.valid
        assert any("executor identity" in item for item in report.blockers)
