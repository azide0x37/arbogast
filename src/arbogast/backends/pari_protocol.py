"""Hardened fresh-process and framed-JSON protocol for PARI/GP.

The public adapter never accepts GP source.  This module is private support for
the finite set of templates in :mod:`arbogast.backends.pari`.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbogast.cert import validate_content_address

RESPONSE_SCHEMA = "arbogast.pari.response.v1"
BEGIN_PREFIX = "ARBOGAST_PARI_BEGIN:"
END_PREFIX = "ARBOGAST_PARI_END:"


class PariBackendError(RuntimeError):
    """Base class for fail-closed PARI adapter errors."""


class PariProtocolError(PariBackendError):
    """The child process did not return the exact framed response protocol."""


class PariOperationError(PariBackendError):
    """GP rejected an operation-specific closed template."""


class PariTimeoutError(PariBackendError):
    """The fresh GP process exceeded its wall-clock budget."""


class PariOutputLimitError(PariBackendError):
    """The fresh GP process reached its hard output cap."""


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    """Bounded byte output from one child process."""

    returncode: int
    stdout: bytes
    stderr: bytes


def run_secure_process(
    executable: str,
    arguments: Sequence[str],
    *,
    input_bytes: bytes | None,
    timeout_seconds: float,
    output_limit_bytes: int,
    memory_limit_bytes: int,
    cpu_limit_seconds: int,
    pari_stack_bytes: int | None = None,
) -> ProcessOutput:
    """Run one process with an ignored startup file, clean cwd/env, and hard limits."""

    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise ValueError("PARI executable must be an absolute path")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("PARI timeout must be positive and finite")
    for name, value in (
        ("output_limit_bytes", output_limit_bytes),
        ("memory_limit_bytes", memory_limit_bytes),
        ("cpu_limit_seconds", cpu_limit_seconds),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"PARI {name} must be a positive integer")

    command = [executable, "-f", "-q"]
    if pari_stack_bytes is not None:
        if isinstance(pari_stack_bytes, bool) or not isinstance(pari_stack_bytes, int):
            raise ValueError("PARI stack size must be an integer")
        if pari_stack_bytes <= 0 or pari_stack_bytes > memory_limit_bytes:
            raise ValueError("PARI stack size must be positive and within the memory cap")
        command.extend(("-s", str(pari_stack_bytes)))
    command.extend(arguments)

    with tempfile.TemporaryDirectory(prefix="arbogast-pari-") as temporary:
        os.chmod(temporary, 0o700)
        clean_environment = {
            "HOME": temporary,
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        }
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=temporary,
                    env=clean_environment,
                    stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    close_fds=True,
                    start_new_session=True,
                    preexec_fn=_resource_limiter(
                        output_limit_bytes,
                        memory_limit_bytes,
                        cpu_limit_seconds,
                    ),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise PariOperationError(f"could not start fresh PARI process: {exc}") from exc
            try:
                process.communicate(input=input_bytes, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _terminate_process_group(process)
                process.communicate()
                raise PariTimeoutError(
                    f"PARI process exceeded {timeout_seconds:g} seconds"
                ) from exc

            stdout_size = stdout_file.tell()
            stderr_size = stderr_file.tell()
            if stdout_size >= output_limit_bytes or stderr_size >= output_limit_bytes:
                raise PariOutputLimitError(f"PARI output reached the {output_limit_bytes}-byte cap")
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(output_limit_bytes + 1)
            stderr = stderr_file.read(output_limit_bytes + 1)
            if len(stdout) > output_limit_bytes or len(stderr) > output_limit_bytes:
                raise PariOutputLimitError(
                    f"PARI output exceeded the {output_limit_bytes}-byte cap"
                )
            return ProcessOutput(process.returncode, stdout, stderr)


def _resource_limiter(
    output_limit_bytes: int,
    memory_limit_bytes: int,
    cpu_limit_seconds: int,
) -> Callable[[], None] | None:
    """Return a best-effort POSIX limiter without importing ``resource`` on Windows."""

    try:
        import resource
    except ImportError:  # pragma: no cover - supported PARI deployments are POSIX
        return None

    def limit() -> None:
        limits: tuple[tuple[int, int], ...] = (
            (resource.RLIMIT_CORE, 0),
            (resource.RLIMIT_CPU, cpu_limit_seconds),
            (resource.RLIMIT_FSIZE, output_limit_bytes),
            (resource.RLIMIT_NOFILE, 32),
        )
        if hasattr(resource, "RLIMIT_AS"):
            limits += ((resource.RLIMIT_AS, memory_limit_bytes),)
        for resource_kind, requested in limits:
            try:
                _soft, hard = resource.getrlimit(resource_kind)
                effective = requested if hard < 0 else min(requested, hard)
                resource.setrlimit(resource_kind, (effective, effective))
            except (OSError, ValueError):
                # GP also receives a bounded PARI stack.  A kernel that lacks one
                # particular rlimit must not disable all the other limits.
                continue

    return limit


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        process.kill()


def framed_program(request_id: str, seed: int, operation_body: str) -> bytes:
    """Wrap one internally generated operation body in the fixed GP protocol."""

    validate_content_address(request_id)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0:
        raise ValueError("PARI deterministic seed must be a positive integer")
    if not isinstance(operation_body, str) or not operation_body.strip():
        raise ValueError("PARI operation body must be non-empty")
    # None of these helpers evaluate caller text.  Rational coordinates are
    # emitted as [numerator, denominator], matching the arithmetic substrate.
    preamble = f"""\\
default(colors, "no");
default(echo, 0);
default(timer, 0);
default(secure, 1);
setrand({seed});
arb_jq(q)=Str("[",numerator(q),",",denominator(q),"]");
arb_jqvec(v)=Str("[",strjoin(vector(#v,i,arb_jq(v[i])),","),"]");
arb_jintvec(v)=Str("[",strjoin(vector(#v,i,Str(v[i])),","),"]");
arb_jqmat(m)=Str("[",strjoin(vector(matsize(m)[1],i,arb_jqvec(Vec(m[i,]))),","),"]");
arb_jintmat(m)=Str("[",strjoin(vector(matsize(m)[1],i,arb_jintvec(Vec(m[i,]))),","),"]");
arb_jelt(a,n)=arb_jqvec(vector(n,i,polcoef(lift(a),i-1)));
arb_jelts(v,n)=Str("[",strjoin(vector(#v,i,arb_jelt(v[i],n)),","),"]");
arb_power_basis_matrix(nf,n)=Mat(vector(n,j,vector(n,i,polcoef(lift(nf.zk[j]),i-1))~));
arb_emit(result_json)={{
  print("{BEGIN_PREFIX}{request_id}");
  print("{{\\\"ok\\\":true,\\\"request_id\\\":\\\"{request_id}\\\",\\\"result\\\":",result_json,",\\\"schema\\\":\\\"{RESPONSE_SCHEMA}\\\"}}");
  print("{END_PREFIX}{request_id}");
}};
"""
    return f"{preamble}\n{operation_body.rstrip()}\nquit(0);\n".encode()


def parse_framed_response(output: ProcessOutput, request_id: str) -> dict[str, Any]:
    """Decode exactly one framed JSON object and reject all foreign output."""

    validate_content_address(request_id)
    if output.returncode != 0:
        detail = _decode_diagnostic(output.stderr) or f"exit status {output.returncode}"
        raise PariOperationError(f"PARI operation failed: {detail}")
    if output.stderr.strip():
        raise PariProtocolError(
            f"PARI wrote unexpected stderr: {_decode_diagnostic(output.stderr)}"
        )
    try:
        text = output.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PariProtocolError("PARI stdout was not valid UTF-8") from exc
    if "\x00" in text:
        raise PariProtocolError("PARI stdout contained a NUL byte")
    lines = text.splitlines()
    expected_begin = f"{BEGIN_PREFIX}{request_id}"
    expected_end = f"{END_PREFIX}{request_id}"
    if len(lines) != 3 or lines[0] != expected_begin or lines[2] != expected_end:
        raise PariProtocolError("PARI output was not one exact request-bound frame")
    try:
        decoded = json.loads(
            lines[1],
            object_pairs_hook=_unique_object,
            parse_float=_reject_inexact_json,
            parse_constant=_reject_inexact_json,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PariProtocolError(f"PARI frame did not contain strict JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise PariProtocolError("PARI response JSON must be an object")
    required = {"ok", "request_id", "result", "schema"}
    if set(decoded) != required:
        raise PariProtocolError("PARI response JSON has missing or foreign fields")
    if decoded["schema"] != RESPONSE_SCHEMA:
        raise PariProtocolError("PARI response used an unsupported protocol schema")
    if decoded["request_id"] != request_id:
        raise PariProtocolError("PARI response request ID does not match the request")
    if decoded["ok"] is not True:
        raise PariOperationError("PARI response did not report success")
    result = decoded["result"]
    if not isinstance(result, dict):
        raise PariProtocolError("PARI response result must be an object")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_inexact_json(value: str) -> None:
    raise ValueError(f"inexact or non-finite JSON number is forbidden: {value}")


def _decode_diagnostic(value: bytes) -> str:
    decoded = value.decode("utf-8", errors="replace").strip().splitlines()
    return decoded[-1][:500] if decoded else ""


__all__ = [
    "BEGIN_PREFIX",
    "END_PREFIX",
    "RESPONSE_SCHEMA",
    "PariBackendError",
    "PariOperationError",
    "PariOutputLimitError",
    "PariProtocolError",
    "PariTimeoutError",
    "ProcessOutput",
    "framed_program",
    "parse_framed_response",
    "run_secure_process",
]
