"""Registry of optional backend status probes."""

from __future__ import annotations

from collections.abc import Iterable

from .base import Backend, BackendStatus, BackendUnavailableError, RequirementLike
from .flint import FLINT
from .gap import GAP
from .magma import MAGMA
from .pari import PARI
from .python import PYTHON
from .sage import SAGE


class BackendRegistry:
    """A deterministic registry of capability/status providers."""

    def __init__(self, backends: Iterable[Backend] = ()) -> None:
        self._backends: dict[str, Backend] = {}
        for backend in backends:
            self.register(backend)

    def register(self, backend: Backend, *, replace: bool = False) -> None:
        name = backend.name.lower()
        if name in self._backends and not replace:
            raise ValueError(f"backend {name!r} is already registered")
        self._backends[name] = backend

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))

    def get(self, name: str) -> Backend:
        try:
            return self._backends[name.lower()]
        except KeyError as error:
            raise KeyError(f"unknown backend: {name}") from error

    def status(self, name: str) -> BackendStatus:
        return self.get(name).status()

    def statuses(self) -> tuple[BackendStatus, ...]:
        return tuple(self._backends[name].status() for name in self.names())

    def require(self, requirement: RequirementLike) -> BackendStatus:
        try:
            status = self.status(requirement.name)
        except KeyError as error:
            raise BackendUnavailableError(str(error)) from error
        if not status.meets(requirement):
            requested = ", ".join(requirement.capabilities) or "declared capabilities"
            detail = status.reason or (
                f"found version {status.version!r}; required {requirement.version!r}"
                if requirement.version is not None
                else f"missing one or more capabilities: {requested}"
            )
            raise BackendUnavailableError(f"backend {requirement.name!r} is unavailable: {detail}")
        return status


DEFAULT_BACKENDS = BackendRegistry((PYTHON, FLINT, GAP, PARI, SAGE, MAGMA))


def backend_statuses() -> tuple[BackendStatus, ...]:
    """Probe all built-in backend declarations in stable name order."""

    return DEFAULT_BACKENDS.statuses()


def require_backend(requirement: RequirementLike) -> BackendStatus:
    """Return a matching status or raise an honest capability error."""

    return DEFAULT_BACKENDS.require(requirement)
