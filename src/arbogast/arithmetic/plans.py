"""Deterministic, strict Selmer assembly plans for fleet execution.

Planner helpers are intentionally not re-exported from
``arbogast.arithmetic``: ``selmer`` remains the public mathematical
operation, while specs and fleet profiles may register these stable paths.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from arbogast.core import CanonicalJSON, CanonicalObject, VerificationError
from arbogast.linalg import DenseMatrix

from ._support import identity_of, stack_matrices
from .certificate import ArithmeticError
from .selmer import SelmerKernel, SelmerProblem, selmer


class SelmerPlanError(ArithmeticError):
    """Raised when a fleet block cannot belong to a Selmer plan."""


@dataclass(frozen=True, slots=True)
class SelmerPlanTask(CanonicalObject):
    """One immutable place/generator column task."""

    plan_id: str
    index: int
    place_index: int
    place_id: str
    generator_index: int
    row_count: int
    local_condition_certificate_id: str
    localization_certificate_id: str | None

    @property
    def task_id(self) -> str:
        return self.content_id

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "generator_index": self.generator_index,
            "index": self.index,
            "local_condition_certificate_id": self.local_condition_certificate_id,
            "localization_certificate_id": self.localization_certificate_id,
            "place_id": self.place_id,
            "place_index": self.place_index,
            "plan_id": self.plan_id,
            "row_count": self.row_count,
            "type": "arbogast.selmer_plan_task",
        }


@dataclass(frozen=True, slots=True)
class SelmerBlock(CanonicalObject):
    """A certified column of one place-local quotient map."""

    plan_id: str
    task_id: str
    index: int
    place_index: int
    place_id: str
    generator_index: int
    column: tuple[int, ...]
    local_condition_certificate_id: str
    localization_certificate_id: str | None

    @property
    def block_id(self) -> str:
        return self.content_id

    def verify(self, task: SelmerPlanTask) -> bool:
        if (
            self.plan_id != task.plan_id
            or self.task_id != task.task_id
            or self.index != task.index
            or self.place_index != task.place_index
            or self.place_id != task.place_id
            or self.generator_index != task.generator_index
            or len(self.column) != task.row_count
            or self.local_condition_certificate_id != task.local_condition_certificate_id
            or self.localization_certificate_id != task.localization_certificate_id
        ):
            raise VerificationError("Selmer block is not bound to the requested task")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "column": list(self.column),
            "generator_index": self.generator_index,
            "index": self.index,
            "local_condition_certificate_id": self.local_condition_certificate_id,
            "localization_certificate_id": self.localization_certificate_id,
            "place_id": self.place_id,
            "place_index": self.place_index,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "type": "arbogast.selmer_block",
        }


@dataclass(frozen=True, slots=True, init=False)
class SelmerAssemblyPlan(CanonicalObject):
    """Canonical place-major, generator-minor Selmer assembly plan."""

    problem: SelmerProblem
    plan_id: str
    tasks: tuple[SelmerPlanTask, ...]

    def __init__(self, problem: SelmerProblem) -> None:
        if not isinstance(problem, SelmerProblem):
            raise TypeError("SelmerAssemblyPlan requires a SelmerProblem")
        problem.verify()
        manifest = {
            "problem": problem.to_canonical_data(),
            "order": "place-major-generator-minor",
            "place_ids": tuple(identity_of(place, role="place") for place in problem.places),
            "generator_count": problem.global_dimension,
            "row_counts": tuple(matrix.nrows for matrix in problem.quotient_blocks),
            "type": "arbogast.selmer_plan_manifest",
        }
        # A temporary canonical object is unnecessary; content identity is
        # supplied by the exact core helper through a tiny private wrapper.
        plan_id = _Manifest(manifest).content_id
        tasks: list[SelmerPlanTask] = []
        for place_index, (place, matrix, block) in enumerate(
            zip(problem.places, problem.quotient_blocks, problem._blocks, strict=True)
        ):
            localization_certificate = getattr(block.localization, "certificate", None)
            localization_certificate_id = getattr(
                localization_certificate,
                "certificate_id",
                None,
            )
            for generator_index in range(problem.global_dimension):
                tasks.append(
                    SelmerPlanTask(
                        plan_id=plan_id,
                        index=len(tasks),
                        place_index=place_index,
                        place_id=identity_of(place, role="place"),
                        generator_index=generator_index,
                        row_count=matrix.nrows,
                        local_condition_certificate_id=(block.condition.certificate.certificate_id),
                        localization_certificate_id=localization_certificate_id,
                    )
                )
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "tasks", tuple(tasks))

    def run(self, task: SelmerPlanTask) -> SelmerBlock:
        """Run exactly one task after rejecting foreign or reordered input."""

        if not isinstance(task, SelmerPlanTask):
            raise SelmerPlanError("run requires a SelmerPlanTask")
        if task.index < 0 or task.index >= len(self.tasks):
            raise SelmerPlanError("task index is foreign to this plan")
        expected = self.tasks[task.index]
        if task != expected:
            raise SelmerPlanError("task is foreign, altered, or reordered")
        block = self.problem._blocks[task.place_index]
        quotient = block.condition.quotient_matrix @ block.matrix
        result = SelmerBlock(
            plan_id=self.plan_id,
            task_id=task.task_id,
            index=task.index,
            place_index=task.place_index,
            place_id=task.place_id,
            generator_index=task.generator_index,
            column=quotient.column(task.generator_index),
            local_condition_certificate_id=task.local_condition_certificate_id,
            localization_certificate_id=task.localization_certificate_id,
        )
        result.verify(task)
        return result

    @property
    def shard_specs(self) -> tuple[SelmerPlanTask, ...]:
        """Stable fleet-facing alias for the canonical task manifest."""

        return self.tasks

    def run_all(self) -> tuple[SelmerBlock, ...]:
        return tuple(self.run(task) for task in self.tasks)

    def reduce(self, blocks: Sequence[SelmerBlock]) -> SelmerKernel:
        """Reduce only a complete, unique, in-order set of native blocks."""

        materialized = tuple(blocks)
        if len(materialized) != len(self.tasks):
            raise SelmerPlanError(
                f"missing or extra Selmer blocks: got {len(materialized)}, "
                f"expected {len(self.tasks)}"
            )
        if any(not isinstance(block, SelmerBlock) for block in materialized):
            raise SelmerPlanError("reducer input contains a non-Selmer block")
        block_ids = tuple(block.block_id for block in materialized)
        if len(set(block_ids)) != len(block_ids):
            raise SelmerPlanError("duplicate Selmer blocks are not accepted")
        for expected, block in zip(self.tasks, materialized, strict=True):
            if block.plan_id != self.plan_id:
                raise SelmerPlanError("reducer input contains a foreign Selmer block")
            if block.index != expected.index:
                raise SelmerPlanError("Selmer blocks were reordered")
            try:
                block.verify(expected)
            except VerificationError as exc:
                raise SelmerPlanError(str(exc)) from exc

        place_matrices: list[DenseMatrix] = []
        offset = 0
        for place_matrix in self.problem.quotient_blocks:
            count = self.problem.global_dimension
            native = materialized[offset : offset + count]
            columns = tuple(block.column for block in native)
            reconstructed = DenseMatrix.from_columns(
                place_matrix.field,
                columns,
                nrows=place_matrix.nrows,
            )
            if reconstructed != place_matrix:
                raise SelmerPlanError("a Selmer block column was altered")
            place_matrices.append(reconstructed)
            offset += count
        assembled = stack_matrices(
            self.problem.global_to_local_quotient.field,
            tuple(place_matrices),
            ncols=self.problem.global_dimension,
        )
        if assembled != self.problem.global_to_local_quotient:
            raise SelmerPlanError("reduced Selmer matrix differs from direct exact assembly")
        return selmer(self.problem)

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "plan_id": self.plan_id,
            "problem": self.problem.to_canonical_data(),
            "tasks": [task.to_canonical_data() for task in self.tasks],
            "type": "arbogast.selmer_assembly_plan",
        }


@dataclass(frozen=True, slots=True)
class _Manifest(CanonicalObject):
    value: Mapping[str, object]

    def to_canonical_data(self) -> CanonicalJSON:
        return self.value  # type: ignore[return-value]


def plan_selmer(problem: SelmerProblem) -> SelmerAssemblyPlan:
    """Construct the stable fleet plan for a finite Selmer problem."""

    return SelmerAssemblyPlan(problem)


__all__ = [
    "SelmerAssemblyPlan",
    "SelmerBlock",
    "SelmerPlanError",
    "SelmerPlanTask",
    "plan_selmer",
]
