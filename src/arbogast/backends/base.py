"""Honest optional-backend capability and status protocols."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from arbogast.formats import BACKEND_STATUS_SCHEMA, JSONValue


class BackendUnavailableError(RuntimeError):
    """Raised when a required external capability is unavailable."""


@dataclass(frozen=True, slots=True)
class BackendStatus:
    """A point-in-time, non-fictional account of backend availability."""

    name: str
    available: bool
    capabilities: tuple[str, ...]
    version: str | None = None
    executable: str | None = None
    reason: str | None = None
    schema: str = BACKEND_STATUS_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("backend status name must be a non-empty string")
        if not isinstance(self.available, bool):
            raise ValueError("backend status available must be boolean")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.capabilities
        ):
            raise ValueError("backend capabilities must be a tuple of non-empty strings")
        for field_name, value in (
            ("version", self.version),
            ("executable", self.executable),
            ("reason", self.reason),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"backend {field_name} must be a non-empty string or None")
        if self.schema != BACKEND_STATUS_SCHEMA:
            raise ValueError("unsupported backend-status schema")
        object.__setattr__(self, "name", self.name.strip().lower())
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))
        if self.available and self.reason is not None:
            raise ValueError("an available backend status cannot include an unavailability reason")
        if not self.available and self.reason is None:
            raise ValueError("an unavailable backend status must explain why")

    def has(self, capability: str) -> bool:
        return self.available and capability in self.capabilities

    def meets(self, requirement: RequirementLike) -> bool:
        if not self.available or self.name != requirement.name.lower():
            return False
        if not set(requirement.capabilities).issubset(self.capabilities):
            return False
        return requirement.version is None or requirement.version == self.version

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "available": self.available,
            "capabilities": list(self.capabilities),
            "executable": self.executable,
            "name": self.name,
            "reason": self.reason,
            "schema": self.schema,
            "version": self.version,
        }


@runtime_checkable
class RequirementLike(Protocol):
    """Structural interface accepted by backend matching."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str | None: ...

    @property
    def capabilities(self) -> tuple[str, ...]: ...


@runtime_checkable
class Backend(Protocol):
    """Capability/status protocol; not a computer-algebra facade."""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> tuple[str, ...]: ...

    def status(self) -> BackendStatus: ...


@dataclass(frozen=True, slots=True)
class ExecutableBackend:
    """Probe a coarse-grained external executable without invoking algebra."""

    name: str
    executables: tuple[str, ...]
    capabilities: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("backend name must be a non-empty string")
        for field_name, values in (
            ("executables", self.executables),
            ("capabilities", self.capabilities),
            ("version_args", self.version_args),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise ValueError(f"backend {field_name} must be a tuple of non-empty strings")
        if not self.executables:
            raise ValueError("executable backend must name at least one executable")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("backend timeout_seconds must be positive")

    def status(self) -> BackendStatus:
        executable = next(
            (located for candidate in self.executables if (located := shutil.which(candidate))),
            None,
        )
        if executable is None:
            names = ", ".join(self.executables)
            return BackendStatus(
                name=self.name,
                available=False,
                capabilities=self.capabilities,
                reason=f"no executable found on PATH (tried: {names})",
            )
        try:
            completed = subprocess.run(
                [executable, *self.version_args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return BackendStatus(
                name=self.name,
                available=False,
                capabilities=self.capabilities,
                executable=executable,
                reason=f"version probe failed: {error}",
            )
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        first_line = output.splitlines()[0] if output else None
        if completed.returncode != 0:
            detail = first_line or f"exit status {completed.returncode}"
            return BackendStatus(
                name=self.name,
                available=False,
                capabilities=self.capabilities,
                executable=executable,
                reason=f"version probe unsuccessful: {detail}",
            )
        return BackendStatus(
            name=self.name,
            available=True,
            capabilities=self.capabilities,
            executable=str(Path(executable)),
            version=first_line or "unknown",
        )


@dataclass(frozen=True, slots=True)
class PythonModuleBackend:
    """Probe an optional Python module and distribution version."""

    name: str
    module: str
    distribution: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("module", self.module),
            ("distribution", self.distribution),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"backend {field_name} must be a non-empty string")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(item, str) or not item for item in self.capabilities
        ):
            raise ValueError("backend capabilities must be a tuple of non-empty strings")

    def status(self) -> BackendStatus:
        try:
            found = importlib.util.find_spec(self.module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            return BackendStatus(
                name=self.name,
                available=False,
                capabilities=self.capabilities,
                reason=f"Python module {self.module!r} is not importable",
            )
        try:
            version = importlib.metadata.version(self.distribution)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return BackendStatus(
            name=self.name,
            available=True,
            capabilities=self.capabilities,
            version=version,
        )
