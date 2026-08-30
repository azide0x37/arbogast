from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

import arbogast.padic.fields as padic_fields
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import Claim, ClaimGraph
from arbogast.padic.certificate import PAdicReceipt
from arbogast.padic.errors import PAdicValidationError, PAdicVerificationError
from arbogast.padic.fields import (
    LocalFieldEmbedding,
    PAdicAutomorphism,
    PAdicBall,
    PAdicElement,
    PAdicField,
    PAdicPrecisionRing,
    PAdicPresentationKind,
)
from arbogast.padic.matrices import PAdicMatrix, PAdicMatrixError
from arbogast.padic.modules import PAdicModule, PAdicSubmodule
from arbogast.padic.semantic import receipt_for_result


def test_portable_rational_unramified_and_eisenstein_presentations() -> None:
    rational = PAdicField.rational(3)
    unramified = PAdicField.unramified(3, (1, 0, 1))
    eisenstein = PAdicField.eisenstein(3, (-3, 0, 1))
    degree_one_eisenstein = PAdicField.eisenstein(3, (-3, 1))

    assert rational.verify()
    assert (rational.degree, rational.ramification_index, rational.residue_degree) == (1, 1, 1)
    assert (unramified.degree, unramified.ramification_index, unramified.residue_degree) == (
        2,
        1,
        2,
    )
    assert (eisenstein.degree, eisenstein.ramification_index, eisenstein.residue_degree) == (
        2,
        2,
        1,
    )
    assert unramified.uniformizer_element.valuation == 1
    assert eisenstein.uniformizer_element.valuation == Fraction(1, 2)
    assert degree_one_eisenstein.generator == degree_one_eisenstein.uniformizer_element
    assert degree_one_eisenstein.generator == degree_one_eisenstein.from_coordinates((3,))
    assert PAdicField.unramified(3, (1, 1)).verify()


def test_invalid_local_presentations_fail_closed() -> None:
    with pytest.raises(PAdicValidationError, match="irreducible modulo p"):
        PAdicField.unramified(3, (-1, 0, 1))
    with pytest.raises(PAdicValidationError, match="divisible by p"):
        PAdicField.eisenstein(3, (-3, 1, 1))
    with pytest.raises(PAdicValidationError, match="exact p-valuation one"):
        PAdicField.eisenstein(3, (-9, 0, 1))
    with pytest.raises(PAdicValidationError, match="ramification and residue"):
        PAdicField(
            3,
            (1, 0, 1),
            witness=PAdicPresentationKind.UNRAMIFIED,
            ramification_index=2,
        )
    with pytest.raises(TypeError, match="integer"):
        PAdicField.rational(True)  # type: ignore[arg-type]


def test_exact_elements_arithmetic_inverse_and_normalized_valuation() -> None:
    field = PAdicField.eisenstein(3, (-3, 0, 1))
    uniformizer = field.generator

    assert uniformizer * uniformizer == field.from_power_basis_coordinates((3,))
    assert uniformizer.valuation == Fraction(1, 2)
    assert (uniformizer / 3).valuation == Fraction(-1, 2)
    value = field.from_power_basis_coordinates((1, 1))
    assert value * value.inverse() == field.one
    assert PAdicElement.from_dict(field, value.to_schema_document()) == value


def test_precision_rings_are_exact_finite_rings_and_balls_are_cosets() -> None:
    unramified = PAdicField.unramified(3, (1, 0, 1))
    unramified_ring = PAdicPrecisionRing(unramified, 2)
    assert unramified_ring.cardinality == 81
    assert unramified_ring.modulus_hnf == ((9, 0), (0, 9))

    ramified = PAdicField.eisenstein(3, (-3, 0, 1))
    ring = PAdicPrecisionRing(ramified, 3)
    assert ring.cardinality == 27
    assert ring.uniformizer**2 == ring.from_element(ramified.from_power_basis_coordinates((3,)))
    assert not (ring.uniformizer**2).is_zero
    assert ring.uniformizer.valuation_interval == (Fraction(1, 2), Fraction(1, 2))
    assert (ring.uniformizer**2).valuation_interval == (Fraction(1), Fraction(1))
    assert ring.zero.valuation_interval == (Fraction(3, 2), None)

    unit = ring.from_element(ramified.from_power_basis_coordinates((1, 1)))
    assert unit * unit.inverse() == ring.one
    assert PAdicBall(ring, (9, 3)) == ring.zero
    with pytest.raises(PAdicValidationError, match="nonintegral"):
        ring.from_element(ramified.from_power_basis_coordinates((Fraction(1, 3),)))


def test_precision_ring_uses_the_local_p_primary_uniformizer_lattice() -> None:
    rational_with_unit_uniformizer = PAdicField(
        3,
        witness=PAdicPresentationKind.RATIONAL,
        uniformizer=(6,),
    )
    assert PAdicPrecisionRing(rational_with_unit_uniformizer, 3).modulus_hnf == ((27,),)

    ramified = PAdicField.eisenstein(3, (6, 3, 1))
    expected_hnfs = (
        ((3, 0), (0, 1)),
        ((3, 0), (0, 3)),
        ((9, 0), (0, 3)),
        ((9, 0), (0, 9)),
    )
    for precision, expected_hnf in enumerate(expected_hnfs, start=1):
        ring = PAdicPrecisionRing(ramified, precision)
        assert ring.modulus_hnf == expected_hnf
        assert ring.cardinality == 3**precision
        assert verify_certificate(ring.certificate).valid
        assert ring.claim().verify().verified


def test_precision_ring_rejects_excessive_saturation_work_before_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field = PAdicField.eisenstein(2, (-2, *(0 for _ in range(15)), 1))

    def unexpected_saturation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("p-primary saturation started before its work cap")

    monkeypatch.setattr(padic_fields, "_p_primary_saturation", unexpected_saturation)
    with pytest.raises(PAdicValidationError, match="exact replay work bound"):
        PAdicPrecisionRing(field, 256)


def test_local_embedding_and_finite_ring_automorphism_replay() -> None:
    field = PAdicField.rational(5)
    embedding = LocalFieldEmbedding(field, field, field.zero)
    assert embedding.apply(field.from_coordinates((Fraction(7, 2),))) == field.from_coordinates(
        (Fraction(7, 2),)
    )

    ring = PAdicPrecisionRing(field, 3)
    automorphism = PAdicAutomorphism.identity(ring)
    assert automorphism.apply(ring.from_coordinates((17,))) == ring.from_coordinates((17,))
    assert (
        LocalFieldEmbedding.from_dict(
            field,
            field,
            embedding.to_schema_document(),
        )
        == embedding
    )
    assert PAdicAutomorphism.from_dict(ring, automorphism.to_schema_document()) == automorphism

    quadratic = PAdicField.unramified(3, (1, 0, 1))
    with pytest.raises(PAdicValidationError, match="does not satisfy"):
        LocalFieldEmbedding(quadratic, quadratic, quadratic.one)


def test_matrix_arithmetic_berkowitz_charpoly_and_safe_inversion() -> None:
    field = PAdicField.rational(3)
    ring = PAdicPrecisionRing(field, 3)
    matrix = PAdicMatrix(ring, ((1, 2), (0, 1)))

    assert matrix @ matrix.inverse() == PAdicMatrix.identity(ring, 2)
    assert tuple(value.coordinates[0] for value in matrix.charpoly()) == (1, 25, 1)
    assert matrix.determinant == ring.one
    assert matrix.transpose().entries[1][0] == ring.from_coordinates((2,))
    assert PAdicMatrix.from_dict(ring, matrix.to_schema_document()) == matrix

    exact = PAdicMatrix(field, ((1, 2), (3, 4)))
    assert tuple(value.coordinates[0] for value in exact.charpoly()) == (-2, -5, 1)
    assert exact @ exact.inverse() == PAdicMatrix.identity(field, 2)

    with pytest.raises(PAdicMatrixError, match="not invertible"):
        PAdicMatrix(ring, ((3, 0), (0, 1))).inverse()
    foreign = PAdicPrecisionRing(PAdicField.rational(5), 2)
    with pytest.raises(PAdicValidationError, match="different precision ring"):
        PAdicMatrix(ring, ((foreign.one,),))
    with pytest.raises(PAdicValidationError, match="identity size"):
        PAdicMatrix.identity(field, 65)
    with pytest.raises(PAdicMatrixError, match="exact replay work bound"):
        PAdicMatrix.identity(field, 64).charpoly()


def test_free_module_and_nonfree_submodule_have_canonical_hnf() -> None:
    ring = PAdicPrecisionRing(PAdicField.rational(2), 2)
    module = PAdicModule(ring, 1, basis_labels=("v",))
    even = PAdicSubmodule(module, ((2,),))

    assert even.preimage_hnf == ((2,),)
    assert even.cardinality == 2
    assert even.contains((0,))
    assert even.contains((2,))
    assert not even.contains((1,))
    assert PAdicSubmodule.zero(module).cardinality == 1
    assert PAdicSubmodule.whole(module).cardinality == 4

    rank_two = PAdicModule(ring, 2)
    first_then_second = PAdicSubmodule(
        rank_two,
        (rank_two.basis_vector(0), tuple(value * 2 for value in rank_two.basis_vector(1))),
    )
    second_then_first = PAdicSubmodule(
        rank_two,
        (tuple(value * 2 for value in rank_two.basis_vector(1)), rank_two.basis_vector(0)),
    )
    assert first_then_second == second_then_first
    assert PAdicModule.from_dict(ring, module.to_schema_document()) == module
    assert PAdicSubmodule.from_dict(module, even.to_schema_document()) == even


def test_submodule_hnf_rejects_work_beyond_the_portable_bound() -> None:
    field = PAdicField.eisenstein(3, (-3, *(0 for _ in range(7)), 1))
    ring = PAdicPrecisionRing(field, 1)
    module = PAdicModule(ring, 16)
    with pytest.raises(PAdicValidationError, match="exact replay work bound"):
        PAdicSubmodule(module, ((0,) * module.rank for _ in range(128)))


def test_strict_transport_and_arithmetic_tampering_are_rejected() -> None:
    field = PAdicField.unramified(3, (1, 0, 1))
    field_document = deepcopy(field.to_schema_document())
    field_document["residue_degree"] = 1
    with pytest.raises(PAdicValidationError, match="ramification and residue"):
        PAdicField.from_dict(field_document)

    ring = PAdicPrecisionRing(field, 2)
    ring_document = deepcopy(ring.to_schema_document())
    hnf = ring_document["modulus_hnf"]
    assert isinstance(hnf, list) and isinstance(hnf[0], list)
    hnf[0][0] = 3
    with pytest.raises(PAdicVerificationError, match="strict canonical transport"):
        PAdicPrecisionRing.from_dict(field, ring_document)

    matrix = PAdicMatrix(ring, ((1,),))
    matrix_document = deepcopy(matrix.to_schema_document())
    matrix_document["shape"] = (1, 1)
    with pytest.raises(PAdicVerificationError, match="strict canonical transport"):
        PAdicMatrix.from_dict(ring, matrix_document)


def test_readdressed_ring_and_submodule_receipts_replay_arithmetic() -> None:
    field = PAdicField.rational(5)
    ring = PAdicPrecisionRing(field, 3)
    ring_receipt = receipt_for_result(ring)
    ring_payload = deepcopy(ring_receipt.payload.to_dict())
    ring_result = ring_payload["result"]
    assert isinstance(ring_result, dict)
    modulus_hnf = ring_result["modulus_hnf"]
    assert isinstance(modulus_hnf, list) and isinstance(modulus_hnf[0], list)
    modulus_hnf[0][0] = 25
    forged_ring = PAdicReceipt.create(
        ring_receipt.kind,
        ring_receipt.closure,
        ring_payload,
        proof_context=ring_receipt.proof_context,
        evidence=ring_receipt.evidence,
    )
    with pytest.raises(PAdicVerificationError):
        forged_ring.verify()

    module = PAdicModule(ring, 1)
    submodule = PAdicSubmodule(module, ((5,),))
    submodule_receipt = receipt_for_result(submodule)
    submodule_payload = deepcopy(submodule_receipt.payload.to_dict())
    submodule_result = submodule_payload["result"]
    assert isinstance(submodule_result, dict)
    preimage_hnf = submodule_result["preimage_hnf"]
    assert isinstance(preimage_hnf, list) and isinstance(preimage_hnf[0], list)
    preimage_hnf[0][0] = 1
    forged_submodule = PAdicReceipt.create(
        submodule_receipt.kind,
        submodule_receipt.closure,
        submodule_payload,
        proof_context=submodule_receipt.proof_context,
        evidence=submodule_receipt.evidence,
    )
    with pytest.raises(PAdicVerificationError):
        forged_submodule.verify()


def test_substrate_receipts_roundtrip_and_claim_replays_fresh(tmp_path: Path) -> None:
    field = PAdicField.rational(5)
    ring = PAdicPrecisionRing(field, 3)
    module = PAdicModule(ring, 1)
    submodule = PAdicSubmodule(module, ((5,),))

    values = (
        field,
        ring,
        LocalFieldEmbedding(field, field, field.zero),
        PAdicAutomorphism.identity(ring),
        module,
        submodule,
    )
    assert field.claim().verify().verified
    for value in values:
        certificate = VerificationCertificate.from_dict(value.certificate.to_dict())
        assert verify_certificate(certificate).valid
        assert value.claim().why == ()
        assert value.claim().verify().verified
        assert Claim.from_dict(value.claim().to_dict()).verify().verified
        assert len(value.claim_graph()) == 1
        assert value.claim_graph().verify().verified
        assert ClaimGraph.from_dict(value.claim_graph().to_dict()).verify().verified

    claim_path = tmp_path / "padic-claim-graph.json"
    claim_path.write_text(json.dumps(submodule.claim_graph().to_dict()), encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(project_root / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from arbogast.claims import ClaimGraph; "
                "graph=ClaimGraph.from_dict(json.load(open(sys.argv[1],encoding='utf-8'))); "
                "assert graph.verify().verified"
            ),
            str(claim_path),
            str(project_root / "src"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
