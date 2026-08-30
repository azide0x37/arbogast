from __future__ import annotations

from dataclasses import replace

import pytest

from arbogast.cert import (
    CertificateRef,
    ClaimBinding,
    VerificationCertificate,
    verify_certificate,
)
from arbogast.cert import (
    CertificateVerificationError as CentralCertificateVerificationError,
)
from arbogast.cohom import (
    CertificateVerificationError,
    CohomologyMapCertificate,
    ExactLinearMap,
    ExactSequence,
    corestriction_map,
    h0,
    h1,
    h2,
    inflation_map,
    inflation_restriction,
    restriction_map,
    transgression,
)
from arbogast.rep import FiniteGroupExtension, FiniteGroupMap, Permutation, symmetric_group


class PrimeField:
    characteristic = 2
    order = 2


class TrivialModule:
    field = PrimeField()
    dimension = 1

    def action_matrix(self, _element: object) -> tuple[tuple[int, ...], ...]:
        return ((1,),)


class PrimeFieldThree:
    characteristic = 3
    order = 3


class TrivialModuleThree:
    field = PrimeFieldThree()
    dimension = 1

    def action_matrix(self, _element: object) -> tuple[tuple[int, ...], ...]:
        return ((1,),)


class KernelSignModule:
    field = PrimeFieldThree()
    dimension = 1

    def action_matrix(self, element: tuple[int, int]) -> tuple[tuple[int, ...], ...]:
        return ((1 if element[0] == 0 else 2,),)


class PermutationSignModule:
    field = PrimeFieldThree()
    dimension = 1

    def action_matrix(self, element: Permutation) -> tuple[tuple[int, ...], ...]:
        return ((element.sign % 3,),)


class CyclicGroup:
    def __init__(self, order: int) -> None:
        self.order = order
        self.elements = tuple(range(order))
        self.identity = 0

    def multiply(self, left: int, right: int) -> int:
        return (left + right) % self.order


class KleinGroup:
    elements = ((0, 0), (0, 1), (1, 0), (1, 1))
    identity = (0, 0)

    def multiply(self, left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
        return ((left[0] + right[0]) % 2, (left[1] + right[1]) % 2)


def split_extension() -> FiniteGroupExtension:
    return FiniteGroupExtension(
        CyclicGroup(2),
        KleinGroup(),
        CyclicGroup(2),
        lambda element: (element, 0),
        lambda element: element[1],
        section=lambda element: (0, element),
    )


def nonsplit_extension() -> FiniteGroupExtension:
    return FiniteGroupExtension(
        CyclicGroup(2),
        CyclicGroup(4),
        CyclicGroup(2),
        lambda element: 2 * element,
        lambda element: element % 2,
        section=lambda element: element,
    )


def identity_kernel_extension() -> FiniteGroupExtension:
    return FiniteGroupExtension(
        CyclicGroup(4),
        CyclicGroup(4),
        CyclicGroup(1),
        lambda element: element,
        lambda _element: 0,
        section=lambda _element: 0,
    )


def five_term_semantic_certificate() -> VerificationCertificate:
    return inflation_restriction(nonsplit_extension(), TrivialModule()).verification_certificate()


def test_finite_group_map_and_extension_freeze_their_complete_identity() -> None:
    source = CyclicGroup(4)
    target = CyclicGroup(2)
    calls = 0

    def projection(element: int) -> int:
        nonlocal calls
        calls += 1
        return element % 2

    group_map = FiniteGroupMap(source, target, projection, require_surjective=True)

    assert calls == 4
    assert group_map.apply(3) == 1
    assert group_map.verify()
    assert hash(group_map)
    assert group_map.content_id == f"sha256:{group_map.content_hash}"
    extension = nonsplit_extension()
    assert extension.verify()
    assert extension.total is extension.group
    assert extension.section[0] == extension.group.identity
    assert extension.transversal == extension.right_transversal()


def test_first_class_restriction_and_inflation_preserve_legacy_maps() -> None:
    module = TrivialModule()
    cyclic_four = CyclicGroup(4)
    cyclic_two = CyclicGroup(2)
    group_result = h1(cyclic_four, module)
    quotient_result = h1(cyclic_two, module)

    restriction = restriction_map(group_result, cyclic_two, lambda element: 2 * element)
    inflation = inflation_map(quotient_result, cyclic_four, lambda element: element % 2)

    assert restriction.matrix == ((0,),)
    assert inflation.matrix == ((1,),)
    assert restriction(group_result.basis[0]).is_zero
    assert inflation(quotient_result.basis[0]).coordinates == (1,)
    assert restriction.verify() and inflation.verify()
    assert restriction.claim().verify().verified
    assert inflation.claim_graph().verify().verified
    assert CohomologyMapCertificate.from_json(inflation.certificate.to_json()) == (
        inflation.certificate
    )


def test_corestriction_transfer_formula_and_index_identity() -> None:
    module = TrivialModule()
    for extension, expected_rank in ((split_extension(), 0), (nonsplit_extension(), 1)):
        kernel_result = h1(extension.kernel, module)
        group_result = h1(extension.group, module)
        restriction = restriction_map(group_result, extension.kernel, extension.inclusion)
        canonical_transfer = corestriction_map(
            kernel_result,
            extension.group,
            module,
            extension.inclusion,
        )
        shifted_transversal = tuple(
            extension.group.multiply(extension.inclusion(1), representative)
            for representative in extension.transversal
        )
        shifted_transfer = corestriction_map(
            kernel_result,
            extension.group,
            module,
            extension.inclusion,
            transversal=shifted_transversal,
        )

        assert shifted_transversal != extension.transversal
        assert canonical_transfer.matrix == shifted_transfer.matrix
        assert canonical_transfer.rank == expected_rank
        report = shifted_transfer.certificate.verify()
        assert "transversal-class-independence" in report.checks
        assert "class-map-independent" in report.checks
        # cor(res(x)) = [G:H]x, and the index is zero in F_2 here.
        for basis_class in group_result.basis:
            assert shifted_transfer(restriction(basis_class)).is_zero
        assert canonical_transfer.verify() and shifted_transfer.verify()


def test_corestriction_transfer_index_identity_is_nonzero_over_f3() -> None:
    module = TrivialModuleThree()
    subgroup = CyclicGroup(3)
    group = CyclicGroup(6)

    def inclusion(element: int) -> int:
        return 2 * element

    subgroup_result = h1(subgroup, module)
    group_result = h1(group, module)
    restriction = restriction_map(group_result, subgroup, inclusion)
    canonical_transfer = corestriction_map(subgroup_result, group, module, inclusion)
    shifted_transfer = corestriction_map(
        subgroup_result,
        group,
        module,
        inclusion,
        transversal=(2, 3),
    )

    assert canonical_transfer.matrix == shifted_transfer.matrix
    assert canonical_transfer.certificate.verify().ok
    assert "transfer-index-identity" in shifted_transfer.certificate.verify().checks
    for basis_class in group_result.basis:
        transferred = shifted_transfer(restriction(basis_class))
        assert transferred.coordinates == tuple(
            2 * coordinate % 3 for coordinate in basis_class.coordinates
        )


@pytest.mark.parametrize("degree", (0, 2))
def test_all_induced_map_apis_certify_degrees_zero_and_two(degree: int) -> None:
    module = TrivialModule()
    cyclic_four = CyclicGroup(4)
    cyclic_two = CyclicGroup(2)
    cohomology = h0 if degree == 0 else h2
    group_result = cohomology(cyclic_four, module)
    subgroup_result = cohomology(cyclic_two, module)

    maps = (
        restriction_map(group_result, cyclic_two, lambda element: 2 * element),
        inflation_map(subgroup_result, cyclic_four, lambda element: element % 2),
        corestriction_map(
            subgroup_result,
            cyclic_four,
            module,
            lambda element: 2 * element,
        ),
    )

    for induced_map in maps:
        assert induced_map.degree == degree
        assert induced_map.verify()
        assert induced_map.certificate.verify().ok
        assert induced_map.claim().verify().verified
        assert len(induced_map.matrix) == induced_map.target_dimension
        assert all(len(row) == induced_map.source_dimension for row in induced_map.matrix)


def test_split_and_nonsplit_five_term_sequences_are_recomputed_exactly() -> None:
    expected = {
        "split": ((1, 2, 1, 1, 3), (1, 1, 0, 1)),
        "nonsplit": ((1, 1, 1, 1, 1), (1, 0, 1, 0)),
    }
    for name, extension in (
        ("split", split_extension()),
        ("nonsplit", nonsplit_extension()),
    ):
        sequence = inflation_restriction(extension, TrivialModule())

        assert sequence.certificate.term_dimensions == expected[name][0]
        assert (
            tuple(linear_map.rank for linear_map in sequence.exact_sequence.maps)
            == (expected[name][1])
        )
        assert sequence.verify()
        assert sequence.exact_sequence.verify()
        assert sequence.claim().verify().verified

    nonsplit = inflation_restriction(nonsplit_extension(), TrivialModule())
    connecting = transgression(nonsplit)
    assert connecting.matrix == ((1,),)
    assert connecting.verify()
    assert connecting.certificate is nonsplit.certificate
    assert connecting.claim_graph().verify().verified


def test_public_exact_results_require_bound_five_term_evidence() -> None:
    sequence = inflation_restriction(nonsplit_extension(), TrivialModule())
    exact_sequence = sequence.exact_sequence

    for result in (sequence, exact_sequence, *exact_sequence.maps):
        assert result.verify()
        assert result.certificate is sequence.certificate
        assert verify_certificate(result.verification_certificate()).valid
        assert result.claim().verify().verified
        assert result.claim_graph().verify().verified

    with pytest.raises(TypeError, match="requires an inflation-restriction certificate"):
        ExactLinearMap("inflation_h1", 2, 1, 1, ((1,),), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="requires an inflation-restriction certificate"):
        ExactSequence((1,), (), 2, None)  # type: ignore[arg-type]

    split = inflation_restriction(split_extension(), TrivialModule())
    rebound_map = replace(sequence.transgression, certificate=split.certificate)
    with pytest.raises(ValueError, match="payload does not match its certificate"):
        rebound_map.verify()

    renamed_map = replace(sequence.inflation_h1, name="not_a_five_term_map")
    with pytest.raises(ValueError, match="name is not part"):
        renamed_map.verify()

    rebound_sequence = replace(exact_sequence, certificate=split.certificate)
    with pytest.raises(ValueError, match="payload does not match its certificate"):
        rebound_sequence.verify()

    reordered_sequence = replace(exact_sequence, maps=tuple(reversed(exact_sequence.maps)))
    with pytest.raises(ValueError, match="payload does not match its certificate"):
        reordered_sequence.verify()

    equivalent_certificate = replace(sequence.certificate)
    replayed_sequence = replace(
        exact_sequence,
        maps=tuple(
            replace(linear_map, certificate=equivalent_certificate)
            for linear_map in exact_sequence.maps
        ),
        certificate=equivalent_certificate,
    )
    assert equivalent_certificate is not sequence.certificate
    assert replayed_sequence.verify()


def test_five_term_supports_a_zero_dimensional_invariant_module() -> None:
    sequence = inflation_restriction(split_extension(), KernelSignModule())

    assert sequence.module_invariant_basis == ()
    assert sequence.certificate.term_dimensions == (0, 0, 0, 0, 0)
    assert sequence.verify()
    assert sequence.exact_sequence.verify()
    assert sequence.certificate.verify().ok


def test_zero_invariants_can_have_nonzero_middle_terms() -> None:
    group = symmetric_group(3)
    extension = FiniteGroupExtension(
        group,
        group,
        CyclicGroup(1),
        lambda element: element,
        lambda _element: 0,
        section=lambda _element: group.identity,
    )

    sequence = inflation_restriction(extension, PermutationSignModule())

    assert sequence.module_invariant_basis == ()
    assert sequence.certificate.term_dimensions == (0, 1, 1, 0, 1)
    assert tuple(linear_map.rank for linear_map in sequence.exact_sequence.maps) == (
        0,
        1,
        0,
        0,
    )
    assert sequence.verify()
    assert sequence.certificate.verify().ok
    assert sequence.claim().verify().verified


def test_map_and_five_term_tampering_fail_closed() -> None:
    inflation = inflation_map(
        h1(CyclicGroup(2), TrivialModule()),
        CyclicGroup(4),
        lambda element: element % 2,
    )
    forged_map = replace(inflation.certificate, matrix=((0,),))
    with pytest.raises(CertificateVerificationError):
        forged_map.verify()

    sequence = inflation_restriction(nonsplit_extension(), TrivialModule())
    forged_sequence = replace(
        sequence.certificate,
        map_matrices=(
            sequence.certificate.map_matrices[0],
            sequence.certificate.map_matrices[1],
            ((0,),),
            sequence.certificate.map_matrices[3],
        ),
    )
    with pytest.raises(CertificateVerificationError):
        forged_sequence.verify()

    split = inflation_restriction(split_extension(), TrivialModule())
    forged_projection = replace(
        split.certificate,
        projection_indices=(0, 1, 1, 1),
    )
    with pytest.raises(CertificateVerificationError, match="preserve multiplication"):
        forged_projection.verify()

    identity_kernel = inflation_restriction(identity_kernel_extension(), TrivialModule())
    forged_inclusion = replace(
        identity_kernel.certificate,
        inclusion_indices=(0, 1, 3, 2),
    )
    with pytest.raises(CertificateVerificationError, match="preserve multiplication"):
        forged_inclusion.verify()


def test_five_term_semantic_verifier_rejects_certificate_dependencies() -> None:
    valid = five_term_semantic_certificate()
    forged = replace(
        valid,
        dependencies=(CertificateRef.from_certificate(valid),),
    )

    with pytest.raises(CentralCertificateVerificationError, match="dependencies"):
        verify_certificate(forged)


def test_five_term_semantic_verifier_rejects_claim_dependencies() -> None:
    valid = five_term_semantic_certificate()
    assert valid.statement_hash is not None
    assert valid.claim_boundary_hash is not None
    forged = replace(
        valid,
        claim_dependencies=(
            ClaimBinding(
                "forged.premise",
                valid.statement_hash,
                valid.claim_boundary_hash,
            ),
        ),
    )

    with pytest.raises(CentralCertificateVerificationError, match="dependencies"):
        verify_certificate(forged)


def test_five_term_semantic_verifier_rejects_stronger_guarantees() -> None:
    valid = five_term_semantic_certificate()
    forged = replace(
        valid,
        guarantees=("The five-term sequence proves every stronger global theorem.",),
    )

    with pytest.raises(CentralCertificateVerificationError, match="manifest"):
        verify_certificate(forged)
