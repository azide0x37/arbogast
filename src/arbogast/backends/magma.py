"""Magma availability declaration."""

from __future__ import annotations

from .base import ExecutableBackend


class MagmaBackend(ExecutableBackend):
    """Status probe for a user-installed, vendor-licensed Magma executable."""

    def __init__(self) -> None:
        super().__init__(
            name="magma",
            executables=("magma",),
            capabilities=(
                "finite-groups",
                "group-cohomology",
                "number-fields",
            ),
            version_args=("--version",),
        )


MAGMA = MagmaBackend()
