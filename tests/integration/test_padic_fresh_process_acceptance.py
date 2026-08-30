from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arbogast.padic.fields import PAdicField
from arbogast.padic.results import (
    Partial,
    ProofObligation,
    certified_result,
    partial_result,
    unknown_result,
    unsupported_result,
)


def test_both_verifier_families_and_partial_graph_replay_in_a_fresh_process() -> None:
    field = certified_result(PAdicField(2), "field")
    obligation = ProofObligation(
        "supply a stable reduction witness",
        "stabilization-witness",
        "stable-reduction",
        input_ids=(field.value.content_id,),
    )
    partial = partial_result(
        "padic.stable_reduction",
        "stabilization remains open",
        (field,),
        (obligation,),
        family="three-point",
    )
    assert isinstance(partial, Partial)
    unknown = unknown_result(
        "padic.slopes",
        "ambiguous-newton-polygon",
        "finite precision does not separate every Newton vertex",
        requested={"precision": 4},
        family="finite",
    )
    unsupported = unsupported_result(
        "padic.stable_reduction",
        "not-three-point",
        "only normalized three-point covers are supported",
        requested={"branch_count": 4},
        supported=("normalized-three-point-cover",),
        family="three-point",
    )
    results = (field, partial, unknown, unsupported)
    payload = json.dumps(
        {
            "certificates": [item.certificate.to_dict() for item in results],
            "claims": [item.claim().to_dict() for item in results],
            "graphs": [item.claim_graph().to_dict() for item in results],
        }
    )
    source_root = Path(__file__).resolve().parents[2] / "src"
    program = """
import json, sys
sys.path.insert(0, sys.argv[1])
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import Claim, ClaimGraph

payload = json.load(sys.stdin)
verifiers = set()
for raw in payload["certificates"]:
    certificate = VerificationCertificate.from_dict(raw)
    assert verify_certificate(certificate).valid
    verifiers.add(certificate.verifier)
for raw in payload["claims"]:
    claim = Claim.from_dict(raw)
    assert claim.dependency_ids == ()
    assert claim.verify().verified
for raw in payload["graphs"]:
    assert ClaimGraph.from_dict(raw).verify().verified
assert verifiers == {"padic.finite-exact.v1", "padic.three-point-exact.v1"}
print("padic-fresh-replay-ok")
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", program, str(source_root)),
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == "padic-fresh-replay-ok"
