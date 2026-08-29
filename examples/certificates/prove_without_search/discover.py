"""Search for a witness, then emit only the independently checkable certificate."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from arbogast.cert import DiscoveryReceipt, VerificationCertificate, canonicalize

MODULUS = 29
START = 1
TARGET = 0
OPERATIONS = ("add_3", "double")
VERIFIER = "examples.modular_reachability.v1"


def transition(state: int, operation: str) -> int:
    """Apply one discovery move."""

    if operation == "add_3":
        return (state + 3) % MODULUS
    if operation == "double":
        return (2 * state) % MODULUS
    raise ValueError(f"unknown operation: {operation}")


def discover_path() -> list[dict[str, int | str]]:
    """Find a shortest path by BFS; this function is absent from the verifier."""

    parents: dict[int, tuple[int, str] | None] = {START: None}
    queue: deque[int] = deque([START])

    while queue:
        state = queue.popleft()
        if state == TARGET:
            break
        for operation in OPERATIONS:
            candidate = transition(state, operation)
            if candidate not in parents:
                parents[candidate] = (state, operation)
                queue.append(candidate)

    if TARGET not in parents:
        raise RuntimeError("finite search exhausted without reaching the target")

    reversed_steps: list[dict[str, int | str]] = []
    current = TARGET
    while current != START:
        predecessor = parents[current]
        if predecessor is None:
            raise AssertionError("non-start state has no predecessor")
        previous, operation = predecessor
        reversed_steps.append({"from": previous, "operation": operation, "to": current})
        current = previous
    return list(reversed(reversed_steps))


def build_certificate() -> tuple[DiscoveryReceipt, VerificationCertificate]:
    """Return provenance for the search and a separate proof witness."""

    path = discover_path()
    receipt = DiscoveryReceipt.create(
        "examples.modular_reachability.discover",
        inputs={"modulus": MODULUS, "start": START, "target": TARGET},
        parameters={"algorithm": "breadth-first search", "operations": OPERATIONS},
        result={"path_length": len(path)},
        backend="python",
        notes=("Discovery provenance is not proof evidence.",),
    )
    certificate = VerificationCertificate.create(
        subject="reachability of 0 from 1 in the modular move graph modulo 29",
        verifier=VERIFIER,
        witness={
            "modulus": MODULUS,
            "operations": OPERATIONS,
            "path": path,
            "start": START,
            "target": TARGET,
        },
        checks=("well_formed_problem", "valid_transitions", "target_reached"),
        guarantees=("the stated target is reachable from the stated start",),
    )
    return receipt, certificate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("certificate.json"),
        help="path for the verification certificate (default: certificate.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt, certificate = build_certificate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonicalize(certificate.to_dict())
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"discovery receipt: {receipt.certificate_id}")
    print(f"verification certificate: {certificate.certificate_id}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
