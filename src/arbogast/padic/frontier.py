"""Explicit bounded reduction frontier with a terminal non-conclusion.

Finite local fragments are useful evidence, but they do not silently become a
local cover model, stable reduction, a lift, or an effectively descended global
model.  The public M23 Hurwitz dataset is four-point finite-exact data without
the equations required by this three-point p-adic lane, so it is refused before
any arithmetic inference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ._schema import PAdicSchemaObject, strict_int
from .covers import LocalFactorizationFragment
from .errors import PAdicValidationError
from .results import Partial, ProofObligation, Unknown, Unsupported, partial_result

if TYPE_CHECKING:
    from arbogast.hurwitz import M23ExactDataset

    from .results import Certified


def _frontier_obligations(fragment: LocalFactorizationFragment) -> tuple[ProofObligation, ...]:
    input_ids = (fragment.content_id,)
    return (
        ProofObligation(
            "Pin exact three-point cover equations and bind the displayed local polynomial "
            "to their complete special fiber.",
            "ThreePointCoverAndSpecialFiberBinding",
            "SemistableReduction",
            input_ids=input_ids,
        ),
        ProofObligation(
            "Construct and replay a complete semistable or stable local cover model; a finite "
            "factorization alone is not such a model.",
            "SemistableReductionWitness",
            "StableReduction",
            input_ids=input_ids,
        ),
        ProofObligation(
            "Construct the finite lift set, its exact Galois action, and every fixed lift.",
            "FixedLiftSetWitness",
            "FixedLiftSet",
            input_ids=input_ids,
        ),
        ProofObligation(
            "Replay an effective descent datum and descended equations over the asserted "
            "field; local solubility or a fixed lift is insufficient.",
            "EffectiveDescentWitness",
            "DescendedModel",
            input_ids=input_ids,
        ),
    )


def reduction_frontier(
    source: M23ExactDataset | Certified[LocalFactorizationFragment],
    *,
    prime: int,
) -> Partial | Unknown | Unsupported:
    """Report exactly what one bounded reduction input proves and what remains open.

    A certified local factorization produces a ``Partial`` result whose semantic
    claim explicitly says the requested full conclusion remains unknown.  The
    public M23 dataset produces ``Unsupported`` because its four-point finite
    Hurwitz data contain no pinned cover equations or local model.
    """

    from arbogast.hurwitz import M23ExactDataset

    from .results import Certified, unsupported_result

    normalized_prime = strict_int(prime, "reduction-frontier prime", minimum=2)
    if isinstance(source, M23ExactDataset):
        if not source.certificate.verify(source):
            raise PAdicValidationError("M23 exact dataset certificate replay returned false")
        return unsupported_result(
            "padic.reduction_frontier",
            "m23-four-point-equations-and-local-model-missing",
            "The public M23 fixture certifies a four-point finite Hurwitz dataset, not pinned "
            "three-point equations, a local cover model, stable reduction, lifts, or descent.",
            requested={
                "dataset_sha256": source.verification.dataset_sha256,
                "manifest_sha256": source.verification.manifest_sha256,
                "prime": normalized_prime,
            },
            supported=("exact three-point equations with independently certified local witnesses",),
            family="three-point",
        )
    if not isinstance(source, Certified):
        raise TypeError(
            "reduction_frontier source must be M23ExactDataset or "
            "Certified[LocalFactorizationFragment]"
        )
    source.verify()
    if not isinstance(source.value, LocalFactorizationFragment):
        raise TypeError("certified reduction-frontier source has the wrong value type")
    fragment = source.value
    if normalized_prime != fragment.prime:
        raise PAdicValidationError("frontier prime disagrees with the certified fragment")
    fragments = (cast("Certified[PAdicSchemaObject]", source),)
    return partial_result(
        "padic.reduction_frontier",
        "One displayed mod-p polynomial is completely factored, but the local model, stable "
        "reduction, lift action, fixed lifts, and effective descent remain unproved.",
        fragments,
        _frontier_obligations(fragment),
        family="three-point",
    )


__all__ = ["reduction_frontier"]
