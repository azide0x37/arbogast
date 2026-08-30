"""Run a certified local/global norm campaign over Q(t)/(t^2-t-1).

The example is intentionally small, but its mathematical boundary is real.  A
quadratic Hilbert-symbol screen is complete for the declared norm problem; only
locally unobstructed targets are sent to a bounded global witness search.  An
unsuccessful bounded search is reported as ``UNKNOWN`` and never closes a target.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path

from arbogast.campaign import (
    Campaign,
    CampaignSpec,
    CampaignTask,
    DerivationRule,
    ExecutionTelemetry,
    Observation,
    Outcome,
    OutcomeScope,
    Strategy,
    TargetLedger,
    TargetSpec,
    TaskProvenance,
    closure_subject,
)
from arbogast.cert import (
    CertificateError,
    CertificateVerificationError,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    certificate_from_dict,
    verifier,
    verify_certificate,
)
from arbogast.export import export_json
from arbogast.fleet import FunctionalOperation, LocalExecutor, ShardSpec, TaskSpec
from arbogast.formats import JSONValue, normalize_json
from arbogast.galois import FieldEmbedding, NumberField

LOCAL_OPERATION = "examples.arithmetic.local_norm_filter.v2"
GLOBAL_OPERATION = "examples.arithmetic.global_norm_aim.v2"
LOCAL_STRATEGY = "quadratic-hilbert-local-filter"
GLOBAL_STRATEGY = "bounded-global-norm-aim"
LOCAL_FACTORY = "examples.antieau-klueners-malle:local-task.v2"
DERIVATION = "locally-unobstructed-to-global-aim.v2"
CAPABILITY = "portable-quadratic-arithmetic"
VERIFIER = "examples.arithmetic.local-global-norm.v2"
SOURCE = "supplied-interview:antieau-klueners-malle-workflow"

FIELD_POLYNOMIAL = (-1, -1, 1)
EXTENSION_SQUARECLASS = 5
KUMMER_GENERATORS = ("extension", "target")
SEARCH_BOUND = 1
TARGETS = (-1, 2, 11)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateVerificationError(f"{name} must be an integer")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CertificateVerificationError(f"{name} must be a nonempty string")
    return value


def golden_field() -> NumberField:
    """Return the pinned golden-ratio field used by every task and verifier."""

    return NumberField(FIELD_POLYNOMIAL, generator_name="t")


def _norm_target(target: int) -> TargetSpec:
    """Return the canonical campaign identity for one exact norm target."""

    return TargetSpec(
        f"golden-norm-{target}",
        {"field_id": golden_field().field_id, "target": target},
        importance=4,
        label=f"Is {target} a norm from Q(t)/(t^2-t-1)?",
        metadata={"extension_squareclass": EXTENSION_SQUARECLASS},
    )


def _prime_factors(value: int) -> tuple[int, ...]:
    remaining = abs(value)
    factors: list[int] = []
    divisor = 2
    while divisor * divisor <= remaining:
        if remaining % divisor == 0:
            factors.append(divisor)
            while remaining % divisor == 0:
                remaining //= divisor
        divisor = 3 if divisor == 2 else divisor + 2
    if remaining > 1:
        factors.append(remaining)
    return tuple(factors)


def relevant_places(target: int) -> tuple[tuple[str, int | None], ...]:
    """Return the complete finite support for the quadratic norm criterion."""

    if target == 0:
        raise ValueError("the norm target must be nonzero")
    odd = sorted(
        prime for prime in set(_prime_factors(EXTENSION_SQUARECLASS * target)) if prime != 2
    )
    return (("real", None), ("q2", 2), *((f"q{prime}", prime) for prime in odd))


def _valuation(value: int, prime: int) -> int:
    if value == 0:
        raise ValueError("Hilbert symbols require nonzero entries")
    exponent = 0
    remaining = abs(value)
    while remaining % prime == 0:
        exponent += 1
        remaining //= prime
    return exponent


def _legendre(unit: int, prime: int) -> int:
    residue = unit % prime
    if residue == 0:
        raise ValueError("Legendre symbol input is not a unit")
    value = pow(residue, (prime - 1) // 2, prime)
    if value == 1:
        return 1
    if value == prime - 1:
        return -1
    raise ArithmeticError("Euler-criterion replay did not produce a sign")


def hilbert_symbol(left: int, right: int, prime: int | None) -> int:
    """Compute ``(left,right)_v`` over Q for the real or a rational finite place."""

    if left == 0 or right == 0:
        raise ValueError("Hilbert symbols require nonzero entries")
    if prime is None:
        return -1 if left < 0 and right < 0 else 1
    alpha = _valuation(left, prime)
    beta = _valuation(right, prime)
    left_unit = left // (prime**alpha)
    right_unit = right // (prime**beta)
    if prime == 2:
        epsilon_left = (left_unit - 1) // 2
        epsilon_right = (right_unit - 1) // 2
        omega_left = (left_unit * left_unit - 1) // 8
        omega_right = (right_unit * right_unit - 1) // 8
        exponent = epsilon_left * epsilon_right + alpha * omega_right + beta * omega_left
        return -1 if exponent % 2 else 1
    exponent = alpha * beta * ((prime - 1) // 2)
    sign = -1 if exponent % 2 else 1
    if beta % 2 and _legendre(left_unit, prime) == -1:
        sign = -sign
    if alpha % 2 and _legendre(right_unit, prime) == -1:
        sign = -sign
    return sign


def _place_payload(label: str, prime: int | None) -> dict[str, JSONValue]:
    return {"label": label, "prime": prime}


def _local_shards(task: TaskSpec) -> tuple[ShardSpec, ...]:
    target = _integer(task.parameters.get("target"), "target")
    shards: list[ShardSpec] = []
    ordinal = 0
    for label, prime in relevant_places(target):
        for generator_index, generator_name in enumerate(KUMMER_GENERATORS):
            shards.append(
                ShardSpec(
                    task.task_hash,
                    f"{ordinal:03d}-{label}-{generator_name}",
                    {
                        "field_id": _string(task.parameters.get("field_id"), "field_id"),
                        "generator_index": generator_index,
                        "generator_name": generator_name,
                        "place": _place_payload(label, prime),
                        "target": target,
                    },
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return tuple(shards)


def plan_local(task: TaskSpec) -> tuple[ShardSpec, ...]:
    return _local_shards(task)


def evaluate_local(task: TaskSpec, shard: ShardSpec) -> dict[str, JSONValue]:
    target = _integer(task.parameters.get("target"), "target")
    payload = shard.payload.to_dict()
    generator_name = _string(payload.get("generator_name"), "generator_name")
    value = EXTENSION_SQUARECLASS if generator_name == "extension" else target
    raw_place = payload.get("place")
    if not isinstance(raw_place, dict):
        raise ValueError("local shard omits its exact place")
    prime = raw_place.get("prime")
    if prime is not None:
        prime = _integer(prime, "prime")
    return {
        "field_id": payload["field_id"],
        "generator_index": payload["generator_index"],
        "generator_name": generator_name,
        "ordinal": shard.ordinal,
        "place": raw_place,
        "shard_key": shard.key,
        "sign": -1 if value < 0 else 1,
        "unit": value if prime is None else value // (prime ** _valuation(value, prime)),
        "valuation": 0 if prime is None else _valuation(value, prime),
        "value": value,
    }


def _expected_local_partials(task: TaskSpec) -> list[JSONValue]:
    return [normalize_json(evaluate_local(task, shard)) for shard in _local_shards(task)]


def _local_rows(target: int) -> list[dict[str, JSONValue]]:
    return [
        {
            "hilbert_symbol": hilbert_symbol(EXTENSION_SQUARECLASS, target, prime),
            "obstructed": hilbert_symbol(EXTENSION_SQUARECLASS, target, prime) == -1,
            "place": _place_payload(label, prime),
        }
        for label, prime in relevant_places(target)
    ]


def _certificate(
    task: TaskSpec,
    *,
    outcome: Outcome,
    scope: OutcomeScope,
    phase: str,
    witness: Mapping[str, object],
) -> VerificationCertificate:
    target_id = _string(task.parameters.get("target_id"), "target_id")
    return VerificationCertificate.create(
        closure_subject(target_id, outcome, scope),
        VERIFIER,
        witness={
            "field_id": golden_field().field_id,
            "field_polynomial": list(FIELD_POLYNOMIAL),
            "outcome": outcome.value,
            "outcome_scope": scope.value,
            "phase": phase,
            "target_id": target_id,
            "task_hash": task.task_hash,
            **witness,
        },
        checks=("pinned-field", "complete-domain", "exact-replay", "outcome-binding"),
        guarantees=("the certificate proves only the outcome and scope named in its subject",),
    )


def reduce_local(task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, JSONValue]:
    expected = _expected_local_partials(task)
    if list(partials) != expected:
        raise ValueError("local reducer rejected missing, duplicate, foreign, or reordered shards")
    target = _integer(task.parameters.get("target"), "target")
    rows = _local_rows(target)
    obstructed = any(row["obstructed"] is True for row in rows)
    outcome = Outcome.PROVED_IMPOSSIBLE if obstructed else Outcome.SEARCH_EXHAUSTED
    scope = OutcomeScope.TARGET_GLOBAL if obstructed else OutcomeScope.TASK_LOCAL
    certificate = _certificate(
        task,
        outcome=outcome,
        scope=scope,
        phase="local",
        witness={
            "complete_place_set": True,
            "extension_squareclass": EXTENSION_SQUARECLASS,
            "kummer_generators": list(KUMMER_GENERATORS),
            "local_rows": rows,
            "shards": expected,
            "target": target,
        },
    )
    return {
        "certificate": normalize_json(certificate.to_dict()),
        "execution_telemetry": ExecutionTelemetry(
            progress_completed=len(expected), progress_total=len(expected)
        ).to_dict(),
        "local_rows": rows,
        "outcome": outcome.value,
        "outcome_scope": scope.value,
        "target": target,
    }


def _candidate_pairs(bound: int) -> tuple[tuple[int, int], ...]:
    if bound < 0:
        raise ValueError("search bound must be nonnegative")
    preferred = ((0, 1),) if bound >= 1 else ()
    remaining = tuple(
        (left, right)
        for left in range(-bound, bound + 1)
        for right in range(-bound, bound + 1)
        if (left, right) not in preferred
    )
    return (*preferred, *remaining)


def plan_global(task: TaskSpec) -> tuple[ShardSpec, ...]:
    bound = _integer(task.parameters.get("search_bound"), "search_bound")
    return tuple(
        ShardSpec(
            task.task_hash,
            f"candidate-{ordinal:03d}",
            {"left": left, "right": right},
            ordinal=ordinal,
        )
        for ordinal, (left, right) in enumerate(_candidate_pairs(bound))
    )


def evaluate_global(task: TaskSpec, shard: ShardSpec) -> dict[str, JSONValue]:
    left = _integer(shard.payload.get("left"), "left")
    right = _integer(shard.payload.get("right"), "right")
    element = golden_field()((left, right))
    norm = element.norm()
    if norm.denominator != 1:
        raise ArithmeticError("integral search unexpectedly produced a fractional norm")
    return {
        "coefficients": [left, right],
        "norm": norm.numerator,
        "ordinal": shard.ordinal,
        "shard_key": shard.key,
    }


def _expected_global_partials(task: TaskSpec) -> list[JSONValue]:
    return [normalize_json(evaluate_global(task, shard)) for shard in plan_global(task)]


def reduce_global(task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, JSONValue]:
    expected = _expected_global_partials(task)
    if list(partials) != expected:
        raise ValueError("global reducer rejected missing, duplicate, foreign, or reordered shards")
    target = _integer(task.parameters.get("target"), "target")
    matches = [row for row in expected if isinstance(row, dict) and row.get("norm") == target]
    common: dict[str, JSONValue] = {
        "execution_telemetry": ExecutionTelemetry(
            progress_completed=len(expected), progress_total=len(expected)
        ).to_dict(),
        "rows": expected,
        "target": target,
    }
    if not matches:
        return {
            **common,
            "outcome": Outcome.UNKNOWN.value,
            "outcome_scope": OutcomeScope.TASK_LOCAL.value,
            "reason": "the declared bounded search found no witness; this is not nonexistence",
        }

    coefficients = matches[0]["coefficients"]
    assert isinstance(coefficients, list)
    left, right = (_integer(value, "witness coefficient") for value in coefficients)
    conjugate = [left + right, -right]
    certificate = _certificate(
        task,
        outcome=Outcome.FOUND,
        scope=OutcomeScope.TARGET_GLOBAL,
        phase="global",
        witness={
            "conjugate_generator_image": [1, -1],
            "conjugate_witness": conjugate,
            "rows": expected,
            "search_bound": _integer(task.parameters.get("search_bound"), "search_bound"),
            "target": target,
            "witness_coefficients": [left, right],
        },
    )
    return {
        **common,
        "candidates": [
            {
                "canonical_key": f"quadratic-norm-witness:{golden_field().field_id}:{target}",
                "canonicalizer": "examples.quadratic-norm-witness.v2",
                "equivalence_scope": "TARGET",
                "evidence": "VERIFIED",
                "invariants": {
                    "coefficients": [left, right],
                    "field_id": golden_field().field_id,
                    "norm": target,
                },
                "quality": len(expected),
                "quality_metric": "bounded-candidates-checked",
            }
        ],
        "certificate": normalize_json(certificate.to_dict()),
        "outcome": Outcome.FOUND.value,
        "outcome_scope": OutcomeScope.TARGET_GLOBAL.value,
        "witness_coefficients": [left, right],
    }


def _verify_common(certificate: VerificationCertificate) -> tuple[dict[str, object], int]:
    witness = certificate.witness.to_dict()
    target_id = _string(witness.get("target_id"), "target_id")
    target = _integer(witness.get("target"), "target")
    outcome = Outcome(_string(witness.get("outcome"), "outcome"))
    scope = OutcomeScope(_string(witness.get("outcome_scope"), "outcome_scope"))
    task_hash = _string(witness.get("task_hash"), "task_hash")
    if len(task_hash) != 64 or any(character not in "0123456789abcdef" for character in task_hash):
        raise CertificateVerificationError("task_hash is not canonical")
    if witness.get("field_polynomial") != list(FIELD_POLYNOMIAL):
        raise CertificateVerificationError("certificate names another defining polynomial")
    if witness.get("field_id") != golden_field().field_id:
        raise CertificateVerificationError("certificate names another pinned field")
    if target_id != _norm_target(target).target_id:
        raise CertificateVerificationError(
            "certificate target_id does not identify its exact integer norm target"
        )
    if certificate.subject != closure_subject(target_id, outcome, scope):
        raise CertificateVerificationError("certificate subject does not bind outcome scope")
    return witness, target


@verifier(VERIFIER, certificate_type=VerificationCertificate)
def verify_norm_campaign(certificate: VerificationCertificate) -> VerificationReport:
    """Replay the complete local screen or exact global norm witness."""

    witness, target = _verify_common(certificate)
    phase = _string(witness.get("phase"), "phase")
    outcome = Outcome(_string(witness.get("outcome"), "outcome"))
    scope = OutcomeScope(_string(witness.get("outcome_scope"), "outcome_scope"))
    if phase == "local":
        expected_rows = _local_rows(target)
        if witness.get("local_rows") != expected_rows:
            raise CertificateVerificationError("local Hilbert table failed exact replay")
        if witness.get("complete_place_set") is not True:
            raise CertificateVerificationError("local certificate does not assert complete support")
        if witness.get("extension_squareclass") != EXTENSION_SQUARECLASS:
            raise CertificateVerificationError("local certificate changed the quadratic extension")
        if witness.get("kummer_generators") != list(KUMMER_GENERATORS):
            raise CertificateVerificationError("local certificate changed the generator order")
        raw_shards = witness.get("shards")
        if not isinstance(raw_shards, list) or len(raw_shards) != 2 * len(expected_rows):
            raise CertificateVerificationError("local certificate has incomplete place shards")
        for ordinal, row in enumerate(raw_shards):
            if not isinstance(row, dict) or row.get("ordinal") != ordinal:
                raise CertificateVerificationError("local shards are missing or reordered")
            place = row.get("place")
            expected_place = expected_rows[ordinal // 2]["place"]
            if place != expected_place or row.get("generator_index") != ordinal % 2:
                raise CertificateVerificationError("local shard has foreign place or generator")
            generator = KUMMER_GENERATORS[ordinal % 2]
            expected_value = EXTENSION_SQUARECLASS if generator == "extension" else target
            if row.get("generator_name") != generator or row.get("value") != expected_value:
                raise CertificateVerificationError("local shard changed its Kummer generator")
        obstructed = any(row["obstructed"] is True for row in expected_rows)
        expected_outcome = Outcome.PROVED_IMPOSSIBLE if obstructed else Outcome.SEARCH_EXHAUSTED
        expected_scope = OutcomeScope.TARGET_GLOBAL if obstructed else OutcomeScope.TASK_LOCAL
        if outcome is not expected_outcome or scope is not expected_scope:
            raise CertificateVerificationError("local result overstates its mathematical scope")
        checks = ("complete-place-support", "quadratic-hilbert-symbols", "outcome-scope")
    elif phase == "global":
        bound = _integer(witness.get("search_bound"), "search_bound")
        expected_rows = [
            {
                "coefficients": [left, right],
                "norm": left * left + left * right - right * right,
                "ordinal": ordinal,
                "shard_key": f"candidate-{ordinal:03d}",
            }
            for ordinal, (left, right) in enumerate(_candidate_pairs(bound))
        ]
        if witness.get("rows") != expected_rows:
            raise CertificateVerificationError("global bounded domain failed exact replay")
        coordinates = witness.get("witness_coefficients")
        conjugate_coordinates = witness.get("conjugate_witness")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or not isinstance(conjugate_coordinates, list)
            or len(conjugate_coordinates) != 2
        ):
            raise CertificateVerificationError("global witness coordinates are malformed")
        left, right = (_integer(value, "witness coefficient") for value in coordinates)
        field = golden_field()
        element = field((left, right))
        if witness.get("conjugate_generator_image") != [1, -1]:
            raise CertificateVerificationError("certificate changed the exact conjugation")
        conjugation = FieldEmbedding(field, field, 1 - field.generator)
        conjugate = conjugation(element)
        if [value.numerator for value in conjugate.coefficients] != conjugate_coordinates:
            raise CertificateVerificationError("conjugate witness failed exact replay")
        if any(value.denominator != 1 for value in conjugate.coefficients):
            raise CertificateVerificationError("conjugate witness is not integral")
        if element * conjugate != field(target) or element.norm() != Fraction(target):
            raise CertificateVerificationError("global witness has the wrong exact norm")
        if outcome is not Outcome.FOUND or scope is not OutcomeScope.TARGET_GLOBAL:
            raise CertificateVerificationError("global witness does not bind exact target closure")
        checks = ("complete-bounded-domain", "explicit-conjugation", "exact-norm")
    else:
        raise CertificateVerificationError("unknown local/global proof phase")

    return VerificationReport(
        valid=True,
        verifier=VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=checks,
        details=FrozenMap({"phase": phase, "target": target}),
    )


def _verify_result(task: TaskSpec, result: JSONValue) -> bool:
    try:
        if not isinstance(result, dict):
            return False
        raw = result.get("certificate")
        if raw is None:
            return result.get("outcome") == Outcome.UNKNOWN.value
        if not isinstance(raw, Mapping):
            return False
        certificate = certificate_from_dict(raw)
        if not isinstance(certificate, VerificationCertificate):
            return False
        report = verify_certificate(certificate)
        return (
            report.valid
            and certificate.witness["task_hash"] == task.task_hash
            and result.get("outcome") == certificate.witness["outcome"]
            and result.get("outcome_scope") == certificate.witness["outcome_scope"]
        )
    except (
        CertificateError,
        CertificateVerificationError,
        KeyError,
        LookupError,
        TypeError,
        ValueError,
    ):
        return False


LOCAL_NORM_OPERATION = FunctionalOperation(
    planner=plan_local,
    runner=evaluate_local,
    reducer=reduce_local,
    verifier=_verify_result,
)
GLOBAL_NORM_OPERATION = FunctionalOperation(
    planner=plan_global,
    runner=evaluate_global,
    reducer=reduce_global,
    verifier=_verify_result,
)


def build_local_task(
    target: TargetSpec,
    provenance: TaskProvenance,
    checkpoint_ref: str | None,
) -> CampaignTask:
    value = _integer(target.parameters.get("target"), "target")
    field = golden_field()
    return CampaignTask(
        TaskSpec(
            operation=LOCAL_OPERATION,
            input_refs=(field.content_id,),
            parameters={
                "field_id": field.field_id,
                "target": value,
                "target_id": target.target_id,
            },
        ),
        target,
        LOCAL_STRATEGY,
        "Run the complete cheap Hilbert-symbol obstruction screen first.",
        provenance=provenance,
        checkpoint_ref=checkpoint_ref,
        capability_requirements=(CAPABILITY,),
        usefulness=8,
        information_gain=8,
        estimated_cost=2 * len(relevant_places(value)),
    )


def derive_global_task(
    observation: Observation,
    ledger: TargetLedger,
) -> tuple[CampaignTask, ...]:
    target = ledger.get(observation.target_id)
    value = _integer(target.parameters.get("target"), "target")
    field = golden_field()
    return (
        CampaignTask(
            TaskSpec(
                operation=GLOBAL_OPERATION,
                input_refs=(field.content_id,),
                parameters={
                    "field_id": field.field_id,
                    "search_bound": SEARCH_BOUND,
                    "target": value,
                    "target_id": target.target_id,
                },
            ),
            target,
            GLOBAL_STRATEGY,
            "Aim for an exact norm witness only after the complete local screen passes.",
            capability_requirements=(CAPABILITY,),
            usefulness=6,
            information_gain=5,
            estimated_cost=len(_candidate_pairs(SEARCH_BOUND)),
        ),
    )


LOCAL_TO_GLOBAL = DerivationRule(
    DERIVATION,
    derive=derive_global_task,
    outcomes=(Outcome.SEARCH_EXHAUSTED,),
    rationale="a verified complete local pass motivates, but does not settle, global aiming",
)


def build_campaign(output: Path) -> Campaign:
    targets = tuple(_norm_target(target) for target in TARGETS)
    strategy = Strategy(
        LOCAL_STRATEGY,
        LOCAL_OPERATION,
        "Run complete local obstructions before any global witness search.",
        capability_requirements=(CAPABILITY,),
        task_factory=build_local_task,
        task_factory_name=LOCAL_FACTORY,
        verify_results=True,
        usefulness=8,
        information_gain=8,
        estimated_cost=6,
    )
    spec = CampaignSpec(
        "antieau-klueners-malle-certified-local-global",
        objective=(
            "Resolve bounded quadratic norm targets with cheap complete local obstructions "
            "followed by provenance-driven exact global aiming."
        ),
        targets=targets,
        strategies=(strategy,),
        derivations=(LOCAL_TO_GLOBAL,),
        metadata={
            "field": "Q(t)/(t^2-t-1)",
            "local_global_boundary": "locally unobstructed is not globally soluble",
            "source": SOURCE,
        },
    )
    return Campaign(
        spec,
        executor=LocalExecutor(output / "artifacts", max_workers=4),
        operations={LOCAL_OPERATION: LOCAL_NORM_OPERATION, GLOBAL_OPERATION: GLOBAL_NORM_OPERATION},
        derivations=(LOCAL_TO_GLOBAL,),
        capabilities=(CAPABILITY,),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="campaign state directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    campaign = build_campaign(args.output)
    observations = campaign.run()

    results = tuple((item, item.details.to_dict().get("result")) for item in observations)
    local = [
        item for item, result in results if isinstance(result, dict) and "local_rows" in result
    ]
    global_aims = [
        item
        for item, result in results
        if isinstance(result, dict) and "rows" in result and "local_rows" not in result
    ]
    if len(local) != 3 or len(global_aims) != 2:
        raise RuntimeError("campaign did not preserve the expected local/global task boundary")
    outcomes_by_target = {
        campaign.ledger.get(item.target_id).parameters["target"]: item for item in observations
    }
    if outcomes_by_target[2].outcome is not Outcome.PROVED_IMPOSSIBLE:
        raise RuntimeError("target 2 should close from its Q_2 obstruction")
    if (
        campaign.ledger.status(
            next(target for target in campaign.targets if target.parameters["target"] == -1)
        ).mathematical_outcome.value
        != Outcome.FOUND.value
    ):
        raise RuntimeError("target -1 should close with the exact witness t")
    target_11 = next(target for target in campaign.targets if target.parameters["target"] == 11)
    if not campaign.ledger.status(target_11).open:
        raise RuntimeError("failed bounded search for 11 must remain globally open")

    snapshot = campaign.save(args.output / "campaign.json")
    (args.output / "claims.json").write_text(
        export_json(campaign.export_claims(), pretty=True), encoding="utf-8"
    )
    replayed = Campaign.load(
        snapshot,
        executor=LocalExecutor(args.output / "replay-artifacts", max_workers=2),
        operations={LOCAL_OPERATION: LOCAL_NORM_OPERATION, GLOBAL_OPERATION: GLOBAL_NORM_OPERATION},
        task_factories={LOCAL_FACTORY: build_local_task},
        derivations=(LOCAL_TO_GLOBAL,),
        capabilities=(CAPABILITY,),
    )
    if replayed.export_claims() != campaign.export_claims():
        raise RuntimeError("campaign claim graph changed during fresh state replay")
    status = replayed.status()
    if (status.closed_targets, status.open_targets) != (2, 1):
        raise RuntimeError("campaign replay changed the exact target boundary")

    witness = next(
        item
        for item in observations
        if item.outcome is Outcome.FOUND and item.outcome_scope is OutcomeScope.TARGET_GLOBAL
    )
    witness_result = witness.details["result"]
    print(f"field: {golden_field().field_id}")
    print("local targets checked: 3")
    print("global follow-up tasks: 2")
    print("target 2: PROVED_IMPOSSIBLE at Q_2")
    print(f"target -1: FOUND witness {witness_result['witness_coefficients']}")
    print("target 11: UNKNOWN after a complete bounded search (non-closing)")
    print(f"claim graph: {len(replayed.claims)} nodes")
    print(f"status: closed={status.closed_targets}, open={status.open_targets}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
