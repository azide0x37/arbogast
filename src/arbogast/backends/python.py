"""The built-in Python control-plane backend declaration."""

from __future__ import annotations

import platform
from dataclasses import dataclass

from .base import BackendStatus


@dataclass(frozen=True, slots=True)
class PythonBackend:
    """The always-available orchestration backend, not an algebra engine."""

    name: str = "python"
    capabilities: tuple[str, ...] = (
        "canonical-json",
        "certificate-verification",
        "control-plane",
        "small-exact-computations",
    )

    def status(self) -> BackendStatus:
        return BackendStatus(
            name=self.name,
            available=True,
            capabilities=self.capabilities,
            version=platform.python_version(),
            executable=None,
        )


PYTHON = PythonBackend()
