"""Bounded environment capture for readiness subjects."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import arbogast
from arbogast.cert import content_address, freeze_mapping

from .models import EnvironmentSnapshot, FileIdentity


def _file_identity(path: Path) -> FileIdentity:
    payload = path.read_bytes()
    return FileIdentity(
        path=str(path.resolve()),
        sha256=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        size=len(payload),
    )


def _package_tree_identity(root: Path) -> str:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        payload = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "size": len(payload),
            }
        )
    return content_address(
        {"schema": "arbogast.bootstrap.package-tree/v1", "files": tuple(records)}
    )


def _package_identities(enabled: bool) -> dict[str, object]:
    if not enabled:
        return {}
    packages: dict[str, object] = {}
    try:
        distributions = tuple(importlib.metadata.distributions())
    except Exception as error:
        return {"$probe_error": f"{type(error).__name__}: {error}"}
    for distribution in distributions:
        try:
            try:
                raw_name = distribution.metadata["Name"]
            except KeyError:
                raw_name = None
            name = raw_name.lower().replace("_", "-") if isinstance(raw_name, str) else None
            if not name:
                continue
            version = distribution.version
            descriptor = {
                "name": name,
                "version": version,
                "metadata_identity": content_address(
                    {
                        "name": name,
                        "version": version,
                        "requires": tuple(sorted(distribution.requires or ())),
                    }
                ),
            }
            existing = packages.get(name)
            if existing is None:
                packages[name] = descriptor
            elif existing != descriptor:
                packages[name] = {
                    "conflict": True,
                    "records": tuple(sorted((existing, descriptor), key=lambda item: str(item))),
                }
        except Exception as error:
            packages[f"$distribution-error-{len(packages)}"] = f"{type(error).__name__}: {error}"
    return packages


def _lock_state(
    root: Path | None,
    enabled: bool,
) -> tuple[tuple[FileIdentity, ...], bool | None, str]:
    if not enabled:
        return (), True, "lock consistency was not required by this environment capture"
    if root is None:
        return (), None, "no project root was supplied for lock consistency"
    pyproject = root / "pyproject.toml"
    candidates = tuple(
        path
        for path in (
            root / "uv.lock",
            root / "poetry.lock",
            root / "requirements.lock",
            root / "requirements.txt",
        )
        if path.is_file()
    )
    try:
        identities = tuple(_file_identity(path) for path in sorted(candidates))
    except OSError as error:
        return (), None, f"lockfile read failed: {type(error).__name__}: {error}"
    if not pyproject.is_file():
        if identities:
            return identities, None, "lockfiles exist but pyproject.toml is absent"
        return (), False, "project has neither pyproject.toml nor a supported lockfile"
    if not identities:
        return (), False, "pyproject.toml exists but no supported lockfile was found"
    uv_lock = root / "uv.lock"
    if not uv_lock.is_file():
        return (
            identities,
            None,
            "the available lockfile format lacks a portable v1 consistency check",
        )

    uv_executable = shutil.which("uv")
    if uv_executable is None:
        return identities, None, "uv.lock is present but the uv executable is unavailable"
    try:
        uv_identity = _file_identity(Path(uv_executable))
    except OSError as error:
        return (
            identities,
            None,
            f"uv executable identity failed: {type(error).__name__}: {error}",
        )

    # Resolve the executable once, then run a fixed offline command with no uv
    # configuration discovery and no inherited UV/Python startup settings.
    command = (
        str(Path(uv_executable).resolve()),
        "--no-config",
        "--offline",
        "--no-progress",
        "--no-cache",
        "--no-python-downloads",
        "--directory",
        str(root),
        "lock",
        "--check",
    )
    clean_environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "UV_NO_CONFIG": "1",
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    system_root = os.environ.get("SYSTEMROOT")
    if system_root is not None:
        clean_environment["SYSTEMROOT"] = system_root
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=20,
            check=False,
            env=clean_environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return identities, None, f"uv lock --check failed: {type(error).__name__}: {error}"
    if completed.returncode == 1:
        return identities, False, "uv lock --check reports that uv.lock is stale"
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:4096]
        suffix = f": {detail}" if detail else ""
        return (
            identities,
            None,
            f"uv lock --check returned {completed.returncode}{suffix}",
        )
    return (
        identities,
        True,
        "uv lock --check succeeded with "
        f"{uv_identity.path} ({uv_identity.sha256}) under fixed offline settings",
    )


def _status_dict(status: object) -> dict[str, object]:
    to_dict = getattr(status, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("backend status does not expose to_dict")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("backend status to_dict did not return an object")
    return dict(value)


def _backend_snapshots(probe_external: bool) -> tuple[dict[str, object], dict[str, str]]:
    from arbogast.backends import DEFAULT_BACKENDS, PYTHON

    backends: dict[str, object] = {}
    errors: dict[str, str] = {}
    names = DEFAULT_BACKENDS.names() if probe_external else (PYTHON.name,)
    for name in names:
        try:
            status = DEFAULT_BACKENDS.status(name)
            backends[name] = _status_dict(status)
        except Exception as error:
            errors[f"backend.{name}"] = f"{type(error).__name__}: {error}"
            backends[name] = {
                "available": None,
                "capabilities": (),
                "name": name,
                "reason": "backend probe did not determine availability",
                "version": None,
            }
    return backends, errors


def capture_environment(
    *,
    project_root: str | Path | None = None,
    package_hashes: bool = True,
    lockfile: bool = True,
    backends: bool = False,
    capabilities: Iterable[str] = (),
    probe_external: bool = False,
) -> EnvironmentSnapshot:
    """Capture one finite environment subject using fixed local probes.

    ``probe_external`` (or the compatibility spelling ``backends=True``)
    enables the fixed built-in backend list.  No entry points, user import
    paths, startup files, or serialized callables are inspected.
    """

    root = Path.cwd().resolve() if project_root is None else Path(project_root).resolve()
    package_root = Path(arbogast.__file__).resolve().parent
    probe_errors: dict[str, str] = {}
    try:
        executable_identity = _file_identity(Path(sys.executable))
    except OSError as error:
        executable_identity = None
        probe_errors["python.executable"] = f"{type(error).__name__}: {error}"
    try:
        tree_identity = _package_tree_identity(package_root)
    except OSError as error:
        tree_identity = content_address(
            {
                "schema": "arbogast.bootstrap.package-tree-error/v1",
                "location": str(package_root),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        probe_errors["arbogast.tree"] = f"{type(error).__name__}: {error}"
    lockfiles, lock_consistent, lock_detail = _lock_state(root, lockfile)
    backend_records, backend_errors = _backend_snapshots(backends or probe_external)
    probe_errors.update(backend_errors)
    declared_capabilities = set(capabilities)
    probed_capabilities: set[str] = set()
    for record in backend_records.values():
        if isinstance(record, Mapping) and record.get("available") is True:
            raw = record.get("capabilities", ())
            if isinstance(raw, Sequence) and not isinstance(raw, str):
                probed_capabilities.update(item for item in raw if isinstance(item, str))
    found_capabilities = declared_capabilities | probed_capabilities
    return EnvironmentSnapshot(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        # Preserve the environment entry point rather than resolving a venv
        # symlink to a base interpreter that cannot import the installed tree.
        python_executable=str(Path(sys.executable).absolute()),
        python_executable_identity=executable_identity,
        platform=platform.platform(),
        arbogast_version=arbogast.__version__,
        arbogast_location=str(package_root),
        arbogast_tree_sha256=tree_identity,
        project_root=str(root),
        lockfiles=lockfiles,
        lock_consistent=lock_consistent,
        lock_detail=lock_detail,
        packages=freeze_mapping(_package_identities(package_hashes)),
        backends=freeze_mapping(backend_records),
        capabilities=tuple(sorted(found_capabilities)),
        declared_capabilities=tuple(sorted(declared_capabilities)),
        probed_capabilities=tuple(sorted(probed_capabilities)),
        capture_options=freeze_mapping(
            {
                "package_hashes": package_hashes,
                "lockfile": lockfile,
                "probe_external": backends or probe_external,
            }
        ),
        probe_errors=freeze_mapping(probe_errors),
    )


__all__ = ["capture_environment"]
