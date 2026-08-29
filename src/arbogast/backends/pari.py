"""PARI/GP availability declaration."""

from __future__ import annotations

from .base import ExecutableBackend


class PariBackend(ExecutableBackend):
    """Status probe for PARI/GP."""

    def __init__(self) -> None:
        super().__init__(
            name="pari",
            executables=("gp",),
            capabilities=(
                "class-groups",
                "local-fields",
                "number-fields",
                "padic-arithmetic",
            ),
            version_args=("--version",),
        )


PARI = PariBackend()
