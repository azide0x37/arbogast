from __future__ import annotations

import json

import pytest

from arbogast.cli import main
from arbogast.formats import CLI_BACKENDS_SCHEMA, schema_document, validate_document


def test_backends_name_pari_uses_detailed_probe_and_stable_cli_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("backends", "--name", "pari", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == CLI_BACKENDS_SCHEMA
    assert payload["backend"]["schema"] == "arbogast.backend.pari-probe.v1"
    assert payload["backend"]["receipt"]["layer"] == "discovery"
    projected_status = payload["backend"]["status"]
    assert projected_status["name"] == "pari"
    if projected_status["available"]:
        assert payload["backend"]["smoke_tests"]["field-invariants"] is True
        assert "quadratic-hilbert-pairings" in projected_status["capabilities"]
    assert validate_document(payload, CLI_BACKENDS_SCHEMA) == payload
    assert schema_document(CLI_BACKENDS_SCHEMA)["$id"] == CLI_BACKENDS_SCHEMA


def test_backends_rejects_unknown_name_without_json_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("backends", "--name", "not-a-backend", "--json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown backend" in captured.err
