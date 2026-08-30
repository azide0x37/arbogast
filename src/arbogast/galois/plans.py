"""Deterministic shard plans for local arithmetic.

Plan and shard identities commit to ordered canonical place IDs and, for
localization, the ordered Kummer basis.  Reducers fail closed on missing,
duplicate, foreign, or reordered shard output.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arbogast.backends.pari_results import PariArithmeticResult
from arbogast.cert import content_address
from arbogast.linalg import DenseMatrix, PrimeField

from ._common import Vector, canonical_snapshot, snapshot_id
from .kummer import KummerSpace
from .local import LocalH1Space, LocalizationMap, local_h1, localize
from .proof import ProofContext, Unsupported


class ShardReductionError(ValueError):
    """Raised when shard custody or ordering cannot be proved."""


@dataclass(frozen=True, slots=True)
class LocalH1ShardSpec:
    plan_id: str
    index: int
    place_id: str
    place: Any

    @property
    def key(self) -> str:
        return self.place_id


@dataclass(frozen=True, slots=True)
class LocalH1ShardResult:
    plan_id: str
    index: int
    key: str
    value: LocalH1Space | Unsupported | PariArithmeticResult


@dataclass(frozen=True, slots=True)
class LocalH1Plan:
    places: tuple[Any, ...]
    prime: int
    presentations: Mapping[str, Mapping[str, object]]
    proof_context: ProofContext | None
    shard_specs: tuple[LocalH1ShardSpec, ...]
    plan_id: str

    def run(self, spec: LocalH1ShardSpec) -> LocalH1ShardResult:
        if spec.plan_id != self.plan_id or not 0 <= spec.index < len(self.shard_specs):
            raise ShardReductionError("foreign local-H1 shard specification")
        if spec != self.shard_specs[spec.index]:
            raise ShardReductionError("local-H1 shard specification was altered")
        presentation = self.presentations.get(spec.place_id)
        raw_basis = None if presentation is None else presentation.get("basis")
        if raw_basis is not None and not isinstance(raw_basis, Iterable):
            raise TypeError("local-H1 shard presentation basis must be iterable")
        value = local_h1(
            spec.place,
            prime=self.prime,
            basis=raw_basis,
            proof_context=self.proof_context,
            presentation=presentation,
        )
        return LocalH1ShardResult(self.plan_id, spec.index, spec.key, value)

    def run_all(self) -> tuple[LocalH1ShardResult, ...]:
        return tuple(self.run(spec) for spec in self.shard_specs)

    def reduce(
        self,
        results: Iterable[LocalH1ShardResult],
    ) -> tuple[LocalH1Space | Unsupported | PariArithmeticResult, ...]:
        materialized = tuple(results)
        _validate_results(
            self.plan_id,
            tuple(spec.key for spec in self.shard_specs),
            materialized,
        )
        return tuple(result.value for result in materialized)


@dataclass(frozen=True, slots=True)
class LocalizationShardSpec:
    plan_id: str
    index: int
    place_id: str
    generator_index: int
    local_space: LocalH1Space

    @property
    def key(self) -> str:
        return f"{self.place_id}:{self.generator_index}"


@dataclass(frozen=True, slots=True)
class LocalizationShardResult:
    plan_id: str
    index: int
    key: str
    place_id: str
    generator_index: int
    local_space: LocalH1Space
    column: Vector


@dataclass(frozen=True, slots=True)
class LocalizationPlan:
    space: KummerSpace
    local_spaces: tuple[LocalH1Space, ...]
    matrices: Mapping[str, DenseMatrix | Iterable[Iterable[int]]]
    shard_specs: tuple[LocalizationShardSpec, ...]
    plan_id: str

    def _map_for(self, local_space: LocalH1Space) -> LocalizationMap:
        supplied = self.matrices.get(snapshot_id(local_space.place))
        result = localize(self.space, local_space, matrix=supplied)
        if isinstance(result, Unsupported):
            raise ShardReductionError(result.reason)
        if not isinstance(result, LocalizationMap):
            raise ShardReductionError("localization shard did not produce a map")
        return result

    def run(self, spec: LocalizationShardSpec) -> LocalizationShardResult:
        if spec.plan_id != self.plan_id or not 0 <= spec.index < len(self.shard_specs):
            raise ShardReductionError("foreign localization shard specification")
        if spec != self.shard_specs[spec.index]:
            raise ShardReductionError("localization shard specification was altered")
        localization = self._map_for(spec.local_space)
        return LocalizationShardResult(
            self.plan_id,
            spec.index,
            spec.key,
            spec.place_id,
            spec.generator_index,
            spec.local_space,
            localization.matrix.column(spec.generator_index),
        )

    def run_all(self) -> tuple[LocalizationShardResult, ...]:
        return tuple(self.run(spec) for spec in self.shard_specs)

    def reduce(self, results: Iterable[LocalizationShardResult]) -> tuple[LocalizationMap, ...]:
        materialized = tuple(results)
        _validate_results(
            self.plan_id,
            tuple(spec.key for spec in self.shard_specs),
            materialized,
        )
        maps: list[LocalizationMap] = []
        offset = 0
        for local_space in self.local_spaces:
            count = self.space.dimension
            block = materialized[offset : offset + count]
            if len(block) != count or any(
                result.place_id != snapshot_id(local_space.place)
                or result.generator_index != index
                or result.local_space.content_id != local_space.content_id
                for index, result in enumerate(block)
            ):
                raise ShardReductionError("localization shard block has foreign semantic content")
            matrix = DenseMatrix.from_columns(
                PrimeField(self.space.prime),
                tuple(result.column for result in block),
                nrows=local_space.dimension,
            )
            localization = self._map_for(local_space)
            if localization.matrix != matrix:
                raise ShardReductionError(
                    "reduced localization columns differ from the proving map"
                )
            localization.verify()
            maps.append(localization)
            offset += count
        if offset != len(materialized):
            raise ShardReductionError("localization reducer received surplus shards")
        return tuple(maps)


def _validate_results(
    plan_id: str,
    expected_keys: tuple[str, ...],
    results: tuple[Any, ...],
) -> None:
    if len(results) != len(expected_keys):
        raise ShardReductionError(
            f"missing or surplus shards: received {len(results)}, expected {len(expected_keys)}"
        )
    indices = tuple(result.index for result in results)
    if len(set(indices)) != len(indices):
        raise ShardReductionError("duplicate shard indices")
    keys = tuple(result.key for result in results)
    if len(set(keys)) != len(keys):
        raise ShardReductionError("duplicate shard keys")
    if any(result.plan_id != plan_id for result in results):
        raise ShardReductionError("foreign shard plan ID")
    if indices != tuple(range(len(results))) or keys != expected_keys:
        raise ShardReductionError("shards are reordered or carry foreign keys")


def plan_local_h1(
    places: Iterable[Any],
    *,
    prime: int = 2,
    presentations: Mapping[str, Mapping[str, object]] | None = None,
    proof_context: ProofContext | None = None,
) -> LocalH1Plan:
    """Shard local H1 deterministically by canonical place ID."""

    normalized_places = tuple(sorted(tuple(places), key=snapshot_id))
    place_ids = tuple(snapshot_id(place) for place in normalized_places)
    if len(set(place_ids)) != len(place_ids):
        raise ValueError("local-H1 plan place IDs must be unique")
    normalized_presentations = dict(presentations or {})
    plan_id = content_address(
        {
            "type": "arbogast.local_h1_plan/v1",
            "prime": prime,
            "places": tuple(canonical_snapshot(place) for place in normalized_places),
            "presentations": normalized_presentations,
            "proof_context": proof_context,
        }
    )
    specs = tuple(
        LocalH1ShardSpec(plan_id, index, place_id, place)
        for index, (place_id, place) in enumerate(zip(place_ids, normalized_places, strict=True))
    )
    return LocalH1Plan(
        normalized_places,
        prime,
        normalized_presentations,
        proof_context,
        specs,
        plan_id,
    )


def plan_localize(
    space: KummerSpace,
    local_spaces: Iterable[LocalH1Space],
    *,
    matrices: Mapping[str, DenseMatrix | Iterable[Iterable[int]]] | None = None,
) -> LocalizationPlan:
    """Shard localization by the exact ``(place, Kummer generator)`` key."""

    normalized_locals = tuple(sorted(tuple(local_spaces), key=lambda item: snapshot_id(item.place)))
    place_ids = tuple(snapshot_id(item.place) for item in normalized_locals)
    if len(set(place_ids)) != len(place_ids):
        raise ValueError("localization plan local spaces must have distinct places")
    normalized_matrices = dict(matrices or {})
    plan_id = content_address(
        {
            "type": "arbogast.localization_plan/v1",
            "space": space.content_id,
            "local_spaces": tuple(item.content_id for item in normalized_locals),
            "matrices": normalized_matrices,
        }
    )
    specs: list[LocalizationShardSpec] = []
    for local_space in normalized_locals:
        place_id = snapshot_id(local_space.place)
        for generator_index in range(space.dimension):
            specs.append(
                LocalizationShardSpec(
                    plan_id,
                    len(specs),
                    place_id,
                    generator_index,
                    local_space,
                )
            )
    return LocalizationPlan(
        space,
        normalized_locals,
        normalized_matrices,
        tuple(specs),
        plan_id,
    )


__all__ = [
    "LocalH1Plan",
    "LocalH1ShardResult",
    "LocalH1ShardSpec",
    "LocalizationPlan",
    "LocalizationShardResult",
    "LocalizationShardSpec",
    "ShardReductionError",
    "plan_local_h1",
    "plan_localize",
]
