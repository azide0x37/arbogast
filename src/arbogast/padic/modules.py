"""Finite free p-adic modules and canonical finite-ring submodules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import TYPE_CHECKING, ClassVar, cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON

from ._schema import (
    MAX_CANONICAL_INTEGER_BITS,
    MAX_DIMENSION,
    MAX_EXACT_REPLAY_WORK,
    PAdicSemanticObject,
    canonical_label,
    strict_canonical_equal,
    strict_int,
)
from .errors import PAdicValidationError, PAdicVerificationError
from .fields import (
    IntegerMatrix,
    PAdicBall,
    PAdicPrecisionRing,
    _dependency_receipt,
    _extended_gcd,
    _in_lattice,
    _ring_from_evidence,
    _validate_hnf,
)

if TYPE_CHECKING:
    from .certificate import PAdicPayloadReplay

ModuleVector = tuple[PAdicBall, ...]
MAX_FLAT_MODULE_DIMENSION = 128
MAX_SUBMODULE_GENERATORS = 128


def _hnf_int(value: object) -> int:
    result = strict_int(value, "submodule-HNF entry")
    if result.bit_length() > MAX_CANONICAL_INTEGER_BITS:
        raise PAdicValidationError("submodule HNF contains an oversized integer")
    return result


def _raw_mapping(value: Mapping[str, object], expected: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise PAdicVerificationError(f"{name} has a foreign transport shape")
    return dict(value)


def _raw_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _column_hnf_generators(rows: Sequence[Sequence[int]]) -> IntegerMatrix:
    """Canonical column HNF for a full-rank rectangular generator matrix."""

    dimension = len(rows)
    if dimension == 0:
        raise PAdicValidationError("submodule lattice must have positive dimension")
    columns = len(rows[0])
    if columns < dimension or any(len(row) != columns for row in rows):
        raise PAdicValidationError(
            "submodule generator matrix must have at least as many columns as rows"
        )
    work = [list(row) for row in rows]
    offset = columns - dimension
    for row in range(dimension - 1, -1, -1):
        pivot_column = offset + row
        for column in range(pivot_column):
            left = work[row][column]
            right = work[row][pivot_column]
            if left == 0:
                continue
            divisor, coefficient_left, coefficient_right = _extended_gcd(left, right)
            old_left = [work[index][column] for index in range(dimension)]
            old_right = [work[index][pivot_column] for index in range(dimension)]
            for index in range(dimension):
                work[index][column] = (right // divisor) * old_left[index] - (
                    left // divisor
                ) * old_right[index]
                work[index][pivot_column] = (
                    coefficient_left * old_left[index] + coefficient_right * old_right[index]
                )
        pivot = work[row][pivot_column]
        if pivot == 0:
            raise PAdicValidationError("submodule generators do not define a full-rank preimage")
        if pivot < 0:
            for index in range(dimension):
                work[index][pivot_column] = -work[index][pivot_column]
            pivot = -pivot
        for column in range(pivot_column + 1, columns):
            quotient, _ = divmod(work[row][column], pivot)
            if quotient:
                for index in range(dimension):
                    work[index][column] -= quotient * work[index][pivot_column]
    if any(any(work[row][column] for row in range(dimension)) for column in range(offset)):
        raise PAdicVerificationError("rectangular HNF elimination left a foreign generator")
    result = tuple(
        tuple(work[row][offset + column] for column in range(dimension)) for row in range(dimension)
    )
    _validate_hnf(result)
    return result


def _block_modulus(module: PAdicModule) -> IntegerMatrix:
    degree = module.ring.field.degree
    dimension = module.rank * degree
    return tuple(
        tuple(
            (
                module.ring.modulus_hnf[row % degree][column % degree]
                if row // degree == column // degree
                else 0
            )
            for column in range(dimension)
        )
        for row in range(dimension)
    )


def _flatten(vector: Sequence[PAdicBall]) -> tuple[int, ...]:
    return tuple(coordinate for value in vector for coordinate in value.coordinates)


def _determinant_hnf(hnf: IntegerMatrix) -> int:
    result = 1
    for index in range(len(hnf)):
        result *= hnf[index][index]
    return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicModule(PAdicSemanticObject):
    """A finite free module over one exact p-adic precision ring."""

    schema_version: ClassVar[str] = "arbogast.padic.module/v1"

    ring: PAdicPrecisionRing
    rank: int
    basis_labels: tuple[str, ...]

    def __init__(
        self,
        ring: PAdicPrecisionRing,
        rank: int,
        *,
        basis_labels: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(ring, PAdicPrecisionRing):
            raise TypeError("module ring must be a PAdicPrecisionRing")
        normalized_rank = strict_int(rank, "module rank", minimum=1)
        if normalized_rank > MAX_DIMENSION:
            raise PAdicValidationError("module rank exceeds the portable bound")
        if normalized_rank * ring.field.degree > MAX_FLAT_MODULE_DIMENSION:
            raise PAdicValidationError("flattened module lattice exceeds the portable bound")
        labels = (
            tuple(f"e{index}" for index in range(normalized_rank))
            if basis_labels is None
            else tuple(
                canonical_label(label, "module basis label")
                for label in islice(basis_labels, normalized_rank + 1)
            )
        )
        if len(labels) != normalized_rank or len(set(labels)) != len(labels):
            raise PAdicValidationError("module needs one unique ordered label per basis element")
        object.__setattr__(self, "ring", ring)
        object.__setattr__(self, "rank", normalized_rank)
        object.__setattr__(self, "basis_labels", labels)

    @property
    def module_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        return (self.ring.certificate,)

    @property
    def base(self) -> PAdicPrecisionRing:
        return self.ring

    @property
    def dimension(self) -> int:
        return self.rank

    @property
    def zero(self) -> ModuleVector:
        return (self.ring.zero,) * self.rank

    def vector(self, entries: Iterable[PAdicBall | int]) -> ModuleVector:
        values = tuple(entries)
        if len(values) != self.rank:
            raise PAdicValidationError("module vector has the wrong rank")
        normalized: list[PAdicBall] = []
        for value in values:
            if isinstance(value, PAdicBall):
                if value.ring != self.ring:
                    raise PAdicValidationError("module vector entry uses a foreign precision ring")
                normalized.append(value)
            elif isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("module vector entries must be p-adic balls or integers")
            else:
                normalized.append(self.ring.one * value)
        return tuple(normalized)

    def basis_vector(self, index: int) -> ModuleVector:
        selected = strict_int(index, "module basis index", minimum=0)
        if selected >= self.rank:
            raise PAdicValidationError("module basis index is out of range")
        return tuple(
            self.ring.one if position == selected else self.ring.zero
            for position in range(self.rank)
        )

    def verify(self) -> bool:
        replay = PAdicModule(self.ring, self.rank, basis_labels=self.basis_labels)
        if replay != self:
            raise PAdicVerificationError("p-adic module normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "basis_labels": list(self.basis_labels),
            "coordinate_convention": "component-major column vectors",
            "rank": self.rank,
            "ring_id": self.ring.ring_id,
            "type": "arbogast.padic.module",
        }

    @classmethod
    def from_dict(
        cls,
        ring: PAdicPrecisionRing,
        value: Mapping[str, object],
    ) -> PAdicModule:
        raw = _raw_mapping(
            value,
            {
                "basis_labels",
                "coordinate_convention",
                "rank",
                "ring_id",
                "schema",
                "type",
            },
            "p-adic module",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.module"
            or raw["ring_id"] != ring.ring_id
            or raw["coordinate_convention"] != "component-major column vectors"
        ):
            raise PAdicVerificationError("p-adic module ring, schema, or convention was altered")
        labels = _raw_list(raw["basis_labels"], "module basis labels")
        if any(type(label) is not str for label in labels):
            raise PAdicVerificationError("module basis labels must be strings")
        result = cls(
            ring,
            strict_int(raw["rank"], "module rank", minimum=1),
            basis_labels=cast(list[str], labels),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic module is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicSubmodule(PAdicSemanticObject):
    """A canonical, possibly nonfree submodule of a finite free module."""

    schema_version: ClassVar[str] = "arbogast.padic.submodule/v1"

    ambient: PAdicModule
    preimage_hnf: IntegerMatrix

    def __init__(
        self,
        ambient: PAdicModule,
        generators: Iterable[Iterable[PAdicBall | int]] = (),
        *,
        preimage_hnf: Iterable[Iterable[int]] | None = None,
    ) -> None:
        if not isinstance(ambient, PAdicModule):
            raise TypeError("submodule ambient must be a PAdicModule")
        if preimage_hnf is not None:
            raw_generators = tuple(islice(generators, 1))
            if raw_generators:
                raise PAdicValidationError(
                    "submodule construction cannot mix generators and a canonical HNF"
                )
            dimension = ambient.rank * ambient.ring.field.degree
            raw_rows = tuple(islice(preimage_hnf, dimension + 1))
            if len(raw_rows) > dimension:
                raise PAdicValidationError("submodule HNF exceeds the flattened dimension")
            hnf = tuple(
                tuple(_hnf_int(value) for value in islice(row, dimension + 1)) for row in raw_rows
            )
            _validate_hnf(hnf)
        else:
            raw_vectors = tuple(islice(generators, MAX_SUBMODULE_GENERATORS + 1))
            if len(raw_vectors) > MAX_SUBMODULE_GENERATORS:
                raise PAdicValidationError("submodule generator count exceeds the portable bound")
            dimension = ambient.rank * ambient.ring.field.degree
            columns_count = dimension + len(raw_vectors) * ambient.ring.field.degree
            if dimension * dimension * columns_count > MAX_EXACT_REPLAY_WORK:
                raise PAdicValidationError(
                    "submodule HNF computation exceeds the exact replay work bound"
                )
            normalized_generators = tuple(ambient.vector(vector) for vector in raw_vectors)
            hnf = self._hnf_from_generators(ambient, normalized_generators)
        object.__setattr__(self, "ambient", ambient)
        object.__setattr__(self, "preimage_hnf", hnf)
        self._validate_preimage()

    @classmethod
    def zero(cls, ambient: PAdicModule) -> PAdicSubmodule:
        return cls(ambient)

    @classmethod
    def whole(cls, ambient: PAdicModule) -> PAdicSubmodule:
        return cls(ambient, (ambient.basis_vector(index) for index in range(ambient.rank)))

    @staticmethod
    def _hnf_from_generators(
        ambient: PAdicModule,
        generators: Sequence[ModuleVector],
    ) -> IntegerMatrix:
        modulus = _block_modulus(ambient)
        degree = ambient.ring.field.degree
        dimension = len(modulus)
        columns_count = dimension + len(generators) * degree
        if dimension * dimension * columns_count > MAX_EXACT_REPLAY_WORK:
            raise PAdicValidationError(
                "submodule HNF computation exceeds the exact replay work bound"
            )
        columns: list[tuple[int, ...]] = [
            tuple(modulus[row][column] for row in range(len(modulus)))
            for column in range(len(modulus))
        ]
        ring_basis = tuple(
            PAdicBall(
                ambient.ring,
                tuple(1 if coordinate == index else 0 for coordinate in range(degree)),
            )
            for index in range(degree)
        )
        for generator in generators:
            for scalar in ring_basis:
                columns.append(_flatten(tuple(scalar * value for value in generator)))
        rows = tuple(
            tuple(columns[column][row] for column in range(len(columns)))
            for row in range(len(modulus))
        )
        return _column_hnf_generators(rows)

    @property
    def submodule_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        return (self.ambient.certificate,)

    @property
    def module(self) -> PAdicModule:
        return self.ambient

    @property
    def cardinality(self) -> int:
        modulus_index = int(pow(self.ambient.ring.cardinality, self.ambient.rank))
        preimage_index = _determinant_hnf(self.preimage_hnf)
        quotient, remainder = divmod(modulus_index, preimage_index)
        if remainder:
            raise PAdicVerificationError("submodule preimage index does not divide the ambient")
        return quotient

    @property
    def canonical_generators(self) -> tuple[ModuleVector, ...]:
        degree = self.ambient.ring.field.degree
        dimension = self.ambient.rank * degree
        result: list[ModuleVector] = []
        for column in range(dimension):
            flattened = tuple(self.preimage_hnf[row][column] for row in range(dimension))
            result.append(
                tuple(
                    PAdicBall(
                        self.ambient.ring,
                        flattened[component * degree : (component + 1) * degree],
                    )
                    for component in range(self.ambient.rank)
                )
            )
        return tuple(result)

    def contains(self, vector: Iterable[PAdicBall | int]) -> bool:
        return _in_lattice(self.preimage_hnf, _flatten(self.ambient.vector(vector)))

    def _validate_preimage(self) -> None:
        dimension = self.ambient.rank * self.ambient.ring.field.degree
        if len(self.preimage_hnf) != dimension or any(
            len(row) != dimension for row in self.preimage_hnf
        ):
            raise PAdicValidationError("submodule HNF has the wrong flattened dimension")
        modulus = _block_modulus(self.ambient)
        for column in range(dimension):
            vector = tuple(modulus[row][column] for row in range(dimension))
            if not _in_lattice(self.preimage_hnf, vector):
                raise PAdicValidationError(
                    "submodule preimage does not contain the ambient modulus lattice"
                )
        degree = self.ambient.ring.field.degree
        ring_basis = tuple(
            PAdicBall(
                self.ambient.ring,
                tuple(1 if coordinate == index else 0 for coordinate in range(degree)),
            )
            for index in range(degree)
        )
        for generator in self.canonical_generators:
            for scalar in ring_basis:
                scaled = _flatten(tuple(scalar * value for value in generator))
                if not _in_lattice(self.preimage_hnf, scaled):
                    raise PAdicValidationError(
                        "submodule preimage is not stable under precision-ring scalars"
                    )
        if self.cardinality > self.ambient.ring.cardinality**self.ambient.rank:
            raise PAdicValidationError("submodule cardinality exceeds its ambient module")

    def verify(self) -> bool:
        replay = PAdicSubmodule(self.ambient, preimage_hnf=self.preimage_hnf)
        if replay != self:
            raise PAdicVerificationError("p-adic submodule normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "ambient_id": self.ambient.module_id,
                "cardinality": self.cardinality,
                "preimage_hnf": [list(row) for row in self.preimage_hnf],
                "type": "arbogast.padic.submodule",
            },
        )

    @classmethod
    def from_dict(
        cls,
        ambient: PAdicModule,
        value: Mapping[str, object],
    ) -> PAdicSubmodule:
        raw = _raw_mapping(
            value,
            {"ambient_id", "cardinality", "preimage_hnf", "schema", "type"},
            "p-adic submodule",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.submodule"
            or raw["ambient_id"] != ambient.module_id
        ):
            raise PAdicVerificationError("p-adic submodule ambient, schema, or type was altered")
        raw_hnf = _raw_list(raw["preimage_hnf"], "submodule HNF")
        rows: list[tuple[int, ...]] = []
        for index, item in enumerate(raw_hnf):
            row = _raw_list(item, f"submodule HNF[{index}]")
            rows.append(tuple(_hnf_int(entry) for entry in row))
        result = cls(ambient, preimage_hnf=rows)
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic submodule is not strict canonical transport")
        return result


def _module_from_evidence(
    evidence: Sequence[VerificationCertificate],
    module_id: object,
) -> tuple[PAdicModule, tuple[str, ...]]:
    from .certificate import PAdicReceipt

    candidates: list[tuple[PAdicModule, str]] = []
    for certificate in evidence:
        try:
            receipt = cast(
                PAdicReceipt,
                _dependency_receipt(certificate, "module"),
            )
        except PAdicVerificationError:
            continue
        payload = receipt.payload.to_dict()
        if set(payload) != {"result"} or type(payload["result"]) is not dict:
            raise PAdicVerificationError("module dependency omits its result")
        document = cast(dict[str, object], payload["result"])
        ring, _ = _ring_from_evidence(receipt.evidence, document.get("ring_id"))
        module = PAdicModule.from_dict(ring, document)
        if module.module_id == module_id:
            candidates.append((module, certificate.certificate_id))
    if len(candidates) != 1:
        raise PAdicVerificationError("module dependency is missing or ambiguous")
    module, certificate_id = candidates[0]
    return module, (certificate_id,)


def _register_payload_verifiers() -> None:
    from .certificate import padic_payload_verifier, replay_schema_payload

    @padic_payload_verifier("module")
    def verify_module(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        raw = payload.get("result")
        if type(raw) is not dict:
            raise PAdicVerificationError("module payload omits its result")
        ring, evidence_ids = _ring_from_evidence(
            evidence,
            cast(dict[str, object], raw).get("ring_id"),
        )
        return replay_schema_payload(
            payload,
            evidence,
            decoder=lambda value: PAdicModule.from_dict(ring, value),
            checks=(
                "finite free module rank and ordered basis replayed",
                "coefficient precision ring bound exactly",
            ),
            evidence_ids=evidence_ids,
        )

    @padic_payload_verifier("submodule")
    def verify_submodule(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        raw = payload.get("result")
        if type(raw) is not dict:
            raise PAdicVerificationError("submodule payload omits its result")
        ambient, evidence_ids = _module_from_evidence(
            evidence,
            cast(dict[str, object], raw).get("ambient_id"),
        )
        return replay_schema_payload(
            payload,
            evidence,
            decoder=lambda value: PAdicSubmodule.from_dict(ambient, value),
            checks=(
                "canonical preimage HNF reconstructed",
                "modulus containment, scalar closure, and cardinality replayed",
            ),
            evidence_ids=evidence_ids,
        )


_register_payload_verifiers()


__all__ = ["PAdicModule", "PAdicSubmodule"]
