from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("journey", "expected_lines"),
    (
        (
            "frobenius_slopes",
            (
                "Frobenius convention: arithmetic",
                "Newton slopes: (('0', 1), ('1', 1))",
                "ordinary part without projector: Unknown missing-saturated-projector",
                "ordinary part with projector: Certified 1",
            ),
        ),
        (
            "three_point_good_reduction",
            (
                "p=5 reduction: Certified (0, 0, 3, 2)",
                "p=5 stable model: 1 source component, 0 nodes",
                "p=2 good-reduction request: Unsupported outside-beta-p5-certified-slice",
                "p=2 semistable request: Unsupported outside-beta-p5-certified-slice",
            ),
        ),
        (
            "special_deformation_datum",
            (
                "internal datum: Certified componentwise-rank-one-tame-formal-identities",
                "character values: (1, 4)",
                "geometric extraction: Unknown missing-deformation-datum-witness",
            ),
        ),
        (
            "lifts_rigid_descent",
            (
                "missing chart: Unknown missing-pinned-chart-exhaustion",
                "chart-complete lifts: 2",
                "without exact model transports: Unknown",
                "arithmetic fixed classes: 2",
                "descent claimed by fixed_lifts: False",
                "without descent witness: Unknown",
                "witnessed rigid descent: Certified (1, 2)",
            ),
        ),
        (
            "m23_local_frontier",
            (
                "finite M23 replay: 1428 generating inner classes",
                (
                    "M23 p-adic request: Unsupported "
                    "m23-four-point-equations-and-local-model-missing"
                ),
                "local factorization frontier: Partial 4 open obligations",
            ),
        ),
    ),
)
def test_padic_journeys_preserve_certified_and_nonconclusion_boundaries(
    journey: str,
    expected_lines: tuple[str, ...],
) -> None:
    script = PROJECT_ROOT / "examples" / "padic" / journey / "run.py"
    completed = subprocess.run(
        (sys.executable, str(script)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    lines = completed.stdout.splitlines()
    for line in expected_lines:
        assert line in lines
    assert "Traceback" not in completed.stderr
