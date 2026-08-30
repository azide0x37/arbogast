from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arbogast.numeric import (
    AlgebraicCandidate,
    ComplexBall,
    Dyadic,
    ExactificationResult,
    ExactPolynomial,
    NumericPoint,
    PolynomialSystem,
    RecognitionBounds,
    exactify,
    recognize,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _exact_sqrt2() -> ExactificationResult:
    enclosure = ComplexBall(Dyadic(181, -7), Dyadic(1, -10))
    candidate = recognize(enclosure, RecognitionBounds(2, 2))
    assert isinstance(candidate, AlgebraicCandidate)
    system = PolynomialSystem(
        1,
        (
            ExactPolynomial(
                1,
                {(0,): -2, (2,): 1},
                variable_names=("x",),
            ),
        ),
    )
    result = exactify(NumericPoint(system, (enclosure,)), candidate=candidate)
    assert isinstance(result, ExactificationResult)
    return result


def test_numeric_certificate_and_claim_graph_replay_in_an_isolated_process(
    tmp_path: Path,
) -> None:
    result = _exact_sqrt2()
    payload_path = tmp_path / "numeric-exactification.json"
    payload_path.write_text(
        json.dumps(
            {
                "certificate": result.certificate.to_dict(),
                "claim_graph": result.claim_graph().to_dict(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    code = """
import json
import sys
import arbogast.numeric.semantic
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import ClaimGraph

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
certificate = VerificationCertificate.from_dict(payload["certificate"])
report = verify_certificate(certificate)
assert report.valid
graph = ClaimGraph.from_dict(payload["claim_graph"])
assert graph.verify().verified
assert graph.claims[0].status.value == "exact"
print(certificate.certificate_id)
print(graph.claims[0].status.value)
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(payload_path)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.splitlines() == [result.certificate.certificate_id, "exact"]
