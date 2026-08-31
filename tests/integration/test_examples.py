"""End-to-end checks for the documented, runnable examples."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COHOMOLOGY_EXAMPLE = PROJECT_ROOT / "examples/group_cohomology/cyclic_action_h1.py"
DISCOVER_EXAMPLE = PROJECT_ROOT / "examples/certificates/prove_without_search/discover.py"
VERIFY_EXAMPLE = PROJECT_ROOT / "examples/certificates/prove_without_search/verify.py"
M23_COMPUTE = PROJECT_ROOT / "examples/hurwitz/m23_real_component/compute.py"
M23_VERIFY = PROJECT_ROOT / "examples/hurwitz/m23_real_component/verify.py"
CAMPAIGN_EXAMPLE = PROJECT_ROOT / "examples/campaigns/antieau_klueners_malle/run.py"


def run_example(*arguments: object) -> subprocess.CompletedProcess[str]:
    """Run one example under the same interpreter as pytest."""

    return subprocess.run(
        [sys.executable, *(str(argument) for argument in arguments)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cyclic_action_h1_runs_and_verifies() -> None:
    completed = run_example(COHOMOLOGY_EXAMPLE)
    assert completed.returncode == 0, completed.stderr
    assert "module weights: 1: dimension 1, 3: dimension 1, 4: dimension 1" in completed.stdout
    assert "dim Z^1: 2" in completed.stdout
    assert "dim B^1: 2" in completed.stdout
    assert "dim H^1: 0" in completed.stdout
    assert "explicit-quotient-maps" in completed.stdout


def test_discovery_emits_a_search_free_verification_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    discovered = run_example(DISCOVER_EXAMPLE, "--output", certificate)
    assert discovered.returncode == 0, discovered.stderr

    payload = json.loads(certificate.read_text(encoding="utf-8"))
    assert payload["layer"] == "verification"
    assert payload["verifier"] == "examples.modular_reachability.v1"
    assert "breadth-first search" not in certificate.read_text(encoding="utf-8")

    verified = run_example(VERIFY_EXAMPLE, certificate)
    assert verified.returncode == 0, verified.stderr
    assert "valid_transitions" in verified.stdout
    assert "path length: 6" in verified.stdout


def test_modular_certificate_tampering_is_rejected(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    assert run_example(DISCOVER_EXAMPLE, "--output", certificate).returncode == 0
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["witness"]["path"][0]["to"] = 28
    certificate.write_text(json.dumps(payload), encoding="utf-8")

    rejected = run_example(VERIFY_EXAMPLE, certificate)
    assert rejected.returncode == 1
    assert "verification failed" in rejected.stderr


def test_local_campaign_replays_verified_bounded_outcome(tmp_path: Path) -> None:
    output = tmp_path / "campaign"
    completed = run_example(CAMPAIGN_EXAMPLE, "--output", output)
    assert completed.returncode == 0, completed.stderr
    assert "capability matched: small-exact-computations" in completed.stdout
    assert "mathematical outcome: SEARCH_EXHAUSTED" in completed.stdout
    assert "operational state: COMPLETED" in completed.stdout
    assert "target closed: True" in completed.stdout
    assert "claim kinds: imported=imported, computed=computed" in completed.stdout

    claim_graph = json.loads((output / "claims.json").read_text(encoding="utf-8"))
    claims = {claim["id"]: claim for claim in claim_graph["claims"]}
    imported = claims["demo.catalogue.mod17_residue3_absent"]
    snapshot = json.loads((output / "campaign.json").read_text(encoding="utf-8"))
    target_id = snapshot["spec"]["targets"][0]["target_id"]
    computed_claims = [
        claim
        for claim in claims.values()
        if claim["kind"] == "computed" and claim["metadata"].get("target_id") == target_id
    ]
    assert len(computed_claims) == 1
    computed = computed_claims[0]
    assert claim_graph["graph_id"] == f"campaign:{snapshot['spec']['campaign_id']}"
    assert snapshot["claims"] == claim_graph
    assert imported["kind"] == "imported"
    assert imported["status"] == "conditional"
    assert computed["kind"] == "computed"
    assert computed["status"] == "certified"
    assert computed["evidence"][0]["certificate_layer"] == "verification"
    assert len(computed["attached_certificates"]) == 1
    assert computed["attached_certificates"][0]["verifier"] == "campaign.claim-closure.v1"

    event_kinds = [event["kind"] for event in snapshot["ledger"]["events"]]
    assert event_kinds == [
        "TARGET_ADDED",
        "TASK_PLANNED",
        "PLAN_RECORDED",
        "TASK_STARTED",
        "ATTEMPT_RECORDED",
        "OBSERVATION_RECORDED",
        "CANDIDATE_RECORDED",
        "CLAIM_BOUND",
        "ATTEMPT_RECORDED",
    ]
    attempts = [
        event["payload"]["attempt"]
        for event in snapshot["ledger"]["events"]
        if event["kind"] == "ATTEMPT_RECORDED"
    ]
    assert [attempt["state"] for attempt in attempts] == ["RUNNING", "COMPLETED"]
    candidates = [
        event["payload"]["candidate"]
        for event in snapshot["ledger"]["events"]
        if event["kind"] == "CANDIDATE_RECORDED"
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["target_id"] == target_id
    assert candidate["canonicalizer"] == "examples.modular-residue-table.v1"
    assert candidate["equivalence_scope"] == "TARGET"
    assert candidate["evidence"] == "VERIFIED"
    assert candidate["quality_metric"] == "checked-residues"
    assert candidate["quality"] == 17
    binding = next(
        event["payload"]["binding"]
        for event in snapshot["ledger"]["events"]
        if event["kind"] == "CLAIM_BOUND"
    )
    assert binding["claim_id"] == computed["id"]
    assert binding["target_id"] == target_id


def test_local_campaign_operation_contract_binds_certifiable_closure_verifier() -> None:
    script = "\n".join(
        (
            "import json",
            "from arbogast.cert import default_verifiers",
            "from arbogast.fleet import FleetOperationRegistry",
            "from examples.campaigns.antieau_klueners_malle import run",
            "operation = FleetOperationRegistry({run.OPERATION: run.RESIDUE_OPERATION})",
            "entry = operation.readiness_manifest()['operations'][0]",
            "verifier = default_verifiers.readiness_manifest((run.VERIFIER,))['verifiers'][0]",
            "print(json.dumps({'operation': entry, 'verifier': verifier}))",
        )
    )

    completed = run_example("-c", script)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["operation"]["certifiable"] is True
    assert payload["operation"]["contract"]["closure_verifiers"] == [
        "examples.campaign.residue-scan.v1"
    ]
    assert payload["verifier"]["certifiable"] is True


def test_m23_projection_carries_exact_certified_claims(tmp_path: Path) -> None:
    projection = tmp_path / "m23-claims.json"
    computed = run_example(M23_COMPUTE, "--output", projection)
    assert computed.returncode == 0, computed.stderr
    assert "1428 generating inner classes" in computed.stdout
    assert "7114 product-one inner orbits" in computed.stdout
    assert "claim graph: 6 computed, 6 certified" in computed.stdout

    payload = json.loads(projection.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ("arbogast.example.m23-real-component.claim-projection/v3")
    assert payload["hurwitz_dataset_certificate"]["schema_version"] == (
        "arbogast.hurwitz.m23-exact/v1"
    )
    claims = payload["claim_graph"]["claims"]
    assert len(claims) == 6
    assert {claim["kind"] for claim in claims} == {"computed"}
    assert {claim["status"] for claim in claims} == {"certified"}
    assert all(claim["evidence"][0]["certificate_layer"] == "verification" for claim in claims)
    assert all(claim["source"] for claim in claims)
    assert all(claim["hypotheses"] for claim in claims)
    claims_by_id = {claim["id"]: claim for claim in claims}
    assert claims_by_id["m23_236_inner_cardinality"]["why"] == ["m23_236_completeness_partition"]
    assert claims_by_id["m23_236_pure_braid_transitive"]["source"] == [
        "atlas-m23-identity",
        "atlas-m23-class-labels",
        "haefner-right-hurwitz-action",
        "haefner-pure-b4-generators",
    ]
    assert len(payload["certificates"]) == 6
    assert payload["source_registry"]["schema_version"] == "arbogast.sources/v1"
    assert payload["provenance_record"] == "m23_236_public_exact_projection"
    provenance = payload["source_registry"]["provenance"]
    assert len(provenance) == 1
    assert "context" in provenance[0]["parameters"]["source_boundary"]
    report = payload["fixture_verification"]
    assert report["component_cardinality"] == 1428
    assert report["all_inner_orbits"] == 7114
    assert report["nongenerating_inner_orbits"] == 5686
    assert report["c1_fixed"] == 20
    assert report["nongenerating_c1"] == 212
    assert report["inner_real_fixed"] == 70

    verified = run_example(M23_VERIFY, projection)
    assert verified.returncode == 0, verified.stderr
    assert (
        "fixture verification: valid through arbogast.hurwitz (1428 generating, 5686 nongenerating)"
    ) in verified.stdout
    assert "20 generating c=1; 212 nongenerating c=1 guardrail" in verified.stdout
    assert "claim graph: 6 computed, 6 certified" in verified.stdout


def test_m23_certificate_tampering_is_rejected(tmp_path: Path) -> None:
    projection = tmp_path / "m23-claims.json"
    assert run_example(M23_COMPUTE, "--output", projection).returncode == 0
    payload = json.loads(projection.read_text(encoding="utf-8"))
    certificate = next(iter(payload["certificates"].values()))
    certificate["witness"]["verified_value"] = 999
    projection.write_text(json.dumps(payload), encoding="utf-8")

    verified = run_example(M23_VERIFY, projection)
    assert verified.returncode == 1
    assert "M23 verification failed" in verified.stderr
