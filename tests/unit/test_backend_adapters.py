from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from arbogast.backends import BackendStatus, FlintBackend, GapBackend
from arbogast.cert import CertificateLayer
from arbogast.linalg import DenseMatrix, PrimeField


def test_flint_adapter_returns_typed_unpromoted_discovery_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMatrix:
        def rank(self) -> int:
            return 2

        def det(self) -> int:
            return 19

    captured: list[tuple[list[list[int]], int]] = []

    def nmod_mat(rows: list[list[int]], modulus: int) -> FakeMatrix:
        captured.append((rows, modulus))
        return FakeMatrix()

    monkeypatch.setattr(
        FlintBackend,
        "status",
        lambda self: BackendStatus(
            "flint",
            True,
            self.capabilities,
            version="3.2.2",
        ),
    )
    monkeypatch.setattr(
        "arbogast.backends.flint.importlib.import_module",
        lambda name: SimpleNamespace(nmod_mat=nmod_mat),
    )
    backend = FlintBackend()
    matrix = DenseMatrix(PrimeField(7), ((1, 2), (3, 4)))

    rank_result = backend.matrix_rank(matrix)
    determinant_result = backend.matrix_determinant(matrix)

    assert rank_result.value == 2
    assert determinant_result.value == 5
    assert rank_result.receipt.layer is CertificateLayer.DISCOVERY
    assert rank_result.receipt.backend == "flint"
    assert rank_result.receipt.inputs["matrix"] == matrix.content_id
    assert rank_result.to_dict()["schema"] == "arbogast.backend.flint-matrix-result.v1"
    assert captured == [([[1, 2], [3, 4]], 7), ([[1, 2], [3, 4]], 7)]


def test_gap_adapter_generates_closed_source_and_rejects_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GapBackend,
        "status",
        lambda self: BackendStatus(
            "gap",
            True,
            self.capabilities,
            version="GAP 4.14",
            executable="/test/gap",
        ),
    )
    invocations: list[tuple[list[str], str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocations.append((command, str(kwargs["input"])))
        return subprocess.CompletedProcess(command, 0, "ARBOGAST_ORDER:6\n", "")

    monkeypatch.setattr("arbogast.backends.gap.subprocess.run", run)
    result = GapBackend().permutation_group_order(((1, 0, 2), (0, 2, 1)))

    assert result.order == 6
    assert result.receipt.layer is CertificateLayer.DISCOVERY
    assert result.receipt.backend == "gap"
    assert result.to_dict()["schema"] == "arbogast.backend.gap-group-order-result.v1"
    assert invocations[0][0] == ["/test/gap", "-q"]
    assert "PermList([2,1,3])" in invocations[0][1]
    with pytest.raises(ValueError, match="images must be integers"):
        GapBackend().permutation_group_order(((0, "1"),))  # type: ignore[list-item]


def test_backend_adapters_fail_closed_on_malformed_external_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GapBackend,
        "status",
        lambda self: BackendStatus(
            "gap",
            True,
            self.capabilities,
            version="GAP 4.14",
            executable="/test/gap",
        ),
    )
    monkeypatch.setattr(
        "arbogast.backends.gap.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "order=6\n", ""),
    )
    with pytest.raises(RuntimeError, match="canonical group order"):
        GapBackend().permutation_group_order(((1, 0),))
