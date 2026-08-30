"""Emit or compare version-independent mathematical payloads from live PARI anchors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from arbogast.backends import PariArithmeticResult, PariBackend

SCHEMA = "arbogast.pari-anchor-payload/v1"
SUPPORTED_ANCHORS = {"2.15.5", "2.17.4"}
REQUIRED_MATHEMATICAL_PAYLOADS = frozenset(
    {
        "class_group_2_torsion_golden",
        "complex_root_isolation_quartic_0",
        "field_invariants_golden",
        "hilbert_q2_minus_one_minus_one",
        "hilbert_q_sqrt_minus_5_at_2",
        "local_squareclasses_q2",
        "local_squareclasses_q_sqrt_minus_5_at_2",
        "localization_q_at_2",
        "localization_q_sqrt_minus_5_at_2",
        "prime_decomposition_golden_at_2",
        "relative_norm_golden_t",
        "s_kummer_q_at_2",
        "s_kummer_q_sqrt_minus_5",
        "s_kummer_q_sqrt_minus_5_at_11",
    }
)


def _payload(result: PariArithmeticResult) -> dict[str, object]:
    result.verify().require_valid()
    return result.payload.to_dict()


def live_payload() -> dict[str, object]:
    """Run the bounded common arithmetic corpus against one live GP binary."""

    backend = PariBackend(certification_timeout_seconds=30)
    probe = backend.probe()
    if not probe.status.available or probe.normalized_version not in SUPPORTED_ANCHORS:
        raise RuntimeError(
            f"a supported live PARI anchor is required, found {probe.normalized_version!r}"
        )

    rationals = (0, 1)
    golden = (-1, -1, 1)
    t = (0, 1)
    class_two = (5, 0, 1)
    quartic = (1, -1, 0, 0, 1)
    class_two_s_kummer = _payload(backend.s_unit_squareclasses(class_two, ()))
    class_two_local = _payload(backend.local_squareclasses(class_two, 2))
    class_two_representatives = class_two_local.get("representatives")
    if not isinstance(class_two_representatives, list) or not class_two_representatives:
        raise RuntimeError("live PARI anchor omitted the nonrational local squareclass basis")
    class_two_hilbert_matrix = [
        [
            _payload(backend.quadratic_hilbert_pairing(class_two, left, right, 2))["symbol"]
            for right in class_two_representatives
        ]
        for left in class_two_representatives
    ]
    class_two_global_representatives = class_two_s_kummer.get("representatives")
    if not isinstance(class_two_global_representatives, list) or not (
        class_two_global_representatives
    ):
        raise RuntimeError("live PARI anchor omitted the nonrational global squareclass basis")
    mathematical_payloads = {
        "class_group_2_torsion_golden": _payload(backend.class_group_2_torsion(golden)),
        "complex_root_isolation_quartic_0": _payload(backend.complex_root_isolation(quartic, 0)),
        "field_invariants_golden": _payload(backend.field_invariants(golden)),
        "hilbert_q_sqrt_minus_5_at_2": {
            "basis": class_two_representatives,
            "matrix": class_two_hilbert_matrix,
        },
        "hilbert_q2_minus_one_minus_one": _payload(
            backend.quadratic_hilbert_pairing(rationals, (-1,), (-1,), 2)
        ),
        "local_squareclasses_q2": _payload(backend.local_squareclasses(rationals, 2)),
        "local_squareclasses_q_sqrt_minus_5_at_2": class_two_local,
        "localization_q_at_2": _payload(backend.localization_matrix(rationals, ((-1,), (2,)), 2)),
        "localization_q_sqrt_minus_5_at_2": _payload(
            backend.localization_matrix(class_two, class_two_global_representatives, 2)
        ),
        "prime_decomposition_golden_at_2": _payload(backend.prime_decomposition(golden, 2)),
        "relative_norm_golden_t": _payload(backend.relative_norm(golden, t)),
        "s_kummer_q_at_2": _payload(backend.s_unit_squareclasses(rationals, (2,))),
        "s_kummer_q_sqrt_minus_5": class_two_s_kummer,
        "s_kummer_q_sqrt_minus_5_at_11": _payload(backend.s_unit_squareclasses(class_two, (11,))),
    }
    if mathematical_payloads["relative_norm_golden_t"].get("norm") != [
        -1,
        1,
    ]:
        raise RuntimeError("live PARI anchor returned the wrong norm for t")
    lift = mathematical_payloads["s_kummer_q_sqrt_minus_5"].get("s_class_2_torsion")
    if not isinstance(lift, list) or len(lift) != 1:
        raise RuntimeError("live PARI anchor omitted the expected S-class 2-torsion lift")
    nonempty_lift = mathematical_payloads["s_kummer_q_sqrt_minus_5_at_11"].get("s_class_2_torsion")
    if (
        not isinstance(nonempty_lift, list)
        or len(nonempty_lift) != 1
        or nonempty_lift[0].get("s_prime_exponents") != [0]
    ):
        raise RuntimeError("live PARI anchor omitted the expected nonempty-S class 2-torsion lift")
    if set(mathematical_payloads) != REQUIRED_MATHEMATICAL_PAYLOADS:
        raise RuntimeError("live PARI anchor corpus is incomplete")
    return {
        "mathematical_payloads": mathematical_payloads,
        "pari_version": probe.normalized_version,
        "schema": SCHEMA,
    }


def write_payload(path: Path) -> None:
    payload = live_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_payload(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "mathematical_payloads",
        "pari_version",
        "schema",
    }:
        raise ValueError(f"{path} is not a canonical PARI anchor payload")
    if value.get("schema") != SCHEMA:
        raise ValueError(f"{path} has the wrong anchor-payload schema")
    if value.get("pari_version") not in SUPPORTED_ANCHORS:
        raise ValueError(f"{path} names an unsupported PARI version")
    mathematical_payloads = value.get("mathematical_payloads")
    if not isinstance(mathematical_payloads, dict):
        raise ValueError(f"{path} omits its mathematical payloads")
    if set(mathematical_payloads) != REQUIRED_MATHEMATICAL_PAYLOADS:
        raise ValueError(f"{path} has an incomplete mathematical payload corpus")
    return value


def compare_directory(path: Path) -> None:
    files = sorted(path.rglob("pari-*.json"))
    if len(files) != len(SUPPORTED_ANCHORS):
        raise ValueError(
            f"expected {len(SUPPORTED_ANCHORS)} PARI anchor payloads, found {len(files)}"
        )
    records = [_read_payload(item) for item in files]
    versions = {str(record["pari_version"]) for record in records}
    if versions != SUPPORTED_ANCHORS:
        raise ValueError(f"PARI anchor set mismatch: {sorted(versions)!r}")
    first = records[0]["mathematical_payloads"]
    if any(record["mathematical_payloads"] != first for record in records[1:]):
        raise ValueError("supported PARI anchors produced different mathematical payloads")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--compare-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.output is not None:
            write_payload(args.output.resolve())
        else:
            compare_directory(args.compare_dir.resolve())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
