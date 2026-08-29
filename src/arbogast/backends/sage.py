"""SageMath availability declaration."""

from __future__ import annotations

from .base import ExecutableBackend


class SageBackend(ExecutableBackend):
    """Status probe for SageMath."""

    def __init__(self) -> None:
        super().__init__(
            name="sage",
            executables=("sage",),
            capabilities=(
                "computer-algebra-integration",
                "finite-groups",
                "number-fields",
            ),
            version_args=("--version",),
        )


SAGE = SageBackend()
