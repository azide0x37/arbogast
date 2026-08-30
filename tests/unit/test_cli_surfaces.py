from __future__ import annotations

import json

from arbogast.claims import Claim, ClaimGraph, ClaimKind, EpistemicStatus
from arbogast.cli import main
from arbogast.proof import ObligationClass, ProofGap, ProofObligation


def test_version_and_describe_json_are_stable(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(("version", "--json")) == 0
    version = json.loads(capsys.readouterr().out)
    assert version == {"schema": "arbogast.cli.version.v1", "version": "0.5.0"}

    assert main(("describe", "cohom.h1", "--json")) == 0
    description = json.loads(capsys.readouterr().out)
    assert description["operation"]["name"] == "cohom.h1"
    assert description["operation"]["inputs"] == ["FiniteGroup", "Module"]
    assert description["operation"]["input_bundles"] == [
        ["FiniteGroup", "Module"],
        ["CochainComplex"],
    ]


def test_describe_unknown_operation_is_a_clean_cli_error(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(("describe", "not.a.registered.operation", "--json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "arbogast: error: unknown operation: not.a.registered.operation\n"
    assert "Traceback" not in captured.err


def test_claims_filter_and_proof_gap_json(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps(
            {
                "claims": [
                    {"id": "known", "kind": "computed", "status": "certified"},
                    {"id": "hole", "kind": "conjectured", "status": "unknown"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(("claims", str(claims_file), "--status", "conjectured", "--json")) == 0
    filtered = json.loads(capsys.readouterr().out)
    assert filtered["count"] == 1
    assert filtered["claims"][0]["id"] == "hole"

    proof_file = tmp_path / "proof.json"
    proof_gap = ProofGap(
        "known",
        (
            ProofObligation.create("a", "A", ObligationClass.DECIDABLE),
            ProofObligation.create("b", "B", ObligationClass.MISSING_LEMMA),
        ),
    )
    proof_file.write_text(json.dumps(proof_gap.to_dict()), encoding="utf-8")
    assert main(("proof-gap", str(proof_file), "--json")) == 0
    gap = json.loads(capsys.readouterr().out)
    assert gap["summary"]["by_class"] == {"DECIDABLE": 1, "MISSING_LEMMA": 1}
    assert gap["claim"] == "known"
    assert {item["claim_id"] for item in gap["obligations"]} == {"known"}

    graph_file = tmp_path / "claim-graph.json"
    graph = ClaimGraph(
        (
            Claim(
                "known",
                statement="P",
                kind=ClaimKind.CONJECTURED,
                status=EpistemicStatus.UNKNOWN,
                formalization=proof_gap,
            ),
            Claim(
                "without-gap",
                statement="Q",
                kind=ClaimKind.CONJECTURED,
                status=EpistemicStatus.UNKNOWN,
            ),
        )
    )
    graph_file.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    assert main(("proof-gap", str(graph_file), "--claim", "known", "--json")) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["summary"]["total"] == 2
    assert main(("proof-gap", str(graph_file), "--claim", "missing", "--json")) == 2
    assert "unknown claim" in capsys.readouterr().err


def test_proof_gap_rejects_ambiguous_ad_hoc_documents(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    proof_file = tmp_path / "ad-hoc.json"
    proof_file.write_text(
        json.dumps({"obligations": [{"id": "a", "classification": "DECIDABLE"}]}),
        encoding="utf-8",
    )
    assert main(("proof-gap", str(proof_file), "--json")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "expects an arbogast.claim-graph/v1" in captured.err


def test_route_reports_only_real_registered_capabilities(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(("route", "--from", "NielsenClass", "--to", "ComponentCollection", "--json")) == 0
    route = json.loads(capsys.readouterr().out)["route"]
    assert [step["operation"] for step in route["steps"]] == ["hurwitz.components"]

    assert (
        main(
            (
                "route",
                "--from",
                "NielsenEnumerationCertificate",
                "--to",
                "ClaimGraph",
                "--json",
            )
        )
        == 0
    )
    portable_route = json.loads(capsys.readouterr().out)["route"]
    assert [step["operation"] for step in portable_route["steps"]] == ["hurwitz.claim_graph"]

    assert main(("route", "--from", "HurwitzComponent", "--to", "ClaimGraph", "--json")) == 0
    downstream_route = json.loads(capsys.readouterr().out)["route"]
    assert [step["operation"] for step in downstream_route["steps"]] == ["hurwitz.claim_graph"]

    for false_source in ("Matrix", "int", "bool", "Module"):
        assert main(("route", "--from", false_source, "--to", "ClaimGraph", "--json")) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"no capability route from '{false_source}' to 'ClaimGraph'" in captured.err


def test_route_expands_concrete_arithmetic_unions_and_projection_edges(
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    assert main(("route", "--from", "FinitePlace", "--to", "LocalH1Space", "--json")) == 0
    local = json.loads(capsys.readouterr().out)["route"]
    assert [step["operation"] for step in local["steps"]] == ["galois.local_h1"]

    assert main(("route", "--from", "KummerSpace", "--to", "ClaimGraph", "--json")) == 0
    claim = json.loads(capsys.readouterr().out)["route"]
    assert [step["operation"] for step in claim["steps"]] == ["galois.claim_graph"]

    assert main(("route", "--from", "KummerSpace", "--to", "JSONDocument", "--json")) == 0
    exported = json.loads(capsys.readouterr().out)["route"]
    assert exported["steps"][-1]["operation"] == "export.json"


def test_describe_reports_hurwitz_domain_receipts_and_plain_tuple_results(
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    assert main(("describe", "hurwitz.braid_action", "--json")) == 0
    braid = json.loads(capsys.readouterr().out)["operation"]
    assert "BraidEdgeCertificate" in braid["certificate_type"]
    assert "HurwitzOperationCertificate" in braid["certificate_type"]
    assert any(
        "computed-complete Nielsen receipt" in item for item in braid["mathematical_guarantees"]
    )

    assert main(("describe", "hurwitz.real_points", "--json")) == 0
    real = json.loads(capsys.readouterr().out)["operation"]
    assert real["outputs"] == ["tuple[NielsenTuple, ...]"]
    assert real["certificate_type"] is None
    assert any("emits no certificate" in item for item in real["mathematical_guarantees"])


def test_verify_fails_closed_for_non_certificate_json(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    certificate = tmp_path / "not-a-certificate.json"
    certificate.write_text("{}", encoding="utf-8")

    assert main(("verify", str(certificate), "--json")) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False


def test_verify_rejects_duplicate_certificate_keys(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    certificate = tmp_path / "duplicate.json"
    certificate.write_text(
        '{"schema_version":"first","schema_version":"second"}',
        encoding="utf-8",
    )

    assert main(("verify", str(certificate), "--json")) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert "duplicate JSON object key" in report["error"]
