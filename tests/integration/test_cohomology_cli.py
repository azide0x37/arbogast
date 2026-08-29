from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arbogast.cert import VerificationCertificate
from arbogast.claims import FormalStatement
from arbogast.cohom import H1Result, h1
from arbogast.linalg import PrimeField
from arbogast.rep import CyclicGroup, Representation

PROJECT_ROOT = Path(__file__).parents[2]


def _verify_in_fresh_process(certificate_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "arbogast.cli",
            "verify",
            str(certificate_path),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _h1_result() -> H1Result:
    group = CyclicGroup(2)
    module = Representation.trivial(group, PrimeField(2))
    return h1(group, module)


def test_saved_h1_verification_wrapper_replays_in_a_fresh_cli_process(tmp_path: Path) -> None:
    result = _h1_result()
    certificate = result.verification_certificate()
    claim = result.claim()
    assert certificate.certificate_id in {evidence.ref for evidence in claim.evidence}

    certificate_path = tmp_path / "h1-verification-certificate.json"
    certificate_path.write_text(
        json.dumps(certificate.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    completed = _verify_in_fresh_process(certificate_path)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)
    assert report["valid"] is True
    assert report["verifier"] == "cohom.normalized_bar.v1"
    assert report["certificate_id"] == certificate.certificate_id
    assert "kernel-recomputed" in report["checks"]


def test_fresh_cli_rejects_a_rehashed_wrapper_with_a_false_claim_binding(tmp_path: Path) -> None:
    valid = _h1_result().verification_certificate()
    false_statement = FormalStatement.create(
        text="The normalized-bar cohomology has dimension 999."
    )
    forged = VerificationCertificate.create(
        subject=valid.subject,
        verifier=valid.verifier,
        claim_id="false",
        statement_hash=false_statement.statement_hash,
        claim_boundary_hash=valid.claim_boundary_hash,
        claim_dependencies=valid.claim_dependencies,
        witness=valid.witness.to_dict(),
        checks=valid.checks,
        guarantees=valid.guarantees,
    )
    certificate_path = tmp_path / "forged-h1-verification-certificate.json"
    certificate_path.write_text(
        json.dumps(forged.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = _verify_in_fresh_process(certificate_path)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["valid"] is False
    assert "claim ID" in report["error"]
