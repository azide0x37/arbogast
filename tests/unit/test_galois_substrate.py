from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from types import SimpleNamespace

import pytest

import arbogast.galois as public_galois
import arbogast.galois.evidence as galois_evidence
from arbogast.backends.pari_certificate import (
    PARI_VERIFIER_ID,
    create_pari_verification_certificate,
)
from arbogast.cert import (
    CertificateRef,
    VerificationCertificate,
    VerificationReport,
    certificate_from_dict,
    content_address,
    verify_certificate,
)
from arbogast.claims import Claim
from arbogast.core import ValidationError, canonical_json
from arbogast.galois.certificate import (
    ArithmeticCertificateError,
    _verify_archimedean_place_set,
)
from arbogast.galois.fields import (
    FieldEmbedding,
    ModularIrreducibilityWitness,
    NumberField,
    NumberFieldElement,
)
from arbogast.galois.groups import (
    FiniteGaloisQuotient,
    FiniteGaloisQuotientReceipt,
    FiniteGroupExtension,
    FiniteGroupMap,
    finite_galois_quotient_certificate,
)
from arbogast.galois.modules import GaloisModule, GaloisModuleReceipt, galois_module
from arbogast.galois.places import FinitePlace, InfinitePlace, InfinitePlaceKind
from arbogast.galois.proof import (
    Completeness,
    ProofContext,
    Unsupported,
    VerificationRequirement,
    VerifierTrust,
)
from arbogast.galois.semantic import (
    claim_for_result,
    claim_graph_for_result,
    verification_certificate_for_result,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup, Permutation, PermutationGroup, Representation


def _golden_field() -> NumberField:
    return NumberField((-1, -1, 1), generator_name="t")


def _pari_certificate(
    operation: str,
    replay: dict[str, object],
    payload: dict[str, object],
) -> VerificationCertificate:
    return create_pari_verification_certificate(
        operation,
        replay=replay,
        expected_payload=payload,
        backend_version="2.17.4",
        request_id=f"test-{operation}",
        deterministic_seed=1,
        proof_mode="unconditional",
        limits={
            "certification_timeout_seconds": "60",
            "cpu_limit_seconds": 60,
            "memory_limit_bytes": 1_073_741_824,
            "output_limit_bytes": 2_000_000,
            "pari_stack_bytes": 268_435_456,
            "timeout_seconds": "15",
        },
    )


def _accept_stubbed_pari_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    def accept(certificate: VerificationCertificate) -> VerificationReport:
        return VerificationReport(
            valid=True,
            verifier=PARI_VERIFIER_ID,
            certificate_id=certificate.certificate_id,
            checks=("stubbed central replay",),
        )

    monkeypatch.setattr(galois_evidence, "verify_certificate", accept)


def _raw_field_replay(polynomial: tuple[int, ...]) -> dict[str, object]:
    exact_polynomial = [[coefficient, 1] for coefficient in polynomial]
    identity = {
        "defining_polynomial": exact_polynomial,
        "type": "arbogast.pari.raw-number-field/v1",
    }
    return {
        "arguments": {},
        "field": {
            "defining_polynomial": exact_polynomial,
            "field_id": content_address(identity),
            "identity": identity,
            "integral_basis": None,
        },
    }


def _quartic_field_certificate() -> VerificationCertificate:
    polynomial = (1, 1, 0, 0, 1)
    replay = _raw_field_replay(polynomial)
    field_id = replay["field"]["field_id"]  # type: ignore[index]
    basis = [[[int(row == column), 1] for column in range(4)] for row in range(4)]
    return _pari_certificate(
        "field_invariants",
        replay,
        {
            "degree": 4,
            "discriminant": 229,
            "field_id": field_id,
            "index": 1,
            "integral_basis": basis,
            "signature": [0, 2],
        },
    )


def _pinned_field_replay(field: NumberField, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "arguments": arguments,
        "field": {
            "defining_polynomial": [[coefficient, 1] for coefficient in field.defining_polynomial],
            "field_id": field.field_id,
            "identity": field.to_dict(),
            "integral_basis": [
                [[coefficient.numerator, coefficient.denominator] for coefficient in row]
                for row in field.integral_basis
            ],
        },
    }


def _c4_extension() -> FiniteGroupExtension:
    kernel = CyclicGroup(2, name="N")
    total = CyclicGroup(4, name="G")
    quotient = CyclicGroup(2, name="Q")
    kernel_generator = kernel.generator
    total_generator = total.generator
    quotient_generator = quotient.generator
    inclusion = FiniteGroupMap(
        kernel,
        total,
        {
            kernel.identity: total.identity,
            kernel_generator: total_generator * total_generator,
        },
    )
    projection_images: dict[Permutation, Permutation] = {}
    current = total.identity
    for exponent in range(4):
        projection_images[current] = quotient.identity if exponent % 2 == 0 else quotient_generator
        current = current * total_generator
    projection = FiniteGroupMap(total, quotient, projection_images)
    return FiniteGroupExtension(
        kernel,
        total,
        quotient,
        inclusion,
        projection,
    )


def _split_klein_extension() -> FiniteGroupExtension:
    a = Permutation((1, 0, 3, 2))
    b = Permutation((2, 3, 0, 1))
    total = PermutationGroup((a, b), degree=4, name="C2xC2")
    kernel = CyclicGroup(2, name="N")
    quotient = CyclicGroup(2, name="Q")
    inclusion = FiniteGroupMap(
        kernel,
        total,
        {kernel.identity: total.identity, kernel.generator: a},
    )
    images = {
        element: (quotient.identity if element in {total.identity, a} else quotient.generator)
        for element in total.elements
    }
    projection = FiniteGroupMap(total, quotient, images)
    return FiniteGroupExtension(
        kernel,
        total,
        quotient,
        inclusion,
        projection,
    )


def _transversal_is_homomorphism(extension: FiniteGroupExtension) -> bool:
    quotient_elements = extension.projection.codomain_elements
    section = dict(zip(quotient_elements, extension.right_transversal(), strict=True))
    return all(
        section[extension.quotient.multiply(left, right)]
        == extension.group.multiply(section[left], section[right])
        for left in quotient_elements
        for right in quotient_elements
    )


def test_number_field_arithmetic_replays_golden_quadratic_witnesses() -> None:
    field = _golden_field()
    t = field.generator
    assert field.degree == 2
    assert field.defining_polynomial == (-1, -1, 1)
    assert t.coefficients == (Fraction(0), Fraction(1))
    assert t.norm() == -1
    assert t.trace() == 1
    assert (2 * t - 1) ** 2 == field(5)
    assert t.inverse() == t - 1
    assert field.verify()
    assert t.verify()


def test_number_field_identity_binds_polynomial_and_basis_not_display_name() -> None:
    field = _golden_field()
    renamed = NumberField((-1, -1, 1), generator_name="alpha")
    shifted_basis = ((1, 0), (1, 1))
    shifted = NumberField(
        (-1, -1, 1),
        integral_basis=shifted_basis,
        generator_name="t",
    )
    assert renamed == field
    assert renamed.field_id == field.field_id
    assert shifted.field_id != field.field_id
    assert canonical_json(field) == canonical_json(field.to_canonical_data())
    with pytest.raises(ValidationError, match="monic"):
        NumberField((-2, -2, 2), integral_basis=((1, 0), (0, 1)))
    with pytest.raises(ValidationError, match="reducible"):
        NumberField((-1, 0, 1))
    with pytest.raises(ValidationError, match="closed"):
        NumberField((-1, -1, 1), integral_basis=((1, 0), (Fraction(0), Fraction(1, 2))))
    with pytest.raises(ValidationError, match="nonmaximal"):
        NumberField((-1, -1, 1), integral_basis=((1, 0), (0, 2)))
    sqrt_five = NumberField(
        (-5, 0, 1),
        integral_basis=((1, 0), (Fraction(1, 2), Fraction(1, 2))),
    )
    assert sqrt_five.discriminant == 5
    with pytest.raises(ValidationError, match="nonmaximal"):
        NumberField((-5, 0, 1))


def test_higher_degree_field_requires_and_replays_irreducibility_boundary() -> None:
    with pytest.raises(ValidationError, match="degree >= 4"):
        NumberField((1, 1, 0, 0, 1))
    with pytest.raises(ValidationError, match="maximality"):
        NumberField(
            (1, 1, 0, 0, 1),
            irreducibility_witness=ModularIrreducibilityWitness(2),
        )
    with pytest.raises(ValidationError, match="not irreducible"):
        NumberField(
            (1, 0, 0, 0, 1),
            irreducibility_witness=ModularIrreducibilityWitness(2),
        )
    bare_pari = VerificationRequirement.pinned_external("pari", "2.17.4")
    with pytest.raises(ValidationError, match="bare verifier requirement"):
        NumberField(
            (-1, 0, 0, 0, 1),
            irreducibility_requirement=bare_pari,
        )


def test_nested_field_invariants_certificate_binds_polynomial_basis_and_completeness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_stubbed_pari_replay(monkeypatch)
    certificate = _quartic_field_certificate()
    requirement = VerificationRequirement.pinned_external(
        PARI_VERIFIER_ID,
        "2.17.4",
        capabilities=("field_invariants",),
    )
    field = NumberField(
        (1, 1, 0, 0, 1),
        irreducibility_requirement=requirement,
        field_invariants_certificate=certificate,
    )
    assert field.degree == 4
    assert field.discriminant == 229
    assert field.verify()
    with pytest.raises(ValidationError, match="different polynomial"):
        NumberField(
            (1, -1, 0, 0, 1),
            field_invariants_certificate=certificate,
        )
    with pytest.raises(ValidationError, match="does not match"):
        NumberField(
            (1, 1, 0, 0, 1),
            irreducibility_requirement=VerificationRequirement.pinned_external(
                PARI_VERIFIER_ID,
                "2.15.5",
                capabilities=("field_invariants",),
            ),
            field_invariants_certificate=certificate,
        )
    with pytest.raises(ValidationError, match="does not match"):
        NumberField(
            (1, 1, 0, 0, 1),
            irreducibility_requirement=VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v2",
                "2.17.4",
                capabilities=("field_invariants",),
            ),
            field_invariants_certificate=certificate,
        )


def test_element_coefficients_are_reduced_and_field_bound() -> None:
    field = _golden_field()
    element = NumberFieldElement(field, (1, 2, 3, 4))
    expected = field(1) + 2 * field.generator + 3 * field.generator**2 + 4 * field.generator**3
    assert element == expected
    assert element.to_dict()["coefficients"] == [
        [element.coefficients[0].numerator, element.coefficients[0].denominator],
        [element.coefficients[1].numerator, element.coefficients[1].denominator],
    ]
    other = NumberField((1, 0, 1), generator_name="i")
    with pytest.raises(ValidationError, match="different pinned fields"):
        _ = element + other.generator


def test_explicit_field_embedding_checks_generator_image() -> None:
    field = _golden_field()
    conjugation = FieldEmbedding(field, field, 1 - field.generator)
    assert conjugation(field.generator) == 1 - field.generator
    assert conjugation(conjugation(field.generator)) == field.generator
    assert conjugation.verify()
    with pytest.raises(ValidationError, match="does not satisfy"):
        FieldEmbedding(field, field, field.one)


def test_places_bind_hnf_and_exact_real_isolation() -> None:
    rationals = NumberField.rationals()
    at_two = FinitePlace(rationals, 2, ((2,),), 1, 1)
    infinity = InfinitePlace(rationals, InfinitePlaceKind.REAL, (-1, 1))
    assert at_two.norm == 2
    assert at_two.verify()
    assert infinity.isolating_interval == (Fraction(-1), Fraction(1))
    assert infinity.embedding_index == 0
    assert infinity.verify()
    assert at_two.place_id != infinity.place_id
    with pytest.raises(ValidationError, match="determinant"):
        FinitePlace(rationals, 2, ((4,),), 1, 1)
    with pytest.raises(ValidationError, match="exactly one"):
        InfinitePlace(rationals, "real", (1, 2))
    gaussian = NumberField((1, 0, 1), generator_name="i")
    complex_place = InfinitePlace(
        gaussian,
        "complex",
        (-2, 2, Fraction(1, 2), 2),
    )
    assert complex_place.verify()
    with pytest.raises(ValidationError, match="imaginary part"):
        InfinitePlace(gaussian, "complex", (-2, 2, 1, 2))
    bare_pari = VerificationRequirement.pinned_external("pari", "2.17.4")
    with pytest.raises(ValidationError, match="bare verifier requirement"):
        InfinitePlace(
            gaussian,
            "complex",
            (-2, 2, Fraction(1, 2), 2),
            verification_requirement=bare_pari,
        )


def test_finite_place_rejects_composite_residue_quotient() -> None:
    gaussian = NumberField((1, 0, 1), generator_name="i")
    with pytest.raises(ValidationError, match="not a field"):
        FinitePlace(gaussian, 2, ((2, 0), (0, 2)), 1, 2)
    with pytest.raises(ValidationError, match="ramification_index"):
        FinitePlace(gaussian, 2, ((2, 1), (0, 1)), 1, 1)
    prime = FinitePlace(gaussian, 2, ((2, 1), (0, 1)), 2, 1)
    assert prime.residue_field_witness["method"] == "prime-order-quotient"
    assert prime.verify()


def test_nested_prime_decomposition_certificate_binds_exact_hnf_e_and_f(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_stubbed_pari_replay(monkeypatch)
    field = NumberField(
        (1, 1, 0, 0, 1),
        field_invariants_certificate=_quartic_field_certificate(),
    )
    hnf = tuple(tuple(2 if row == column else 0 for column in range(4)) for row in range(4))
    record = {
        "ideal_hnf": [list(row) for row in hnf],
        "norm": 16,
        "place_id": "sha256:" + "0" * 64,
        "ramification_index": 1,
        "residue_degree": 4,
    }
    certificate = _pari_certificate(
        "prime_decomposition",
        _pinned_field_replay(field, {"rational_prime": 2}),
        {
            "field_id": field.field_id,
            "prime_ideals": [record],
            "rational_prime": 2,
        },
    )
    requirement = VerificationRequirement.pinned_external(
        PARI_VERIFIER_ID,
        "2.17.4",
        capabilities=("prime_decomposition",),
    )
    place = FinitePlace(
        field,
        2,
        hnf,
        1,
        4,
        verification_requirement=requirement,
        prime_decomposition_certificate=certificate,
    )
    assert place.verify()
    bare_pari = VerificationRequirement.pinned_external("pari", "2.17.4")
    with pytest.raises(ValidationError, match="bare verifier requirement"):
        FinitePlace(
            field,
            2,
            hnf,
            1,
            4,
            verification_requirement=bare_pari,
        )
    with pytest.raises(ValidationError, match="does not match"):
        FinitePlace(
            field,
            2,
            hnf,
            1,
            4,
            verification_requirement=VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v2",
                "2.17.4",
                capabilities=("prime_decomposition",),
            ),
            prime_decomposition_certificate=certificate,
        )
    bad_record = {**record, "ramification_index": 2}
    bad_certificate = _pari_certificate(
        "prime_decomposition",
        _pinned_field_replay(field, {"rational_prime": 2}),
        {
            "field_id": field.field_id,
            "prime_ideals": [bad_record],
            "rational_prime": 2,
        },
    )
    with pytest.raises(ValidationError, match="does not prove this exact"):
        FinitePlace(
            field,
            2,
            hnf,
            1,
            4,
            prime_decomposition_certificate=bad_certificate,
        )


def test_nested_complex_isolation_certificate_binds_rectangle_and_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_stubbed_pari_replay(monkeypatch)
    field = NumberField(
        (1, 1, 0, 0, 1),
        field_invariants_certificate=_quartic_field_certificate(),
    )
    isolation = (
        Fraction(-1, 4),
        Fraction(1, 4),
        Fraction(3, 4),
        Fraction(5, 4),
    )
    payload = {
        "embedding_index": 0,
        "field_id": field.field_id,
        "isolation": [[value.numerator, value.denominator] for value in isolation],
        "kind": "complex",
        "ordering": "pari-polroots-positive-imaginary",
        "root_count": 1,
        "rouche_witness": {
            "center": [[0, 1], [1, 1]],
            "inner_margin": [1, 8],
            "inner_radius": [1, 4],
            "outer_margin": [1, 16],
            "outer_radius": [1, 2],
        },
    }
    certificate = _pari_certificate(
        "complex_root_isolation",
        _pinned_field_replay(field, {"embedding_index": 0, "max_bits": 160}),
        payload,
    )
    requirement = VerificationRequirement.pinned_external(
        PARI_VERIFIER_ID,
        "2.17.4",
        capabilities=("complex_root_isolation",),
    )
    place = InfinitePlace(
        field,
        "complex",
        isolation,
        embedding_index=0,
        verification_requirement=requirement,
        isolation_certificate=certificate,
    )
    assert place.verify()
    with pytest.raises(ValidationError, match="exact complex rectangle"):
        InfinitePlace(
            field,
            "complex",
            (
                Fraction(-1, 4),
                Fraction(1, 3),
                Fraction(3, 4),
                Fraction(5, 4),
            ),
            embedding_index=0,
            isolation_certificate=certificate,
        )
    bare_pari = VerificationRequirement.pinned_external("pari", "2.17.4")
    with pytest.raises(ValidationError, match="bare verifier requirement"):
        InfinitePlace(
            field,
            "complex",
            isolation,
            embedding_index=0,
            verification_requirement=bare_pari,
        )
    with pytest.raises(ValidationError, match="does not match"):
        InfinitePlace(
            field,
            "complex",
            isolation,
            embedding_index=0,
            verification_requirement=VerificationRequirement.pinned_external(
                PARI_VERIFIER_ID,
                "2.15.5",
                capabilities=("complex_root_isolation",),
            ),
            isolation_certificate=certificate,
        )


def test_complex_place_batch_replays_distinctness_and_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_stubbed_pari_replay(monkeypatch)
    field = NumberField(
        (1, 1, 0, 0, 1),
        field_invariants_certificate=_quartic_field_certificate(),
    )

    def place(index: int, real_lower: Fraction) -> InfinitePlace:
        isolation = (
            real_lower,
            real_lower + 1,
            Fraction(1),
            Fraction(2),
        )
        center = (real_lower + Fraction(1, 2), Fraction(3, 2))
        certificate = _pari_certificate(
            "complex_root_isolation",
            _pinned_field_replay(field, {"embedding_index": index, "max_bits": 160}),
            {
                "embedding_index": index,
                "field_id": field.field_id,
                "isolation": [[value.numerator, value.denominator] for value in isolation],
                "kind": "complex",
                "ordering": "pari-polroots-positive-imaginary",
                "root_count": 1,
                "rouche_witness": {
                    "center": [[value.numerator, value.denominator] for value in center],
                    "inner_margin": [1, 8],
                    "inner_radius": [1, 2],
                    "outer_margin": [1, 16],
                    "outer_radius": [1, 1],
                },
            },
        )
        return InfinitePlace(
            field,
            "complex",
            isolation,
            embedding_index=index,
            isolation_certificate=certificate,
        )

    left = place(0, Fraction(-2))
    right = place(1, Fraction(0))
    receipt = SimpleNamespace(
        field=field.to_dict(),
        field_id=field.field_id,
        places=(left.to_dict(), right.to_dict()),
        place_ids=(left.place_id, right.place_id),
    )
    certificates = {
        left.isolation_certificate.certificate_id: left.isolation_certificate,
        right.isolation_certificate.certificate_id: right.isolation_certificate,
    }
    entries = tuple(
        {
            "certificate_id": item.isolation_certificate.certificate_id,
            "place_id": item.place_id,
        }
        for item in (left, right)
    )
    _verify_archimedean_place_set(receipt, (0, 2), certificates, entries)

    overlapping = place(1, Fraction(-3, 2))
    overlapping_receipt = SimpleNamespace(
        field=field.to_dict(),
        field_id=field.field_id,
        places=(left.to_dict(), overlapping.to_dict()),
        place_ids=(left.place_id, overlapping.place_id),
    )
    overlapping_certificates = {
        left.isolation_certificate.certificate_id: left.isolation_certificate,
        overlapping.isolation_certificate.certificate_id: overlapping.isolation_certificate,
    }
    overlapping_entries = (
        entries[0],
        {
            "certificate_id": overlapping.isolation_certificate.certificate_id,
            "place_id": overlapping.place_id,
        },
    )
    with pytest.raises(ArithmeticCertificateError, match="pairwise disjoint"):
        _verify_archimedean_place_set(
            overlapping_receipt,
            (0, 2),
            overlapping_certificates,
            overlapping_entries,
        )
    with pytest.raises(ArithmeticCertificateError, match="missing, duplicated, or reordered"):
        _verify_archimedean_place_set(receipt, (0, 2), certificates, entries[:1])


def test_real_embedding_indices_are_canonical_left_to_right() -> None:
    field = _golden_field()
    left = InfinitePlace(field, "real", (-1, 0), embedding_index=0)
    right = InfinitePlace(field, "real", (1, 2), embedding_index=1)
    assert left.place_id != right.place_id
    with pytest.raises(ValidationError, match="canonical left-to-right"):
        InfinitePlace(field, "real", (-1, 0), embedding_index=1)


def test_proof_context_keeps_assumptions_trust_and_completeness_independent() -> None:
    python = VerificationRequirement.portable_python(
        "galois.exact-replay.v1",
        capabilities=("field-arithmetic",),
    )
    pari = VerificationRequirement.pinned_external(
        "pari",
        "2.17.4",
        capabilities=("bnfcertify",),
    )
    context = ProofContext(
        assumptions=("GRH",),
        verification_requirements=(pari, python),
        completeness=Completeness.COMPLETE,
    )
    assert context.conditional
    assert not context.portable
    assert context.complete
    assert context.to_dict()["assumptions"] == ["GRH"]
    assert pari.trust is VerifierTrust.PINNED_EXTERNAL
    with pytest.raises(ValidationError, match="pin an exact version"):
        VerificationRequirement("pari", VerifierTrust.PINNED_EXTERNAL)
    with pytest.raises(ValidationError, match="candidate"):
        ProofContext().require_complete()


def test_typed_unsupported_is_canonical_and_replayable() -> None:
    result = Unsupported(
        "local_h1",
        "automatic local arithmetic is limited to p=2 in 0.2",
        requested={"prime": 3},
        supported=("prime=2",),
    )
    assert result.verify()
    assert result.to_dict()["requested"] == {"prime": 3}
    assert result.certificate.verifier == "galois.unsupported.v1"
    assert result.certificate.certificate_id in {
        evidence.ref for evidence in result.claim().evidence
    }
    assert result.claim_graph().ids() == (result.claim().id,)
    assert verification_certificate_for_result(result) == result.certificate
    assert claim_for_result(result) == result.claim()
    assert claim_graph_for_result(result).digest == result.claim_graph().digest


def test_typed_unsupported_certificate_replays_fresh_and_rejects_rehashed_tamper() -> None:
    result = Unsupported(
        "local_h1",
        "automatic local arithmetic is limited to p=2 in 0.2",
        requested={"prime": 3},
        supported=("prime=2",),
    )
    program = """
import json
import sys

from arbogast.cert import certificate_from_dict, verify_certificate

certificate = certificate_from_dict(json.load(sys.stdin))
assert verify_certificate(certificate).valid
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(result.certificate.to_dict()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    payload = result.certificate.to_dict()
    payload.pop("certificate_id")
    witness = payload["witness"]
    assert isinstance(witness, dict)
    unsupported = witness["unsupported"]
    assert isinstance(unsupported, dict)
    unsupported["reason"] = "forged broader unsupported boundary"
    tampered = VerificationCertificate.from_dict(payload)
    with pytest.raises(ValueError, match=r"binding|boundary"):
        verify_certificate(tampered)


def test_group_maps_and_split_and_nonsplit_extensions_replay() -> None:
    nonsplit = _c4_extension()
    split = _split_klein_extension()
    assert nonsplit.verify()
    assert not _transversal_is_homomorphism(nonsplit)
    assert split.verify()
    assert _transversal_is_homomorphism(split)
    assert nonsplit.content_id != split.content_id
    quotient_identity_index = nonsplit.projection.codomain_snapshot["identity_index"]
    projection_kernel = {
        index
        for index, image in enumerate(nonsplit.projection.image_indices)
        if image == quotient_identity_index
    }
    assert projection_kernel == set(nonsplit.inclusion.image_indices)


def test_group_map_rejects_nonhomomorphic_images() -> None:
    c4 = CyclicGroup(4)
    c2 = CyclicGroup(2)
    images = {element: c2.identity for element in c4.elements}
    images[c4.generator * c4.generator] = c2.generator
    with pytest.raises(ValueError, match="preserve multiplication"):
        FiniteGroupMap(c4, c2, images)


def test_galois_module_binds_quotient_and_all_action_matrices() -> None:
    group = CyclicGroup(2)
    quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="quadratic-test-quotient",
        proof_context=ProofContext(completeness=Completeness.CANDIDATE),
    )
    field = PrimeField(2)
    identity = DenseMatrix.identity(field, 1)
    module = galois_module(
        quotient,
        field,
        {element: identity for element in group.elements},
        name="mu2",
    )
    assert isinstance(module, GaloisModule)
    assert quotient.claim().status.value == "unknown"
    assert verify_certificate(quotient.certificate).valid
    assert quotient.claim_graph().ids() == (quotient.claim().id,)
    assert module.prime == 2
    assert module.dimension == 1
    assert module.verify()
    assert GaloisModuleReceipt.from_dict(module.receipt.to_dict()) == module.receipt
    assert verify_certificate(module.certificate).valid
    assert module.claim_graph().ids() == (module.claim().id,)
    assert verification_certificate_for_result(module) == module.certificate
    assert claim_for_result(module) == module.claim()
    assert claim_graph_for_result(module).digest == module.claim_graph().digest
    assert public_galois.GaloisModuleReceipt is GaloisModuleReceipt
    assert module.action_matrix(group.generator) == identity
    direct = GaloisModule(
        quotient,
        Representation.trivial(group, field),
        name="mu2-other-label",
    )
    assert direct.module_id == module.module_id

    tampered_payload = module.certificate.to_dict()
    tampered_payload.pop("certificate_id")
    witness = tampered_payload["witness"]
    assert isinstance(witness, dict)
    receipt = witness["module_receipt"]
    assert isinstance(receipt, dict)
    module_snapshot = receipt["module"]
    assert isinstance(module_snapshot, dict)
    module_snapshot["action_matrices"] = [[[0]], [[0]]]
    tampered = VerificationCertificate.from_dict(tampered_payload)
    with pytest.raises(ValueError, match=r"content-bound|identity"):
        verify_certificate(tampered)


def test_complete_galois_quotient_requires_and_replays_actual_arithmetic_evidence() -> None:
    assert public_galois.FiniteGaloisQuotientReceipt is FiniteGaloisQuotientReceipt
    assert public_galois.finite_galois_quotient_certificate is finite_galois_quotient_certificate
    field = NumberField.rationals()
    nontrivial = CyclicGroup(2)
    with pytest.raises(ValidationError, match="complete ProofContext is not evidence"):
        FiniteGaloisQuotient(
            field,
            nontrivial,
            label="unsupported-complete-c2",
            proof_context=ProofContext(completeness=Completeness.COMPLETE),
        )
    presentation = {
        "arithmetic_action": "trivial",
        "method": "portable-trivial-quotient-v1",
    }
    trivial = PermutationGroup.trivial(1)
    certificate = finite_galois_quotient_certificate(
        field,
        trivial,
        label="canonical-trivial-quotient",
        presentation=presentation,
    )
    quotient = FiniteGaloisQuotient(
        field,
        trivial,
        label="canonical-trivial-quotient",
        presentation=presentation,
        proof_context=ProofContext(completeness=Completeness.COMPLETE),
        quotient_certificate=certificate,
    )
    receipt = FiniteGaloisQuotientReceipt(
        field,
        trivial,
        label="canonical-trivial-quotient",
        presentation=presentation,
    )
    assert FiniteGaloisQuotientReceipt.from_dict(receipt.to_dict()) == receipt
    decoded = certificate_from_dict(certificate.to_dict())
    assert isinstance(decoded, VerificationCertificate)
    assert verify_certificate(decoded).valid
    assert quotient.verify()
    assert quotient.proving_certificate == certificate
    assert quotient.certificate.dependencies == (CertificateRef.from_certificate(certificate),)
    claim = quotient.claim()
    assert claim.status.value == "exact"
    assert claim.verify().verified
    assert quotient.claim_graph().verify().verified
    assert Claim.from_dict(claim.to_dict()).verify().verified
    assert verification_certificate_for_result(quotient) == quotient.certificate
    assert claim_for_result(quotient) == claim
    assert claim_graph_for_result(quotient).digest == quotient.claim_graph().digest
    module = galois_module(
        quotient,
        Representation.trivial(trivial, PrimeField(2)),
        name="complete-trivial-module",
    )
    module_claim = module.claim()
    assert module_claim.verify().verified
    assert module.claim_graph().verify().verified
    assert Claim.from_dict(module_claim.to_dict()).verify().verified

    program = """
import json
import sys

from arbogast.claims import Claim

for payload in json.load(sys.stdin):
    claim = Claim.from_dict(payload)
    assert claim.verify().verified
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps([claim.to_dict(), module_claim.to_dict()]),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_finite_quotient_certificate_lazy_replays_in_a_fresh_process() -> None:
    field = NumberField.rationals()
    certificate = finite_galois_quotient_certificate(
        field,
        PermutationGroup.trivial(1),
        label="fresh-trivial-quotient",
        presentation={
            "arithmetic_action": "trivial",
            "method": "portable-trivial-quotient-v1",
        },
    )
    program = """
import json
import sys

from arbogast.cert import certificate_from_dict, verify_certificate

certificate = certificate_from_dict(json.load(sys.stdin))
assert verify_certificate(certificate).valid
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(certificate.to_dict()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_quotient_presentation_and_module_certificates_fresh_replay_and_tamper() -> None:
    group = PermutationGroup.trivial(1)
    quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="fresh-candidate-quotient",
    )
    module = galois_module(
        quotient,
        Representation.trivial(group, PrimeField(2)),
        name="fresh-trivial-module",
    )
    program = """
import json
import sys

from arbogast.cert import certificate_from_dict, verify_certificate

for payload in json.load(sys.stdin):
    certificate = certificate_from_dict(payload)
    assert verify_certificate(certificate).valid
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps([quotient.certificate.to_dict(), module.certificate.to_dict()]),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert module.claim().verify().verified
    assert module.claim_graph().verify().verified
    assert Claim.from_dict(module.claim().to_dict()).verify().verified

    tampered = quotient.certificate.to_dict()
    tampered.pop("certificate_id")
    witness = tampered["witness"]
    assert isinstance(witness, dict)
    snapshot = witness["quotient"]
    assert isinstance(snapshot, dict)
    snapshot["label"] = "foreign-quotient"
    rejected = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps([tampered]),
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
