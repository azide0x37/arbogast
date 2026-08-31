from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from arbogast import bootstrap as bootstrap_module
from arbogast import cli

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


@dataclass(frozen=True)
class _Report:
    mode: str
    ready: bool

    def to_dict(self) -> dict[str, object]:
        status = "READY" if self.ready else "BLOCKED"
        check_status = "SATISFIED" if self.ready else "UNSATISFIED"
        return {
            "schema": "arbogast.environment-preflight.v1",
            "mode": self.mode,
            "profile": {"name": f"{self.mode}-preflight-v1"},
            "authoritative": False,
            "status": status,
            "ready": self.ready,
            "captured_at": "2026-08-30T00:00:00Z",
            "environment_digest": "sha256:" + "0" * 64,
            "arbogast": {},
            "python": {},
            "uv": {},
            "project": {},
            "portable_core": {},
            "capabilities": [],
            "checks": [
                {
                    "name": "python.supported",
                    "requirement": "REQUIRED",
                    "status": check_status,
                }
            ],
            "required_blockers": [] if self.ready else ["python.supported"],
            "optional_blockers": [],
            "warnings": [],
            "next_commands": [],
        }


@pytest.mark.parametrize(("ready", "expected_exit"), ((True, 0), (False, 1)))
def test_doctor_emits_only_json_and_maps_readiness_to_exit(
    ready: bool,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        bootstrap_module,
        "environment_preflight",
        lambda mode: _Report(mode, ready),
    )

    assert cli.main(("doctor", "--mode", "replay", "--json")) == expected_exit
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert set(payload) == DOCTOR_FIELDS
    assert payload["ready"] is ready
    assert payload["status"] == ("READY" if ready else "BLOCKED")
    assert captured.err == ""


def test_doctor_diagnostic_failure_is_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def crash(_mode: str) -> object:
        raise RuntimeError("probe crashed before producing a report")

    monkeypatch.setattr(bootstrap_module, "environment_preflight", crash)

    assert cli.main(("doctor", "--mode", "replay", "--json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "doctor diagnostic failed" in captured.err
    assert "probe crashed" in captured.err


@pytest.mark.parametrize(
    "arguments",
    (
        ("doctor", "--mode", "invalid", "--json"),
        ("doctor", "--mode", "replay"),
        ("doctor", "--json"),
    ),
)
def test_doctor_misuse_is_argparse_exit_two(arguments: tuple[str, ...]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 2


def test_real_replay_doctor_is_ready_without_project_or_uv(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from arbogast.bootstrap import preflight as preflight_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        preflight_module,
        "_probe_uv",
        lambda: {
            "available": False,
            "version": None,
            "executable": None,
            "probe_error": None,
        },
    )

    assert cli.main(("doctor", "--mode", "replay", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is True
    assert payload["status"] == "READY"
    assert payload["authoritative"] is False
    assert not payload["required_blockers"]
