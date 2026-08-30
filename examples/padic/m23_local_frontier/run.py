"""Keep the exact finite M23 theorem separate from its p-adic frontier."""

from __future__ import annotations

from pathlib import Path

from arbogast.cert import verify_certificate
from arbogast.hurwitz import load_m23_exact_dataset
from arbogast.padic import (
    FiniteFieldFactor,
    Partial,
    Unsupported,
    local_factorization_fragment,
    reduction_frontier,
)

HERE = Path(__file__).resolve().parent
M23_EXPECTED = HERE.parents[1] / "hurwitz" / "m23_real_component" / "expected"


def main() -> int:
    dataset = load_m23_exact_dataset(
        M23_EXPECTED / "manifest.json",
        M23_EXPECTED / "dataset.json",
    )
    assert dataset.certificate.verify(dataset)
    assert dataset.verification.component_cardinality == 1428

    m23_frontier = reduction_frontier(dataset, prime=23)
    assert isinstance(m23_frontier, Unsupported)
    assert m23_frontier.reason_code == "m23-four-point-equations-and-local-model-missing"
    assert m23_frontier.verify()
    assert verify_certificate(m23_frontier.certificate).valid
    assert m23_frontier.claim_graph().verify().verified

    fragment = local_factorization_fragment(
        "beta-zero-fiber-mod-23",
        23,
        (0, 0, 1, 22),
        22,
        (FiniteFieldFactor(23, (0, 1), 2), FiniteFieldFactor(23, (22, 1))),
    )
    local_frontier = reduction_frontier(fragment, prime=23)
    assert isinstance(local_frontier, Partial)
    assert len(local_frontier.fragments) == 1
    assert len(local_frontier.obligations) == 4
    assert local_frontier.verify()
    assert verify_certificate(local_frontier.certificate).valid
    assert local_frontier.claim().status.value == "unknown"
    assert local_frontier.claim_graph().verify().verified

    print(
        "finite M23 replay:",
        dataset.verification.component_cardinality,
        "generating inner classes",
    )
    print("M23 p-adic request:", type(m23_frontier).__name__, m23_frontier.reason_code)
    print(
        "local factorization frontier:",
        type(local_frontier).__name__,
        len(local_frontier.obligations),
        "open obligations",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
