"""Central v1 certificate path for pinned-PARI arithmetic completeness.

Unlike a discovery receipt, this verifier reruns the named closed operation in
a fresh hardened GP process and compares the complete normalized payload.  The
witness contains data, never executable GP source.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any, cast

from arbogast.cert import (
    CertificateError,
    DiscoveryReceipt,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    content_address,
    freeze_mapping,
    verifier,
)
from arbogast.cert.registry import CertificateVerificationError
from arbogast.claims import ClaimKind, claim_boundary_hash

from .pari_results import (
    PariCompleteness,
    PariOutcome,
    PariVerificationRequirement,
    _pari_claim_id,
    _pari_hypotheses,
    _pari_statement,
    _pari_status,
)

PARI_VERIFIER_ID = "arbogast.backends.pari.v1"
PARI_WITNESS_SCHEMA = "arbogast.pari.verification-witness.v1"
PARI_OPERATIONAL_VERIFIER_ID = "arbogast.backends.pari.operational.v1"
PARI_OPERATIONAL_WITNESS_SCHEMA = "arbogast.pari.operational-witness.v1"
_CHECKS = (
    "closed operation reconstructed from canonical data",
    "fresh GP process used with startup files ignored",
    "normalized backend version matched",
    "request identity and deterministic seed matched",
    "complete mathematical payload matched exactly",
)
_GUARANTEES = (
    "payload was reproduced by the pinned PARI verifier",
    "assumptions and completeness remain separate caller-visible axes",
)
_OPERATIONAL_CHECKS = (
    "non-success outcome remains non-closing",
    "request identity and resource budget are content-bound",
    "discovery receipt integrity replayed",
    "no arithmetic completeness evidence is asserted",
)
_OPERATIONAL_GUARANTEES = (
    "the recorded PARI operation exhausted or failed within the stated operational boundary",
    "no arithmetic candidate is promoted to a mathematical conclusion",
)


def pari_payload_id(payload: Mapping[str, object]) -> str:
    """Return the canonical ID used in PARI certificate subjects and witnesses."""

    return content_address(payload)


def create_pari_verification_certificate(
    operation: str,
    *,
    replay: Mapping[str, object],
    expected_payload: Mapping[str, object],
    backend_version: str,
    request_id: str,
    deterministic_seed: int,
    proof_mode: str,
    limits: Mapping[str, object],
    completeness: str = PariCompleteness.COMPLETE.value,
) -> VerificationCertificate:
    """Create central verification evidence for one already-run closed operation."""

    from .pari import PARI_SUPPORTED_RANGE, PARI_TEMPLATE_VERSION
    from .pari_protocol import RESPONSE_SCHEMA

    if proof_mode not in {"unconditional", "grh-conditional"}:
        raise ValueError("unsupported PARI proof mode")
    try:
        completeness_value = PariCompleteness(completeness)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported PARI completeness value") from exc
    expected_id = pari_payload_id(expected_payload)
    assumptions = ("GRH",) if proof_mode == "grh-conditional" else ()
    requirement = PariVerificationRequirement.pari(backend_version)
    claim_id = _pari_claim_id(operation, expected_payload)
    statement = _pari_statement(
        operation,
        expected_payload,
        completeness_value,
        PariOutcome.SUCCESS,
    )
    status = _pari_status(assumptions, PariOutcome.SUCCESS, requirement)
    hypotheses = _pari_hypotheses(assumptions)
    witness = {
        "backend_version": backend_version,
        "completeness": completeness_value.value,
        "deterministic_seed": deterministic_seed,
        "expected_payload": dict(expected_payload),
        "expected_payload_id": expected_id,
        "limits": dict(limits),
        "operation": operation,
        "proof_mode": proof_mode,
        "protocol": RESPONSE_SCHEMA,
        "replay": dict(replay),
        "request_id": request_id,
        "schema": PARI_WITNESS_SCHEMA,
        "supported_range": PARI_SUPPORTED_RANGE,
        "template": PARI_TEMPLATE_VERSION,
    }
    return VerificationCertificate.create(
        f"pari:{operation}:{expected_id}",
        PARI_VERIFIER_ID,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=status,
            hypotheses=hypotheses,
        ),
        witness=witness,
        checks=_CHECKS,
        guarantees=_GUARANTEES,
    )


def create_pari_operational_certificate(
    operation: str,
    *,
    payload: Mapping[str, object],
    receipt: DiscoveryReceipt,
    outcome: PariOutcome,
) -> VerificationCertificate:
    """Certify only a non-closing operational outcome, never arithmetic truth."""

    if outcome is PariOutcome.SUCCESS:
        raise ValueError("successful PARI arithmetic needs the proving certificate path")
    payload_id = content_address(payload)
    claim_id = _pari_claim_id(operation, payload)
    statement = _pari_statement(
        operation,
        payload,
        PariCompleteness.CANDIDATE,
        outcome,
    )
    status = _pari_status((), outcome, None)
    witness = {
        "operation": operation,
        "outcome": outcome.value,
        "payload": dict(payload),
        "payload_id": payload_id,
        "receipt": receipt.to_dict(),
        "schema": PARI_OPERATIONAL_WITNESS_SCHEMA,
    }
    return VerificationCertificate.create(
        f"pari:operational:{operation}:{payload_id}",
        PARI_OPERATIONAL_VERIFIER_ID,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=status,
        ),
        witness=witness,
        checks=_OPERATIONAL_CHECKS,
        guarantees=_OPERATIONAL_GUARANTEES,
    )


@verifier(PARI_VERIFIER_ID, certificate_type=VerificationCertificate)
def verify_pari_certificate(certificate: VerificationCertificate) -> VerificationReport:
    """Rerun a strict closed operation and compare its entire normalized payload."""

    from .pari import (
        PARI_SUPPORTED_RANGE,
        PARI_TEMPLATE_VERSION,
        PariBackend,
        normalize_pari_version,
    )
    from .pari_protocol import RESPONSE_SCHEMA

    witness = certificate.witness.to_dict()
    expected_keys = {
        "backend_version",
        "completeness",
        "deterministic_seed",
        "expected_payload",
        "expected_payload_id",
        "limits",
        "operation",
        "proof_mode",
        "protocol",
        "replay",
        "request_id",
        "schema",
        "supported_range",
        "template",
    }
    _keys(witness, expected_keys, "PARI certificate witness")
    if witness["schema"] != PARI_WITNESS_SCHEMA:
        raise CertificateVerificationError("unsupported PARI witness schema")
    if witness["protocol"] != RESPONSE_SCHEMA:
        raise CertificateVerificationError("PARI witness protocol changed")
    if witness["template"] != PARI_TEMPLATE_VERSION:
        raise CertificateVerificationError("PARI witness template changed")
    if witness["supported_range"] != PARI_SUPPORTED_RANGE:
        raise CertificateVerificationError("PARI witness supported range changed")
    operation = _string(witness["operation"], "operation")
    version = _string(witness["backend_version"], "backend version")
    if normalize_pari_version(version) != version:
        raise CertificateVerificationError("PARI witness backend version is not normalized")
    proof_mode = _string(witness["proof_mode"], "proof mode")
    if proof_mode not in {"unconditional", "grh-conditional"}:
        raise CertificateVerificationError("PARI witness has an invalid proof mode")
    expected = _mapping(witness["expected_payload"], "expected payload")
    expected_id = _string(witness["expected_payload_id"], "expected payload ID")
    if content_address(expected) != expected_id:
        raise CertificateVerificationError("PARI expected payload ID does not match its payload")
    if certificate.subject != f"pari:{operation}:{expected_id}":
        raise CertificateVerificationError("PARI certificate subject is not payload-bound")
    if certificate.checks != _CHECKS:
        raise CertificateVerificationError("PARI certificate omitted required replay checks")
    if certificate.guarantees != _GUARANTEES:
        raise CertificateVerificationError("PARI certificate guarantees changed")
    if certificate.dependencies or certificate.claim_dependencies:
        raise CertificateVerificationError("PARI certificate introduced foreign dependencies")
    try:
        completeness = PariCompleteness(_string(witness["completeness"], "completeness"))
    except ValueError as exc:
        raise CertificateVerificationError("PARI witness has invalid completeness") from exc
    assumptions = ("GRH",) if proof_mode == "grh-conditional" else ()
    requirement = PariVerificationRequirement.pari(version)
    claim_id = _pari_claim_id(operation, expected)
    statement = _pari_statement(operation, expected, completeness, PariOutcome.SUCCESS)
    status = _pari_status(assumptions, PariOutcome.SUCCESS, requirement)
    hypotheses = _pari_hypotheses(assumptions)
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=status,
        hypotheses=hypotheses,
    )
    if (
        certificate.claim_id != claim_id
        or certificate.statement_hash != statement.statement_hash
        or certificate.claim_boundary_hash != expected_boundary
    ):
        raise CertificateVerificationError("PARI certificate claim envelope changed")
    limits = _limits(_mapping(witness["limits"], "limits"))
    replay = _mapping(witness["replay"], "replay")
    # Canonical identities are checked before any external process is located
    # or spawned.  A matching attacker-controlled payload is not evidence that
    # it names the same pinned field, element, or place presentation.
    _preflight_replay(operation, replay)
    backend = PariBackend(**cast(Any, limits))
    probe = backend.probe()
    if not probe.status.available or probe.normalized_version != version:
        found = probe.normalized_version or "unavailable"
        raise CertificateVerificationError(
            f"pinned PARI version mismatch: certificate requires {version}, found {found}"
        )
    actual = _replay(backend, operation, replay, proof_mode)
    actual_payload = actual.payload.to_dict()
    if content_address(actual_payload) != expected_id or actual_payload != expected:
        raise CertificateVerificationError("fresh PARI replay payload did not match")
    request_id = _string(witness["request_id"], "request ID")
    request_from_receipt = actual.receipt.inputs.to_dict().get("request")
    if request_from_receipt != request_id:
        raise CertificateVerificationError("fresh PARI replay request ID did not match")
    seed = _positive_int(witness["deterministic_seed"], "deterministic seed")
    replay_seed = actual.receipt.parameters.to_dict().get("deterministic_seed")
    if replay_seed != seed:
        raise CertificateVerificationError("fresh PARI deterministic seed did not match")
    return VerificationReport(
        valid=True,
        verifier=PARI_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_CHECKS,
        details=freeze_mapping(
            {
                "backend_version": version,
                "expected_payload_id": expected_id,
                "operation": operation,
                "proof_mode": proof_mode,
                "request_id": request_id,
            }
        ),
    )


@verifier(PARI_OPERATIONAL_VERIFIER_ID, certificate_type=VerificationCertificate)
def verify_pari_operational_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    """Replay a non-closing process outcome without asserting arithmetic truth."""

    from .pari import (
        PARI_EXCLUSIVE_MAXIMUM_VERSION,
        PARI_MINIMUM_VERSION,
        PARI_SUPPORTED_RANGE,
        PARI_TEMPLATE_VERSION,
        normalize_pari_version,
    )
    from .pari_protocol import RESPONSE_SCHEMA

    witness = certificate.witness.to_dict()
    _keys(
        witness,
        {"operation", "outcome", "payload", "payload_id", "receipt", "schema"},
        "PARI operational witness",
    )
    if witness["schema"] != PARI_OPERATIONAL_WITNESS_SCHEMA:
        raise CertificateVerificationError("unsupported PARI operational witness schema")
    operation = _string(witness["operation"], "operation")
    try:
        outcome = PariOutcome(_string(witness["outcome"], "outcome"))
    except ValueError as exc:
        raise CertificateVerificationError("invalid PARI operational outcome") from exc
    if outcome is PariOutcome.SUCCESS:
        raise CertificateVerificationError("success cannot use an operational certificate")
    payload = _mapping(witness["payload"], "operational payload")
    payload_id = _string(witness["payload_id"], "operational payload ID")
    if content_address(payload) != payload_id:
        raise CertificateVerificationError("PARI operational payload ID does not match")
    _keys(
        payload,
        {"budget", "field_id", "reason", "request", "request_id"},
        "PARI operational payload",
    )
    if payload["reason"] != "PARI certification exceeded its resource budget":
        raise CertificateVerificationError("PARI operational reason changed")
    request = _mapping(payload["request"], "PARI operational request")
    _keys(
        request,
        {"field", "inputs", "operation", "parameters", "protocol", "template"},
        "PARI operational request",
    )
    if (
        request["operation"] != operation
        or request["protocol"] != RESPONSE_SCHEMA
        or request["template"] != PARI_TEMPLATE_VERSION
        or request["field"] != payload["field_id"]
    ):
        raise CertificateVerificationError("PARI operational request boundary changed")
    request_id = _string(payload["request_id"], "request ID")
    if content_address(request) != request_id:
        raise CertificateVerificationError("PARI operational request ID does not match")
    budget = _mapping(payload["budget"], "PARI operational budget")
    _keys(budget, {"timeout_seconds"}, "PARI operational budget")
    timeout = _positive_decimal(budget["timeout_seconds"], "operational timeout")
    del timeout
    raw_receipt = _mapping(witness["receipt"], "operational receipt")
    try:
        receipt = DiscoveryReceipt.from_dict(raw_receipt)
    except CertificateError as exc:
        raise CertificateVerificationError("invalid PARI operational receipt") from exc
    if receipt.operation != f"backends.pari.{operation}" or receipt.backend != "pari":
        raise CertificateVerificationError("PARI operational receipt names a different operation")
    if (
        receipt.backend_version is None
        or normalize_pari_version(receipt.backend_version) != receipt.backend_version
    ):
        raise CertificateVerificationError("PARI operational receipt version is not normalized")
    version_tuple = tuple(int(part) for part in receipt.backend_version.split("."))
    if not PARI_MINIMUM_VERSION <= version_tuple < PARI_EXCLUSIVE_MAXIMUM_VERSION:
        raise CertificateVerificationError("PARI operational receipt version is unsupported")
    receipt_inputs = receipt.inputs.to_dict()
    expected_inputs = {
        "field": request["field"],
        **_mapping(request["inputs"], "request inputs"),
        "request": request_id,
    }
    if receipt_inputs != expected_inputs:
        raise CertificateVerificationError("PARI operational receipt inputs changed")
    seed = int(request_id.split(":", 1)[1][:15], 16) + 1
    expected_parameters = {
        **_mapping(request["parameters"], "request parameters"),
        "assumptions": [],
        "completeness": PariCompleteness.CANDIDATE.value,
        "deterministic_seed": seed,
        "protocol": RESPONSE_SCHEMA,
        "supported_range": PARI_SUPPORTED_RANGE,
        "template": PARI_TEMPLATE_VERSION,
        "timeout_seconds": budget["timeout_seconds"],
    }
    if receipt.parameters.to_dict() != expected_parameters:
        raise CertificateVerificationError("PARI operational receipt parameters changed")
    expected_result = {"outcome": outcome.value, "payload": payload_id}
    if (
        receipt.result.to_dict() != expected_result
        or receipt.artifacts
        or receipt.notes
        != ("certification timeout is non-closing; no GRH assumption was inferred",)
    ):
        raise CertificateVerificationError("PARI operational receipt result changed")
    if certificate.subject != f"pari:operational:{operation}:{payload_id}":
        raise CertificateVerificationError("PARI operational subject changed")
    if certificate.checks != _OPERATIONAL_CHECKS:
        raise CertificateVerificationError("PARI operational checks changed")
    if certificate.guarantees != _OPERATIONAL_GUARANTEES:
        raise CertificateVerificationError("PARI operational guarantees changed")
    if certificate.dependencies or certificate.claim_dependencies:
        raise CertificateVerificationError("PARI operational certificate has foreign dependencies")
    claim_id = _pari_claim_id(operation, payload)
    statement = _pari_statement(
        operation,
        payload,
        PariCompleteness.CANDIDATE,
        outcome,
    )
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=_pari_status((), outcome, None),
    )
    if (
        certificate.claim_id != claim_id
        or certificate.statement_hash != statement.statement_hash
        or certificate.claim_boundary_hash != expected_boundary
    ):
        raise CertificateVerificationError("PARI operational claim envelope changed")
    return VerificationReport(
        valid=True,
        verifier=PARI_OPERATIONAL_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_OPERATIONAL_CHECKS,
        details=freeze_mapping(
            {
                "operation": operation,
                "outcome": outcome.value,
                "payload_id": payload_id,
                "request_id": request_id,
            }
        ),
    )


def _replay(
    backend: Any,
    operation: str,
    replay: Mapping[str, object],
    proof_mode: str,
) -> Any:
    _keys(replay, {"arguments", "field"}, "PARI replay")
    field_spec = _mapping(replay["field"], "field replay")
    field = _replay_field(field_spec)
    arguments = _mapping(replay["arguments"], "operation arguments")
    allow_grh = proof_mode == "grh-conditional"
    if operation == "field_invariants":
        _keys(arguments, set(), "field-invariants arguments")
        return backend.field_invariants(field)
    if operation == "prime_decomposition":
        _keys(arguments, {"rational_prime"}, "prime-decomposition arguments")
        return backend.prime_decomposition(
            field, _positive_int(arguments["rational_prime"], "rational prime")
        )
    if operation == "complex_root_isolation":
        _keys(arguments, {"embedding_index", "max_bits"}, "complex-isolation arguments")
        return backend.complex_root_isolation(
            field,
            _nonnegative_int(arguments["embedding_index"], "embedding index"),
            max_bits=_positive_int(arguments["max_bits"], "maximum isolation bits"),
        )
    if operation == "s_unit_squareclasses":
        _keys(arguments, {"places"}, "S-unit arguments")
        places = tuple(
            _replay_place(field, _mapping(item, "finite place"))
            for item in _sequence(arguments["places"], "finite places")
        )
        return backend.s_unit_squareclasses(field, places, allow_grh=allow_grh)
    if operation == "class_group_2_torsion":
        _keys(arguments, set(), "class-group arguments")
        return backend.class_group_2_torsion(field, allow_grh=allow_grh)
    if operation == "local_squareclasses":
        _keys(
            arguments,
            {"max_candidates", "place", "search_bound"},
            "local-squareclass arguments",
        )
        return backend.local_squareclasses(
            field,
            _replay_place(field, _mapping(arguments["place"], "finite place")),
            search_bound=_positive_int(arguments["search_bound"], "search bound"),
            max_candidates=_positive_int(arguments["max_candidates"], "max candidates"),
        )
    if operation == "localization_matrix":
        _keys(
            arguments,
            {"generators", "max_candidates", "place", "search_bound"},
            "localization arguments",
        )
        generators = tuple(
            _replay_element(field, _mapping(item, "generator"))
            for item in _sequence(arguments["generators"], "generators")
        )
        return backend.localization_matrix(
            field,
            generators,
            _replay_place(field, _mapping(arguments["place"], "finite place")),
            search_bound=_positive_int(arguments["search_bound"], "search bound"),
            max_candidates=_positive_int(arguments["max_candidates"], "max candidates"),
        )
    if operation == "relative_norm":
        _keys(arguments, {"element"}, "relative-norm arguments")
        return backend.relative_norm(
            field, _replay_element(field, _mapping(arguments["element"], "element"))
        )
    if operation == "quadratic_hilbert_pairing":
        _keys(arguments, {"left", "place", "right"}, "Hilbert-pairing arguments")
        raw_place = arguments["place"]
        place = (
            None
            if raw_place is None
            else _replay_place(field, _mapping(raw_place, "Hilbert place"))
        )
        return backend.quadratic_hilbert_pairing(
            field,
            _replay_element(field, _mapping(arguments["left"], "left element")),
            _replay_element(field, _mapping(arguments["right"], "right element")),
            place,
        )
    raise CertificateVerificationError(f"unsupported closed PARI operation: {operation}")


class _ReplayPreflightBackend:
    """Consume decoded arguments without crossing the external boundary."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *_args, **_kwargs: None


def _preflight_replay(operation: str, replay: Mapping[str, object]) -> None:
    _replay(_ReplayPreflightBackend(), operation, replay, "unconditional")


def _replay_field(value: Mapping[str, object]) -> object:
    _keys(
        value,
        {"defining_polynomial", "field_id", "identity", "integral_basis"},
        "field replay",
    )
    polynomial = _rational_data(value["defining_polynomial"], "defining polynomial")
    field_id = _string(value["field_id"], "field ID")
    identity = _identity(value["identity"], field_id, "field identity")
    basis = value["integral_basis"]
    if basis is None:
        # Raw coefficient-vector calls have a deterministic ID; require it to
        # agree rather than smuggling an arbitrary identity into replay.
        expected_identity = {
            "defining_polynomial": [list(pair) for pair in polynomial],
            "type": "arbogast.pari.raw-number-field/v1",
        }
        if identity != expected_identity:
            raise CertificateVerificationError("raw field identity does not match replay data")
        return SimpleNamespace(
            _arbogast_canonical_identity=identity,
            defining_polynomial=polynomial,
            field_id=field_id,
            integral_basis=None,
        )
    rows = _sequence(basis, "integral basis")
    integral_basis = tuple(_rational_data(row, "integral basis row") for row in rows)
    expected_keys = {
        "defining_polynomial",
        "integral_basis",
        "irreducibility_requirement",
        "irreducibility_witness",
        "type",
    }
    if identity.get("type") != "arbogast.number_field" or set(identity) != expected_keys:
        raise CertificateVerificationError("canonical field identity has an unsupported shape")
    integral_polynomial = _integral_rationals(polynomial, "canonical defining polynomial")
    if identity["defining_polynomial"] != list(integral_polynomial):
        raise CertificateVerificationError("field identity polynomial does not match replay data")
    canonical_basis = [[list(pair) for pair in row] for row in integral_basis]
    if identity["integral_basis"] != canonical_basis:
        raise CertificateVerificationError("field identity basis does not match replay data")
    return SimpleNamespace(
        _arbogast_canonical_identity=identity,
        defining_polynomial=polynomial,
        integral_basis=integral_basis,
        field_id=field_id,
    )


def _replay_element(field: object, value: Mapping[str, object]) -> object:
    _keys(value, {"coefficients", "element_id", "identity"}, "element replay")
    coefficients = _rational_data(value["coefficients"], "element coefficients")
    element_id = _string(value["element_id"], "element ID")
    identity = _identity(value["identity"], element_id, "element identity")
    if set(identity) != {"coefficients", "field_id", "type"} or identity.get("type") not in {
        "arbogast.number_field_element",
        "arbogast.pari.raw-number-field-element/v1",
    }:
        raise CertificateVerificationError("element identity has an unsupported shape")
    field_id = getattr(field, "field_id", None)
    if identity["field_id"] != field_id:
        raise CertificateVerificationError("element identity names a different field")
    if identity["coefficients"] != [list(pair) for pair in coefficients]:
        raise CertificateVerificationError("element identity coefficients do not match replay data")
    return SimpleNamespace(
        _arbogast_canonical_identity=identity,
        coefficients=coefficients,
        element_id=element_id,
        field=field,
    )


def _replay_place(field: object, value: Mapping[str, object]) -> object:
    kind = value.get("kind")
    if kind in {"real", "complex"}:
        _keys(
            value,
            {"embedding_index", "identity", "isolation", "kind", "place_id"},
            "infinite-place replay",
        )
        place_id = _string(value["place_id"], "place ID")
        identity = _identity(value["identity"], place_id, "infinite-place identity")
        isolation = _rational_data(value["isolation"], "place isolation")
        embedding_index = _nonnegative_int(value["embedding_index"], "embedding index")
        expected_keys = {
            "embedding_index",
            "field_id",
            "isolation",
            "kind",
            "type",
            "verification_requirement",
        }
        if identity.get("type") != "arbogast.infinite_place" or set(identity) != expected_keys:
            raise CertificateVerificationError("infinite-place identity has an unsupported shape")
        if (
            identity["field_id"] != getattr(field, "field_id", None)
            or identity["kind"] != kind
            or identity["isolation"] != [list(pair) for pair in isolation]
            or identity["embedding_index"] != embedding_index
        ):
            raise CertificateVerificationError("infinite-place identity does not match replay data")
        return SimpleNamespace(
            _arbogast_canonical_identity=identity,
            embedding_index=embedding_index,
            field=field,
            isolation=isolation,
            kind=kind,
            place_id=place_id,
        )
    _keys(
        value,
        {
            "ideal_hnf",
            "identity",
            "place_id",
            "ramification_index",
            "rational_prime",
            "residue_degree",
        },
        "finite-place replay",
    )
    place_id = _string(value["place_id"], "place ID")
    identity = _identity(value["identity"], place_id, "finite-place identity")
    rational_prime = _positive_int(value["rational_prime"], "rational prime")
    ideal_hnf = value["ideal_hnf"]
    if ideal_hnf is None:
        if value["ramification_index"] is not None or value["residue_degree"] is not None:
            raise CertificateVerificationError("finite-place selector cannot declare e or f")
        expected_identity = {
            "field_id": getattr(field, "field_id", None),
            "rational_prime": rational_prime,
            "selection": "unique-prime-above",
            "type": "arbogast.pari.finite-place-selector/v1",
        }
        if identity != expected_identity:
            raise CertificateVerificationError("finite-place selector identity does not match")
        return _positive_int(value["rational_prime"], "rational prime")
    rows = _sequence(ideal_hnf, "ideal HNF")
    normalized_hnf = tuple(
        tuple(_integer(item, "ideal HNF entry") for item in _sequence(row, "ideal HNF row"))
        for row in rows
    )
    ramification_index = _positive_int(value["ramification_index"], "ramification index")
    residue_degree = _positive_int(value["residue_degree"], "residue degree")
    expected_keys = {
        "field_id",
        "ideal_hnf",
        "ramification_index",
        "rational_prime",
        "residue_degree",
        "residue_field_witness",
        "type",
        "verification_requirement",
    }
    if identity.get("type") != "arbogast.finite_place" or set(identity) != expected_keys:
        raise CertificateVerificationError("finite-place identity has an unsupported shape")
    if (
        identity["field_id"] != getattr(field, "field_id", None)
        or identity["rational_prime"] != rational_prime
        or identity["ideal_hnf"] != [list(row) for row in normalized_hnf]
        or identity["ramification_index"] != ramification_index
        or identity["residue_degree"] != residue_degree
    ):
        raise CertificateVerificationError("finite-place identity does not match replay data")
    return SimpleNamespace(
        _arbogast_canonical_identity=identity,
        field=field,
        ideal_hnf=normalized_hnf,
        place_id=place_id,
        ramification_index=ramification_index,
        rational_prime=rational_prime,
        residue_degree=residue_degree,
    )


def _limits(value: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "certification_timeout_seconds",
        "cpu_limit_seconds",
        "memory_limit_bytes",
        "output_limit_bytes",
        "pari_stack_bytes",
        "timeout_seconds",
    }
    _keys(value, expected, "PARI limits")
    return {
        "certification_timeout_seconds": _positive_decimal(
            value["certification_timeout_seconds"], "certification timeout"
        ),
        "cpu_limit_seconds": _positive_int(value["cpu_limit_seconds"], "CPU limit"),
        "memory_limit_bytes": _positive_int(value["memory_limit_bytes"], "memory limit"),
        "output_limit_bytes": _positive_int(value["output_limit_bytes"], "output limit"),
        "pari_stack_bytes": _positive_int(value["pari_stack_bytes"], "PARI stack"),
        "timeout_seconds": _positive_decimal(value["timeout_seconds"], "timeout"),
    }


def _identity(value: object, claimed_id: str, name: str) -> dict[str, object]:
    identity = _mapping(value, name)
    if content_address(identity) != claimed_id:
        raise CertificateVerificationError(f"{name} does not match its claimed canonical ID")
    return identity


def _integral_rationals(
    value: tuple[tuple[int, int], ...],
    name: str,
) -> tuple[int, ...]:
    if any(denominator != 1 for _, denominator in value):
        raise CertificateVerificationError(f"{name} must have integer coefficients")
    return tuple(numerator for numerator, _ in value)


def _rational_data(value: object, name: str) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for raw in _sequence(value, name):
        pair = _sequence(raw, name)
        if len(pair) != 2:
            raise CertificateVerificationError(f"{name} contains a malformed rational pair")
        numerator = _integer(pair[0], name)
        denominator = _positive_int(pair[1], name)
        result.append((numerator, denominator))
    return tuple(result)


def _positive_decimal(value: object, name: str) -> float:
    text = _string(value, name)
    try:
        parsed = float(text)
    except ValueError as exc:
        raise CertificateVerificationError(f"{name} is not decimal") from exc
    if not math.isfinite(parsed) or parsed <= 0 or format(parsed, ".17g") != text:
        raise CertificateVerificationError(f"{name} is not a canonical positive decimal")
    return parsed


def _keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise CertificateVerificationError(f"{name} has missing or foreign fields")


def _mapping(value: object, name: str) -> dict[str, object]:
    if isinstance(value, FrozenMap):
        return value.to_dict()
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CertificateVerificationError(f"{name} must be a string-keyed mapping")
    return cast(dict[str, object], dict(value))


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CertificateVerificationError(f"{name} must be a sequence")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CertificateVerificationError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateVerificationError(f"{name} must be an integer")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _integer(value, name)
    if result <= 0:
        raise CertificateVerificationError(f"{name} must be positive")
    return result


def _nonnegative_int(value: object, name: str) -> int:
    result = _integer(value, name)
    if result < 0:
        raise CertificateVerificationError(f"{name} must be nonnegative")
    return result


__all__ = [
    "PARI_OPERATIONAL_VERIFIER_ID",
    "PARI_OPERATIONAL_WITNESS_SCHEMA",
    "PARI_VERIFIER_ID",
    "PARI_WITNESS_SCHEMA",
    "create_pari_operational_certificate",
    "create_pari_verification_certificate",
    "pari_payload_id",
    "verify_pari_certificate",
    "verify_pari_operational_certificate",
]
