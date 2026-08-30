from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("script", "expected_lines"),
    (
        (
            "examples/numeric/sqrt2_exactification/run.py",
            (
                "recognized polynomial: (-2, 0, 1)",
                "exactification verified: True",
                "wide enclosure: NumericUnknown",
                "tampered receipt rejected: True",
                "verified claim nodes: 1",
            ),
        ),
        (
            "examples/numeric/two_sheet_cover/run.py",
            (
                "finite branch cycles: ((1, 0), (1, 0))",
                "branch-cycle status: exact",
                "bound Nielsen vertex: 0",
                "vertex status: exact",
                "B2 continuation: BraidContinuationResult",
                "B2 status: exact",
                "missing B2 witness: NumericUnknown",
                "general braid word: NumericUnknown",
                "reordered evidence rejected: True",
                "verified claim nodes: 1",
            ),
        ),
        (
            "examples/numeric/weighted_braid_plan/run.py",
            (
                "unweighted direct edges: 1",
                "weighted exact edges: 2",
                "weighted exact cost: 2",
                "numerical continuation: NumericUnknown",
                "verified claim nodes: 1",
            ),
        ),
    ),
)
def test_numeric_journeys_run_without_an_optional_backend(
    script: str,
    expected_lines: tuple[str, ...],
) -> None:
    completed = subprocess.run(
        (sys.executable, script),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        # The exact B2 journey's single claim-graph replay takes about 36 s on
        # the reference host.  Allow bounded CI variance while remaining well
        # below the artifact qualifier's 300 s packaged-example boundary.
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    for line in expected_lines:
        assert line in completed.stdout.splitlines()
    assert "certificate: sha256:" in completed.stdout
