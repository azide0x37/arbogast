"""Independently replayable finite-group cohomology certificates."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._linear import (
    Vector,
    compose_is_zero,
    contains,
    image_basis,
    matrix_vector,
    nullspace,
    rank,
    span_basis,
)
from .complex import (
    DEFAULT_LIMITS,
    CohomologyError,
    ComplexityLimitError,
    ComplexityLimits,
    _bar_differential_from_snapshot,
    _canonical_json,
    _cochain_dimension,
    _matrix_hash,
    _validate_snapshot,
)


class CertificateVerificationError(CohomologyError):
    """Raised when a cohomology certificate fails independent replay."""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Structured result of certificate verification."""

    ok: bool
    checks: tuple[str, ...]
    error: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return value


def _strict_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _strict_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{name} must use Unicode NFC")
    return value


def _tuple_rows(value: object, name: str) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for row_index, row in enumerate(_sequence(value, name)):
        materialized = tuple(_sequence(row, f"{name}[{row_index}]"))
        rows.append(
            tuple(
                _strict_integer(entry, f"{name}[{row_index}][{column_index}]")
                for column_index, entry in enumerate(materialized)
            )
        )
    return tuple(rows)


def _tuple_matrices(value: object, name: str) -> tuple[tuple[tuple[int, ...], ...], ...]:
    return tuple(
        _tuple_rows(matrix, f"{name}[{index}]")
        for index, matrix in enumerate(_sequence(value, name))
    )


def _tuple_strings(value: object, name: str) -> tuple[str, ...]:
    return tuple(
        _strict_string(item, f"{name}[{index}]")
        for index, item in enumerate(_sequence(value, name))
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _require_canonical_residues(
    name: str,
    vectors: tuple[tuple[int, ...], ...] | tuple[tuple[tuple[int, ...], ...], ...],
    prime: int,
) -> None:
    def entries(value: Any) -> Any:
        for item in value:
            if isinstance(item, tuple):
                yield from entries(item)
            else:
                yield item

    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < prime
        for value in entries(vectors)
    ):
        raise CertificateVerificationError(
            f"{name} must use canonical integer residues in range({prime})"
        )


@dataclass(frozen=True, slots=True)
class CohomologyCertificate:
    """A backend-free receipt for one exact ``H^n(G, M)`` computation.

    The payload includes the finite multiplication table and action.  Verification reconstructs
    every normalized-bar differential and recomputes its kernel and preceding image; dimensions
    and supplied bases are never trusted as assertions.
    """

    schema_version: str
    prime: int
    degree: int
    group_element_ids: tuple[str, ...]
    identity_index: int
    multiplication_table: tuple[tuple[int, ...], ...]
    module_dimension: int
    action_matrices: tuple[tuple[tuple[int, ...], ...], ...]
    differential_hashes: tuple[str, ...]
    cocycle_basis: tuple[Vector, ...]
    coboundary_basis: tuple[Vector, ...]
    representative_basis: tuple[Vector, ...]
    quotient_projection: tuple[Vector, ...]
    quotient_section: tuple[Vector, ...]

    @property
    def dimension(self) -> int:
        """The claimed quotient dimension (verification recomputes it)."""

        return len(self.representative_basis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prime": self.prime,
            "degree": self.degree,
            "group_element_ids": list(self.group_element_ids),
            "identity_index": self.identity_index,
            "multiplication_table": [list(row) for row in self.multiplication_table],
            "module_dimension": self.module_dimension,
            "action_matrices": [[list(row) for row in matrix] for matrix in self.action_matrices],
            "differential_hashes": list(self.differential_hashes),
            "cocycle_basis": [list(row) for row in self.cocycle_basis],
            "coboundary_basis": [list(row) for row in self.coboundary_basis],
            "representative_basis": [list(row) for row in self.representative_basis],
            "quotient_projection": [list(row) for row in self.quotient_projection],
            "quotient_section": [list(row) for row in self.quotient_section],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        canonical = _canonical_json(self.to_dict())
        if indent is None:
            return canonical
        return json.dumps(
            json.loads(canonical),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=indent,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> CohomologyCertificate:
        required = {
            "schema_version",
            "prime",
            "degree",
            "group_element_ids",
            "identity_index",
            "multiplication_table",
            "module_dimension",
            "action_matrices",
            "differential_hashes",
            "cocycle_basis",
            "coboundary_basis",
            "representative_basis",
            "quotient_projection",
            "quotient_section",
        }
        if any(not isinstance(key, str) for key in payload):
            raise ValueError("certificate field names must be strings")
        fields = set(payload)
        missing = required - fields
        extra = fields - required
        if missing or extra:
            raise ValueError(
                f"certificate fields mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        return cls(
            schema_version=_strict_string(payload["schema_version"], "schema_version"),
            prime=_strict_integer(payload["prime"], "prime"),
            degree=_strict_integer(payload["degree"], "degree"),
            group_element_ids=_tuple_strings(payload["group_element_ids"], "group_element_ids"),
            identity_index=_strict_integer(payload["identity_index"], "identity_index"),
            multiplication_table=_tuple_rows(
                payload["multiplication_table"], "multiplication_table"
            ),
            module_dimension=_strict_integer(payload["module_dimension"], "module_dimension"),
            action_matrices=_tuple_matrices(payload["action_matrices"], "action_matrices"),
            differential_hashes=_tuple_strings(
                payload["differential_hashes"], "differential_hashes"
            ),
            cocycle_basis=_tuple_rows(payload["cocycle_basis"], "cocycle_basis"),
            coboundary_basis=_tuple_rows(payload["coboundary_basis"], "coboundary_basis"),
            representative_basis=_tuple_rows(
                payload["representative_basis"], "representative_basis"
            ),
            quotient_projection=_tuple_rows(payload["quotient_projection"], "quotient_projection"),
            quotient_section=_tuple_rows(payload["quotient_section"], "quotient_section"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> CohomologyCertificate:
        decoded = json.loads(payload, object_pairs_hook=_object_without_duplicate_keys)
        if not isinstance(decoded, Mapping):
            raise ValueError("certificate JSON must contain an object")
        return cls.from_dict(decoded)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def verify(
        self,
        *,
        raise_on_error: bool = True,
        limits: ComplexityLimits | None = None,
    ) -> VerificationReport:
        checks: list[str] = []
        try:
            self._verify(checks, limits or DEFAULT_LIMITS)
        except (CohomologyError, ValueError, TypeError, IndexError) as error:
            if raise_on_error:
                raise CertificateVerificationError(str(error)) from error
            return VerificationReport(False, tuple(checks), str(error))
        return VerificationReport(True, tuple(checks))

    def _verify(self, checks: list[str], limits: ComplexityLimits) -> None:
        if self.schema_version != "arbogast.cohomology.v1":
            raise CertificateVerificationError("unsupported cohomology certificate schema")
        if self.degree < 0:
            raise CertificateVerificationError("cohomology degree must be nonnegative")
        if len(self.group_element_ids) != len(self.multiplication_table):
            raise CertificateVerificationError(
                "group labels do not match multiplication-table size"
            )
        if len(set(self.group_element_ids)) != len(self.group_element_ids):
            raise CertificateVerificationError("group element identifiers are not unique")
        for identifier in self.group_element_ids:
            try:
                decoded_identifier = json.loads(
                    identifier,
                    object_pairs_hook=_object_without_duplicate_keys,
                )
                canonical_identifier = _canonical_json(decoded_identifier)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise CertificateVerificationError(
                    "group element identifiers must be canonical JSON"
                ) from error
            if canonical_identifier != identifier:
                raise CertificateVerificationError(
                    "group element identifiers must use the shared canonical JSON encoding"
                )
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.differential_hashes
        ):
            raise CertificateVerificationError(
                "differential hashes must be lowercase SHA-256 hexadecimal digests"
            )
        for name, vectors in (
            ("action matrices", self.action_matrices),
            ("cocycle basis", self.cocycle_basis),
            ("coboundary basis", self.coboundary_basis),
            ("representative basis", self.representative_basis),
            ("quotient projection", self.quotient_projection),
            ("quotient section", self.quotient_section),
        ):
            _require_canonical_residues(name, vectors, self.prime)
        group_order = len(self.multiplication_table)
        if group_order > limits.max_group_order:
            raise ComplexityLimitError(
                f"certificate group order {group_order} exceeds "
                f"max_group_order={limits.max_group_order}"
            )
        for cochain_degree in range(self.degree + 2):
            dimension = _cochain_dimension(group_order, self.module_dimension, cochain_degree)
            if dimension > limits.max_cochain_dimension:
                raise ComplexityLimitError(
                    f"certificate C^{cochain_degree} dimension {dimension} exceeds "
                    f"max_cochain_dimension={limits.max_cochain_dimension}"
                )
        for differential_degree in range(self.degree + 1):
            source_dimension = _cochain_dimension(
                group_order, self.module_dimension, differential_degree
            )
            target_dimension = _cochain_dimension(
                group_order, self.module_dimension, differential_degree + 1
            )
            if source_dimension * target_dimension > limits.max_rref_cells:
                raise ComplexityLimitError(
                    f"certificate d_{differential_degree} nominal shape exceeds "
                    f"max_rref_cells={limits.max_rref_cells}"
                )
        _validate_snapshot(
            self.prime,
            self.multiplication_table,
            self.identity_index,
            self.action_matrices,
            self.module_dimension,
        )
        checks.extend(("prime-field", "finite-group-axioms", "representation-homomorphism"))

        differentials = tuple(
            _bar_differential_from_snapshot(
                self.prime,
                self.multiplication_table,
                self.identity_index,
                self.action_matrices,
                self.module_dimension,
                degree,
            )
            for degree in range(self.degree + 1)
        )
        if any(matrix.nnz > limits.max_differential_nonzeros for matrix in differentials):
            raise ComplexityLimitError(
                "a reconstructed certificate differential exceeds "
                f"max_differential_nonzeros={limits.max_differential_nonzeros}"
            )
        fresh_hashes = tuple(_matrix_hash(matrix) for matrix in differentials)
        if fresh_hashes != self.differential_hashes:
            raise CertificateVerificationError(
                "differential hashes do not match a fresh normalized-bar construction"
            )
        checks.append("differentials-reconstructed")
        for degree in range(1, len(differentials)):
            if not compose_is_zero(differentials[degree], differentials[degree - 1]):
                raise CertificateVerificationError(
                    f"d_{degree} composed with d_{degree - 1} is nonzero"
                )
        checks.append("d-squared-zero")

        current = differentials[self.degree]
        ambient_dimension = current.ncols
        fresh_cocycles = nullspace(current)
        if self.degree == 0:
            fresh_coboundaries: tuple[Vector, ...] = ()
        else:
            fresh_coboundaries = image_basis(differentials[self.degree - 1])
        if span_basis(self.cocycle_basis, ambient_dimension, self.prime) != fresh_cocycles:
            raise CertificateVerificationError(
                "stored cocycles are not the freshly computed kernel"
            )
        if span_basis(self.coboundary_basis, ambient_dimension, self.prime) != fresh_coboundaries:
            raise CertificateVerificationError(
                "stored coboundaries are not the freshly computed preceding image"
            )
        if any(not contains(fresh_cocycles, vector, self.prime) for vector in fresh_coboundaries):
            raise CertificateVerificationError("the preceding image is not contained in the kernel")
        checks.extend(("kernel-recomputed", "image-recomputed", "image-contained-in-kernel"))

        canonical_representatives = span_basis(
            self.representative_basis, ambient_dimension, self.prime
        )
        if len(canonical_representatives) != len(self.representative_basis):
            raise CertificateVerificationError("representative cocycles are linearly dependent")
        if any(
            not contains(fresh_cocycles, vector, self.prime) for vector in canonical_representatives
        ):
            raise CertificateVerificationError("a representative is not a cocycle")
        combined = span_basis(
            [*fresh_coboundaries, *canonical_representatives],
            ambient_dimension,
            self.prime,
        )
        if combined != fresh_cocycles:
            raise CertificateVerificationError(
                "coboundaries and representatives do not give the complete cocycle space"
            )
        expected_dimension = len(fresh_cocycles) - len(fresh_coboundaries)
        if len(canonical_representatives) != expected_dimension:
            raise CertificateVerificationError("representative count is not dim(Z)-dim(B)")
        checks.append("quotient-representatives")

        quotient_dimension = expected_dimension
        if len(self.quotient_projection) != quotient_dimension or any(
            len(row) != ambient_dimension for row in self.quotient_projection
        ):
            raise CertificateVerificationError("quotient projection has the wrong shape")
        if len(self.quotient_section) != ambient_dimension or any(
            len(row) != quotient_dimension for row in self.quotient_section
        ):
            raise CertificateVerificationError("quotient section has the wrong shape")
        for boundary in fresh_coboundaries:
            if any(matrix_vector(self.quotient_projection, boundary, self.prime)):
                raise CertificateVerificationError("quotient projection does not kill coboundaries")
        for index, representative in enumerate(canonical_representatives):
            expected = tuple(
                1 if coordinate == index else 0 for coordinate in range(quotient_dimension)
            )
            if matrix_vector(self.quotient_projection, representative, self.prime) != expected:
                raise CertificateVerificationError(
                    "quotient projection does not send representatives to standard coordinates"
                )
            section_column = tuple(row[index] for row in self.quotient_section)
            if section_column != representative:
                raise CertificateVerificationError("quotient section is not the representative map")
        for cocycle in fresh_cocycles:
            coordinates = matrix_vector(self.quotient_projection, cocycle, self.prime)
            lifted = tuple(
                sum(
                    self.quotient_section[row][column] * coordinates[column]
                    for column in range(quotient_dimension)
                )
                % self.prime
                for row in range(ambient_dimension)
            )
            difference = tuple(
                (value - replacement) % self.prime
                for value, replacement in zip(cocycle, lifted, strict=True)
            )
            if not contains(fresh_coboundaries, difference, self.prime):
                raise CertificateVerificationError(
                    "projection followed by section does not recover a class modulo coboundaries"
                )
        checks.append("explicit-quotient-maps")

        expected_ambient = _cochain_dimension(
            len(self.multiplication_table), self.module_dimension, self.degree
        )
        if ambient_dimension != expected_ambient:
            raise CertificateVerificationError("ambient cochain dimension is inconsistent")
        if rank(fresh_coboundaries, ambient_dimension, self.prime) != len(fresh_coboundaries):
            raise CertificateVerificationError("fresh coboundary basis is unexpectedly dependent")
        checks.append("dimension-recomputed")


__all__ = [
    "CertificateVerificationError",
    "CohomologyCertificate",
    "VerificationReport",
]
