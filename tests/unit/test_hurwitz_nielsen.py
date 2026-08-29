from __future__ import annotations

import json
from dataclasses import replace

import pytest

from arbogast.hurwitz import (
    CertificateVerificationError,
    ConcreteGroupMismatchError,
    ImportedBoundaryError,
    InvalidConjugacyClassError,
    InvalidNielsenTupleError,
    NielsenEnumerationCertificate,
    NielsenTuple,
    load_precomputed_nielsen_class,
    nielsen_class,
    plan_nielsen_class,
    verify_nielsen_certificate_payload,
)
from arbogast.hurwitz._group import ConcreteGroupContext
from arbogast.rep import Permutation, PermutationGroup


def s3() -> tuple[PermutationGroup, Permutation, Permutation]:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    return PermutationGroup((left, right), degree=3), left, right


class _KeyedC2:
    elements = (0, 1)
    identity = 0

    def __init__(self, zero_key: tuple[str, ...]) -> None:
        self.zero_key = zero_key

    def multiply(self, left: int, right: int) -> int:
        return left ^ right

    def inverse(self, value: int) -> int:
        return value

    def element_key(self, value: int) -> tuple[str, ...] | str:
        return self.zero_key if value == 0 else "x"


def test_group_fingerprint_element_key_framing_is_injective() -> None:
    formerly_colliding = _KeyedC2(("a;s:b", "c"))
    distinct = _KeyedC2(("a", "b", "c"))

    assert ConcreteGroupContext.build(formerly_colliding).fingerprint != (
        ConcreteGroupContext.build(distinct).fingerprint
    )


def test_nielsen_tuple_checks_every_defining_invariant() -> None:
    group, left, right = s3()
    transpositions = group.conjugacy_class(left)
    valid = NielsenTuple(group, (left, left, right, right), (transpositions,) * 4)

    assert valid.verify()
    assert valid.is_product_one
    assert valid.generates_group
    assert valid.has_expected_classes

    with pytest.raises(InvalidNielsenTupleError, match="product one"):
        NielsenTuple(group, (left, right), (transpositions, transpositions))
    with pytest.raises(InvalidNielsenTupleError, match="generate"):
        NielsenTuple(group, (left, left), (transpositions, transpositions))
    three_cycles = group.conjugacy_class(left * right)
    with pytest.raises(InvalidNielsenTupleError, match="explicit conjugacy class"):
        NielsenTuple(group, (left, left, right, right), (three_cycles,) * 4)


def test_explicit_conjugacy_classes_are_exact_orbits() -> None:
    group, left, _ = s3()
    full_class = group.conjugacy_class(left)

    with pytest.raises(InvalidConjugacyClassError, match="not exactly one"):
        nielsen_class(group, ((full_class[0],),) * 4)

    other_group, _, _ = s3()
    other_class = other_group.conjugacy_class(other_group.generators[0])
    other_nielsen = nielsen_class(other_group, (other_class,) * 4)
    with pytest.raises(ConcreteGroupMismatchError):
        nielsen_class(group, (other_nielsen.classes[0],) * 4)


def test_s3_four_transposition_enumeration_is_exhaustive() -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    result = nielsen_class(group, (transpositions,) * 4)

    assert result.cardinality == 4
    assert result.certificate is not None
    assert result.certificate.candidate_count == 27
    assert result.certificate.product_one_count == 27
    assert result.certificate.generating_count == 24
    assert len(result.certificate.orbit_witnesses) == 24
    assert result.verify()

    bad = replace(result.certificate, generating_count=23)
    assert bad.certificate_id != result.certificate.certificate_id
    with pytest.raises(CertificateVerificationError, match="generating-tuple count"):
        bad.verify()


def test_nielsen_certificate_has_stable_transport_and_semantic_wrapper() -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    result = nielsen_class(group, (transpositions,) * 4)
    certificate = result.certificate
    assert certificate is not None

    payload = certificate.to_dict()
    assert payload["certificate_id"] == certificate.content_id
    assert payload["inner_conjugacy_convention"] == "simultaneous inner action g->h^-1*g*h"
    restored = NielsenEnumerationCertificate.from_dict(
        payload,
        group=group,
        classes=(transpositions,) * 4,
    )
    assert restored.certificate_id == certificate.certificate_id
    assert restored.verify()
    semantic = restored.verification_certificate()
    assert semantic.verify_integrity() == semantic.certificate_id

    tampered = dict(payload)
    tampered["generating_count"] = 23
    with pytest.raises(ValueError, match="content address mismatch"):
        NielsenEnumerationCertificate.from_dict(
            tampered,
            group=group,
            classes=(transpositions,) * 4,
        )


@pytest.mark.parametrize("field", ["group_fingerprint", "class_fingerprints"])
def test_portable_nielsen_fingerprints_are_derived_from_finite_tables(field: str) -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    certificate = nielsen_class(group, (transpositions,) * 4).certificate
    assert certificate is not None
    payload = certificate.to_canonical()
    if field == "group_fingerprint":
        payload[field] = "0" * 64
    else:
        payload[field] = ("0" * 64,) * 4

    with pytest.raises(CertificateVerificationError, match=r"portable .*fingerprint mismatch"):
        verify_nielsen_certificate_payload(payload)


def test_deterministic_shards_reduce_to_the_same_certificate() -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    serial = nielsen_class(group, (transpositions,) * 4)
    plan = plan_nielsen_class(group, (transpositions,) * 4, shards=5)

    assert plan.candidate_count == 27
    parallel = plan.reduce(reversed(plan.run_all()))
    assert tuple(value.key() for value in parallel) == tuple(value.key() for value in serial)
    assert parallel.certificate is not None
    assert parallel.certificate.verify()

    with pytest.raises(CertificateVerificationError, match="missing Nielsen shards"):
        plan.reduce(plan.run_all()[:-1])


def test_precomputed_loader_marks_the_completeness_boundary(tmp_path: object) -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    computed = nielsen_class(group, (transpositions,) * 4)
    path = tmp_path / "nielsen.json"  # type: ignore[operator]
    payload = {
        "schema": "arbogast.hurwitz.precomputed-nielsen.v1",
        "group_fingerprint": computed.context.fingerprint,
        "class_fingerprints": [value.fingerprint for value in computed.classes],
        "representatives": [
            [list(entry.images) for entry in representative.entries] for representative in computed
        ],
        "declared_cardinality": len(computed),
        "metadata": {"theorem_claim": "not promoted by this loader"},
    }
    path.write_text(json.dumps(payload))

    imported = load_precomputed_nielsen_class(
        path,
        group,
        (transpositions,) * 4,
        decode_element=Permutation,
    )
    assert imported.status == "IMPORTED"
    assert imported.representatives_verified
    assert not imported.completeness_certified
    assert imported.verify_representatives()
    assert imported.nielsen_class.certificate is None
    with pytest.raises(CertificateVerificationError, match="not a completeness certificate"):
        imported.verify_complete()


def test_precomputed_loader_rejects_ambiguous_or_inexact_json(tmp_path: object) -> None:
    group, left, _ = s3()
    transpositions = group.conjugacy_class(left)
    computed = nielsen_class(group, (transpositions,) * 4)
    path = tmp_path / "nielsen.json"  # type: ignore[operator]
    prefix = (
        '{"schema":"arbogast.hurwitz.precomputed-nielsen.v1",'
        f'"group_fingerprint":"{computed.context.fingerprint}",'
        '"group_fingerprint":"duplicate",'
        '"class_fingerprints":[],"representatives":[]}'
    )
    path.write_text(prefix)
    with pytest.raises(ImportedBoundaryError, match="strict exact JSON"):
        load_precomputed_nielsen_class(
            path,
            group,
            (transpositions,) * 4,
            decode_element=Permutation,
        )

    path.write_text(
        json.dumps(
            {
                "schema": "arbogast.hurwitz.precomputed-nielsen.v1",
                "group_fingerprint": computed.context.fingerprint,
                "class_fingerprints": [value.fingerprint for value in computed.classes],
                "representatives": [],
                "metadata": {"approximation": float("nan")},
            }
        )
    )
    with pytest.raises(ImportedBoundaryError, match="strict exact JSON"):
        load_precomputed_nielsen_class(
            path,
            group,
            (transpositions,) * 4,
            decode_element=Permutation,
        )

    path.write_text(
        json.dumps(
            {
                "schema": "arbogast.hurwitz.precomputed-nielsen.v1",
                "group_fingerprint": computed.context.fingerprint,
                "class_fingerprints": [value.fingerprint for value in computed.classes],
                "representatives": [],
                "ignored": True,
            }
        )
    )
    with pytest.raises(ImportedBoundaryError, match=r"unexpected=\['ignored'\]"):
        load_precomputed_nielsen_class(
            path,
            group,
            (transpositions,) * 4,
            decode_element=Permutation,
        )
