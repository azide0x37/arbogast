"""Exact degree-zero framing constraints."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from arbogast.core import CanonicalJSON
from arbogast.formats import DEFORM_FRAMING_SCHEMA_V1
from arbogast.linalg import DenseMatrix, LinearSubspace, PrimeField, nullspace

from ._schema import (
    DeformationSemanticObject,
    _canonical_dense_matrix,
    _canonical_linear_subspace,
)
from .complex import DeformationComplex
from .errors import DeformationError, DeformationVerificationError

if TYPE_CHECKING:
    from .equivariant import InvariantDeformations
    from .problem import DeformationPresentation, DeformationProblem


def _label(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeformationError("framing label must be a non-empty string or None")
    return unicodedata.normalize("NFC", value.strip())


@dataclass(frozen=True, slots=True, init=False)
class Framing(DeformationSemanticObject):
    """Linear marking constraints whose kernel is the allowed gauge space."""

    constraints: DenseMatrix
    allowed_gauge: LinearSubspace
    label: str | None

    schema_version = DEFORM_FRAMING_SCHEMA_V1

    def __init__(self, constraints: DenseMatrix, label: str | None = None) -> None:
        if not isinstance(constraints, DenseMatrix):
            raise TypeError("framing constraints must be a DenseMatrix")
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "allowed_gauge", nullspace(constraints))
        object.__setattr__(self, "label", _label(label))
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.constraints.field

    @property
    def ambient_dimension(self) -> int:
        return self.constraints.ncols

    @property
    def allowed_dimension(self) -> int:
        return self.allowed_gauge.dimension

    def inclusion_matrix(self) -> DenseMatrix:
        """Return ``allowed C0 -> original C0`` in canonical coordinates."""

        return DenseMatrix.from_columns(
            self.constraints.field,
            self.allowed_gauge.basis,
            nrows=self.ambient_dimension,
        )

    def restrict(self, complex: DeformationComplex) -> DeformationComplex:
        """Restrict degree zero and its differential to framing-preserving gauges."""

        if not isinstance(complex, DeformationComplex):
            raise TypeError("complex must be a DeformationComplex")
        complex.verify()
        if self.constraints.field != complex.field:
            raise DeformationError("framing and deformation complex use different fields")
        if self.ambient_dimension != complex.degree0_dimension:
            raise DeformationError("framing constraints have the wrong degree-zero dimension")
        restricted = DeformationComplex(
            complex.field,
            complex.d0 @ self.inclusion_matrix(),
            complex.d1,
            name=complex.name,
        )
        restricted.verify()
        return restricted

    def verify(self) -> bool:
        if not _canonical_dense_matrix(self.constraints):
            raise DeformationVerificationError(
                "framing constraints contain noncanonical field coordinates"
            )
        if not _canonical_linear_subspace(
            self.allowed_gauge,
            field=self.constraints.field,
            ambient_dimension=self.constraints.ncols,
        ):
            raise DeformationVerificationError("allowed gauge space is not canonical")
        expected = nullspace(self.constraints)
        if self.allowed_gauge != expected:
            raise DeformationVerificationError("allowed gauge space is not the framing kernel")
        if _label(self.label) != self.label:
            raise DeformationVerificationError("framing label normalization was altered")
        inclusion = self.inclusion_matrix()
        if inclusion.shape != (self.ambient_dimension, self.allowed_dimension):
            raise DeformationVerificationError("framing inclusion has the wrong shape")
        if self.constraints @ inclusion != DenseMatrix.zeros(
            self.constraints.field,
            self.constraints.nrows,
            self.allowed_dimension,
        ):
            raise DeformationVerificationError("framing inclusion violates its constraints")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "allowed_gauge": self.allowed_gauge.to_canonical_data(),
            "ambient_dimension": self.ambient_dimension,
            "constraints": self.constraints.to_canonical_data(),
            "label": self.label,
            "type": "arbogast.deform.framing",
        }


def frame(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
    framing: Framing,
) -> DeformationProblem:
    """Return the deformation problem with its degree-zero gauges restricted."""

    from .equivariant import InvariantDeformations
    from .problem import DeformationPresentation, DeformationProblem
    from .problem import deformation_problem as make_problem

    if not isinstance(
        source,
        (DeformationComplex, DeformationPresentation, DeformationProblem, InvariantDeformations),
    ):
        raise TypeError("source must be a deformation complex, presentation, or problem")
    if not isinstance(framing, Framing):
        raise TypeError("framing must be a Framing")
    return make_problem(source, framing)


__all__ = ["Framing", "frame"]
