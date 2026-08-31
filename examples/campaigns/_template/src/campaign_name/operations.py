"""One deterministic discovery operation for the template campaign."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from arbogast.campaign import ExecutionTelemetry, Outcome, OutcomeScope, closure_subject
from arbogast.cert import VerificationCertificate
from arbogast.fleet import FunctionalOperation, ShardSpec, TaskSpec
from arbogast.formats import JSONValue, normalize_json

from .specification import (
    CLAIM_ID,
    MODULUS,
    RESULT_BOUNDARY_HASH,
    RESULT_STATEMENT_HASH,
    TARGET_RESIDUE,
    VERIFIER,
)
from .verifiers import verify_residue_square


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def plan_residues(task: TaskSpec) -> tuple[ShardSpec, ...]:
    """Plan the complete finite domain in canonical order."""

    modulus = _integer(task.parameters.get("modulus"), "modulus")
    return tuple(
        ShardSpec(
            task.task_hash,
            f"residue-{residue:02d}",
            {"residue": residue},
            ordinal=residue,
        )
        for residue in range(modulus)
    )


def evaluate_residue(task: TaskSpec, shard: ShardSpec) -> dict[str, int]:
    """Evaluate one residue without making a proof claim."""

    modulus = _integer(task.parameters.get("modulus"), "modulus")
    residue = _integer(shard.payload.get("residue"), "residue")
    return {"residue": residue, "square": residue * residue % modulus}


def reduce_residues(task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, JSONValue]:
    """Normalize discovery rows and emit a certificate for independent replay."""

    modulus = _integer(task.parameters.get("modulus"), "modulus")
    target = _integer(task.parameters.get("target_residue"), "target_residue")
    target_id = _string(task.parameters.get("target_id"), "target_id")
    rows: list[dict[str, int]] = []
    for index, partial in enumerate(partials):
        if not isinstance(partial, dict):
            raise ValueError(f"partial {index} is not an object")
        rows.append(
            {
                "residue": _integer(partial.get("residue"), "residue"),
                "square": _integer(partial.get("square"), "square"),
            }
        )
    rows.sort(key=lambda row: row["residue"])
    roots = [row["residue"] for row in rows if row["square"] == target]
    if modulus != MODULUS or target != TARGET_RESIDUE or not roots:
        raise ValueError("template fixture must find the declared modular square root")

    outcome = Outcome.FOUND
    scope = OutcomeScope.TARGET_GLOBAL
    certificate = VerificationCertificate.create(
        closure_subject(target_id, outcome, scope),
        VERIFIER,
        claim_id=CLAIM_ID,
        statement_hash=RESULT_STATEMENT_HASH,
        claim_boundary_hash=RESULT_BOUNDARY_HASH,
        witness={
            "modulus": modulus,
            "outcome": outcome.value,
            "outcome_scope": scope.value,
            "rows": rows,
            "target": target,
            "target_id": target_id,
            "task_hash": task.task_hash,
        },
        checks=("canonical-domain", "modular-squares", "claim-binding"),
        guarantees=("the displayed roots satisfy the target in the complete residue domain",),
    )
    return {
        "candidates": [
            {
                "canonical_key": f"modular-square:{modulus}:{target}:{roots[0]}",
                "canonicalizer": "campaign-template.modular-root.v1",
                "certificate_ref": certificate.certificate_id,
                "equivalence_scope": "TARGET",
                "evidence": "VERIFIED",
                "invariants": {"modulus": modulus, "roots": roots, "target": target},
                "quality": len(rows),
                "quality_metric": "checked-residues",
            }
        ],
        "certificate": normalize_json(certificate.to_dict()),
        "execution_telemetry": ExecutionTelemetry(
            progress_completed=len(rows),
            progress_total=modulus,
        ).to_dict(),
        "outcome": outcome.value,
        "outcome_scope": scope.value,
        "roots": roots,
    }


def verify_reduced_result(task: TaskSpec, result: JSONValue) -> bool:
    """Require independent certificate replay before fleet-level promotion."""

    try:
        from arbogast.cert import certificate_from_dict

        if not isinstance(result, dict):
            return False
        encoded = result.get("certificate")
        if not isinstance(encoded, Mapping):
            return False
        certificate = certificate_from_dict(encoded)
        if not isinstance(certificate, VerificationCertificate):
            return False
        report = verify_residue_square(certificate)
        return (
            report.valid
            and certificate.witness["task_hash"] == task.task_hash
            and result.get("outcome") == Outcome.FOUND.value
            and result.get("outcome_scope") == OutcomeScope.TARGET_GLOBAL.value
        )
    except (KeyError, LookupError, TypeError, ValueError):
        return False


TEMPLATE_OPERATION = FunctionalOperation(
    planner=plan_residues,
    runner=evaluate_residue,
    reducer=reduce_residues,
    verifier=verify_reduced_result,
    closure_verifiers=(VERIFIER,),
)

__all__ = ["TEMPLATE_OPERATION"]
