"""Typed discovery results emitted by optional exact-algebra adapters."""

from __future__ import annotations

from dataclasses import dataclass

from arbogast.cert import DiscoveryReceipt


@dataclass(frozen=True, slots=True)
class FlintMatrixResult:
    """One exact FLINT matrix scalar plus a discovery receipt.

    The receipt records an external computation; callers still need an Arbogast verification
    certificate before promoting the value into a computed theorem claim.
    """

    operation: str
    value: int
    receipt: DiscoveryReceipt

    def __post_init__(self) -> None:
        if self.operation not in {"rank", "determinant"}:
            raise ValueError("unsupported FLINT matrix-result operation")
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError("FLINT matrix-result value must be an integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "receipt": self.receipt.to_dict(),
            "schema": "arbogast.backend.flint-matrix-result.v1",
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class GapGroupOrderResult:
    """Exact order returned by GAP for a pinned permutation generating set."""

    order: int
    receipt: DiscoveryReceipt

    def __post_init__(self) -> None:
        if isinstance(self.order, bool) or not isinstance(self.order, int) or self.order <= 0:
            raise ValueError("GAP group order must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "order": self.order,
            "receipt": self.receipt.to_dict(),
            "schema": "arbogast.backend.gap-group-order-result.v1",
        }


__all__ = ["FlintMatrixResult", "GapGroupOrderResult"]
