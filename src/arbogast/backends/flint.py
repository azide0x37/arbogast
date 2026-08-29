"""Narrow python-flint adapter for exact finite-field matrix discovery."""

from __future__ import annotations

import importlib
from typing import Protocol, SupportsInt, cast

from arbogast.cert import DiscoveryReceipt
from arbogast.linalg import Matrix

from .base import BackendUnavailableError, PythonModuleBackend
from .results import FlintMatrixResult


class _NModMatrix(Protocol):
    def rank(self) -> int: ...

    def det(self) -> SupportsInt: ...


class FlintBackend(PythonModuleBackend):
    """Explicit python-flint adapter; no fallback CAS is implied."""

    def __init__(self) -> None:
        super().__init__(
            name="flint",
            module="flint",
            distribution="python-flint",
            capabilities=(
                "exact-finite-fields",
                "exact-integer-linear-algebra",
                "exact-polynomials",
                "exact-rational-linear-algebra",
            ),
        )

    def matrix_rank(self, matrix: Matrix) -> FlintMatrixResult:
        """Compute an exact rank through ``python-flint`` as discovery evidence."""

        status = self.status()
        if not status.available:
            raise BackendUnavailableError(status.reason or "python-flint is unavailable")
        native = self._native_matrix(matrix)
        value = native.rank()
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("python-flint returned a non-integer rank")
        if not 0 <= value <= min(matrix.nrows, matrix.ncols):
            raise RuntimeError("python-flint returned an impossible matrix rank")
        return FlintMatrixResult(
            "rank",
            value,
            self._receipt(matrix, "rank", value, status.version),
        )

    def matrix_determinant(self, matrix: Matrix) -> FlintMatrixResult:
        """Compute a square-matrix determinant through ``python-flint``."""

        if matrix.nrows != matrix.ncols:
            raise ValueError("FLINT determinant requires a square matrix")
        status = self.status()
        if not status.available:
            raise BackendUnavailableError(status.reason or "python-flint is unavailable")
        native = self._native_matrix(matrix)
        value = int(native.det()) % matrix.field.p
        return FlintMatrixResult(
            "determinant",
            value,
            self._receipt(matrix, "determinant", value, status.version),
        )

    @staticmethod
    def _native_matrix(matrix: Matrix) -> _NModMatrix:
        module = importlib.import_module("flint")
        constructor = getattr(module, "nmod_mat", None)
        if not callable(constructor):
            raise BackendUnavailableError("python-flint does not expose nmod_mat")
        return cast(_NModMatrix, constructor([list(row) for row in matrix.rows], matrix.field.p))

    @staticmethod
    def _receipt(
        matrix: Matrix,
        operation: str,
        value: int,
        backend_version: str | None,
    ) -> DiscoveryReceipt:
        return DiscoveryReceipt.create(
            f"backends.flint.matrix_{operation}",
            inputs={"matrix": matrix.content_id},
            parameters={"characteristic": matrix.field.p, "shape": list(matrix.shape)},
            result={operation: value},
            backend="flint",
            backend_version=backend_version,
            notes=("external exact result; verify independently before theorem promotion",),
        )


FLINT = FlintBackend()
