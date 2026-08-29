from __future__ import annotations

import json

import arbogast.cli as cli_module
from arbogast.campaign import Campaign, Strategy, TargetSpec
from arbogast.cli import main
from arbogast.fleet import LOCAL_ECHO_OPERATION, UnknownFleetOperationError


def test_campaign_init_status_and_empty_claim_export(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    campaign_file = tmp_path / "campaign.json"

    assert (
        main(
            (
                "campaign",
                "init",
                "antieau-demo",
                str(campaign_file),
                "--objective",
                "Resolve the selected finite exact targets",
                "--success-criterion",
                "Every closing outcome carries replayable evidence",
                "--json",
            )
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["schema"] == "arbogast.cli.campaign.v1"
    assert initialized["command"] == "campaign.init"
    assert initialized["result"]["target_count"] == 0

    assert main(("status", str(campaign_file), "--json")) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["command"] == "status"
    assert status["campaign_id"] == initialized["campaign_id"]

    assert main(("export", "claims", str(campaign_file), "--json")) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["claims"] == []
    assert exported["graph_id"] == f"campaign:{initialized['campaign_id']}"
    assert exported["schema_version"] == "arbogast.claim-graph/v1"


def test_campaign_plan_explain_and_run_fail_closed_without_operations(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    campaign_file = tmp_path / "planned.json"
    target = TargetSpec("24T-demo", {"degree": 24})
    Campaign(
        "planned-demo",
        objective="Resolve one exact target",
        targets=(target,),
        strategies=(
            Strategy(
                "exact-search",
                "example.uninjected",
                "Exercise a trusted local operation only when explicitly injected",
            ),
        ),
    ).save(campaign_file)

    assert main(("plan", str(campaign_file), "--json")) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["command"] == "plan"
    assert len(plan["result"]["recommendations"]) == 1
    task = plan["result"]["recommendations"][0]["task"]
    assert task["target"]["key"] == "24T-demo"

    assert main(("target", str(campaign_file), "24T-demo", "--explain", "--json")) == 0
    explanation = json.loads(capsys.readouterr().out)
    assert explanation["command"] == "target.explain"
    assert explanation["result"]["state"]["status"] == "OPEN"

    assert main(("run", str(campaign_file), "--json")) == 2
    error = capsys.readouterr()
    assert error.out == ""
    assert "without locally injected fleet operations" in error.err
    assert "example.uninjected" in error.err


def test_campaign_harvest_does_not_deserialize_fleet_runs(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    campaign_file = tmp_path / "campaign.json"
    Campaign("demo", objective="Keep runtime objects out of persisted input").save(campaign_file)

    assert main(("harvest", str(campaign_file), "--json")) == 2
    error = capsys.readouterr()
    assert error.out == ""
    assert "cannot reconstruct a live FleetRun" in error.err


def test_campaign_cli_rejects_noncanonical_json_without_tracebacks(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    duplicate_campaign = tmp_path / "duplicate-campaign.json"
    duplicate_campaign.write_text('{"campaign_id":"a","campaign_id":"b"}', encoding="utf-8")

    assert main(("status", str(duplicate_campaign), "--json")) == 2
    status_error = capsys.readouterr()
    assert status_error.out == ""
    assert "duplicate JSON object key" in status_error.err

    campaign_file = tmp_path / "campaign.json"
    Campaign("strict-json", objective="Reject ambiguous observations").save(campaign_file)
    for name, document, expected in (
        ("duplicate", '{"task_id":"a","task_id":"b"}', "duplicate JSON object key"),
        ("nan", '{"task_id":NaN}', "not part of exact canonical JSON"),
    ):
        observation_file = tmp_path / f"{name}.json"
        observation_file.write_text(document, encoding="utf-8")
        assert (
            main(
                (
                    "harvest",
                    str(campaign_file),
                    "--observation",
                    str(observation_file),
                    "--json",
                )
            )
            == 2
        )
        harvest_error = capsys.readouterr()
        assert harvest_error.out == ""
        assert expected in harvest_error.err


def test_campaign_run_projects_registry_failures_without_tracebacks(
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    class MissingRuntimeRegistry:
        def run(self, *, limit: int | None = None) -> tuple[object, ...]:
            del limit
            raise UnknownFleetOperationError("persisted.named-operation")

    monkeypatch.setattr(
        cli_module,
        "_load_campaign",
        lambda _path, **_runtime: MissingRuntimeRegistry(),
    )

    assert main(("run", "persisted.json", "--json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "trusted runtime registry" in captured.err
    assert "persisted.named-operation" in captured.err
    assert "Traceback" not in captured.err


def test_campaign_run_auto_uses_only_the_audited_named_registry(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    campaign_file = tmp_path / "automatic.json"
    Campaign(
        "automatic-local-demo",
        objective="Exercise trusted local scheduling without claiming mathematics",
        targets=(TargetSpec("demo:target"),),
        strategies=(
            Strategy(
                "echo-runtime",
                LOCAL_ECHO_OPERATION,
                "Record canonical task custody and return UNKNOWN",
            ),
        ),
    ).save(campaign_file)

    assert (
        main(
            (
                "run",
                str(campaign_file),
                "--fleet",
                "auto",
                "--limit",
                "1",
                "--json",
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "run"
    assert len(payload["result"]) == 1
    assert payload["result"][0]["outcome"] == "UNKNOWN"
    assert payload["result"][0]["details"]["result"]["operation"] == LOCAL_ECHO_OPERATION
    assert (tmp_path / "automatic.json.fleet" / "objects" / "sha256").is_dir()
    assert "runner" not in campaign_file.read_text(encoding="utf-8")

    missing_file = tmp_path / "missing-operation.json"
    Campaign(
        "missing-runtime-demo",
        objective="Fail closed on untrusted operation names",
        targets=(TargetSpec("demo:missing"),),
        strategies=(Strategy("missing", "not.registered", "must not import from data"),),
    ).save(missing_file)
    assert main(("run", str(missing_file), "--fleet", "auto", "--limit", "1")) == 2
    error = capsys.readouterr()
    assert "not.registered" in error.err
    assert "Traceback" not in error.err
