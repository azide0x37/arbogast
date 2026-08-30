from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.fields import PAdicAutomorphism, PAdicField, PAdicPrecisionRing
from arbogast.padic.frobenius import (
    FrobeniusConvention,
    FrobeniusOperator,
    SlopeProjector,
    frobenius,
    ordinary_part,
    slopes,
)
from arbogast.padic.inertia import (
    FiniteInertiaQuotient,
    InertiaFiltration,
    InertiaRepresentation,
    inertia_action,
)
from arbogast.padic.matrices import PAdicMatrix
from arbogast.padic.modules import PAdicModule
from arbogast.rep import Permutation, PermutationGroup


def test_frobenius_slopes_ordinary_and_inertia_replay_fresh() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(5), 3)
    module = PAdicModule(ring, 2)
    operator = FrobeniusOperator(
        module,
        PAdicMatrix(ring, ((1, 0), (0, 5))),
        PAdicAutomorphism.identity(ring),
        FrobeniusConvention.ARITHMETIC,
    )
    identity = PAdicMatrix.identity(ring, 2)
    projector = SlopeProjector(
        operator,
        0,
        1,
        PAdicMatrix(ring, ((1, 0), (0, 0))),
        identity,
        identity,
    )
    inertia_generator = Permutation.from_cycles(3, ((0, 1, 2),))
    inertia_group = PermutationGroup((inertia_generator,), degree=3)
    quotient = FiniteInertiaQuotient(module.module_id, "v2", 2, 1, inertia_group)
    filtration = InertiaFiltration(
        quotient,
        (inertia_group.elements, (inertia_group.identity,)),
    )
    inertia = InertiaRepresentation(
        module,
        quotient,
        filtration,
        {element: identity for element in inertia_group.elements},
    )
    results = (
        frobenius(module, datum=operator),
        slopes(operator, projectors=(projector,)),
        ordinary_part(operator, projector=projector),
        inertia_action(module, datum=inertia),
    )
    certificates = [result.certificate.to_dict() for result in results]

    forged_payload = deepcopy(results[0].receipt.payload.to_dict())
    forged_document = forged_payload["result"]
    assert isinstance(forged_document, dict)
    forged_document["semilinear_period"] = 2
    forged_receipt = PAdicReceipt.create(
        results[0].receipt.kind,
        results[0].receipt.closure,
        forged_payload,
        proof_context=results[0].receipt.proof_context,
        evidence=results[0].receipt.evidence,
    )
    hostile_payload = deepcopy(results[3].receipt.payload.to_dict())
    hostile_document = hostile_payload["result"]
    assert isinstance(hostile_document, dict)
    hostile_quotient = hostile_document["quotient"]
    assert isinstance(hostile_quotient, dict)
    hostile_group = hostile_quotient["group"]
    assert isinstance(hostile_group, dict)
    # A 10-cycle and a transposition generate S_10.  The declared table is
    # intentionally left small and false: replay must hit the bounded closure
    # ceiling after 1,025 elements, before PermutationGroup's unbounded BFS.
    hostile_group["degree"] = 10
    hostile_group["order"] = 3
    hostile_group["generators"] = [
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
        [1, 0, 2, 3, 4, 5, 6, 7, 8, 9],
    ]
    hostile_receipt = PAdicReceipt.create(
        results[3].receipt.kind,
        results[3].receipt.closure,
        hostile_payload,
        proof_context=results[3].receipt.proof_context,
        evidence=results[3].receipt.evidence,
    )
    oversized_generator_payload = deepcopy(results[3].receipt.payload.to_dict())
    oversized_generator_document = oversized_generator_payload["result"]
    assert isinstance(oversized_generator_document, dict)
    oversized_generator_quotient = oversized_generator_document["quotient"]
    assert isinstance(oversized_generator_quotient, dict)
    oversized_generator_group = oversized_generator_quotient["group"]
    assert isinstance(oversized_generator_group, dict)
    oversized_generator_group["generators"] = [list(range(65))]
    oversized_generator_receipt = PAdicReceipt.create(
        results[3].receipt.kind,
        results[3].receipt.closure,
        oversized_generator_payload,
        proof_context=results[3].receipt.proof_context,
        evidence=results[3].receipt.evidence,
    )
    oversized_matrix_payload = deepcopy(results[0].receipt.payload.to_dict())
    oversized_matrix_document = oversized_matrix_payload["result"]
    assert isinstance(oversized_matrix_document, dict)
    oversized_matrix = oversized_matrix_document["matrix"]
    assert isinstance(oversized_matrix, dict)
    oversized_entries = oversized_matrix["entries"]
    assert isinstance(oversized_entries, list) and oversized_entries
    oversized_entries.extend(deepcopy(oversized_entries[0]) for _ in range(63))
    oversized_matrix_receipt = PAdicReceipt.create(
        results[0].receipt.kind,
        results[0].receipt.closure,
        oversized_matrix_payload,
        proof_context=results[0].receipt.proof_context,
        evidence=results[0].receipt.evidence,
    )
    oversized_projectors_payload = deepcopy(results[1].receipt.payload.to_dict())
    oversized_projectors_document = oversized_projectors_payload["result"]
    assert isinstance(oversized_projectors_document, dict)
    projector_documents = oversized_projectors_document["projectors"]
    assert isinstance(projector_documents, list) and projector_documents
    oversized_projectors_document["projectors"] = [
        deepcopy(projector_documents[0]) for _ in range(module.rank + 1)
    ]
    oversized_projectors_receipt = PAdicReceipt.create(
        results[1].receipt.kind,
        results[1].receipt.closure,
        oversized_projectors_payload,
        proof_context=results[1].receipt.proof_context,
        evidence=results[1].receipt.evidence,
    )
    oversized_hnf_payload = deepcopy(results[2].receipt.payload.to_dict())
    oversized_hnf_document = oversized_hnf_payload["result"]
    assert isinstance(oversized_hnf_document, dict)
    oversized_submodule = oversized_hnf_document["submodule"]
    assert isinstance(oversized_submodule, dict)
    oversized_hnf = oversized_submodule["preimage_hnf"]
    assert isinstance(oversized_hnf, list) and oversized_hnf
    oversized_hnf.append(deepcopy(oversized_hnf[0]))
    oversized_hnf_receipt = PAdicReceipt.create(
        results[2].receipt.kind,
        results[2].receipt.closure,
        oversized_hnf_payload,
        proof_context=results[2].receipt.proof_context,
        evidence=results[2].receipt.evidence,
    )
    payload = json.dumps(
        {
            "certificates": certificates,
            "forged_receipt": forged_receipt.to_dict(),
            "hostile_receipt": hostile_receipt.to_dict(),
            "oversized_generator_receipt": oversized_generator_receipt.to_dict(),
            "oversized_receipts": [
                oversized_matrix_receipt.to_dict(),
                oversized_projectors_receipt.to_dict(),
                oversized_hnf_receipt.to_dict(),
            ],
        }
    )
    source_root = Path(__file__).resolve().parents[2] / "src"
    program = """
import json, sys
sys.path.insert(0, sys.argv[1])
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.errors import PAdicResourceError, PAdicVerificationError

payload = json.load(sys.stdin)
for raw in payload["certificates"]:
    certificate = VerificationCertificate.from_dict(raw)
    assert verify_certificate(certificate).valid
forged = PAdicReceipt.from_dict(payload["forged_receipt"])
try:
    forged.verify()
except PAdicVerificationError:
    pass
else:
    raise AssertionError("tampered Frobenius witness replayed as valid")
hostile = PAdicReceipt.from_dict(payload["hostile_receipt"])
try:
    hostile.verify()
except PAdicResourceError:
    pass
else:
    raise AssertionError("unbounded hostile finite-group closure reached general replay")
oversized_generator = PAdicReceipt.from_dict(payload["oversized_generator_receipt"])
try:
    oversized_generator.verify()
except PAdicVerificationError:
    pass
else:
    raise AssertionError("oversized generator row reached permutation construction")
for raw in payload["oversized_receipts"]:
    oversized = PAdicReceipt.from_dict(raw)
    try:
        oversized.verify()
    except PAdicResourceError:
        pass
    else:
        raise AssertionError("oversized nested p-adic collection reached unbounded replay")
print("padic-frobenius-inertia-fresh-ok")
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
    assert completed.stdout.strip() == "padic-frobenius-inertia-fresh-ok"
