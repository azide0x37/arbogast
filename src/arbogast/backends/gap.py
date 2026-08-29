"""Narrow GAP adapter for pinned finite permutation-group discovery."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from arbogast.cert import DiscoveryReceipt
from arbogast.cert.canonical import content_address

from .base import BackendUnavailableError, ExecutableBackend
from .results import GapGroupOrderResult


class GapBackend(ExecutableBackend):
    """Explicit GAP adapter with a closed, integer-only operation surface."""

    def __init__(self) -> None:
        super().__init__(
            name="gap",
            executables=("gap",),
            capabilities=(
                "characters",
                "conjugacy-classes",
                "finite-groups",
                "permutation-actions",
                "stabilizers",
            ),
            version_args=("--version",),
        )

    def permutation_group_order(
        self,
        generators: Sequence[Sequence[int]],
    ) -> GapGroupOrderResult:
        """Return the order of a pinned zero-based permutation generating set.

        No caller-provided GAP source is accepted.  The adapter validates integer permutations,
        generates a closed script, and treats the external answer as a discovery receipt.
        """

        normalized = _permutation_generators(generators)
        status = self.status()
        if not status.available or status.executable is None:
            raise BackendUnavailableError(status.reason or "GAP is unavailable")
        gap_generators = ",".join(
            f"PermList([{','.join(str(image + 1) for image in generator)}])"
            for generator in normalized
        )
        script = (
            f"gens := [{gap_generators}];;\n"
            "G := Group(gens);;\n"
            'Print("ARBOGAST_ORDER:", Size(G), "\\n");\n'
            "QUIT_GAP(0);\n"
        )
        try:
            completed = subprocess.run(
                [status.executable, "-q"],
                input=script,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BackendUnavailableError(f"GAP invocation failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit status {completed.returncode}"
            raise RuntimeError(f"GAP group-order operation failed: {message}")
        values = [
            line.removeprefix("ARBOGAST_ORDER:").strip()
            for line in completed.stdout.splitlines()
            if line.startswith("ARBOGAST_ORDER:")
        ]
        if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
            raise RuntimeError("GAP output did not contain one canonical group order")
        order = int(values[0])
        if order <= 0:
            raise RuntimeError("GAP returned a non-positive group order")
        degree = len(normalized[0])
        input_id = content_address(
            {
                "degree": degree,
                "generators": normalized,
                "type": "arbogast.gap.permutation-generators/v1",
            }
        )
        receipt = DiscoveryReceipt.create(
            "backends.gap.permutation_group_order",
            inputs={"generators": input_id},
            parameters={"degree": degree},
            result={"order": order},
            backend="gap",
            backend_version=status.version,
            notes=("external exact result; verify independently before theorem promotion",),
        )
        return GapGroupOrderResult(order, receipt)


def _permutation_generators(
    generators: Sequence[Sequence[int]],
) -> tuple[tuple[int, ...], ...]:
    if isinstance(generators, (str, bytes)) or not generators:
        raise ValueError("GAP requires a non-empty permutation generating set")
    normalized: list[tuple[int, ...]] = []
    degree: int | None = None
    for generator in generators:
        if isinstance(generator, (str, bytes)):
            raise ValueError("permutation generators must be integer sequences")
        images = tuple(generator)
        if any(isinstance(image, bool) or not isinstance(image, int) for image in images):
            raise ValueError("permutation images must be integers")
        if degree is None:
            degree = len(images)
            if degree == 0:
                raise ValueError("permutation degree must be positive")
        if len(images) != degree or tuple(sorted(images)) != tuple(range(degree)):
            raise ValueError("each generator must be a permutation of one pinned degree")
        normalized.append(images)
    return tuple(normalized)


GAP = GapBackend()
