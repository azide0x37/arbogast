from __future__ import annotations

import json

import pytest

from arbogast.proof import (
    ObligationClass,
    ProofGap,
    ProofObligation,
    ProofObligationError,
)


def test_proof_gap_preserves_classes_and_formalization_distance() -> None:
    finite = ProofObligation.create(
        "check.product_one",
        "sigma_1 sigma_2 sigma_3 = 1",
        ObligationClass.DECIDABLE,
    )
    lemma = ProofObligation.create(
        "lemma.generation",
        "the tuple generates G",
        ObligationClass.MISSING_LEMMA,
        dependencies=(finite.id,),
    )
    gap = ProofGap("claim.hurwitz", (lemma, finite))
    assert gap.topological_ids() == (finite.id, lemma.id)
    assert gap.distance.decidable_steps == 1
    assert gap.distance.missing_elementary_lemmas == 1
    assert gap.blockers == (lemma,)
    assert not gap.complete


def test_proof_obligation_cycles_and_false_discharge_fail_closed() -> None:
    with pytest.raises(ProofObligationError, match="OPEN"):
        ProofObligation.create(
            "open.problem",
            "P",
            ObligationClass.OPEN,
            discharged_by=("wishful-thinking",),
        )
    left = ProofObligation.create(
        "left",
        "L",
        ObligationClass.MISSING_LEMMA,
        dependencies=("right",),
    )
    right = ProofObligation.create(
        "right",
        "R",
        ObligationClass.MISSING_LEMMA,
        dependencies=("left",),
    )
    with pytest.raises(ProofObligationError, match="cycle"):
        ProofGap("claim.cycle", (left, right))


def test_proof_transport_is_strict_and_checks_derived_distance() -> None:
    obligation = ProofObligation.create(
        "finite.check",
        "P",
        ObligationClass.DECIDABLE,
    )
    gap = ProofGap("claim.p", (obligation,))
    payload = gap.to_dict()
    json.dumps(payload)
    assert ProofGap.from_dict(payload).digest == gap.digest

    malformed = obligation.to_dict()
    malformed["id"] = 7
    with pytest.raises(ProofObligationError, match="id must be a string"):
        ProofObligation.from_dict(malformed)

    unknown = obligation.to_dict()
    unknown["ignored"] = True
    with pytest.raises(ProofObligationError, match="unexpected proof obligation"):
        ProofObligation.from_dict(unknown)

    tampered = gap.to_dict()
    distance = tampered["distance"]
    assert isinstance(distance, dict)
    distance["score"] = 0
    with pytest.raises(ProofObligationError, match="distance does not match"):
        ProofGap.from_dict(tampered)
