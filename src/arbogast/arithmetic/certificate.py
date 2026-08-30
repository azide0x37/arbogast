"""Portable finite witnesses for the arithmetic layer.

The arithmetic objects in :mod:`arbogast.arithmetic` retain rich Python
objects (number fields, places, and Kummer spaces).  The receipt below is the
narrow proof boundary: it contains only canonical integers, labels, and
prime-field matrices.  Replaying a receipt therefore never requires PARI or a
live arithmetic backend.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from fractions import Fraction
from typing import ClassVar

from arbogast.cert import (
    CertificateError,
    CertificateLayer,
    ContentAddressedCertificate,
    FrozenMap,
    VerificationCertificate,
    content_address,
    default_verifiers,
    freeze_mapping,
)
from arbogast.core import ValidationError, VerificationError
from arbogast.formats import (
    AIM_RECEIPT_SCHEMA,
    CARTIER_DUAL_RECEIPT_SCHEMA,
    DESCENT_RECEIPT_SCHEMA,
    DUAL_SELMER_RECEIPT_SCHEMA,
    LOCAL_CONDITION_RECEIPT_SCHEMA,
    LOCAL_PAIRING_RECEIPT_SCHEMA,
    SELMER_RECEIPT_SCHEMA,
)
from arbogast.galois.certificate import (
    SUPPLIED_PRESENTATION_WITNESS_SCHEMA,
    KummerReceipt,
    LocalH1Receipt,
    LocalizationReceipt,
    relevant_places_complete,
)
from arbogast.galois.proof import (
    Completeness,
    ProofContext,
    VerificationRequirement,
    VerifierTrust,
)
from arbogast.linalg import (
    DenseMatrix,
    LinearSubspace,
    PrimeField,
    inverse,
    nullspace,
    rank,
    solve,
)


class ArithmeticError(ValueError):
    """Base class for invalid certified-arithmetic requests."""


class ArithmeticVerificationError(ArithmeticError, VerificationError):
    """Raised when an arithmetic witness fails independent finite replay."""


class UnsupportedArithmeticOperation(ArithmeticError, NotImplementedError):
    """Typed boundary for arithmetic intentionally outside the 0.2 slice."""


RECEIPT_SCHEMAS: dict[str, str] = {
    "aim-affine": AIM_RECEIPT_SCHEMA,
    "aim-obstruction": AIM_RECEIPT_SCHEMA,
    "cartier-dual": CARTIER_DUAL_RECEIPT_SCHEMA,
    "descent-obstructed": DESCENT_RECEIPT_SCHEMA,
    "descent-realized": DESCENT_RECEIPT_SCHEMA,
    "descent-unknown": DESCENT_RECEIPT_SCHEMA,
    "dual-selmer": DUAL_SELMER_RECEIPT_SCHEMA,
    "local-condition": LOCAL_CONDITION_RECEIPT_SCHEMA,
    "local-pairing": LOCAL_PAIRING_RECEIPT_SCHEMA,
    "selmer-group": SELMER_RECEIPT_SCHEMA,
    "selmer-kernel": SELMER_RECEIPT_SCHEMA,
}


def coerce_completeness(
    value: object,
    *,
    default: Completeness = Completeness.CANDIDATE,
) -> Completeness:
    """Normalize a foreign completeness enum without conflating it with truth."""

    if value is None:
        return default
    if isinstance(value, Completeness):
        return value
    if isinstance(value, bool):
        return Completeness.COMPLETE if value else Completeness.CANDIDATE
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        normalized = raw.strip().upper()
        if normalized in {"COMPLETE", "CERTIFIED_COMPLETE"}:
            return Completeness.COMPLETE
        if normalized in {"CANDIDATE", "INCOMPLETE", "UNKNOWN"}:
            return Completeness.CANDIDATE
    raise ArithmeticError(f"unsupported completeness value: {value!r}")


def is_complete(value: object) -> bool:
    """Return whether a foreign object explicitly advertises completeness."""

    if hasattr(value, "completeness"):
        value = value.completeness
    try:
        return coerce_completeness(value) is Completeness.COMPLETE
    except ArithmeticError:
        return False


def normalized_assumptions(*sources: object) -> tuple[str, ...]:
    """Collect ordered, de-duplicated mathematical assumptions."""

    result: list[str] = []
    for source in sources:
        raw = getattr(source, "assumptions", source)
        if raw is None:
            continue
        if isinstance(raw, str):
            values: Sequence[object] = (raw,)
        elif isinstance(raw, Sequence):
            values = raw
        else:
            raise ArithmeticError("assumptions must be a sequence of strings")
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise ArithmeticError("assumptions must contain non-blank strings")
            if item not in result:
                result.append(item)
    return tuple(result)


def _portable_requirement() -> VerificationRequirement:
    return VerificationRequirement.portable_python(
        "arithmetic.finite-linear.v1",
        capabilities=("finite-linear-replay",),
    )


def proof_context(
    *sources: object,
    completeness: Completeness | str | None = None,
    assumptions: Sequence[str] = (),
) -> ProofContext:
    """Merge proof axes while preserving external verifier requirements."""

    assumption_sources: list[object] = []
    for source in sources:
        context = getattr(source, "proof_context", None)
        if context is not None:
            assumption_sources.append(context)
        elif hasattr(source, "assumptions"):
            assumption_sources.append(source)
    assumption_values = normalized_assumptions(*assumption_sources, assumptions)
    requirements: list[VerificationRequirement] = [_portable_requirement()]
    for source in sources:
        context = getattr(source, "proof_context", None)
        if context is None:
            context = source if hasattr(source, "verification_requirements") else None
        if context is None:
            continue
        raw = getattr(context, "verification_requirements", ())
        if raw is None:
            continue
        if not isinstance(raw, Sequence):
            raise ArithmeticError("verification requirements must be a sequence")
        for requirement in raw:
            if not isinstance(requirement, VerificationRequirement):
                raise ArithmeticError(
                    "verification requirements must contain VerificationRequirement values"
                )
            if requirement not in requirements:
                requirements.append(requirement)
    if completeness is None:
        normalized = (
            Completeness.COMPLETE
            if sources
            and all(
                coerce_completeness(
                    getattr(getattr(source, "proof_context", None), "completeness", None)
                )
                is Completeness.COMPLETE
                for source in sources
            )
            else Completeness.CANDIDATE
        )
    else:
        normalized = coerce_completeness(completeness)
    return ProofContext(assumption_values, requirements, normalized)


def evidence_from_sources(*sources: object) -> tuple[VerificationCertificate, ...]:
    """Collect concrete central certificates, never verifier names alone."""

    result: list[VerificationCertificate] = []
    for source in sources:
        if source is None:
            continue
        candidates: list[object] = []
        if isinstance(source, VerificationCertificate):
            candidates.append(source)
        else:
            try:
                certificate = getattr(source, "certificate", None)
            except (ArithmeticError, VerificationError, ValueError):
                certificate = None
            if certificate is not None:
                candidates.append(certificate)
                if (
                    isinstance(certificate, VerificationCertificate)
                    and certificate.verifier == "arithmetic.finite-linear.v1"
                ):
                    raw_receipt = certificate.witness.to_dict().get("arithmetic_receipt")
                    if isinstance(raw_receipt, Mapping):
                        with suppress(TypeError, ValueError):
                            candidates.extend(ArithmeticReceipt.from_dict(raw_receipt).evidence)
            receipt = getattr(source, "receipt", None)
            nested = getattr(receipt, "evidence", ())
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                candidates.extend(nested)
            for attribute in (
                "evidence_certificates",
                "dependency_certificates",
                "verification_dependencies",
                "proving_certificates",
            ):
                raw = getattr(source, attribute, ())
                if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                    candidates.extend(raw)
            proving_certificate = getattr(source, "proving_certificate", None)
            if proving_certificate is not None:
                candidates.append(proving_certificate)
        for candidate in candidates:
            if not isinstance(candidate, VerificationCertificate):
                continue
            if all(item.certificate_id != candidate.certificate_id for item in result):
                result.append(candidate)
    return tuple(result)


def verified_complete(value: object) -> bool:
    """Require actual replayable evidence, not a forged COMPLETE flag."""

    context = getattr(value, "proof_context", None)
    if not isinstance(context, ProofContext) or not context.complete:
        return False
    aggregate = getattr(value, "_verified_completeness", None)
    if callable(aggregate):
        try:
            return bool(aggregate())
        except (TypeError, ValueError, VerificationError):
            return False
    verifier = getattr(value, "verify", None)
    if not callable(verifier):
        return False
    try:
        outcome = verifier()
    except (TypeError, ValueError, VerificationError):
        return False
    if outcome is False or getattr(outcome, "valid", True) is False:
        return False
    evidence = evidence_from_sources(value)
    if not evidence:
        return False
    try:
        _replay_evidence_closure(evidence)
    except ArithmeticVerificationError:
        return False
    available: dict[str, list[VerificationCertificate]] = {}
    for item in evidence:
        available.setdefault(item.verifier, []).append(item)
    for requirement in context.verification_requirements:
        if (
            requirement.verifier == "arithmetic.finite-linear.v1"
            and requirement.trust is VerifierTrust.PORTABLE_PYTHON
        ):
            # The object's own verify() call above replays this requirement;
            # demanding a pre-existing certificate would be circular.
            continue
        certificates = available.get(requirement.verifier, [])
        if not certificates:
            return False
        if requirement.version is not None and not any(
            _contains_exact_value(certificate.to_dict(), requirement.version)
            for certificate in certificates
        ):
            return False
    return True


def _contains_exact_value(value: object, target: str) -> bool:
    if value == target:
        return True
    if isinstance(value, Mapping):
        return any(_contains_exact_value(item, target) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_exact_value(item, target) for item in value)
    return False


def _replay_evidence_closure(
    evidence: Sequence[VerificationCertificate],
) -> None:
    by_id = {certificate.certificate_id: certificate for certificate in evidence}
    if len(by_id) != len(evidence):
        raise ArithmeticVerificationError("nested verification evidence must be unique")
    replayed: set[str] = set()
    active: set[str] = set()

    def replay(certificate: VerificationCertificate) -> None:
        certificate_id = certificate.certificate_id
        if certificate_id in replayed:
            return
        if certificate_id in active:
            raise ArithmeticVerificationError(
                f"nested verification evidence has a dependency cycle at {certificate_id}"
            )
        active.add(certificate_id)
        try:
            for reference in certificate.dependencies:
                supporting = by_id.get(reference.certificate_id)
                if supporting is None:
                    raise ArithmeticVerificationError(
                        f"nested verification evidence lacks dependency {reference.certificate_id}"
                    )
                if supporting.layer is not reference.layer:
                    raise ArithmeticVerificationError(
                        "nested verification dependency has the wrong certificate layer"
                    )
                schema = getattr(supporting, "schema_version", None)
                if reference.schema_version is not None and schema != reference.schema_version:
                    raise ArithmeticVerificationError(
                        "nested verification dependency has the wrong schema"
                    )
                supporting.verify_integrity(reference.certificate_id)
                replay(supporting)
            default_verifiers.verify(certificate)
        except ArithmeticVerificationError:
            raise
        except Exception as exc:  # verifier exceptions are normalized here
            raise ArithmeticVerificationError(
                f"nested verification evidence failed: {certificate_id}: {exc}"
            ) from exc
        finally:
            active.remove(certificate_id)
        replayed.add(certificate_id)

    for certificate in evidence:
        replay(certificate)


def _verify_receipt_evidence(receipt: ArithmeticReceipt) -> tuple[str, ...]:
    evidence_by_verifier: dict[str, list[VerificationCertificate]] = {}
    _replay_evidence_closure(receipt.evidence)
    for certificate in receipt.evidence:
        evidence_by_verifier.setdefault(certificate.verifier, []).append(certificate)
    for requirement in receipt.proof_context.verification_requirements:
        if (
            requirement.verifier == "arithmetic.finite-linear.v1"
            and requirement.trust is VerifierTrust.PORTABLE_PYTHON
        ):
            continue
        certificates = evidence_by_verifier.get(requirement.verifier, [])
        if not certificates:
            raise ArithmeticVerificationError(
                f"proof context requirement lacks nested evidence: {requirement.verifier}"
            )
        if requirement.version is not None and not any(
            _contains_exact_value(certificate.to_dict(), requirement.version)
            for certificate in certificates
        ):
            raise ArithmeticVerificationError(
                f"nested evidence does not bind required version {requirement.version}"
            )
    if (
        receipt.completeness is Completeness.COMPLETE
        and not receipt.evidence
        and receipt.kind
        in {
            "local-condition",
            "selmer-group",
            "dual-selmer",
        }
    ):
        raise ArithmeticVerificationError(
            "complete promoted arithmetic evidence must nest its input certificates"
        )
    return (
        "dependency-closed-input-certificates",
        "nested-input-certificates",
        "verification-requirements-satisfied",
    )


@dataclass(frozen=True)
class ArithmeticReceipt(ContentAddressedCertificate):
    """An independently versioned finite arithmetic receipt.

    The central :class:`~arbogast.cert.VerificationCertificate` embeds the
    complete dictionary form of this receipt.  This specialized class is not a
    fourth evidence layer; it is verification-layer evidence with a
    domain-specific schema.
    """

    kind: str
    payload: FrozenMap
    proof_context: ProofContext
    evidence: tuple[VerificationCertificate, ...] = ()

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION

    def __post_init__(self) -> None:
        if self.kind not in RECEIPT_SCHEMAS:
            raise CertificateError(f"unsupported arithmetic receipt kind: {self.kind!r}")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
        if not isinstance(self.proof_context, ProofContext):
            raise CertificateError("arithmetic receipt proof_context must be a ProofContext")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if any(not isinstance(item, VerificationCertificate) for item in self.evidence):
            raise CertificateError(
                "arithmetic evidence must contain VerificationCertificate values"
            )
        evidence_ids = tuple(item.certificate_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise CertificateError("arithmetic evidence certificates must be unique")

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def schema_version(self) -> str:
        return RECEIPT_SCHEMAS[self.kind]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "kind": self.kind,
            "payload": self.payload,
            "proof_context": self.proof_context.to_canonical_data(),
            "evidence": tuple(item.to_dict() for item in self.evidence),
        }

    @classmethod
    def create(
        cls,
        kind: str,
        payload: Mapping[str, object],
        *,
        completeness: Completeness | str = Completeness.CANDIDATE,
        assumptions: Sequence[str] = (),
        context: ProofContext | None = None,
        verification_requirements: Sequence[VerificationRequirement] = (),
        evidence: Sequence[VerificationCertificate] = (),
    ) -> ArithmeticReceipt:
        if context is not None and (assumptions or verification_requirements):
            raise ArithmeticError(
                "context cannot be combined with separate assumptions or verifier requirements"
            )
        normalized_context = context or ProofContext(
            normalized_assumptions(assumptions),
            tuple(dict.fromkeys((_portable_requirement(), *verification_requirements))),
            coerce_completeness(completeness),
        )
        return cls(
            kind=kind,
            payload=freeze_mapping(payload),
            proof_context=normalized_context,
            evidence=tuple(evidence),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ArithmeticReceipt:
        allowed = {
            "schema_version",
            "layer",
            "kind",
            "payload",
            "proof_context",
            "evidence",
            "certificate_id",
        }
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise CertificateError(f"unexpected arithmetic receipt fields: {', '.join(unexpected)}")
        required = allowed - {"certificate_id"}
        missing = sorted(required - set(value))
        if missing:
            raise CertificateError(f"missing arithmetic receipt fields: {', '.join(missing)}")
        kind = value["kind"]
        payload = value["payload"]
        context_value = value["proof_context"]
        evidence_value = value["evidence"]
        if not isinstance(kind, str):
            raise CertificateError("arithmetic receipt kind must be a string")
        if kind not in RECEIPT_SCHEMAS:
            raise CertificateError(f"unsupported arithmetic receipt kind: {kind!r}")
        if value["schema_version"] != RECEIPT_SCHEMAS[kind]:
            raise CertificateError("missing or unsupported arithmetic receipt schema")
        if value["layer"] != CertificateLayer.VERIFICATION.value:
            raise CertificateError("arithmetic receipt has the wrong evidence layer")
        if not isinstance(payload, Mapping):
            raise CertificateError("arithmetic receipt payload must be a mapping")
        if not isinstance(context_value, Mapping):
            raise CertificateError("arithmetic proof_context must be a mapping")
        if isinstance(evidence_value, (str, bytes)) or not isinstance(evidence_value, Sequence):
            raise CertificateError("arithmetic evidence must be a sequence")
        context = _proof_context_from_dict(context_value)
        evidence: list[VerificationCertificate] = []
        for raw in evidence_value:
            if not isinstance(raw, Mapping):
                raise CertificateError("arithmetic evidence certificate must be a mapping")
            evidence.append(VerificationCertificate.from_dict(raw))
        receipt = cls.create(
            kind,
            payload,
            context=context,
            evidence=evidence,
        )
        expected = value.get("certificate_id")
        if expected is not None:
            if not isinstance(expected, str):
                raise CertificateError("arithmetic certificate_id must be a string")
            receipt.verify_integrity(expected)
        return receipt

    def verify(self) -> tuple[str, ...]:
        """Replay the receipt without consulting the originating Python object."""

        self.verify_integrity()
        return verify_arithmetic_receipt(self)


# Public names emphasize the independently versioned receipt families while
# retaining one strict decoder and verifier implementation.
LocalConditionCertificate = ArithmeticReceipt
SelmerCertificate = ArithmeticReceipt
DualSelmerCertificate = ArithmeticReceipt
LocalPairingCertificate = ArithmeticReceipt
AimCertificate = ArithmeticReceipt
DescentCertificate = ArithmeticReceipt


def _strict_int(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArithmeticVerificationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ArithmeticVerificationError(f"{name} must be at least {minimum}")
    return value


def _strict_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArithmeticVerificationError(f"{name} must be a non-blank string")
    return value


def _strict_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ArithmeticVerificationError(f"{name} must be a boolean")
    return value


def _proof_context_from_dict(value: Mapping[str, object]) -> ProofContext:
    required = {"type", "assumptions", "verification_requirements", "completeness"}
    unexpected = sorted(set(value) - required)
    missing = sorted(required - set(value))
    if unexpected or missing:
        detail = unexpected if unexpected else missing
        raise CertificateError(f"invalid proof_context fields: {', '.join(detail)}")
    if value["type"] != "arbogast.proof_context":
        raise CertificateError("proof_context has the wrong type tag")
    assumptions_raw = value["assumptions"]
    requirements_raw = value["verification_requirements"]
    if isinstance(assumptions_raw, (str, bytes)) or not isinstance(assumptions_raw, Sequence):
        raise CertificateError("proof_context assumptions must be a sequence")
    if isinstance(requirements_raw, (str, bytes)) or not isinstance(requirements_raw, Sequence):
        raise CertificateError("proof_context verification requirements must be a sequence")
    requirements: list[VerificationRequirement] = []
    for raw in requirements_raw:
        if not isinstance(raw, Mapping):
            raise CertificateError("verification requirement must be a mapping")
        expected = {"type", "verifier", "trust", "version", "capabilities"}
        if set(raw) != expected or raw["type"] != "arbogast.verification_requirement":
            raise CertificateError("invalid verification requirement payload")
        capabilities = raw["capabilities"]
        if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Sequence):
            raise CertificateError("verification capabilities must be a sequence")
        verifier = _strict_string(raw["verifier"], "verifier")
        trust = _strict_string(raw["trust"], "trust")
        version = raw["version"]
        if version is not None and not isinstance(version, str):
            raise CertificateError("verification requirement version must be a string or null")
        requirements.append(
            VerificationRequirement(
                verifier,
                trust,
                version=version,
                capabilities=tuple(_strict_string(item, "capability") for item in capabilities),
            )
        )
    return ProofContext(
        tuple(_strict_string(item, "assumption") for item in assumptions_raw),
        requirements,
        coerce_completeness(value["completeness"]),
    )


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ArithmeticVerificationError(f"{name} must be a sequence")
    return value


def _rows(
    value: object,
    name: str,
    *,
    prime: int,
    ncols: int,
) -> tuple[tuple[int, ...], ...]:
    result: list[tuple[int, ...]] = []
    for row_index, raw_row in enumerate(_sequence(value, name)):
        row = tuple(
            _strict_int(item, f"{name}[{row_index}][{column_index}]")
            for column_index, item in enumerate(_sequence(raw_row, f"{name}[{row_index}]"))
        )
        if len(row) != ncols:
            raise ArithmeticVerificationError(f"{name} has a row with the wrong length")
        if any(not 0 <= item < prime for item in row):
            raise ArithmeticVerificationError(f"{name} entries are not canonical residues")
        result.append(row)
    return tuple(result)


def _vector(
    value: object,
    name: str,
    *,
    prime: int,
    length: int,
) -> tuple[int, ...]:
    result = tuple(
        _strict_int(item, f"{name}[{index}]") for index, item in enumerate(_sequence(value, name))
    )
    if len(result) != length:
        raise ArithmeticVerificationError(f"{name} has the wrong length")
    if any(not 0 <= item < prime for item in result):
        raise ArithmeticVerificationError(f"{name} entries are not canonical residues")
    return result


def _field(payload: Mapping[str, object]) -> tuple[PrimeField, int]:
    prime = _strict_int(payload.get("prime"), "prime", minimum=2)
    try:
        field = PrimeField(prime)
    except ValidationError as exc:
        raise ArithmeticVerificationError(str(exc)) from exc
    return field, prime


def _matrix_from_payload(
    payload: Mapping[str, object],
    *,
    prefix: str = "matrix",
) -> DenseMatrix:
    field, prime = _field(payload)
    nrows = _strict_int(payload.get(f"{prefix}_nrows"), f"{prefix}_nrows", minimum=0)
    ncols = _strict_int(payload.get(f"{prefix}_ncols"), f"{prefix}_ncols", minimum=0)
    rows = _rows(payload.get(prefix), prefix, prime=prime, ncols=ncols)
    if len(rows) != nrows:
        raise ArithmeticVerificationError(f"{prefix} has the wrong row count")
    return DenseMatrix(field, rows, ncols=ncols)


def matrix_payload(matrix: DenseMatrix, *, prefix: str = "matrix") -> dict[str, object]:
    """Return the strict compact matrix encoding used by arithmetic receipts."""

    return {
        "prime": matrix.field.p,
        prefix: matrix.rows,
        f"{prefix}_nrows": matrix.nrows,
        f"{prefix}_ncols": matrix.ncols,
    }


def _check_exact_keys(
    payload: Mapping[str, object],
    required: set[str],
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    unexpected = sorted(set(payload) - allowed)
    missing = sorted(required - set(payload))
    if unexpected:
        raise ArithmeticVerificationError(
            f"unexpected arithmetic payload fields: {', '.join(unexpected)}"
        )
    if missing:
        raise ArithmeticVerificationError(
            f"missing arithmetic payload fields: {', '.join(missing)}"
        )


def _verify_local_condition(
    payload: Mapping[str, object],
    evidence_ids: tuple[str, ...],
) -> tuple[str, ...]:
    required = {
        "prime",
        "ambient_dimension",
        "basis",
        "place_id",
        "space_id",
        "input_evidence_ids",
    }
    _check_exact_keys(payload, required)
    field, prime = _field(payload)
    ambient = _strict_int(payload["ambient_dimension"], "ambient_dimension", minimum=0)
    basis = _rows(payload["basis"], "basis", prime=prime, ncols=ambient)
    canonical = LinearSubspace(field, ambient, basis)
    if canonical.basis != basis:
        raise ArithmeticVerificationError("local-condition basis is not canonical")
    _strict_string(payload["place_id"], "place_id")
    _strict_string(payload["space_id"], "space_id")
    advertised = tuple(
        _strict_string(item, "input_evidence_id")
        for item in _sequence(payload["input_evidence_ids"], "input_evidence_ids")
    )
    if advertised != evidence_ids:
        raise ArithmeticVerificationError("local-condition input evidence manifest was altered")
    return ("prime-field", "canonical-local-subspace", "place-and-space-binding")


def _verify_selmer(
    payload: Mapping[str, object],
    *,
    complete: bool,
    evidence_ids: tuple[str, ...],
    evidence: Sequence[VerificationCertificate],
) -> tuple[str, ...]:
    required = {
        "prime",
        "matrix",
        "matrix_nrows",
        "matrix_ncols",
        "kernel_basis",
        "global_space_id",
        "place_ids",
        "place_set_complete",
        "dimension",
        "input_evidence_ids",
        "global_certificate_id",
        "local_blocks",
    }
    _check_exact_keys(payload, required)
    matrix = _matrix_from_payload(payload)
    basis = _rows(
        payload["kernel_basis"],
        "kernel_basis",
        prime=matrix.field.p,
        ncols=matrix.ncols,
    )
    expected = nullspace(matrix)
    if basis != expected.basis:
        raise ArithmeticVerificationError(
            "Selmer kernel basis does not equal the recomputed kernel"
        )
    dimension = _strict_int(payload["dimension"], "dimension", minimum=0)
    if dimension != expected.dimension:
        raise ArithmeticVerificationError("Selmer dimension does not match the recomputed kernel")
    _strict_string(payload["global_space_id"], "global_space_id")
    place_ids = tuple(
        _strict_string(item, "place_id") for item in _sequence(payload["place_ids"], "place_ids")
    )
    if len(set(place_ids)) != len(place_ids):
        raise ArithmeticVerificationError("Selmer place IDs must be unique")
    place_set_complete = _strict_bool(payload["place_set_complete"], "place_set_complete")
    if complete and not place_set_complete:
        raise ArithmeticVerificationError("complete Selmer group has an incomplete place set")
    advertised = tuple(
        _strict_string(item, "input_evidence_id")
        for item in _sequence(payload["input_evidence_ids"], "input_evidence_ids")
    )
    if advertised != evidence_ids:
        raise ArithmeticVerificationError("Selmer input evidence manifest was altered")
    if complete:
        _verify_complete_selmer_inputs(
            payload,
            matrix,
            place_ids,
            evidence,
        )
    return ("prime-field", "global-to-local-quotient-map", "recomputed-kernel")


def _certificate_mapping(
    evidence: Sequence[VerificationCertificate],
) -> dict[str, VerificationCertificate]:
    return {certificate.certificate_id: certificate for certificate in evidence}


def _nested_witness(
    certificate: VerificationCertificate,
    *,
    verifier: str,
    field: str,
) -> Mapping[str, object]:
    if certificate.verifier != verifier:
        raise ArithmeticVerificationError(f"nested {field} evidence names the wrong verifier")
    witness = certificate.witness.to_dict()
    raw = witness.get(field)
    if set(witness) != {field} or not isinstance(raw, Mapping):
        raise ArithmeticVerificationError(f"nested {field} evidence is malformed")
    return raw


def _verify_complete_selmer_inputs(
    payload: Mapping[str, object],
    matrix: DenseMatrix,
    place_ids: tuple[str, ...],
    evidence: Sequence[VerificationCertificate],
) -> None:
    by_id = _certificate_mapping(evidence)
    global_certificate_id = _strict_string(
        payload["global_certificate_id"],
        "global_certificate_id",
    )
    global_certificate = by_id.get(global_certificate_id)
    if global_certificate is None:
        raise ArithmeticVerificationError("complete Selmer evidence lacks its Kummer certificate")
    try:
        global_receipt = KummerReceipt.from_dict(
            _nested_witness(
                global_certificate,
                verifier="galois.kummer.v1",
                field="kummer_receipt",
            )
        )
        global_receipt.verify()
    except (TypeError, ValueError) as exc:
        raise ArithmeticVerificationError("complete Selmer Kummer receipt did not replay") from exc
    if (
        global_receipt.object_type != "space"
        or global_receipt.content_id != payload["global_space_id"]
        or tuple(global_receipt.place_ids) != place_ids
        or global_receipt.proof_context.get("completeness") != "complete"
        or not relevant_places_complete(global_receipt)
    ):
        raise ArithmeticVerificationError(
            "complete Selmer Kummer certificate is bound to different global data"
        )

    raw_blocks = _sequence(payload["local_blocks"], "local_blocks")
    if len(raw_blocks) != len(place_ids):
        raise ArithmeticVerificationError("Selmer local evidence block count is wrong")
    reconstructed_rows: list[tuple[int, ...]] = []
    by_place: list[str] = []
    for index, (raw_block, expected_place) in enumerate(zip(raw_blocks, place_ids, strict=True)):
        if not isinstance(raw_block, Mapping):
            raise ArithmeticVerificationError("Selmer local evidence block is not an object")
        _check_exact_keys(
            raw_block,
            {
                "place_id",
                "localization_certificate_id",
                "condition_certificate_id",
            },
        )
        block_place = _strict_string(raw_block["place_id"], f"local_blocks[{index}].place_id")
        if block_place != expected_place:
            raise ArithmeticVerificationError("Selmer local evidence blocks were reordered")
        by_place.append(block_place)
        localization_id = _strict_string(
            raw_block["localization_certificate_id"],
            f"local_blocks[{index}].localization_certificate_id",
        )
        condition_id = _strict_string(
            raw_block["condition_certificate_id"],
            f"local_blocks[{index}].condition_certificate_id",
        )
        localization_certificate = by_id.get(localization_id)
        condition_certificate = by_id.get(condition_id)
        if localization_certificate is None or condition_certificate is None:
            raise ArithmeticVerificationError("Selmer local block names missing evidence")
        try:
            localization_receipt = LocalizationReceipt.from_dict(
                _nested_witness(
                    localization_certificate,
                    verifier="galois.localization.v1",
                    field="localization_receipt",
                )
            )
            localization_receipt.verify()
            condition_receipt = ArithmeticReceipt.from_dict(
                _nested_witness(
                    condition_certificate,
                    verifier="arithmetic.finite-linear.v1",
                    field="arithmetic_receipt",
                )
            )
            condition_receipt.verify()
        except (TypeError, ValueError) as exc:
            raise ArithmeticVerificationError(
                "Selmer local input certificate did not replay"
            ) from exc
        if (
            localization_receipt.domain.content_id != global_receipt.content_id
            or localization_receipt.codomain.place_id != block_place
            or localization_receipt.proof_context.get("completeness") != "complete"
            or condition_receipt.kind != "local-condition"
            or condition_receipt.completeness is not Completeness.COMPLETE
            or condition_receipt.payload["place_id"] != block_place
            or condition_receipt.payload["space_id"] != localization_receipt.codomain.content_id
        ):
            raise ArithmeticVerificationError(
                "Selmer local certificate is bound to different place or space data"
            )
        local_matrix = DenseMatrix(
            matrix.field,
            localization_receipt.matrix,
            ncols=global_receipt.dimension,
        )
        condition_basis = _rows(
            condition_receipt.payload["basis"],
            f"local_blocks[{index}].condition_basis",
            prime=matrix.field.p,
            ncols=localization_receipt.codomain.dimension,
        )
        condition = LinearSubspace(
            matrix.field,
            localization_receipt.codomain.dimension,
            condition_basis,
        )
        reconstructed_rows.extend(
            (nullspace(condition.basis_matrix).basis_matrix @ local_matrix).rows
        )
    if (
        tuple(by_place) != place_ids
        or DenseMatrix(
            matrix.field,
            tuple(reconstructed_rows),
            ncols=matrix.ncols,
        )
        != matrix
    ):
        raise ArithmeticVerificationError(
            "Selmer matrix does not equal the certified local quotient assembly"
        )


def _local_h1_receipts(
    evidence: Sequence[VerificationCertificate],
) -> dict[str, LocalH1Receipt]:
    result: dict[str, LocalH1Receipt] = {}
    for certificate in evidence:
        if certificate.verifier != "galois.local_h1.v1":
            continue
        witness = certificate.witness.to_dict()
        raw = witness.get("local_h1_receipt")
        if not isinstance(raw, Mapping):
            raise ArithmeticVerificationError(
                "nested local-H1 certificate lacks its canonical receipt"
            )
        try:
            receipt = LocalH1Receipt.from_dict(raw)
            receipt.verify()
        except (TypeError, ValueError) as exc:
            raise ArithmeticVerificationError("nested local-H1 receipt did not replay") from exc
        if receipt.object_type != "space":
            continue
        result[receipt.content_id] = receipt
    return result


def _rational_basis_value(value: object, name: str) -> Fraction:
    if not isinstance(value, Mapping):
        raise ArithmeticVerificationError(f"{name} is not a number-field element snapshot")
    coefficients = _sequence(value.get("coefficients"), f"{name}.coefficients")
    if len(coefficients) != 1:
        raise ArithmeticVerificationError(f"{name} is not a rational element")
    pair = _sequence(coefficients[0], f"{name}.coefficients[0]")
    if len(pair) != 2:
        raise ArithmeticVerificationError(f"{name} has a malformed rational coefficient")
    numerator = _strict_int(pair[0], f"{name}.numerator")
    denominator = _strict_int(pair[1], f"{name}.denominator", minimum=1)
    result = Fraction(numerator, denominator)
    if (result.numerator, result.denominator) != (numerator, denominator) or result == 0:
        raise ArithmeticVerificationError(f"{name} is not a canonical nonzero rational")
    return result


def _valuation(value: int, prime: int) -> int:
    exponent = 0
    while value % prime == 0:
        value //= prime
        exponent += 1
    return exponent


def _q2_hilbert_exponent(left: Fraction, right: Fraction) -> int:
    left_valuation = _valuation(abs(left.numerator), 2) - _valuation(left.denominator, 2)
    right_valuation = _valuation(abs(right.numerator), 2) - _valuation(right.denominator, 2)

    def unit_residue(value: Fraction, valuation: int) -> int:
        unit = value / (2**valuation) if valuation >= 0 else value * (2 ** (-valuation))
        return int(unit.numerator % 8 * pow(unit.denominator % 8, -1, 8) % 8)

    left_unit = unit_residue(left, left_valuation)
    right_unit = unit_residue(right, right_valuation)
    left_epsilon = ((left_unit % 4) - 1) // 2 % 2
    right_epsilon = ((right_unit % 4) - 1) // 2 % 2
    left_omega = 0 if left_unit in {1, 7} else 1
    right_omega = 0 if right_unit in {1, 7} else 1
    return (
        left_epsilon * right_epsilon + left_valuation * right_omega + right_valuation * left_omega
    ) % 2


def _verify_portable_pairing_witness(
    matrix: DenseMatrix,
    witness: Mapping[str, object],
    left_receipt: LocalH1Receipt,
    right_receipt: LocalH1Receipt,
    place_id: str,
) -> None:
    required = {"kind", "place_kind", "left_values", "right_values"}
    _check_exact_keys(witness, required)
    if witness["kind"] != "rational-hilbert-v1":
        raise ArithmeticVerificationError("portable pairing witness has the wrong kind")
    left_basis = left_receipt.basis
    right_basis = right_receipt.basis
    left_values = tuple(
        _rational_basis_value(value, f"left_basis[{index}]")
        for index, value in enumerate(left_basis)
    )
    right_values = tuple(
        _rational_basis_value(value, f"right_basis[{index}]")
        for index, value in enumerate(right_basis)
    )
    advertised_left = tuple(
        (
            _strict_int(_sequence(value, "left_values entry")[0], "left numerator"),
            _strict_int(
                _sequence(value, "left_values entry")[1],
                "left denominator",
                minimum=1,
            ),
        )
        for value in _sequence(witness["left_values"], "left_values")
    )
    advertised_right = tuple(
        (
            _strict_int(_sequence(value, "right_values entry")[0], "right numerator"),
            _strict_int(
                _sequence(value, "right_values entry")[1],
                "right denominator",
                minimum=1,
            ),
        )
        for value in _sequence(witness["right_values"], "right_values")
    )
    if advertised_left != tuple(
        (value.numerator, value.denominator) for value in left_values
    ) or advertised_right != tuple((value.numerator, value.denominator) for value in right_values):
        raise ArithmeticVerificationError("pairing witness was rebound to different local bases")
    left_place = left_receipt.place
    right_place = right_receipt.place
    if left_receipt.place_id != place_id or right_receipt.place_id != place_id:
        raise ArithmeticVerificationError("pairing witness is bound to a different place")
    if left_place != right_place:
        raise ArithmeticVerificationError("pairing endpoint place data differ")
    place_kind = _strict_string(witness["place_kind"], "place_kind")
    if left_place.get("rational_prime") == 2:
        expected_kind = "q2"
        rows = tuple(
            tuple(_q2_hilbert_exponent(left, right) for right in right_values)
            for left in left_values
        )
    elif left_place.get("kind") == "real":
        expected_kind = "real"
        rows = tuple(
            tuple(int(left < 0 and right < 0) for right in right_values) for left in left_values
        )
    else:
        raise ArithmeticVerificationError(
            "portable pairing witness supports only Q_2 and rational real places"
        )
    if place_kind != expected_kind or matrix.rows != rows:
        raise ArithmeticVerificationError("Hilbert pairing matrix does not replay")


def _verify_complex_zero_pairing_witness(
    matrix: DenseMatrix,
    witness: Mapping[str, object],
    left_receipt: LocalH1Receipt,
    right_receipt: LocalH1Receipt,
    place_id: str,
) -> None:
    _check_exact_keys(witness, {"kind"})
    if witness["kind"] != "complex-zero-hilbert-v1":
        raise ArithmeticVerificationError("complex zero pairing witness has the wrong kind")
    if left_receipt.place_id != place_id or right_receipt.place_id != place_id:
        raise ArithmeticVerificationError("complex zero pairing is bound to a different place")
    if left_receipt.place != right_receipt.place:
        raise ArithmeticVerificationError("complex zero pairing endpoint place data differ")
    place = left_receipt.place
    if place.get("type") != "arbogast.infinite_place" or place.get("kind") != "complex":
        raise ArithmeticVerificationError("complex zero pairing requires a complex place")
    if left_receipt.prime != 2 or right_receipt.prime != 2:
        raise ArithmeticVerificationError("complex zero Hilbert pairing is only for mu2")
    if left_receipt.basis or right_receipt.basis or matrix.shape != (0, 0):
        raise ArithmeticVerificationError(
            "complex local H1(mu2) pairing must be the zero-dimensional matrix"
        )


def _verify_pari_pairing_witness(
    matrix: DenseMatrix,
    witness: Mapping[str, object],
    left_receipt: LocalH1Receipt,
    right_receipt: LocalH1Receipt,
    place_id: str,
    evidence: Sequence[VerificationCertificate],
) -> None:
    _check_exact_keys(witness, {"kind", "certificate_ids"})
    if witness["kind"] != "pari-hilbert-v1":
        raise ArithmeticVerificationError("PARI pairing witness has the wrong kind")
    certificate_ids = tuple(
        _strict_string(value, "pairing certificate ID")
        for value in _sequence(witness["certificate_ids"], "certificate_ids")
    )
    if len(certificate_ids) != matrix.nrows * matrix.ncols:
        raise ArithmeticVerificationError("PARI pairing witness has the wrong entry count")
    by_id = {certificate.certificate_id: certificate for certificate in evidence}
    left_ids = left_receipt.basis_ids
    right_ids = right_receipt.basis_ids
    for index, certificate_id in enumerate(certificate_ids):
        certificate = by_id.get(certificate_id)
        if certificate is None or certificate.verifier != "arbogast.backends.pari.v1":
            raise ArithmeticVerificationError("PARI pairing witness names missing evidence")
        raw = certificate.witness.to_dict()
        if raw.get("operation") != "quadratic_hilbert_pairing":
            raise ArithmeticVerificationError("nested PARI evidence is not a Hilbert operation")
        expected = raw.get("expected_payload")
        if not isinstance(expected, Mapping):
            raise ArithmeticVerificationError("nested PARI Hilbert payload is malformed")
        row, column = divmod(index, matrix.ncols)
        if (
            expected.get("left_element_id") != left_ids[row]
            or expected.get("right_element_id") != right_ids[column]
            or expected.get("place_id") != place_id
            or expected.get("symbol") != (-1 if matrix.rows[row][column] else 1)
        ):
            raise ArithmeticVerificationError("nested PARI Hilbert entry was rebound")


def _verify_supplied_pairing_witness(
    matrix: DenseMatrix,
    witness: Mapping[str, object],
    left_receipt: LocalH1Receipt,
    right_receipt: LocalH1Receipt,
    place_id: str,
    context: ProofContext,
    evidence: Sequence[VerificationCertificate],
) -> None:
    """Replay the exact boundary for a certified supplied Tate pairing."""

    _check_exact_keys(witness, {"kind", "operation"})
    if witness["kind"] != "certified-supplied-tate-pairing-v1":
        raise ArithmeticVerificationError("supplied pairing witness has the wrong kind")
    operation = _strict_string(witness["operation"], "pairing operation")
    if operation != "supplied_local_pairing":
        raise ArithmeticVerificationError("supplied pairing names an unsupported operation")
    if (
        left_receipt.place_id != place_id
        or right_receipt.place_id != place_id
        or left_receipt.prime != matrix.field.p
        or right_receipt.prime != matrix.field.p
    ):
        raise ArithmeticVerificationError("supplied pairing is bound to different local endpoints")

    matches: list[VerificationCertificate] = []
    for certificate in evidence:
        raw = certificate.witness.to_dict()
        if (
            raw.get("schema") == SUPPLIED_PRESENTATION_WITNESS_SCHEMA
            and raw.get("operation") == operation
        ):
            matches.append(certificate)
    if len(matches) != 1:
        raise ArithmeticVerificationError(
            "a supplied pairing requires exactly one proving certificate"
        )
    certificate = matches[0]
    raw = certificate.witness.to_dict()
    required_fields = {
        "backend_version",
        "expected_payload",
        "expected_payload_id",
        "operation",
        "proof",
        "schema",
    }
    if set(raw) != required_fields:
        raise ArithmeticVerificationError(
            "supplied-pairing certificate witness fields were altered"
        )
    expected_payload = raw.get("expected_payload")
    if not isinstance(expected_payload, Mapping):
        raise ArithmeticVerificationError("supplied pairing payload is malformed")
    actual_payload = {
        "left_space_id": left_receipt.content_id,
        "matrix": matrix.rows,
        "place_id": place_id,
        "prime": matrix.field.p,
        "right_space_id": right_receipt.content_id,
    }
    if set(expected_payload) != set(actual_payload) or content_address(
        expected_payload
    ) != content_address(actual_payload):
        raise ArithmeticVerificationError("supplied-pairing certificate is bound to different data")
    payload_id = content_address(actual_payload)
    if raw.get("expected_payload_id") != payload_id:
        raise ArithmeticVerificationError("supplied-pairing payload ID was altered")
    if certificate.subject != f"galois:supplied:{operation}:{payload_id}":
        raise ArithmeticVerificationError("supplied-pairing subject is not payload-bound")
    version = _strict_string(raw.get("backend_version"), "pairing backend version")
    requirement_matches = tuple(
        requirement
        for requirement in context.verification_requirements
        if requirement.verifier == certificate.verifier
        and requirement.version == version
        and operation in requirement.capabilities
    )
    if len(requirement_matches) != 1:
        raise ArithmeticVerificationError(
            "supplied-pairing certificate has no unique verifier requirement"
        )


def _verify_pairing(
    payload: Mapping[str, object],
    *,
    complete: bool,
    context: ProofContext,
    evidence: Sequence[VerificationCertificate],
) -> tuple[str, ...]:
    required = {
        "prime",
        "matrix",
        "matrix_nrows",
        "matrix_ncols",
        "left_space_id",
        "right_space_id",
        "place_id",
        "pairing_witness",
        "perfect",
    }
    _check_exact_keys(payload, required)
    matrix = _matrix_from_payload(payload)
    left_id = _strict_string(payload["left_space_id"], "left_space_id")
    right_id = _strict_string(payload["right_space_id"], "right_space_id")
    place_id = _strict_string(payload["place_id"], "place_id")
    advertised = _strict_bool(payload["perfect"], "perfect")
    actual = matrix.nrows == matrix.ncols == rank(matrix)
    if advertised != actual:
        raise ArithmeticVerificationError("pairing perfectness flag is incorrect")
    raw_witness = payload["pairing_witness"]
    if raw_witness is None:
        if complete:
            raise ArithmeticVerificationError(
                "complete local pairing lacks a replayable Hilbert/Tate witness"
            )
        return ("pairing-shape", "pairing-rank", "candidate-pairing-boundary")
    if not isinstance(raw_witness, Mapping):
        raise ArithmeticVerificationError("pairing_witness must be an object or null")
    local_receipts = _local_h1_receipts(evidence)
    left_receipt = local_receipts.get(left_id)
    right_receipt = local_receipts.get(right_id)
    if left_receipt is None or right_receipt is None:
        raise ArithmeticVerificationError("pairing lacks nested local-H1 basis evidence")
    if complete and (
        left_receipt.proof_context.get("completeness") != "complete"
        or right_receipt.proof_context.get("completeness") != "complete"
    ):
        raise ArithmeticVerificationError("complete pairing has incomplete local endpoints")
    witness_kind = raw_witness.get("kind")
    if witness_kind == "rational-hilbert-v1":
        _verify_portable_pairing_witness(
            matrix,
            raw_witness,
            left_receipt,
            right_receipt,
            place_id,
        )
        witness_check = "portable-hilbert-replay"
    elif witness_kind == "complex-zero-hilbert-v1":
        _verify_complex_zero_pairing_witness(
            matrix,
            raw_witness,
            left_receipt,
            right_receipt,
            place_id,
        )
        witness_check = "portable-complex-zero-hilbert-replay"
    elif witness_kind == "pari-hilbert-v1":
        _verify_pari_pairing_witness(
            matrix,
            raw_witness,
            left_receipt,
            right_receipt,
            place_id,
            evidence,
        )
        witness_check = "pinned-pari-hilbert-replay"
    elif witness_kind == "certified-supplied-tate-pairing-v1":
        _verify_supplied_pairing_witness(
            matrix,
            raw_witness,
            left_receipt,
            right_receipt,
            place_id,
            context,
            evidence,
        )
        witness_check = "certified-supplied-tate-pairing-replay"
    else:
        raise ArithmeticVerificationError("unsupported local pairing witness")
    return ("pairing-shape", "pairing-rank", "perfectness-decision", witness_check)


def _verify_cartier_dual(payload: Mapping[str, object]) -> tuple[str, ...]:
    required = {
        "module_id",
        "dual_module_id",
        "prime",
        "dimension",
        "quotient_id",
        "action_convention",
        "group_identity",
        "group_table",
        "tate_twist",
        "twist_character",
        "original_action_matrices",
        "dual_action_matrices",
    }
    _check_exact_keys(payload, required)
    field, prime = _field(payload)
    module_id = _strict_string(payload["module_id"], "module_id")
    quotient_id = _strict_string(payload["quotient_id"], "quotient_id")
    convention = _strict_string(payload["action_convention"], "action_convention")
    if convention != "column action: rho(left * right) = rho(left) @ rho(right)":
        raise ArithmeticVerificationError("unsupported Galois action convention")
    dimension = _strict_int(payload["dimension"], "dimension", minimum=1)
    twist = _strict_int(payload["tate_twist"], "tate_twist")

    def matrices(value: object, name: str) -> tuple[DenseMatrix, ...]:
        result = tuple(
            DenseMatrix(
                field,
                _rows(raw, f"{name}[{index}]", prime=prime, ncols=dimension),
                ncols=dimension,
            )
            for index, raw in enumerate(_sequence(value, name))
        )
        if not result or any(matrix.nrows != dimension for matrix in result):
            raise ArithmeticVerificationError(f"{name} has an invalid action matrix")
        if any(rank(matrix) != dimension for matrix in result):
            raise ArithmeticVerificationError(f"{name} contains a singular action matrix")
        return result

    original = matrices(payload["original_action_matrices"], "original_action_matrices")
    dual = matrices(payload["dual_action_matrices"], "dual_action_matrices")
    if len(original) != len(dual):
        raise ArithmeticVerificationError("Cartier actions enumerate different quotient sizes")
    group_order = len(original)
    group_table = _rows(
        payload["group_table"],
        "group_table",
        prime=max(2, group_order + 1),
        ncols=group_order,
    )
    if len(group_table) != group_order or any(
        value >= group_order for row in group_table for value in row
    ):
        raise ArithmeticVerificationError("Cartier group table has invalid entries")
    identity = _strict_int(
        payload["group_identity"],
        "group_identity",
        minimum=0,
    )
    if identity >= group_order or any(
        group_table[identity][index] != index or group_table[index][identity] != index
        for index in range(group_order)
    ):
        raise ArithmeticVerificationError("Cartier group table has the wrong identity")
    for left in range(group_order):
        if not any(
            group_table[left][candidate] == identity and group_table[candidate][left] == identity
            for candidate in range(group_order)
        ):
            raise ArithmeticVerificationError("Cartier group table lacks an inverse")
        for middle in range(group_order):
            if original[left] @ original[middle] != original[group_table[left][middle]]:
                raise ArithmeticVerificationError("source matrices do not define the group action")
            for right in range(group_order):
                if (
                    group_table[group_table[left][middle]][right]
                    != group_table[left][group_table[middle][right]]
                ):
                    raise ArithmeticVerificationError("Cartier group table is not associative")
    raw_character = payload["twist_character"]
    if raw_character is None:
        character = None
        if prime != 2 and twist:
            raise ArithmeticVerificationError("odd-prime Tate twist lacks its character")
    else:
        character = _vector(
            raw_character,
            "twist_character",
            prime=prime,
            length=len(original),
        )
        if any(value == 0 for value in character):
            raise ArithmeticVerificationError("twist character contains zero")
    expected = tuple(inverse(matrix).transpose() for matrix in original)
    if character is not None:
        expected = tuple(
            matrix.scale(pow(value, twist, prime))
            for matrix, value in zip(expected, character, strict=True)
        )
    if dual != expected:
        raise ArithmeticVerificationError("displayed action is not the Cartier dual action")
    module_payload = {
        "action_convention": convention,
        "action_matrices": tuple(matrix.rows for matrix in original),
        "dimension": dimension,
        "prime": prime,
        "quotient_id": quotient_id,
        "type": "arbogast.galois_module",
    }
    if content_address(module_payload) != module_id:
        raise ArithmeticVerificationError("Cartier source module ID is not action-bound")
    dual_module_id = payload["dual_module_id"]
    if dual_module_id is not None:
        dual_identifier = _strict_string(dual_module_id, "dual_module_id")
        dual_payload = {**module_payload, "action_matrices": tuple(matrix.rows for matrix in dual)}
        if content_address(dual_payload) != dual_identifier:
            raise ArithmeticVerificationError("supplied dual module ID is not action-bound")
    return (
        "prime-field",
        "source-module-action-binding",
        "finite-group-representation-replay",
        "contragredient-tate-twist-replay",
    )


def _verify_aim(payload: Mapping[str, object], *, obstruction: bool) -> tuple[str, ...]:
    required = {
        "prime",
        "matrix",
        "matrix_nrows",
        "matrix_ncols",
        "target",
        "kernel_basis",
    }
    required.add("witness" if obstruction else "representative")
    _check_exact_keys(payload, required)
    matrix = _matrix_from_payload(payload)
    target = _vector(
        payload["target"],
        "target",
        prime=matrix.field.p,
        length=matrix.nrows,
    )
    replay = solve(matrix, target)
    basis = _rows(
        payload["kernel_basis"],
        "kernel_basis",
        prime=matrix.field.p,
        ncols=matrix.ncols,
    )
    if basis != replay.kernel.basis:
        raise ArithmeticVerificationError("aiming kernel differs from exact replay")
    if obstruction:
        witness = _vector(
            payload["witness"],
            "witness",
            prime=matrix.field.p,
            length=matrix.nrows,
        )
        if replay.consistent or replay.inconsistency_witness != witness:
            raise ArithmeticVerificationError("aiming obstruction differs from exact replay")
        return ("linear-system", "left-nullspace", "separating-pairing")
    representative = _vector(
        payload["representative"],
        "representative",
        prime=matrix.field.p,
        length=matrix.ncols,
    )
    if not replay.consistent or replay.particular != representative:
        raise ArithmeticVerificationError("aiming representative differs from exact replay")
    return ("linear-system", "checked-representative", "complete-affine-kernel")


def _verify_dual_selmer(
    payload: Mapping[str, object],
    evidence_ids: tuple[str, ...],
    *,
    complete: bool,
    evidence: Sequence[VerificationCertificate],
) -> tuple[str, ...]:
    required = {
        "prime",
        "matrix",
        "matrix_nrows",
        "matrix_ncols",
        "kernel_basis",
        "global_space_id",
        "place_ids",
        "place_set_complete",
        "dimension",
        "orthogonality_checks",
        "input_evidence_ids",
        "global_certificate_id",
        "local_blocks",
        "cartier_certificate_id",
        "pairing_certificate_ids",
        "primal_condition_certificate_ids",
        "dual_condition_certificate_ids",
        "selmer_certificate_id",
    }
    _check_exact_keys(payload, required)
    role_fields = {
        "orthogonality_checks",
        "cartier_certificate_id",
        "pairing_certificate_ids",
        "primal_condition_certificate_ids",
        "dual_condition_certificate_ids",
        "selmer_certificate_id",
    }
    _verify_selmer(
        {key: value for key, value in payload.items() if key not in role_fields},
        complete=complete,
        evidence_ids=evidence_ids,
        evidence=evidence,
    )
    checks = _sequence(payload["orthogonality_checks"], "orthogonality_checks")
    if len(checks) != len(_sequence(payload["place_ids"], "place_ids")):
        raise ArithmeticVerificationError("dual Selmer orthogonality manifest has wrong length")
    by_id = _certificate_mapping(evidence)

    def arithmetic_role(identifier: object, name: str) -> ArithmeticReceipt:
        certificate_id = _strict_string(identifier, name)
        certificate = by_id.get(certificate_id)
        if certificate is None:
            raise ArithmeticVerificationError(f"{name} names missing evidence")
        try:
            receipt = ArithmeticReceipt.from_dict(
                _nested_witness(
                    certificate,
                    verifier="arithmetic.finite-linear.v1",
                    field="arithmetic_receipt",
                )
            )
            receipt.verify()
        except (TypeError, ValueError) as exc:
            raise ArithmeticVerificationError(f"{name} did not replay") from exc
        return receipt

    cartier = arithmetic_role(payload["cartier_certificate_id"], "cartier_certificate_id")
    cartier_prime = cartier.payload.get("prime")
    invalid_kummer_dual = (
        cartier.kind != "cartier-dual"
        or cartier.completeness is not Completeness.COMPLETE
        or cartier_prime != payload["prime"]
        or cartier.payload.get("dimension") != 1
        or cartier.payload.get("tate_twist") != 1
    )
    if invalid_kummer_dual:
        raise ArithmeticVerificationError(
            "dual Selmer Cartier evidence is not certified one-dimensional M^vee(1)"
        )
    if cartier_prime == 2:
        if any(matrix != ((1,),) for matrix in cartier.payload["dual_action_matrices"]):
            raise ArithmeticVerificationError(
                "dual Selmer Cartier evidence is not the trivial mu_2 dual"
            )
    elif cartier.payload.get("twist_character") is None:
        raise ArithmeticVerificationError(
            "odd-prime dual Selmer Cartier evidence lacks a cyclotomic character"
        )
    pairing_ids = _sequence(payload["pairing_certificate_ids"], "pairing_certificate_ids")
    primal_ids = _sequence(
        payload["primal_condition_certificate_ids"],
        "primal_condition_certificate_ids",
    )
    dual_ids = _sequence(
        payload["dual_condition_certificate_ids"],
        "dual_condition_certificate_ids",
    )
    if not (len(pairing_ids) == len(primal_ids) == len(dual_ids) == len(checks)):
        raise ArithmeticVerificationError("dual Selmer role manifests have different lengths")
    local_blocks = _sequence(payload["local_blocks"], "local_blocks")
    place_ids = _sequence(payload["place_ids"], "place_ids")
    for index, (check, pairing_id, primal_id, dual_id, local_block, place_id) in enumerate(
        zip(
            checks,
            pairing_ids,
            primal_ids,
            dual_ids,
            local_blocks,
            place_ids,
            strict=True,
        )
    ):
        if not isinstance(check, Mapping):
            raise ArithmeticVerificationError("orthogonality check must be a mapping")
        if not isinstance(local_block, Mapping):
            raise ArithmeticVerificationError("dual Selmer local block is malformed")
        required_check = {
            "pairing",
            "left_basis",
            "right_basis",
            "left_dimension",
            "right_dimension",
        }
        _check_exact_keys(check, required_check)
        prime = _strict_int(payload["prime"], "prime", minimum=2)
        left_dimension = _strict_int(check["left_dimension"], "left_dimension", minimum=0)
        right_dimension = _strict_int(check["right_dimension"], "right_dimension", minimum=0)
        pairing_rows = _rows(
            check["pairing"],
            f"orthogonality_checks[{index}].pairing",
            prime=prime,
            ncols=right_dimension,
        )
        if len(pairing_rows) != left_dimension:
            raise ArithmeticVerificationError("dual Selmer pairing has the wrong row count")
        field = PrimeField(prime)
        pairing = DenseMatrix(field, pairing_rows, ncols=right_dimension)
        if left_dimension != right_dimension or rank(pairing) != left_dimension:
            raise ArithmeticVerificationError("dual Selmer local pairing is not perfect")
        left_basis = _rows(
            check["left_basis"],
            f"orthogonality_checks[{index}].left_basis",
            prime=prime,
            ncols=left_dimension,
        )
        right_basis = _rows(
            check["right_basis"],
            f"orthogonality_checks[{index}].right_basis",
            prime=prime,
            ncols=right_dimension,
        )
        left = LinearSubspace(field, left_dimension, left_basis)
        right = LinearSubspace(field, right_dimension, right_basis)
        annihilator = nullspace(left.basis_matrix @ pairing)
        if right != annihilator:
            raise ArithmeticVerificationError("dual local condition is not the exact orthogonal")
        pairing_receipt = arithmetic_role(
            pairing_id,
            f"pairing_certificate_ids[{index}]",
        )
        primal_receipt = arithmetic_role(
            primal_id,
            f"primal_condition_certificate_ids[{index}]",
        )
        dual_receipt = arithmetic_role(
            dual_id,
            f"dual_condition_certificate_ids[{index}]",
        )
        if (
            pairing_receipt.kind != "local-pairing"
            or pairing_receipt.completeness is not Completeness.COMPLETE
            or pairing_receipt.payload["matrix"] != pairing.rows
            or pairing_receipt.payload["place_id"] != place_id
            or primal_receipt.kind != "local-condition"
            or primal_receipt.payload["basis"] != left.basis
            or primal_receipt.payload["place_id"] != place_id
            or dual_receipt.kind != "local-condition"
            or dual_receipt.payload["basis"] != right.basis
            or dual_receipt.payload["place_id"] != place_id
            or local_block.get("condition_certificate_id") != dual_id
        ):
            raise ArithmeticVerificationError(
                "dual Selmer role certificate is bound to different local data"
            )
    selmer_receipt = arithmetic_role(
        payload["selmer_certificate_id"],
        "selmer_certificate_id",
    )
    expected_selmer_kind = "selmer-group" if complete else "selmer-kernel"
    selmer_payload = selmer_receipt.payload.to_dict()
    if (
        selmer_receipt.kind != expected_selmer_kind
        or selmer_payload["matrix"] != payload["matrix"]
        or selmer_payload["kernel_basis"] != payload["kernel_basis"]
        or selmer_payload["global_space_id"] != payload["global_space_id"]
        or selmer_payload["place_ids"] != payload["place_ids"]
    ):
        raise ArithmeticVerificationError("dual Selmer result certificate was rebound")
    return ("perfect-local-pairings", "orthogonal-local-conditions", "recomputed-dual-kernel")


def _verify_descent(
    payload: Mapping[str, object],
    *,
    outcome: str,
    evidence_ids: tuple[str, ...],
    evidence: Sequence[VerificationCertificate],
) -> tuple[str, ...]:
    if outcome == "unknown":
        required = {"problem_id", "reason"}
        _check_exact_keys(payload, required)
        _strict_string(payload["problem_id"], "problem_id")
        _strict_string(payload["reason"], "reason")
        return ("problem-binding", "explicit-unknown-boundary")
    required = {
        "problem_id",
        "prime",
        "matrix",
        "matrix_nrows",
        "matrix_ncols",
        "target",
        "witness",
    }
    if outcome == "realized":
        required.update(
            {
                "global_space_id",
                "input_evidence_ids",
                "linear_system_id",
                "realization_kind",
                "witness_certificate_id",
                "witness_source_id",
            }
        )
    _check_exact_keys(payload, required)
    _strict_string(payload["problem_id"], "problem_id")
    matrix = _matrix_from_payload(payload)
    target = _vector(
        payload["target"],
        "target",
        prime=matrix.field.p,
        length=matrix.nrows,
    )
    witness = _vector(
        payload["witness"],
        "witness",
        prime=matrix.field.p,
        length=matrix.nrows if outcome == "obstructed" else matrix.ncols,
    )
    replay = solve(matrix, target)
    if outcome == "realized":
        advertised = tuple(
            _strict_string(item, "input_evidence_id")
            for item in _sequence(payload["input_evidence_ids"], "input_evidence_ids")
        )
        if advertised != evidence_ids:
            raise ArithmeticVerificationError("descent witness evidence manifest was altered")
        if not replay.consistent or matrix.matvec(witness) != target:
            raise ArithmeticVerificationError(
                "descent realization witness does not solve the target"
            )
        realization_kind = _strict_string(payload["realization_kind"], "realization_kind")
        if realization_kind == "finite-linear":
            if any(
                payload[field] is not None
                for field in (
                    "global_space_id",
                    "witness_certificate_id",
                    "witness_source_id",
                )
            ):
                raise ArithmeticVerificationError(
                    "finite-linear realization names an arithmetic witness source"
                )
            if payload["linear_system_id"] != content_address(matrix):
                raise ArithmeticVerificationError(
                    "finite-linear realization is bound to a different exact matrix"
                )
            witness_check = "finite-linear-realization"
        elif realization_kind == "certified-kummer-class":
            if payload["linear_system_id"] is not None:
                raise ArithmeticVerificationError(
                    "Kummer-class realization advertises a bare linear system"
                )
            witness_certificate_id = _strict_string(
                payload["witness_certificate_id"],
                "witness_certificate_id",
            )
            witness_source_id = _strict_string(
                payload["witness_source_id"],
                "witness_source_id",
            )
            global_space_id = _strict_string(
                payload["global_space_id"],
                "global_space_id",
            )
            by_id = _certificate_mapping(evidence)
            witness_certificate = by_id.get(witness_certificate_id)
            if witness_certificate is None:
                raise ArithmeticVerificationError(
                    "descent realization names missing Kummer-class evidence"
                )
            try:
                witness_receipt = KummerReceipt.from_dict(
                    _nested_witness(
                        witness_certificate,
                        verifier="galois.kummer.v1",
                        field="kummer_receipt",
                    )
                )
                witness_receipt.verify()
            except (TypeError, ValueError) as exc:
                raise ArithmeticVerificationError(
                    "descent Kummer-class witness did not replay"
                ) from exc
            if (
                witness_receipt.object_type != "class"
                or witness_receipt.content_id != witness_source_id
                or witness_receipt.coordinates != witness
            ):
                raise ArithmeticVerificationError(
                    "descent realization was rebound to a different Kummer class"
                )
            matching_space = False
            for certificate in evidence:
                if certificate.verifier != "galois.kummer.v1":
                    continue
                try:
                    space_receipt = KummerReceipt.from_dict(
                        _nested_witness(
                            certificate,
                            verifier="galois.kummer.v1",
                            field="kummer_receipt",
                        )
                    )
                    space_receipt.verify()
                except (TypeError, ValueError):
                    continue
                if (
                    space_receipt.object_type == "space"
                    and space_receipt.content_id == global_space_id
                    and space_receipt.field_id == witness_receipt.field_id
                    and space_receipt.place_ids == witness_receipt.place_ids
                    and space_receipt.generator_ids == witness_receipt.generator_ids
                ):
                    matching_space = True
                    break
            if not matching_space:
                raise ArithmeticVerificationError(
                    "descent realization lacks its bound global Kummer-space evidence"
                )
            witness_check = "certified-kummer-class-replay"
        else:
            raise ArithmeticVerificationError("unsupported descent realization kind")
        return ("problem-binding", "checked-global-witness", witness_check)
    if replay.consistent or replay.inconsistency_witness != witness:
        raise ArithmeticVerificationError("descent obstruction is not a separating witness")
    return ("problem-binding", "left-nullspace-obstruction", "nonrealization-in-linear-model")


def verify_arithmetic_receipt(receipt: ArithmeticReceipt) -> tuple[str, ...]:
    """Dispatch strict independent replay by receipt kind."""

    evidence_checks = _verify_receipt_evidence(receipt)
    payload = receipt.payload.to_dict()
    kind = receipt.kind
    evidence_ids = tuple(item.certificate_id for item in receipt.evidence)
    if kind == "local-condition":
        checks = _verify_local_condition(payload, evidence_ids)
    elif kind == "selmer-kernel":
        checks = _verify_selmer(
            payload,
            complete=False,
            evidence_ids=evidence_ids,
            evidence=receipt.evidence,
        )
    elif kind == "selmer-group":
        if receipt.completeness is not Completeness.COMPLETE:
            raise ArithmeticVerificationError("SelmerGroup receipt is not marked COMPLETE")
        checks = _verify_selmer(
            payload,
            complete=True,
            evidence_ids=evidence_ids,
            evidence=receipt.evidence,
        )
    elif kind == "local-pairing":
        checks = _verify_pairing(
            payload,
            complete=receipt.completeness is Completeness.COMPLETE,
            context=receipt.proof_context,
            evidence=receipt.evidence,
        )
    elif kind == "cartier-dual":
        checks = _verify_cartier_dual(payload)
    elif kind == "aim-affine":
        checks = _verify_aim(payload, obstruction=False)
    elif kind == "aim-obstruction":
        checks = _verify_aim(payload, obstruction=True)
    elif kind == "dual-selmer":
        checks = _verify_dual_selmer(
            payload,
            evidence_ids,
            complete=receipt.completeness is Completeness.COMPLETE,
            evidence=receipt.evidence,
        )
    elif kind == "descent-realized":
        checks = _verify_descent(
            payload,
            outcome="realized",
            evidence_ids=evidence_ids,
            evidence=receipt.evidence,
        )
    elif kind == "descent-obstructed":
        checks = _verify_descent(
            payload,
            outcome="obstructed",
            evidence_ids=evidence_ids,
            evidence=receipt.evidence,
        )
    elif kind == "descent-unknown":
        checks = _verify_descent(
            payload,
            outcome="unknown",
            evidence_ids=evidence_ids,
            evidence=receipt.evidence,
        )
    else:  # pragma: no cover - constructor and decoder already reject this
        raise ArithmeticVerificationError(f"unsupported arithmetic receipt kind: {kind}")
    if receipt.completeness not in {Completeness.CANDIDATE, Completeness.COMPLETE}:
        raise ArithmeticVerificationError("invalid completeness axis")
    normalized_assumptions(receipt.assumptions)
    return checks + evidence_checks + ("assumptions-axis", "completeness-axis")


__all__ = [
    "AimCertificate",
    "ArithmeticError",
    "ArithmeticReceipt",
    "ArithmeticVerificationError",
    "Completeness",
    "DescentCertificate",
    "DualSelmerCertificate",
    "LocalConditionCertificate",
    "LocalPairingCertificate",
    "SelmerCertificate",
    "UnsupportedArithmeticOperation",
    "coerce_completeness",
    "is_complete",
    "matrix_payload",
    "normalized_assumptions",
    "verify_arithmetic_receipt",
]
