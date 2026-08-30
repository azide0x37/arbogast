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
            "exact_spaces",
            (
                "spaces (gauge, tangent, obstruction): (1, 1, 1)",
                "framed gauge dimension: 0",
                "invariant tangent dimension: 1",
                "rigid tangent dimension: 0",
                "verified claim nodes: 6",
                "tangent certificate: sha256:",
            ),
        ),
        (
            "finite_lifts",
            (
                "small-extension kernel dimension: 1",
                "lift family dimension modulo gauge: 1",
                "unique lift: (1, 2)",
                "fixed lift: (1, 2)",
                "verified claim nodes: 2",
                "fixed-lift certificate: sha256:",
            ),
        ),
    ),
)
def test_packaged_deformation_journeys_run_end_to_end(
    journey: str,
    expected_lines: tuple[str, ...],
) -> None:
    script = PROJECT_ROOT / "examples" / "deformation" / journey / "run.py"

    completed = subprocess.run(
        (sys.executable, str(script)),
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    for line in expected_lines:
        assert line in completed.stdout
    certificate_lines = [
        line for line in completed.stdout.splitlines() if " certificate: sha256:" in line
    ]
    assert len(certificate_lines) == 1
    certificate_id = certificate_lines[0].split(": ", 1)[1]
    assert certificate_id.startswith("sha256:")
    assert len(certificate_id.removeprefix("sha256:")) == 64
    int(certificate_id.removeprefix("sha256:"), 16)
