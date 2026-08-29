from __future__ import annotations

import json
from dataclasses import replace

import pytest

from arbogast.cert import VerificationCertificate
from arbogast.claims import (
    Claim,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
)
from arbogast.cohom import (
    CertificateVerificationError,
    CoboundaryWitness,
    CohomologyCertificate,
    CohomologyClass,
    CohomologyError,
    ComplexityLimitError,
    ComplexityLimits,
    class_of,
    cochain_complex,
    h0,
    h1,
    h2,
    is_coboundary,
    is_cocycle,
)
from arbogast.cohom.complex import _canonical_json as cohom_canonical_json
from arbogast.core import canonical_json


class PrimeField:
    def __init__(self, prime: int) -> None:
        self.characteristic = prime
        self.order = prime


class CyclicGroup:
    def __init__(self, order: int, *, reverse: bool = False) -> None:
        self.order = order
        sequence = tuple(range(order))
        self.elements = tuple(reversed(sequence)) if reverse else sequence
        self.identity = 0

    def multiply(self, left: int, right: int) -> int:
        return (left + right) % self.order


class ScalarModule:
    def __init__(self, prime: int, action: tuple[int, ...]) -> None:
        self.field = PrimeField(prime)
        self.dimension = 1
        self._action = action

    def action_matrix(self, element: int) -> tuple[tuple[int, ...], ...]:
        return ((self._action[element],),)


def trivial_module(prime: int, group_order: int) -> ScalarModule:
    return ScalarModule(prime, (1,) * group_order)


@pytest.mark.parametrize(
    ("group_order", "prime", "higher_dimension"),
    [(2, 2, 1), (3, 3, 1), (5, 5, 1), (3, 2, 0), (5, 2, 0)],
)
def test_trivial_cyclic_group_cohomology(
    group_order: int, prime: int, higher_dimension: int
) -> None:
    group = CyclicGroup(group_order)
    module = trivial_module(prime, group_order)

    invariant_result = h0(group, module)
    first_result = h1(group, module)
    second_result = h2(group, module)

    assert invariant_result.dimension == 1
    assert first_result.dimension == higher_dimension
    assert second_result.dimension == higher_dimension
    assert invariant_result.verify()
    assert first_result.verify()
    assert second_result.verify()


def test_nontrivial_c2_action_has_no_cohomology_over_f3() -> None:
    group = CyclicGroup(2)
    sign_module = ScalarModule(3, (1, -1))

    assert h0(group, sign_module).dimension == 0
    assert h1(group, sign_module).dimension == 0
    assert h2(group, sign_module).dimension == 0


def test_bar_differentials_square_to_zero_and_are_deterministic() -> None:
    module = trivial_module(3, 3)
    forward = cochain_complex(CyclicGroup(3), module, 2)
    reversed_enumeration = cochain_complex(CyclicGroup(3, reverse=True), module, 2)

    assert forward.content_hash == reversed_enumeration.content_hash
    assert forward.differential_hashes == reversed_enumeration.differential_hashes
    assert forward.verify()
    assert all(
        not any(forward.differential(degree).apply(forward.differential(degree - 1).column(column)))
        for degree in (1, 2)
        for column in range(forward.differential(degree - 1).ncols)
    )


def test_explicit_class_reduction_and_coboundary_primitive() -> None:
    group = CyclicGroup(2)
    sign_module = ScalarModule(3, (1, -1))
    result = h1(group, sign_module)
    cocycle = result.cocycles.basis[0]

    assert is_cocycle(cocycle)
    witness = is_coboundary(cocycle, result)
    assert witness
    assert witness.primitive is not None
    assert witness.verify()
    reduced = class_of(cocycle, result)
    assert reduced.is_zero
    assert reduced.representative.values == (0,)


def test_quotient_projection_and_representative_for_nonzero_h1_class() -> None:
    result = h1(CyclicGroup(2), trivial_module(2, 2))
    generator = result.cocycles.basis[0]
    cohomology_class = result.class_of(generator)

    assert cohomology_class.coordinates == (1,)
    assert cohomology_class.representative == result.representatives[0]
    assert result.quotient_map.project_vector(generator.values) == (1,)
    assert result.quotient_map.section_vector((1,)) == generator.values
    assert cohomology_class.verify()


def test_certificate_json_round_trip_replays_without_group_objects() -> None:
    result = h2(CyclicGroup(3), trivial_module(3, 3))
    encoded = result.certificate.to_json()
    decoded = CohomologyCertificate.from_json(encoded)

    assert decoded == result.certificate
    assert decoded.content_hash == result.certificate.content_hash
    report = decoded.verify()
    assert report
    assert "kernel-recomputed" in report.checks
    assert "explicit-quotient-maps" in report.checks


def test_certificate_tampering_fails_closed() -> None:
    certificate = h1(CyclicGroup(2), trivial_module(2, 2)).certificate
    forged = replace(certificate, representative_basis=())

    report = forged.verify(raise_on_error=False)
    assert not report
    assert report.error is not None
    with pytest.raises(CertificateVerificationError):
        forged.verify()


def test_complexity_limits_are_explicit_and_checked_before_linear_algebra() -> None:
    limits = ComplexityLimits(
        max_group_order=10,
        max_cochain_dimension=10,
        max_differential_nonzeros=100,
        max_rref_cells=100,
    )
    with pytest.raises(ComplexityLimitError, match=r"C\^2|C\^3"):
        h2(CyclicGroup(4), trivial_module(2, 4), limits=limits)


def test_claim_and_certificate_hooks_are_bound() -> None:
    result = h1(CyclicGroup(2), trivial_module(2, 2))
    claim = result.claim()

    assert isinstance(claim, Claim)
    assert claim.kind is ClaimKind.COMPUTED
    assert claim.status is EpistemicStatus.EXACT
    assert claim.statement.parameters["dimension"] == 1
    assert claim.metadata["domain_certificate_hash"] == (
        f"sha256:{result.certificate.content_hash}"
    )
    assert claim.verify().verified
    assert result.certify() is result.certificate
    semantic_certificate = result.verification_certificate()
    assert isinstance(semantic_certificate, VerificationCertificate)
    assert semantic_certificate.claim_id == claim.id
    assert semantic_certificate.statement_hash == claim.statement.statement_hash
    assert semantic_certificate.certificate_id in {evidence.ref for evidence in claim.evidence}

    replayed = Claim.from_dict(json.loads(json.dumps(claim.to_dict())))
    assert replayed == claim
    assert replayed.verify().verified
    exported = Claim.from_dict(json.loads(claim.export("json")))
    assert exported.verify().verified
    assert "normalized-bar cohomology" in claim.export("latex")
    assert "Generated by Arbogast" in claim.export("lean")
    assert result.claim_graph().verify().verified


def test_semantic_verifier_derives_claim_identity_and_statement_from_domain_receipt() -> None:
    result = h1(CyclicGroup(5), trivial_module(11, 5))
    valid = result.verification_certificate()
    false_statement = FormalStatement.create(
        text="The normalized-bar cohomology has dimension 999."
    )
    forged_certificate = VerificationCertificate.create(
        subject=valid.subject,
        verifier=valid.verifier,
        claim_id="false",
        statement_hash=false_statement.statement_hash,
        witness=valid.witness.to_dict(),
        checks=valid.checks,
        guarantees=valid.guarantees,
    )
    forged_claim = Claim(
        id="false",
        statement=false_statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("cohom.h1"),
        certificate=forged_certificate,
    )

    report = forged_claim.verify(raise_on_failure=False)
    assert not report.verified
    assert report.error is not None
    assert "claim ID" in report.error


def test_claim_from_a_larger_complex_uses_a_receipt_replayable_statement() -> None:
    complex_ = cochain_complex(CyclicGroup(2), trivial_module(2, 2), 2)
    result = h1(complex_)

    assert result.claim().verify().verified


def test_complex_verification_binds_differential_objects_and_content_hash() -> None:
    complex_ = cochain_complex(CyclicGroup(2), ScalarModule(3, (1, -1)), 1)
    zero_d0 = type(complex_.differential(0)).zero(
        complex_.differential(0).nrows,
        complex_.differential(0).ncols,
        complex_.prime,
    )
    forged_differentials = replace(complex_, differentials=(zero_d0, complex_.differential(1)))
    with pytest.raises(CohomologyError, match="stored differentials"):
        forged_differentials.verify()

    forged_hash = replace(complex_, content_hash="0" * 64)
    with pytest.raises(CohomologyError, match="content hash"):
        forged_hash.verify()


def test_result_verification_binds_every_public_linear_algebra_field() -> None:
    result = h1(CyclicGroup(2), trivial_module(2, 2))
    for forged in (
        replace(result, representative_vectors=()),
        replace(result, cocycles=replace(result.cocycles, basis_vectors=())),
        replace(
            result,
            coboundaries=replace(
                result.coboundaries,
                basis_vectors=result.certificate.cocycle_basis,
            ),
        ),
        replace(
            result,
            quotient_map=replace(result.quotient_map, projection_matrix=()),
        ),
    ):
        with pytest.raises(CohomologyError, match="not bound"):
            forged.verify()


def test_class_rejects_a_representative_from_another_complex() -> None:
    zero_result = h1(CyclicGroup(3), trivial_module(2, 3))
    foreign_representative = h1(CyclicGroup(2), trivial_module(2, 2)).representatives[0]

    with pytest.raises(ValueError, match="different cochain complex"):
        CohomologyClass(zero_result, (), foreign_representative)


def test_negative_coboundary_witness_recomputes_nonmembership() -> None:
    result = h1(CyclicGroup(2), ScalarModule(3, (1, -1)))
    known_boundary = result.cocycles.basis[0]

    forged_negative = CoboundaryWitness(False, known_boundary, None)
    assert not forged_negative.verify()


def test_certificate_rejects_noncanonical_residue_encodings() -> None:
    certificate = h1(CyclicGroup(2), trivial_module(2, 2)).certificate
    noncanonical_actions = tuple(
        tuple(tuple(value + certificate.prime for value in row) for row in matrix)
        for matrix in certificate.action_matrices
    )
    forged = replace(certificate, action_matrices=noncanonical_actions)

    report = forged.verify(raise_on_error=False)
    assert not report
    assert report.error is not None
    assert "canonical integer residues" in report.error


def test_certificate_from_dict_is_strict_and_json_rejects_duplicate_fields() -> None:
    certificate = h1(CyclicGroup(2), trivial_module(2, 2)).certificate
    payload = certificate.to_dict()
    payload["prime"] = "2"
    with pytest.raises(ValueError, match="prime must be an integer"):
        CohomologyCertificate.from_dict(payload)

    encoded = certificate.to_json()
    duplicated = encoded.replace('"prime":2', '"prime":2,"prime":2', 1)
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        CohomologyCertificate.from_json(duplicated)


def test_cohomology_hashes_share_the_core_canonical_json_boundary() -> None:
    decomposed = {"e\u0301": "e\u0301"}
    assert cohom_canonical_json(decomposed) == canonical_json(decomposed)
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        cohom_canonical_json({1: "not silently stringified"})

    certificate = h1(CyclicGroup(2), trivial_module(2, 2)).certificate
    noncanonical_identifier = json.dumps("e\u0301", ensure_ascii=False)
    forged = replace(
        certificate,
        group_element_ids=(noncanonical_identifier, *certificate.group_element_ids[1:]),
    )
    report = forged.verify(raise_on_error=False)
    assert not report
    assert report.error is not None
    assert "shared canonical JSON" in report.error
