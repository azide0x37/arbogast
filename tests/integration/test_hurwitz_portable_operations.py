from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from arbogast.cert import VerificationCertificate, content_address, verify_certificate
from arbogast.claims import ClaimGraph, EpistemicStatus
from arbogast.hurwitz import (
    BraidWord,
    CertificateVerificationError,
    Collision,
    HurwitzOperationCertificate,
    boundary_incidence,
    braid_action,
    cusps,
    nielsen_class,
    operation_certificate_for,
    real_census,
    real_structure,
    reduced,
    symmetry_from_braid_word,
)
from arbogast.rep import Permutation, PermutationGroup


def _workflow() -> tuple[object, ...]:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    nielsen = nielsen_class(group, (transpositions,) * 4)
    action = braid_action(nielsen)
    component_collection = action.components()
    component = component_collection.one()
    structure = real_structure(nielsen)
    all_real = real_census(nielsen)
    c_one = real_census(nielsen, group.identity)
    cusp_data = cusps(component, "sigma_0")
    symmetry = symmetry_from_braid_word(
        component, BraidWord.generator(0), name="sigma-zero-quotient"
    )
    quotient = reduced(component, (symmetry,))
    incidence = boundary_incidence(component, (Collision(0, 1), Collision(1, 2)))
    return (
        action,
        component_collection,
        component,
        structure,
        all_real,
        c_one,
        quotient,
        cusp_data,
        incidence,
    )


def test_every_public_finite_result_has_a_strict_round_trip_and_exact_claim() -> None:
    expected = (
        "braid_action",
        "components",
        "components",
        "real_structure",
        "real_census",
        "real_census",
        "reduced",
        "cusps",
        "boundary",
    )
    for value, operation in zip(_workflow(), expected, strict=True):
        specialized = operation_certificate_for(value)
        assert specialized.operation == operation
        assert specialized.verify()
        restored = HurwitzOperationCertificate.from_dict(
            json.loads(json.dumps(specialized.to_dict()))
        )
        assert restored == specialized
        assert restored.verify()

        semantic = value.verification_certificate()
        assert semantic.verifier == f"hurwitz.{operation}"
        assert verify_certificate(
            VerificationCertificate.from_dict(json.loads(json.dumps(semantic.to_dict())))
        ).valid
        graph = value.claim_graph()
        report = ClaimGraph.from_dict(json.loads(json.dumps(graph.to_dict()))).verify()
        assert report.verified
        assert graph.claims[0].status is EpistemicStatus.EXACT


def test_operation_certificates_and_claim_graphs_replay_in_a_fresh_process(
    tmp_path: Path,
) -> None:
    values = _workflow()
    payload = {
        "certificates": [value.verification_certificate().to_dict() for value in values],
        "graphs": [value.claim_graph().to_dict() for value in values],
    }
    path = tmp_path / "portable-hurwitz-results.json"
    path.write_text(json.dumps(payload))
    script = (
        "import json,sys; "
        "from arbogast.cert import VerificationCertificate,verify_certificate; "
        "from arbogast.claims import ClaimGraph; "
        "d=json.load(open(sys.argv[1])); "
        "assert all(verify_certificate(VerificationCertificate.from_dict(x)).valid "
        "for x in d['certificates']); "
        "assert all(ClaimGraph.from_dict(x).verify().verified for x in d['graphs'])"
    )
    process = subprocess.run(
        (sys.executable, "-c", script, str(path)),
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr


def test_recomputed_content_ids_do_not_hide_result_or_type_tampering() -> None:
    action = _workflow()[0]
    original = operation_certificate_for(action).to_dict()
    result_tamper = json.loads(json.dumps(original))
    first = result_tamper["result"]["generators"][0]["forward"]
    first[0], first[1] = first[1], first[0]
    result_tamper.pop("certificate_id")
    result_tamper["certificate_id"] = content_address(result_tamper)
    with pytest.raises(CertificateVerificationError, match="result does not replay exactly"):
        HurwitzOperationCertificate.from_dict(result_tamper).verify()

    type_tamper = json.loads(json.dumps(original))
    nested = type_tamper["nielsen_certificate"]
    nested["identity_index"] = True
    nested.pop("certificate_id")
    nested["certificate_id"] = content_address(nested)
    type_tamper.pop("certificate_id")
    type_tamper["certificate_id"] = content_address(type_tamper)
    with pytest.raises(CertificateVerificationError, match="identity_index must be an integer"):
        HurwitzOperationCertificate.from_dict(type_tamper).verify()


def test_context_bound_real_callable_and_imported_nielsen_do_not_promote() -> None:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    transpositions = group.conjugacy_class(left)
    nielsen = nielsen_class(group, (transpositions,) * 4)
    structure = real_structure(
        nielsen,
        transform=lambda context, entries: tuple(
            context.conjugate_left(context.inverse(entry), context.product(entries[:index]))
            for index, entry in enumerate(entries)
        ),
    )
    with pytest.raises(CertificateVerificationError, match="context-bound"):
        structure.claim()
