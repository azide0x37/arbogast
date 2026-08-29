from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import arbogast.hurwitz as hurwitz
from arbogast.cert import (
    CertificateVerificationError,
    VerificationCertificate,
    content_address,
    default_verifiers,
    verify_certificate,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
)
from arbogast.rep import Permutation, PermutationGroup


def _small_nielsen() -> hurwitz.NielsenClass:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    return hurwitz.nielsen_class(group, (transpositions,) * 4)


def test_nielsen_claim_round_trip_replays_without_process_context(tmp_path: Path) -> None:
    nielsen = _small_nielsen()
    graph = nielsen.claim_graph()
    restored = ClaimGraph.from_dict(graph.to_dict())
    assert restored.verify().verified

    graph_path = tmp_path / "nielsen-claim-graph.json"
    graph_path.write_text(json.dumps(graph.to_dict()))
    script = (
        "import json,sys; import arbogast.hurwitz; "
        "from arbogast.claims import ClaimGraph; "
        "g=ClaimGraph.from_dict(json.load(open(sys.argv[1]))); "
        "r=g.verify(); assert r.verified"
    )
    process = subprocess.run(
        (sys.executable, "-c", script, str(graph_path)),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr


def test_public_nielsen_wrapper_verifies_via_fresh_cli_and_detects_tamper(
    tmp_path: Path,
) -> None:
    certificate = hurwitz.verification_certificate_for(_small_nielsen())
    certificate_path = tmp_path / "nielsen-certificate.json"
    certificate_path.write_text(json.dumps(certificate.to_dict()))

    process = subprocess.run(
        (sys.executable, "-m", "arbogast.cli", "verify", str(certificate_path), "--json"),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["valid"] is True

    tampered = certificate.to_dict()
    witness = tampered["witness"]
    assert isinstance(witness, dict)
    specialized = witness["hurwitz_certificate"]
    assert isinstance(specialized, dict)
    specialized["generating_count"] = 23
    # Recompute the generic envelope address at decode time so rejection comes
    # from the nested Hurwitz content address, not merely the outer JSON hash.
    tampered.pop("certificate_id")
    tampered_path = tmp_path / "tampered-nielsen-certificate.json"
    tampered_path.write_text(json.dumps(tampered))
    rejected = subprocess.run(
        (sys.executable, "-m", "arbogast.cli", "verify", str(tampered_path), "--json"),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["valid"] is False


def test_fresh_cli_rejects_relabelled_portable_group_with_recomputed_ids(
    tmp_path: Path,
) -> None:
    good = hurwitz.verification_certificate_for(_small_nielsen())
    transport = good.to_dict()
    witness = transport["witness"]
    assert isinstance(witness, dict)
    specialized = witness["hurwitz_certificate"]
    assert isinstance(specialized, dict)
    forged_specialized = dict(specialized)
    forged_specialized.pop("certificate_id")
    forged_specialized["group_fingerprint"] = "0" * 64
    specialized_id = content_address(forged_specialized)
    forged_specialized["certificate_id"] = specialized_id

    representative_keys = forged_specialized["representative_keys"]
    class_fingerprints = forged_specialized["class_fingerprints"]
    assert isinstance(representative_keys, list)
    assert isinstance(class_fingerprints, list)
    statement = FormalStatement.create(
        good.subject,
        parameters={
            "group_fingerprint": "0" * 64,
            "class_fingerprints": tuple(class_fingerprints),
            "cardinality": len(representative_keys),
        },
    )
    forged = VerificationCertificate.create(
        good.subject,
        good.verifier,
        claim_id=f"hurwitz.nielsen_class.{specialized_id.split(':', 1)[1]}",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=good.claim_boundary_hash,
        claim_dependencies=good.claim_dependencies,
        witness={"hurwitz_certificate": forged_specialized},
        checks=good.checks,
        guarantees=good.guarantees,
    )
    forged_path = tmp_path / "relabelled-nielsen-certificate.json"
    forged_path.write_text(json.dumps(forged.to_dict()))

    rejected = subprocess.run(
        (sys.executable, "-m", "arbogast.cli", "verify", str(forged_path), "--json"),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    report = json.loads(rejected.stdout)
    assert report["valid"] is False
    assert "portable group fingerprint mismatch" in report["error"]


def test_central_nielsen_verifier_rejects_readdressed_coercive_transport() -> None:
    good = hurwitz.verification_certificate_for(_small_nielsen())
    transport = good.to_dict()
    witness = transport["witness"]
    assert isinstance(witness, dict)
    specialized = witness["hurwitz_certificate"]
    assert isinstance(specialized, dict)
    table = specialized["multiplication_table"]
    assert isinstance(table, list)
    row = table[0]
    assert isinstance(row, list)
    assert row[1] == 1
    row[1] = True
    specialized.pop("certificate_id")
    specialized_id = content_address(specialized)
    specialized["certificate_id"] = specialized_id

    forged = VerificationCertificate.create(
        good.subject,
        good.verifier,
        claim_id=f"hurwitz.nielsen_class.{specialized_id.split(':', 1)[1]}",
        statement_hash=good.statement_hash,
        claim_boundary_hash=good.claim_boundary_hash,
        witness={"hurwitz_certificate": specialized},
        checks=good.checks,
        guarantees=good.guarantees,
    )
    with pytest.raises(CertificateVerificationError, match="must be an integer"):
        verify_certificate(forged)


def test_nielsen_receipt_cannot_certify_an_arbitrary_false_statement() -> None:
    nielsen = _small_nielsen()
    good = hurwitz.verification_certificate_for(nielsen)
    false_statement = FormalStatement.create(
        "The complete inner Nielsen class has cardinality 999.",
        parameters={"cardinality": 999},
    )
    forged = VerificationCertificate.create(
        subject=false_statement.text,
        verifier=good.verifier,
        claim_id=good.claim_id,
        statement_hash=false_statement.statement_hash,
        claim_boundary_hash=good.claim_boundary_hash,
        claim_dependencies=good.claim_dependencies,
        witness=good.witness,
        checks=good.checks,
        guarantees=good.guarantees,
    )
    with pytest.raises(CertificateVerificationError, match="subject overstates"):
        verify_certificate(forged)

    assert good.claim_id is not None
    false_claim = Claim(
        good.claim_id,
        statement=false_statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        derivation=Derivation.computation("hurwitz.nielsen_class"),
        certificate=forged,
    )
    assert not false_claim.verify(raise_on_failure=False).verified


def test_hurwitz_verifier_can_be_re_registered_without_replay_closures() -> None:
    claim = _small_nielsen().claim()
    default_verifiers.unregister("hurwitz.nielsen_class")
    try:
        assert not Claim.from_dict(claim.to_dict()).verify(raise_on_failure=False).verified
        hurwitz.register_hurwitz_replay()
        assert Claim.from_dict(claim.to_dict()).verify().verified
    finally:
        if "hurwitz.nielsen_class" not in default_verifiers.names():
            hurwitz.register_hurwitz_replay()


def test_component_result_promotes_only_after_portable_operation_replay() -> None:
    nielsen = _small_nielsen()
    component = hurwitz.braid_action(nielsen, mode="pure").components().one()
    claim = component.claim()
    assert claim.status is EpistemicStatus.EXACT
    assert claim.how is not None
    assert claim.how.operation == "hurwitz.components"
    assert Claim.from_dict(claim.to_dict()).verify().verified
