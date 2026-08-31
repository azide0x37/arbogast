from __future__ import annotations

from pathlib import Path

import pytest

from arbogast import __version__
from arbogast.bootstrap import (
    BootstrapReport,
    EnvironmentPreflightReport,
    environment_preflight,
)
from arbogast.bootstrap import capture as capture_module
from arbogast.bootstrap import preflight as preflight_module
from arbogast.formats import (
    BOOTSTRAP_REPORT_SCHEMA,
    ENVIRONMENT_PREFLIGHT_SCHEMA,
    validate_document,
)

DOCTOR_FIELDS = {
    "schema",
    "mode",
    "profile",
    "authoritative",
    "status",
    "ready",
    "captured_at",
    "environment_digest",
    "arbogast",
    "python",
    "uv",
    "project",
    "portable_core",
    "capabilities",
    "checks",
    "required_blockers",
    "optional_blockers",
    "warnings",
    "next_commands",
}


def _uv_available() -> dict[str, object]:
    return {
        "available": True,
        "version": "0.test",
        "executable": "/test/uv",
        "probe_error": None,
    }


def _checks(report: EnvironmentPreflightReport) -> dict[str, dict[str, object]]:
    return {str(check["name"]): check for check in report.checks}


def test_doctor_and_bootstrap_reports_have_distinct_schemas(tmp_path: Path) -> None:
    report = environment_preflight("replay", project_root=tmp_path, probe_external=False)
    payload = report.to_dict()

    assert EnvironmentPreflightReport.schema == ENVIRONMENT_PREFLIGHT_SCHEMA
    assert BootstrapReport.schema == BOOTSTRAP_REPORT_SCHEMA
    assert set(payload) == DOCTOR_FIELDS
    assert payload["authoritative"] is False
    assert "certificate_id" not in payload
    assert "claim_id" not in payload
    assert "verdict" not in payload
    assert validate_document(payload, ENVIRONMENT_PREFLIGHT_SCHEMA) == payload


def test_installed_empty_project_mode_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preflight_module, "_probe_uv", _uv_available)

    campaign = environment_preflight("campaign", project_root=tmp_path, probe_external=False)
    core = environment_preflight("core", project_root=tmp_path, probe_external=False)
    replay = environment_preflight("replay", project_root=tmp_path, probe_external=False)

    assert (campaign.status, campaign.ready) == ("BLOCKED", False)
    assert (core.status, core.ready) == ("BLOCKED", False)
    assert (replay.status, replay.ready) == ("READY", True)
    assert "project.manifest" in campaign.required_blockers
    assert "project.manifest" in core.required_blockers
    assert not replay.required_blockers


def test_source_checkout_is_core_and_replay_ready_but_not_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).parents[2]
    monkeypatch.setattr(preflight_module, "_probe_uv", _uv_available)

    campaign = environment_preflight("campaign", project_root=root, probe_external=False)
    core = environment_preflight("core", project_root=root, probe_external=False)
    replay = environment_preflight("replay", project_root=root, probe_external=False)

    assert not campaign.ready
    assert "project.separate-from-core" in campaign.required_blockers
    assert core.ready
    assert replay.ready


def test_pinned_campaign_project_is_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight_module, "_probe_uv", _uv_available)
    monkeypatch.setattr(
        capture_module,
        "_lock_state",
        lambda _root, _enabled: ((), True, "validated lock fixture"),
    )
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            (
                "[project]",
                'name = "example-campaign"',
                'version = "0.1.0"',
                'requires-python = ">=3.11,<3.15"',
                f'dependencies = ["arbogast=={__version__}"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        "\n".join(
            (
                "version = 1",
                "revision = 3",
                "",
                "[[package]]",
                'name = "example-campaign"',
                'version = "0.1.0"',
                "",
                "[[package]]",
                'name = "arbogast"',
                f'version = "{__version__}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / ".python-version").write_text("3.13\n", encoding="utf-8")

    report = environment_preflight("campaign", project_root=tmp_path, probe_external=False)

    assert report.ready
    assert report.status == "READY"
    assert not report.required_blockers
    assert _checks(report)["project.arbogast-pin"]["status"] == "SATISFIED"
    assert _checks(report)["project.python-pin"]["requirement"] == "REQUIRED"


def test_missing_optional_backend_does_not_block_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def snapshots(_probe_external: bool) -> tuple[dict[str, object], dict[str, str]]:
        return (
            {
                "python": {
                    "name": "python",
                    "available": True,
                    "version": "test",
                    "capabilities": (
                        "canonical-json",
                        "certificate-verification",
                        "control-plane",
                        "small-exact-computations",
                    ),
                },
                "gap": {
                    "name": "gap",
                    "available": False,
                    "version": None,
                    "capabilities": (),
                    "reason": "not installed",
                },
            },
            {},
        )

    monkeypatch.setattr(capture_module, "_backend_snapshots", snapshots)
    report = environment_preflight("replay", project_root=tmp_path, probe_external=True)

    assert report.ready
    gap = _checks(report)["backend.gap"]
    assert gap["requirement"] == "OPTIONAL"
    assert gap["status"] == "UNSATISFIED"
    assert "backend.gap" in report.optional_blockers


def test_backend_probe_crash_is_unknown_not_a_diagnostic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def snapshots(_probe_external: bool) -> tuple[dict[str, object], dict[str, str]]:
        return (
            {
                "python": {
                    "name": "python",
                    "available": True,
                    "version": "test",
                    "capabilities": (
                        "canonical-json",
                        "certificate-verification",
                        "control-plane",
                        "small-exact-computations",
                    ),
                },
                "gap": {
                    "name": "gap",
                    "available": None,
                    "version": None,
                    "capabilities": (),
                    "reason": "backend probe did not determine availability",
                },
            },
            {"backend.gap": "RuntimeError: probe crashed"},
        )

    monkeypatch.setattr(capture_module, "_backend_snapshots", snapshots)
    report = environment_preflight("replay", project_root=tmp_path, probe_external=True)

    assert report.ready
    assert _checks(report)["backend.gap"]["status"] == "UNKNOWN"
    assert any("probe crashed" in warning for warning in report.warnings)


def test_required_python_backend_probe_crash_completes_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def snapshots(_probe_external: bool) -> tuple[dict[str, object], dict[str, str]]:
        return (
            {
                "python": {
                    "name": "python",
                    "available": None,
                    "version": None,
                    "capabilities": (),
                    "reason": "backend probe did not determine availability",
                }
            },
            {"backend.python": "RuntimeError: required probe crashed"},
        )

    monkeypatch.setattr(capture_module, "_backend_snapshots", snapshots)
    report = environment_preflight("replay", project_root=tmp_path, probe_external=True)

    assert report.status == "UNKNOWN"
    assert not report.ready
    assert _checks(report)["backend.python"]["status"] == "UNKNOWN"
    assert "backend.python" in report.required_blockers


def test_malformed_mode_is_rejected_before_probing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="campaign, core, or replay"):
        environment_preflight("arbitrary", project_root=tmp_path)
