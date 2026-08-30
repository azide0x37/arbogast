"""Versioned, backend-free receipts for Kummer, local, and twist results."""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, ClassVar, cast

from arbogast.cert import (
    CanonicalValue,
    FrozenMap,
    VerificationCertificate,
    canonicalize,
    certificate_from_dict,
    content_address,
    default_verifiers,
    freeze_mapping,
)
from arbogast.formats import (
    KUMMER_RECEIPT_SCHEMA,
    LOCAL_H1_RECEIPT_SCHEMA,
    LOCALIZATION_RECEIPT_SCHEMA,
    TWIST_RECEIPT_SCHEMA,
)

from ._common import (
    Rows,
    Vector,
    canonical_matrix,
    integer_tuple,
    rows_tuple,
    sequence,
    strict_integer,
    strict_string,
    string_tuple,
    validate_group_table,
)


class ArithmeticCertificateError(ValueError):
    """Raised when a finite arithmetic receipt fails independent replay."""


SUPPLIED_PRESENTATION_WITNESS_SCHEMA = "arbogast.galois.supplied-presentation-witness/v1"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _mapping_tuple(value: object, name: str) -> tuple[FrozenMap, ...]:
    return tuple(
        freeze_mapping(_mapping(item, f"{name}[{index}]"))
        for index, item in enumerate(sequence(value, name))
    )


def _optional_coordinates(value: object, name: str) -> Vector | None:
    if value is None:
        return None
    return integer_tuple(value, name)


def _require_fields(
    payload: Mapping[str, object],
    required: set[str],
    *,
    record: str,
) -> None:
    actual = set(payload)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        raise ValueError(f"{record} fields mismatch; missing={missing}, extra={extra}")


def _reject_backend_leaks(value: object) -> None:
    forbidden = {
        "gp_handle",
        "pari_handle",
        "session",
        "session_index",
        "printed_padic",
        "polredbest_identification",
    }
    if isinstance(value, Mapping):
        leaked = forbidden.intersection(value)
        if leaked:
            raise ArithmeticCertificateError(
                f"backend-local fields cannot cross the proof boundary: {sorted(leaked)}"
            )
        for item in value.values():
            _reject_backend_leaks(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_backend_leaks(item)


def _content_bound(identifier: str, value: object, name: str) -> None:
    if content_address(value) != identifier:
        raise ArithmeticCertificateError(f"{name} is not bound to its canonical snapshot")


def _requirement_records(
    context: Mapping[str, object],
    *,
    portable_verifier: str,
    allow_supplied_external: bool = False,
) -> tuple[Mapping[str, object], ...]:
    raw_requirements = sequence(
        context.get("verification_requirements"),
        "proof_context.verification_requirements",
    )
    result: list[Mapping[str, object]] = []
    expected_fields = {"type", "verifier", "trust", "version", "capabilities"}
    for index, raw in enumerate(raw_requirements):
        item = _mapping(raw, f"verification_requirements[{index}]")
        if set(item) != expected_fields:
            raise ArithmeticCertificateError("verification requirement fields were altered")
        if item.get("type") != "arbogast.verification_requirement":
            raise ArithmeticCertificateError("invalid verification requirement type")
        trust = item.get("trust")
        verifier = item.get("verifier")
        version = item.get("version")
        capabilities = string_tuple(item.get("capabilities"), "requirement.capabilities")
        if capabilities != tuple(sorted(set(capabilities))):
            raise ArithmeticCertificateError(
                "verification requirement capabilities are not canonical"
            )
        if trust == "portable-python":
            if verifier != portable_verifier or version is not None:
                raise ArithmeticCertificateError(
                    "portable arithmetic requirement names an unrecognized verifier"
                )
        elif trust == "pinned-external":
            is_pari = isinstance(verifier, str) and (
                verifier == "pari"
                or verifier.startswith("pari.")
                or verifier == "arbogast.backends.pari.v1"
            )
            if (
                not isinstance(verifier, str)
                or not verifier
                or not (is_pari or allow_supplied_external)
            ):
                raise ArithmeticCertificateError(
                    "external arithmetic verifier is outside this presentation boundary"
                )
            if not isinstance(version, str) or not version:
                raise ArithmeticCertificateError("external verification must pin a version")
        else:
            raise ArithmeticCertificateError("unknown arithmetic verifier trust boundary")
        if not capabilities:
            raise ArithmeticCertificateError(
                "arithmetic verification requirement has no capability"
            )
        result.append(item)
    return tuple(result)


def _canonical_context_requirements(
    context: Mapping[str, object],
    *,
    portable_verifier: str,
    allow_supplied_external: bool = False,
) -> tuple[Mapping[str, object], ...]:
    expected_fields = {
        "assumptions",
        "completeness",
        "type",
        "verification_requirements",
    }
    if set(context) != expected_fields or context.get("type") != "arbogast.proof_context":
        raise ArithmeticCertificateError("arithmetic proof context is not canonical")
    assumptions = string_tuple(context.get("assumptions"), "proof_context.assumptions")
    if assumptions != tuple(sorted(set(assumptions))):
        raise ArithmeticCertificateError("arithmetic assumptions are not canonical")
    if context.get("completeness") not in {"candidate", "complete"}:
        raise ArithmeticCertificateError("arithmetic completeness is invalid")
    requirements = _requirement_records(
        context,
        portable_verifier=portable_verifier,
        allow_supplied_external=allow_supplied_external,
    )
    keys = tuple(
        (
            cast(str, requirement.get("verifier")),
            cast(str, requirement.get("trust")),
            cast(str | None, requirement.get("version")) or "",
            string_tuple(requirement.get("capabilities"), "requirement.capabilities"),
        )
        for requirement in requirements
    )
    if len(set(keys)) != len(keys) or keys != tuple(sorted(keys)):
        raise ArithmeticCertificateError("verification requirements are not canonical")
    return requirements


def _rational_constant(snapshot: object) -> Fraction:
    item = _mapping(snapshot, "number-field element")
    if item.get("type") != "arbogast.number_field_element":
        raise ArithmeticCertificateError("squareclass representative is not a field element")
    coefficients = sequence(item.get("coefficients"), "element.coefficients")
    if not coefficients:
        raise ArithmeticCertificateError("field element has no coefficients")
    pair = integer_tuple(coefficients[0], "element.coefficients[0]")
    if len(pair) != 2 or pair[1] == 0:
        raise ArithmeticCertificateError("field element has an invalid rational coefficient")
    for index, coefficient in enumerate(coefficients[1:], start=1):
        trailing = integer_tuple(coefficient, f"element.coefficients[{index}]")
        if len(trailing) != 2 or trailing[1] == 0 or trailing[0] != 0:
            raise ArithmeticCertificateError("field element is not a rational constant")
    return Fraction(pair[0], pair[1])


def _rational_field_id() -> str:
    from .fields import NumberField

    return NumberField.rationals().field_id


def _verify_rational_real_place(place: Mapping[str, object]) -> None:
    if place.get("field_id") != _rational_field_id():
        return
    pairs = tuple(
        integer_tuple(value, f"real isolation[{index}]")
        for index, value in enumerate(sequence(place.get("isolation"), "real isolation"))
    )
    if any(len(pair) != 2 or pair[1] <= 0 for pair in pairs):
        raise ArithmeticCertificateError("rational real-place isolation is malformed")
    isolation = tuple(Fraction(pair[0], pair[1]) for pair in pairs)
    if len(isolation) != 2 or not isolation[0] < 0 < isolation[1]:
        raise ArithmeticCertificateError(
            "rational real-place isolation does not contain the unique root"
        )
    if place.get("embedding_index") != 0:
        raise ArithmeticCertificateError("the rational real place has the wrong index")


def _verify_relevant_place_set_witness(
    receipt: KummerReceipt,
    certificates: tuple[VerificationCertificate, ...] = (),
) -> bool:
    """Replay the place-set-completeness axis independently of K(S,p)."""

    raw = receipt.completeness_witness.get("relevant_place_set")
    if raw is None:
        return False
    witness = _mapping(raw, "witness.relevant_place_set")
    schema = witness.get("schema")
    coefficient_place_key = (
        "coefficient_prime_place_ids"
        if schema == "arbogast.galois.relevant-place-set/v2"
        else "dyadic_place_ids"
    )
    required = {
        "schema",
        "method",
        "prime",
        "place_ids",
        "archimedean_place_ids",
        "discriminant_place_ids",
        "ramified_place_ids",
        coefficient_place_key,
        "complete",
        "evidence",
    }
    if set(witness) != required:
        raise ArithmeticCertificateError("relevant-place-set witness fields were altered")
    if schema not in {
        "arbogast.galois.relevant-place-set/v1",
        "arbogast.galois.relevant-place-set/v2",
    }:
        raise ArithmeticCertificateError("unsupported relevant-place-set witness schema")
    if strict_integer(witness.get("prime"), "relevant-place-set prime") != receipt.prime:
        raise ArithmeticCertificateError("relevant-place-set witness has the wrong prime")
    place_ids = string_tuple(witness.get("place_ids"), "relevant place IDs")
    if place_ids != receipt.place_ids:
        raise ArithmeticCertificateError(
            "relevant-place-set witness is bound to a different place set"
        )

    expected_archimedean = tuple(
        identifier
        for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.infinite_place"
    )
    expected_coefficient_places = tuple(
        identifier
        for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.finite_place"
        and strict_integer(place.get("rational_prime"), "rational_prime") == receipt.prime
    )
    categories = (
        (
            "archimedean_place_ids",
            "archimedean place IDs",
            expected_archimedean,
        ),
        (
            coefficient_place_key,
            "coefficient-prime place IDs",
            expected_coefficient_places,
        ),
    )
    for key, name, expected in categories:
        actual = string_tuple(witness.get(key), name)
        if actual != expected:
            raise ArithmeticCertificateError(f"relevant-place-set witness has incorrect {name}")

    complete = witness.get("complete")
    if not isinstance(complete, bool):
        raise ArithmeticCertificateError("relevant-place-set completeness is not boolean")
    method = witness.get("method")
    if method == "portable-rational-mu2-relevant-places-v1":
        if schema != "arbogast.galois.relevant-place-set/v1":
            raise ArithmeticCertificateError("portable mu2 relevant places require schema v1")
        if witness.get("evidence") is not None:
            raise ArithmeticCertificateError(
                "portable rational relevant-place evidence must be self-contained"
            )
        if receipt.field_id != _rational_field_id() or receipt.prime != 2:
            raise ArithmeticCertificateError(
                "portable relevant-place completeness is only available for Q and p=2"
            )
        expected_complete = len(expected_archimedean) == 1 and len(expected_coefficient_places) == 1
        expected_ramified: tuple[str, ...] = ()
        expected_discriminant: tuple[str, ...] = ()
        if complete is not expected_complete:
            raise ArithmeticCertificateError(
                "portable relevant-place completeness contradicts the declared Q places"
            )
    elif method == "declared-place-set-only-v1":
        if witness.get("evidence") is not None:
            raise ArithmeticCertificateError(
                "a declared-only place set cannot carry proving evidence"
            )
        expected_ramified = tuple(
            identifier
            for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
            if place.get("type") == "arbogast.finite_place"
            and strict_integer(place.get("ramification_index"), "ramification_index") > 1
        )
        expected_discriminant = ()
        if complete:
            raise ArithmeticCertificateError(
                "a declared place set without enumeration evidence cannot be complete"
            )
    elif method == "pari-field-and-prime-decomposition-v1":
        if receipt.prime != 2 or schema != "arbogast.galois.relevant-place-set/v1":
            raise ArithmeticCertificateError("PARI relevant-place closure is only for p=2")
        expected_discriminant, expected_ramified = _verify_pari_relevant_place_set(
            receipt,
            witness,
            certificates,
        )
        if not complete:
            raise ArithmeticCertificateError(
                "complete PARI relevant-place evidence cannot advertise candidate status"
            )
    elif method == "certified-supplied-relevant-places-v1":
        if schema != "arbogast.galois.relevant-place-set/v2":
            raise ArithmeticCertificateError("certified supplied relevant places require schema v2")
        evidence = _mapping(witness.get("evidence"), "supplied relevant-place evidence")
        if set(evidence) != {"operation"} or evidence.get("operation") != (
            "supplied_kummer_presentation"
        ):
            raise ArithmeticCertificateError(
                "supplied relevant-place evidence names a different certificate role"
            )
        if not complete:
            raise ArithmeticCertificateError(
                "certified supplied relevant places cannot advertise candidate status"
            )
        matching = tuple(
            certificate
            for certificate in certificates
            if certificate.witness.get("operation") == "supplied_kummer_presentation"
        )
        if len(matching) != 1:
            raise ArithmeticCertificateError(
                "supplied relevant places lack their unique presentation certificate"
            )
        expected_ramified = tuple(
            identifier
            for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
            if place.get("type") == "arbogast.finite_place"
            and strict_integer(place.get("ramification_index"), "ramification_index") > 1
        )
        expected_discriminant = string_tuple(
            witness.get("discriminant_place_ids"),
            "discriminant place IDs",
        )
        finite_place_ids = {
            identifier
            for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
            if place.get("type") == "arbogast.finite_place"
        }
        if not set(expected_discriminant).issubset(finite_place_ids):
            raise ArithmeticCertificateError(
                "supplied discriminant-place evidence names a nonfinite place"
            )
    else:
        raise ArithmeticCertificateError("unrecognized relevant-place-set witness method")
    actual_ramified = string_tuple(
        witness.get("ramified_place_ids"),
        "ramified place IDs",
    )
    if actual_ramified != expected_ramified:
        raise ArithmeticCertificateError(
            "relevant-place-set witness has incorrect ramified place IDs"
        )
    actual_discriminant = string_tuple(
        witness.get("discriminant_place_ids"),
        "discriminant place IDs",
    )
    if actual_discriminant != expected_discriminant:
        raise ArithmeticCertificateError(
            "relevant-place-set witness has incorrect discriminant place IDs"
        )
    return complete


def relevant_places_complete(receipt: KummerReceipt) -> bool:
    """Return the independently replayed relevant-place-set completeness fact."""

    if not isinstance(receipt, KummerReceipt):
        raise TypeError("receipt must be a KummerReceipt")
    receipt.verify()
    certificates = _decode_proving_certificates(receipt.proving_certificates)
    return _verify_relevant_place_set_witness(receipt, certificates)


def _verify_rational_kummer_witness(receipt: KummerReceipt) -> None:
    if receipt.prime != 2:
        raise ArithmeticCertificateError("portable rational Kummer completeness is only for p=2")
    field = receipt.field
    if field.get("type") != "arbogast.number_field":
        raise ArithmeticCertificateError("portable rational witness has an invalid field")
    polynomial = integer_tuple(field.get("defining_polynomial"), "defining_polynomial")
    if len(polynomial) != 2:
        raise ArithmeticCertificateError("portable rational witness requires a degree-one field")
    finite_primes: list[int] = []
    real_places = 0
    for place in receipt.places:
        if place.get("field_id") != receipt.field_id:
            raise ArithmeticCertificateError("Kummer place is bound to a different field")
        place_type = place.get("type")
        if place_type == "arbogast.finite_place":
            rational_prime = strict_integer(place.get("rational_prime"), "rational_prime")
            ideal_hnf = rows_tuple(place.get("ideal_hnf"), "ideal_hnf")
            if ideal_hnf != ((rational_prime,),):
                raise ArithmeticCertificateError("rational finite-place HNF is not (p)")
            if place.get("ramification_index") != 1 or place.get("residue_degree") != 1:
                raise ArithmeticCertificateError("rational finite-place invariants are invalid")
            finite_primes.append(rational_prime)
        elif place_type == "arbogast.infinite_place":
            if place.get("kind") != "real":
                raise ArithmeticCertificateError("the rational field has no complex place")
            _verify_rational_real_place(place)
            real_places += 1
        else:
            raise ArithmeticCertificateError("unknown place in rational Kummer witness")
    if real_places != 1:
        raise ArithmeticCertificateError("rational Kummer witness must declare its real place")
    if len(set(finite_primes)) != len(finite_primes):
        raise ArithmeticCertificateError("rational Kummer witness repeats a finite prime")
    expected_values = (Fraction(-1), *(Fraction(prime) for prime in sorted(finite_primes)))
    actual_values = tuple(_rational_constant(item) for item in receipt.generators)
    if actual_values != expected_values:
        raise ArithmeticCertificateError("rational S-Kummer basis is not [-1] plus S-primes")
    witness = receipt.completeness_witness
    if tuple(witness["s_unit_generators"]) != receipt.generator_ids:
        raise ArithmeticCertificateError("S-unit witness is not bound to the Kummer basis")
    if tuple(witness["class_group_p_torsion"]):
        raise ArithmeticCertificateError("the rational class-group 2-torsion must be empty")
    if tuple(witness["principalization_witnesses"]):
        raise ArithmeticCertificateError("the rational principalization list must be empty")


def _verify_portable_local_presentation(receipt: LocalH1Receipt) -> None:
    if receipt.prime != 2:
        raise ArithmeticCertificateError("portable local completeness is only for mu2")
    place = receipt.place
    if any(
        _mapping(item, "local basis element").get("field_id") != place.get("field_id")
        for item in receipt.basis
    ):
        raise ArithmeticCertificateError("local basis element belongs to a different field")
    method = receipt.presentation.get("method")
    if receipt.presentation.get("place_id") != receipt.place_id:
        raise ArithmeticCertificateError("local presentation is bound to a different place")
    if tuple(receipt.presentation.get("basis_ids", ())) != receipt.basis_ids:
        raise ArithmeticCertificateError("local presentation is bound to a different basis")
    if receipt.presentation.get("perfect_kummer_identification") is not True:
        raise ArithmeticCertificateError("local Kummer identification witness is absent")
    values = tuple(_rational_constant(item) for item in receipt.basis)
    if method == "portable-real-mu2-v1":
        if place.get("type") != "arbogast.infinite_place" or place.get("kind") != "real":
            raise ArithmeticCertificateError("real mu2 presentation has the wrong place")
        _verify_rational_real_place(place)
        if values != (Fraction(-1),):
            raise ArithmeticCertificateError("real squareclass basis must be [-1]")
    elif method == "portable-complex-mu2-v1":
        if place.get("type") != "arbogast.infinite_place" or place.get("kind") != "complex":
            raise ArithmeticCertificateError("complex mu2 presentation has the wrong place")
        if values:
            raise ArithmeticCertificateError("complex local H1(mu2) must be zero-dimensional")
    elif method == "portable-q2-squareclasses-v1":
        if place.get("type") != "arbogast.finite_place" or place.get("rational_prime") != 2:
            raise ArithmeticCertificateError("Q2 presentation has the wrong finite place")
        if place.get("field_id") != _rational_field_id():
            raise ArithmeticCertificateError("Q2 presentation is not over the rational field")
        if values != (Fraction(-1), Fraction(2), Fraction(5)):
            raise ArithmeticCertificateError("Q2 squareclass basis must be [-1,2,5]")
    elif method == "portable-odd-qadic-squareclasses-v1":
        if place.get("type") != "arbogast.finite_place":
            raise ArithmeticCertificateError("odd Qp presentation has a nonfinite place")
        if place.get("field_id") != _rational_field_id():
            raise ArithmeticCertificateError("Qp presentation is not over the rational field")
        rational_prime = strict_integer(place.get("rational_prime"), "rational_prime")
        if rational_prime == 2 or len(values) != 2 or values[0] != rational_prime:
            raise ArithmeticCertificateError("odd Qp squareclass basis has wrong uniformizer")
        unit = values[1]
        if (
            unit.denominator != 1
            or pow(
                unit.numerator % rational_prime,
                (rational_prime - 1) // 2,
                rational_prime,
            )
            != rational_prime - 1
        ):
            raise ArithmeticCertificateError("odd Qp unit generator is not a nonsquare")
    else:
        raise ArithmeticCertificateError("unrecognized portable local completeness method")


def _decode_proving_certificate(
    value: Mapping[str, object] | None,
) -> VerificationCertificate | None:
    if value is None:
        return None
    try:
        certificate = certificate_from_dict(value)
    except (TypeError, ValueError) as error:
        raise ArithmeticCertificateError(
            f"invalid nested arithmetic proving certificate: {error}"
        ) from error
    if not isinstance(certificate, VerificationCertificate):
        raise ArithmeticCertificateError(
            "nested arithmetic proving evidence must be a VerificationCertificate"
        )
    return certificate


def _decode_proving_certificates(
    values: object,
) -> tuple[VerificationCertificate, ...]:
    certificates = tuple(
        cast(
            VerificationCertificate,
            _decode_proving_certificate(_mapping(value, f"proving_certificates[{index}]")),
        )
        for index, value in enumerate(sequence(values, "proving_certificates"))
    )
    certificate_ids = tuple(item.certificate_id for item in certificates)
    if len(set(certificate_ids)) != len(certificate_ids):
        raise ArithmeticCertificateError("nested proving certificates must be unique")
    return certificates


def _certificate_operation(certificate: VerificationCertificate) -> str:
    operation = certificate.witness.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ArithmeticCertificateError("nested PARI witness lacks its operation")
    return operation


def _matching_pari_requirement(
    requirements: tuple[Mapping[str, object], ...],
    *,
    operation: str,
    version: str,
) -> Mapping[str, object]:
    matching: list[Mapping[str, object]] = []
    for requirement in requirements:
        if requirement.get("trust") != "pinned-external":
            continue
        if requirement.get("verifier") != "arbogast.backends.pari.v1":
            continue
        if requirement.get("version") != version:
            continue
        capabilities = string_tuple(requirement.get("capabilities", ()), "capabilities")
        if operation in capabilities or operation.replace("_", "-") in capabilities:
            matching.append(requirement)
    if not matching:
        raise ArithmeticCertificateError("nested PARI evidence has no matching pinned requirement")
    return matching[0]


def _verify_nested_pari_certificates(
    *,
    context: Mapping[str, object],
    proving_certificates: tuple[Mapping[str, object], ...],
    allowed_operations: tuple[str, ...],
    required_operations: tuple[str, ...] = (),
    repeatable_operations: tuple[str, ...] = (),
) -> tuple[VerificationCertificate, ...]:
    certificates = _decode_proving_certificates(proving_certificates)
    requirements = _canonical_context_requirements(
        context,
        portable_verifier="unreachable.portable.verifier",
    )
    pinned = tuple(item for item in requirements if item.get("trust") == "pinned-external")
    if not pinned:
        raise ArithmeticCertificateError(
            "nested external evidence requires a pinned PARI requirement"
        )
    operations = tuple(_certificate_operation(item) for item in certificates)
    duplicated = {
        operation
        for operation in operations
        if operations.count(operation) > 1 and operation not in repeatable_operations
    }
    if duplicated:
        raise ArithmeticCertificateError(
            f"nested PARI operations must be unique: {sorted(duplicated)}"
        )
    if any(operation not in allowed_operations for operation in operations):
        raise ArithmeticCertificateError("nested PARI operation does not prove this result kind")
    missing = set(required_operations) - set(operations)
    if missing:
        raise ArithmeticCertificateError(
            f"external completeness lacks PARI operations: {sorted(missing)}"
        )
    assumptions = string_tuple(context.get("assumptions", ()), "proof_context.assumptions")
    for certificate in certificates:
        if certificate.verifier != "arbogast.backends.pari.v1":
            raise ArithmeticCertificateError(
                "nested certificate does not use the pinned PARI verifier"
            )
        witness = certificate.witness
        if witness.get("schema") != "arbogast.pari.verification-witness.v1":
            raise ArithmeticCertificateError("nested PARI witness has an unsupported schema")
        version = witness.get("backend_version")
        if not isinstance(version, str) or not version:
            raise ArithmeticCertificateError("nested PARI witness lacks its backend version")
        operation = _certificate_operation(certificate)
        _matching_pari_requirement(
            requirements,
            operation=operation,
            version=version,
        )
        if witness.get("proof_mode") == "grh-conditional" and "GRH" not in assumptions:
            raise ArithmeticCertificateError(
                "GRH-conditional PARI evidence must declare the GRH assumption"
            )
        expected_payload = _mapping(
            witness.get("expected_payload"),
            "nested PARI expected payload",
        )
        expected_payload_id = witness.get("expected_payload_id")
        if not isinstance(expected_payload_id, str):
            raise ArithmeticCertificateError("nested PARI witness lacks its expected payload ID")
        if content_address(expected_payload) != expected_payload_id:
            raise ArithmeticCertificateError("nested PARI payload ID was altered")
        if certificate.subject != f"pari:{operation}:{expected_payload_id}":
            raise ArithmeticCertificateError("nested PARI subject is not payload-bound")
        replay = _mapping(witness.get("replay"), "nested PARI replay")
        replay_field = _mapping(replay.get("field"), "nested PARI replay field")
        if replay_field.get("field_id") != expected_payload.get("field_id"):
            raise ArithmeticCertificateError(
                "nested PARI replay field differs from its expected payload"
            )
        try:
            default_verifiers.verify(certificate)
        except (TypeError, ValueError, LookupError) as error:
            raise ArithmeticCertificateError(
                f"nested PARI certificate did not replay successfully: {error}"
            ) from error
    return certificates


def _verify_supplied_presentation_certificate(
    *,
    requirements: tuple[Mapping[str, object], ...],
    proving_certificates: tuple[Mapping[str, object], ...],
    operation: str,
    expected_payload: Mapping[str, object],
) -> VerificationCertificate:
    """Replay one explicitly certified finite presentation.

    Arbogast checks the exact content binding and dispatches the certificate to
    the verifier named by the proof context.  The verifier, not a caller-set
    completeness flag, owns the arithmetic interpretation of the supplied
    finite presentation.
    """

    certificates = _decode_proving_certificates(proving_certificates)
    if len(certificates) != 1:
        raise ArithmeticCertificateError(
            "a certified supplied presentation requires exactly one proving certificate"
        )
    certificate = certificates[0]
    witness = certificate.witness
    required_fields = {
        "backend_version",
        "expected_payload",
        "expected_payload_id",
        "operation",
        "proof",
        "schema",
    }
    if set(witness) != required_fields:
        raise ArithmeticCertificateError(
            "supplied-presentation certificate witness fields were altered"
        )
    if witness.get("schema") != SUPPLIED_PRESENTATION_WITNESS_SCHEMA:
        raise ArithmeticCertificateError("unsupported supplied-presentation witness schema")
    if witness.get("operation") != operation:
        raise ArithmeticCertificateError(
            "supplied-presentation certificate proves a different operation"
        )
    certified_payload = _mapping(
        witness.get("expected_payload"),
        "supplied-presentation expected payload",
    )
    if canonicalize(certified_payload) != canonicalize(expected_payload):
        raise ArithmeticCertificateError(
            "supplied-presentation certificate is bound to different data"
        )
    expected_id = content_address(expected_payload)
    if witness.get("expected_payload_id") != expected_id:
        raise ArithmeticCertificateError("supplied-presentation payload ID was altered")
    if certificate.subject != f"galois:supplied:{operation}:{expected_id}":
        raise ArithmeticCertificateError("supplied-presentation subject is not payload-bound")

    matches = []
    for requirement in requirements:
        capabilities = string_tuple(
            requirement.get("capabilities", ()),
            "requirement.capabilities",
        )
        if (
            requirement.get("verifier") == certificate.verifier
            and requirement.get("version") == witness.get("backend_version")
            and (operation in capabilities or operation.replace("_", "-") in capabilities)
        ):
            matches.append(requirement)
    if len(matches) != 1:
        raise ArithmeticCertificateError(
            "supplied-presentation certificate has no unique matching verifier requirement"
        )
    try:
        default_verifiers.verify(certificate)
    except (TypeError, ValueError, LookupError) as error:
        raise ArithmeticCertificateError(
            f"supplied-presentation certificate did not replay successfully: {error}"
        ) from error
    _reject_backend_leaks(witness.get("proof"))
    return certificate


def _coefficient_vector(value: object, name: str) -> tuple[tuple[int, int], ...]:
    result = tuple(
        cast(tuple[int, int], integer_tuple(item, f"{name}[{index}]"))
        for index, item in enumerate(sequence(value, name))
    )
    for index, pair in enumerate(result):
        if len(pair) != 2 or pair[1] <= 0:
            raise ArithmeticCertificateError(f"{name}[{index}] is not a canonical rational pair")
        normalized = Fraction(pair[0], pair[1])
        if (normalized.numerator, normalized.denominator) != pair:
            raise ArithmeticCertificateError(f"{name}[{index}] is not a reduced rational pair")
    return result


def _element_coefficients(value: object, name: str) -> tuple[tuple[int, int], ...]:
    element = _mapping(value, name)
    if element.get("type") != "arbogast.number_field_element":
        raise ArithmeticCertificateError(f"{name} is not a number-field element")
    return _coefficient_vector(element.get("coefficients"), f"{name}.coefficients")


def _certificate_payload(certificate: VerificationCertificate) -> Mapping[str, object]:
    return _mapping(
        certificate.witness.get("expected_payload"),
        "nested PARI expected payload",
    )


def _prime_factorization(value: int) -> tuple[tuple[int, int], ...] | None:
    remaining = abs(value)
    if remaining == 0:
        return None
    if remaining <= 1:
        return ()
    result: list[tuple[int, int]] = []
    divisor = 2
    trials = 0
    while divisor * divisor <= remaining:
        trials += 1
        if trials > 1_000_000:
            return None
        if remaining % divisor == 0:
            exponent = 0
            while remaining % divisor == 0:
                remaining //= divisor
                exponent += 1
            result.append((divisor, exponent))
        divisor = 3 if divisor == 2 else divisor + 2
    if remaining > 1:
        result.append((remaining, 1))
    return tuple(result)


def _fraction_vector(value: object, name: str, length: int) -> tuple[Fraction, ...]:
    pairs = tuple(
        integer_tuple(item, f"{name}[{index}]") for index, item in enumerate(sequence(value, name))
    )
    if len(pairs) != length or any(len(pair) != 2 or pair[1] <= 0 for pair in pairs):
        raise ArithmeticCertificateError(f"{name} is malformed")
    result = tuple(Fraction(pair[0], pair[1]) for pair in pairs)
    if any(
        (number.numerator, number.denominator) != pair
        for number, pair in zip(result, pairs, strict=True)
    ):
        raise ArithmeticCertificateError(f"{name} is not canonical")
    return result


def _finite_place_key(value: Mapping[str, object], name: str) -> str:
    return content_address(
        {
            "ideal_hnf": rows_tuple(value.get("ideal_hnf"), f"{name}.ideal_hnf"),
            "ramification_index": strict_integer(
                value.get("ramification_index"),
                f"{name}.ramification_index",
            ),
            "residue_degree": strict_integer(
                value.get("residue_degree"),
                f"{name}.residue_degree",
            ),
        }
    )


def _verify_archimedean_place_set(
    receipt: KummerReceipt,
    signature: tuple[int, int],
    certificates_by_id: Mapping[str, VerificationCertificate],
    isolation_entries: tuple[Mapping[str, object], ...],
) -> None:
    from .places import (
        _sturm_sequence,
        _variations_at,
        _variations_at_negative_infinity,
    )

    polynomial = integer_tuple(
        receipt.field.get("defining_polynomial"),
        "defining_polynomial",
    )
    real_places = tuple(
        place
        for place in receipt.places
        if place.get("type") == "arbogast.infinite_place" and place.get("kind") == "real"
    )
    complex_places = tuple(
        (identifier, place)
        for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.infinite_place" and place.get("kind") == "complex"
    )
    if len(real_places) != signature[0] or len(complex_places) != signature[1]:
        raise ArithmeticCertificateError(
            "PARI signature disagrees with the declared archimedean places"
        )
    real_indices = tuple(
        sorted(
            strict_integer(place.get("embedding_index"), "real embedding index")
            for place in real_places
        )
    )
    complex_indices = tuple(
        sorted(
            strict_integer(place.get("embedding_index"), "complex embedding index")
            for _, place in complex_places
        )
    )
    if real_indices != tuple(range(signature[0])) or complex_indices != tuple(range(signature[1])):
        raise ArithmeticCertificateError(
            "archimedean embedding indices are missing, duplicated, or reordered"
        )

    sturm = _sturm_sequence(polynomial)
    for place in real_places:
        lower, upper = _fraction_vector(place.get("isolation"), "real isolation", 2)
        root_count = _variations_at(sturm, lower) - _variations_at(sturm, upper)
        roots_to_left = _variations_at_negative_infinity(sturm) - _variations_at(
            sturm,
            lower,
        )
        if root_count != 1 or roots_to_left != place.get("embedding_index"):
            raise ArithmeticCertificateError(
                "real place does not isolate its canonically indexed root"
            )

    if len(polynomial) == 3:
        constant, linear, leading = polynomial
        discriminant = linear * linear - 4 * leading * constant
        for _, place in complex_places:
            if discriminant >= 0 or place.get("embedding_index") != 0:
                raise ArithmeticCertificateError("quadratic complex place is invalid")
            real_lower, real_upper, imag_lower, imag_upper = _fraction_vector(
                place.get("isolation"),
                "complex isolation",
                4,
            )
            real_coordinate = Fraction(-linear, 2 * leading)
            scale = 2 * abs(leading)
            if not (
                real_lower < real_coordinate < real_upper
                and 0 < imag_lower < imag_upper
                and (scale * imag_lower) ** 2 < -discriminant < (scale * imag_upper) ** 2
            ):
                raise ArithmeticCertificateError(
                    "quadratic complex place does not isolate its root"
                )
        if isolation_entries:
            raise ArithmeticCertificateError(
                "portable quadratic complex places cannot name external isolation evidence"
            )
        return

    expected_place_ids = tuple(identifier for identifier, _ in complex_places)
    actual_place_ids = tuple(
        strict_string(entry.get("place_id"), "complex-isolation place ID")
        for entry in isolation_entries
    )
    if actual_place_ids != expected_place_ids:
        raise ArithmeticCertificateError(
            "complex-isolation evidence is missing, duplicated, or reordered"
        )
    for entry, (place_id, place) in zip(
        isolation_entries,
        complex_places,
        strict=True,
    ):
        certificate_id = strict_string(
            entry.get("certificate_id"),
            "complex-isolation certificate ID",
        )
        certificate = certificates_by_id.get(certificate_id)
        if certificate is None or _certificate_operation(certificate) != ("complex_root_isolation"):
            raise ArithmeticCertificateError(
                "complex place lacks its nested root-isolation certificate"
            )
        payload = _certificate_payload(certificate)
        if (
            payload.get("field_id") != receipt.field_id
            or payload.get("embedding_index") != place.get("embedding_index")
            or payload.get("kind") != "complex"
            or payload.get("root_count") != 1
            or canonicalize(payload.get("isolation")) != canonicalize(place.get("isolation"))
            or place_id != entry.get("place_id")
        ):
            raise ArithmeticCertificateError(
                "complex root-isolation certificate is bound to another place"
            )

    rectangles = tuple(
        _fraction_vector(place.get("isolation"), "complex isolation", 4)
        for _, place in complex_places
    )
    for left_index, left in enumerate(rectangles):
        for right in rectangles[left_index + 1 :]:
            real_disjoint = left[1] <= right[0] or right[1] <= left[0]
            imaginary_disjoint = left[3] <= right[2] or right[3] <= left[2]
            if not (real_disjoint or imaginary_disjoint):
                raise ArithmeticCertificateError(
                    "complex isolation rectangles are not pairwise disjoint"
                )
    # Each pinned Rouché receipt proves one positive-imaginary root in its
    # rectangle.  Pairwise disjointness makes those roots distinct, while the
    # independently replayed signature says there are exactly r_2 of them.
    # Thus the canonically indexed family is exhaustive as well as injective.
    if len(rectangles) != signature[1]:
        raise ArithmeticCertificateError(
            "complex isolation batch does not exhaust the certified signature"
        )


def _verify_pari_relevant_place_set(
    receipt: KummerReceipt,
    witness: Mapping[str, object],
    certificates: tuple[VerificationCertificate, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    evidence = _mapping(witness.get("evidence"), "relevant-place-set evidence")
    required_fields = {
        "complex_isolation_certificates",
        "discriminant",
        "discriminant_factorization",
        "field_invariants_certificate_id",
        "prime_decomposition_certificates",
        "signature",
    }
    if set(evidence) != required_fields:
        raise ArithmeticCertificateError("PARI relevant-place evidence fields were altered")
    certificates_by_id = {item.certificate_id: item for item in certificates}
    invariants_id = strict_string(
        evidence.get("field_invariants_certificate_id"),
        "field-invariants certificate ID",
    )
    invariants_certificate = certificates_by_id.get(invariants_id)
    if (
        invariants_certificate is None
        or _certificate_operation(invariants_certificate) != "field_invariants"
    ):
        raise ArithmeticCertificateError(
            "relevant-place evidence lacks its field-invariants certificate"
        )
    invariants = _certificate_payload(invariants_certificate)
    discriminant = strict_integer(evidence.get("discriminant"), "field discriminant")
    signature = integer_tuple(evidence.get("signature"), "field signature")
    polynomial = integer_tuple(
        receipt.field.get("defining_polynomial"),
        "defining_polynomial",
    )
    if (
        len(signature) != 2
        or signature[0] < 0
        or signature[1] < 0
        or signature[0] + 2 * signature[1] != len(polynomial) - 1
        or invariants.get("field_id") != receipt.field_id
        or invariants.get("degree") != len(polynomial) - 1
        or invariants.get("discriminant") != discriminant
        or integer_tuple(invariants.get("signature"), "certified field signature") != signature
        or canonicalize(invariants.get("integral_basis"))
        != canonicalize(receipt.field.get("integral_basis"))
    ):
        raise ArithmeticCertificateError(
            "field-invariants evidence is bound to different field data"
        )

    raw_decompositions = sequence(
        evidence.get("prime_decomposition_certificates"),
        "prime-decomposition evidence",
    )
    decomposition_entries = tuple(
        _mapping(item, f"prime-decomposition evidence[{index}]")
        for index, item in enumerate(raw_decompositions)
    )
    if any(set(entry) != {"certificate_id", "rational_prime"} for entry in decomposition_entries):
        raise ArithmeticCertificateError("prime-decomposition evidence fields were altered")
    discriminant_factorization = _prime_factorization(discriminant)
    if discriminant_factorization is None:
        raise ArithmeticCertificateError(
            "discriminant factorization exceeded the portable replay budget"
        )
    advertised_factorization = tuple(
        integer_tuple(item, f"discriminant factorization[{index}]")
        for index, item in enumerate(
            sequence(
                evidence.get("discriminant_factorization"),
                "discriminant factorization",
            )
        )
    )
    if advertised_factorization != discriminant_factorization:
        raise ArithmeticCertificateError(
            "discriminant factorization failed independent exact replay"
        )
    discriminant_primes = tuple(prime for prime, _ in discriminant_factorization)
    required_primes = tuple(sorted({2, *discriminant_primes}))
    actual_primes = tuple(
        strict_integer(entry.get("rational_prime"), "decomposed rational prime")
        for entry in decomposition_entries
    )
    if actual_primes != required_primes:
        raise ArithmeticCertificateError(
            "prime-decomposition evidence is missing, duplicated, or reordered"
        )
    for entry, rational_prime in zip(
        decomposition_entries,
        required_primes,
        strict=True,
    ):
        certificate_id = strict_string(
            entry.get("certificate_id"),
            "prime-decomposition certificate ID",
        )
        certificate = certificates_by_id.get(certificate_id)
        if certificate is None or _certificate_operation(certificate) != ("prime_decomposition"):
            raise ArithmeticCertificateError(
                "relevant-place evidence lacks a prime-decomposition certificate"
            )
        payload = _certificate_payload(certificate)
        if (
            payload.get("field_id") != receipt.field_id
            or payload.get("rational_prime") != rational_prime
        ):
            raise ArithmeticCertificateError(
                "prime-decomposition evidence is bound to another field or prime"
            )
        records = tuple(
            _mapping(item, "prime-decomposition record")
            for item in sequence(payload.get("prime_ideals"), "prime ideals")
        )
        supplied = tuple(
            place
            for place in receipt.places
            if place.get("type") == "arbogast.finite_place"
            and place.get("rational_prime") == rational_prime
        )
        if sorted(
            _finite_place_key(item, "prime-decomposition record") for item in records
        ) != sorted(_finite_place_key(item, "declared finite place") for item in supplied):
            raise ArithmeticCertificateError(
                "declared finite places do not equal the complete PARI decomposition"
            )

    isolation_entries = tuple(
        _mapping(item, f"complex-isolation evidence[{index}]")
        for index, item in enumerate(
            sequence(
                evidence.get("complex_isolation_certificates"),
                "complex-isolation evidence",
            )
        )
    )
    if any(set(entry) != {"certificate_id", "place_id"} for entry in isolation_entries):
        raise ArithmeticCertificateError("complex-isolation evidence fields were altered")
    referenced_certificate_ids = {
        invariants_id,
        *(
            strict_string(entry.get("certificate_id"), "prime-decomposition certificate ID")
            for entry in decomposition_entries
        ),
        *(
            strict_string(entry.get("certificate_id"), "complex-isolation certificate ID")
            for entry in isolation_entries
        ),
    }
    actual_relevant_certificate_ids = {
        certificate.certificate_id
        for certificate in certificates
        if _certificate_operation(certificate)
        in {
            "complex_root_isolation",
            "field_invariants",
            "prime_decomposition",
        }
    }
    if actual_relevant_certificate_ids != referenced_certificate_ids:
        raise ArithmeticCertificateError(
            "relevant-place evidence has missing or unreferenced certificates"
        )
    _verify_archimedean_place_set(
        receipt,
        signature,
        certificates_by_id,
        isolation_entries,
    )
    ramified_primes = set(discriminant_primes)
    discriminant_place_ids = tuple(
        identifier
        for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.finite_place"
        and place.get("rational_prime") in ramified_primes
    )
    ramified_place_ids = tuple(
        identifier
        for identifier, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.finite_place"
        and strict_integer(place.get("ramification_index"), "ramification_index") > 1
    )
    return discriminant_place_ids, ramified_place_ids


def _verify_kummer_pari_payloads(
    receipt: KummerReceipt,
    certificates: tuple[VerificationCertificate, ...],
) -> None:
    versions = {item.witness.get("backend_version") for item in certificates}
    if len(versions) != 1 or not all(isinstance(item, str) for item in versions):
        raise ArithmeticCertificateError("one Kummer proof bundle cannot mix pinned PARI versions")
    s_unit_certificates = tuple(
        item for item in certificates if _certificate_operation(item) == "s_unit_squareclasses"
    )
    if len(s_unit_certificates) > 1:
        raise ArithmeticCertificateError("Kummer evidence repeats its S-unit certificate")
    s_unit_certificate = s_unit_certificates[0] if s_unit_certificates else None
    if s_unit_certificate is None:
        # A partial certificate is meaningful for a candidate presentation but
        # cannot bind a claimed Kummer basis by itself.
        if receipt.proof_context.get("completeness") == "complete":
            raise ArithmeticCertificateError("complete Kummer evidence lacks S-unit replay")
        return
    s_unit_payload = _certificate_payload(s_unit_certificate)
    if s_unit_payload.get("field_id") != receipt.field_id:
        raise ArithmeticCertificateError("PARI S-unit evidence belongs to a different field")
    finite_hnfs = tuple(
        place.get("ideal_hnf")
        for place in receipt.places
        if place.get("type") == "arbogast.finite_place"
    )
    payload_hnfs = tuple(sequence(s_unit_payload.get("prime_ideal_hnfs"), "PARI prime ideal HNFs"))
    if tuple(map(canonicalize, finite_hnfs)) != tuple(map(canonicalize, payload_hnfs)):
        raise ArithmeticCertificateError(
            "PARI S-unit evidence uses a different or reordered finite place set"
        )
    replay = _mapping(s_unit_certificate.witness.get("replay"), "PARI S-unit replay")
    replay_arguments = _mapping(replay.get("arguments"), "PARI S-unit replay arguments")
    replay_place_ids = tuple(
        strict_string(
            _mapping(value, f"PARI S-unit replay place[{index}]").get("place_id"),
            f"PARI S-unit replay place[{index}].place_id",
        )
        for index, value in enumerate(
            sequence(replay_arguments.get("places"), "PARI S-unit replay places")
        )
    )
    receipt_finite_place_ids = tuple(
        place_id
        for place_id, place in zip(receipt.place_ids, receipt.places, strict=True)
        if place.get("type") == "arbogast.finite_place"
    )
    if replay_place_ids != receipt_finite_place_ids:
        raise ArithmeticCertificateError(
            "PARI S-unit replay names a different or reordered finite place set"
        )
    generator_by_id = dict(zip(receipt.generator_ids, receipt.generators, strict=True))
    s_unit_rank = strict_integer(s_unit_payload.get("s_unit_rank"), "PARI S-unit rank")
    if s_unit_rank < 0:
        raise ArithmeticCertificateError("PARI S-unit rank cannot be negative")
    s_unit_ids = string_tuple(
        receipt.completeness_witness.get("s_unit_generators", ()),
        "witness.s_unit_generators",
    )
    if any(identifier not in generator_by_id for identifier in s_unit_ids):
        raise ArithmeticCertificateError("S-unit witness names a foreign Kummer generator")
    if len(s_unit_ids) != s_unit_rank:
        raise ArithmeticCertificateError("S-unit witness has the wrong certified rank")
    s_unit_coefficients = tuple(
        _element_coefficients(generator_by_id[identifier], "S-unit generator")
        for identifier in s_unit_ids
    )
    payload_representatives = tuple(
        _coefficient_vector(value, f"PARI S-unit representative[{index}]")
        for index, value in enumerate(
            sequence(s_unit_payload.get("representatives"), "PARI S-unit representatives")
        )
    )
    if s_unit_coefficients != payload_representatives[:s_unit_rank]:
        raise ArithmeticCertificateError("PARI S-unit representatives differ from the basis")

    s_class_orders = integer_tuple(
        s_unit_payload.get("s_class_group_cyclic_orders"),
        "PARI S-class group cyclic orders",
    )
    if any(order <= 0 for order in s_class_orders):
        raise ArithmeticCertificateError("PARI S-class cyclic orders must be positive")
    raw_torsion_records = sequence(
        s_unit_payload.get("s_class_2_torsion"),
        "PARI S-class 2-torsion",
    )
    torsion_records = tuple(
        _mapping(item, f"PARI S-class record[{index}]")
        for index, item in enumerate(raw_torsion_records)
    )
    even_orders = tuple(order for order in s_class_orders if order % 2 == 0)
    if len(torsion_records) != len(even_orders):
        raise ArithmeticCertificateError("PARI omitted an S-class 2-torsion lift")
    finite_place_count = len(finite_hnfs)
    record_ideals: list[object] = []
    for index, (record, expected_order) in enumerate(
        zip(torsion_records, even_orders, strict=True)
    ):
        cyclic_order = strict_integer(
            record.get("cyclic_order"),
            f"PARI S-class record[{index}].cyclic_order",
        )
        if cyclic_order != expected_order:
            raise ArithmeticCertificateError(
                "PARI S-class lift records are duplicated, missing, or reordered"
            )
        exponents = integer_tuple(
            record.get("s_prime_exponents"),
            f"PARI S-class record[{index}].s_prime_exponents",
        )
        if len(exponents) != finite_place_count:
            raise ArithmeticCertificateError(
                "PARI S-class lift has the wrong S-prime exponent count"
            )
        rows = tuple(
            integer_tuple(row, f"PARI S-class record[{index}].ideal_hnf")
            for row in sequence(
                record.get("ideal_hnf"),
                f"PARI S-class record[{index}].ideal_hnf",
            )
        )
        field_degree = len(_element_coefficients(receipt.generators[0], "Kummer generator"))
        if len(rows) != field_degree or any(len(row) != field_degree for row in rows):
            raise ArithmeticCertificateError(
                "PARI S-class lift ideal HNF has the wrong field degree"
            )
        if any(
            rows[row][row] <= 0
            or any(rows[row][column] != 0 for column in range(row))
            or any(
                not 0 <= rows[row][column] < rows[row][row]
                for column in range(row + 1, field_degree)
            )
            for row in range(field_degree)
        ):
            raise ArithmeticCertificateError(
                "PARI S-class lift ideal is not in canonical column HNF"
            )
        record_ideals.append(rows)
    if len({content_address(value) for value in record_ideals}) != len(record_ideals):
        raise ArithmeticCertificateError("PARI duplicated an S-class 2-torsion lift")
    if receipt.proof_context.get("completeness") == "complete" and (
        s_unit_certificate.witness.get("completeness") != "COMPLETE"
        or s_unit_payload.get("complete") is not True
    ):
        raise ArithmeticCertificateError("PARI S-Kummer evidence is only a candidate")
    lift_ids = receipt.generator_ids[s_unit_rank:]
    if receipt.generator_ids != (*s_unit_ids, *lift_ids):
        raise ArithmeticCertificateError("Kummer basis must order S-units before S-class lifts")
    if len(lift_ids) != len(torsion_records):
        raise ArithmeticCertificateError("Kummer basis has the wrong number of S-class lifts")
    lift_coefficients = tuple(
        _element_coefficients(generator_by_id[identifier], "S-class lift")
        for identifier in lift_ids
    )
    record_coefficients = tuple(
        _coefficient_vector(
            record.get("principalization_generator"),
            f"PARI S-class record[{index}].principalization_generator",
        )
        for index, record in enumerate(torsion_records)
    )
    if lift_coefficients != record_coefficients or payload_representatives[s_unit_rank:] != (
        record_coefficients
    ):
        raise ArithmeticCertificateError("S-class principalization generators differ")
    expected_class_witness = tuple(
        {
            "cyclic_order": record.get("cyclic_order"),
            "ideal_hnf": record.get("ideal_hnf"),
            "s_prime_exponents": record.get("s_prime_exponents"),
        }
        for record in torsion_records
    )
    actual_class_witness = tuple(
        sequence(
            receipt.completeness_witness.get("class_group_p_torsion", ()),
            "witness.class_group_p_torsion",
        )
    )
    if tuple(map(canonicalize, actual_class_witness)) != tuple(
        map(canonicalize, expected_class_witness)
    ):
        raise ArithmeticCertificateError("S-class torsion witnesses differ from PARI replay")
    expected_principalizations = tuple(
        {
            "ideal_hnf": record.get("ideal_hnf"),
            "principalization_generator_id": identifier,
            "s_prime_exponents": record.get("s_prime_exponents"),
        }
        for record, identifier in zip(torsion_records, lift_ids, strict=True)
    )
    actual_principalizations = tuple(
        sequence(
            receipt.completeness_witness.get("principalization_witnesses", ()),
            "witness.principalization_witnesses",
        )
    )
    if tuple(map(canonicalize, actual_principalizations)) != tuple(
        map(canonicalize, expected_principalizations)
    ):
        raise ArithmeticCertificateError(
            "S-class principalization witnesses differ from PARI replay"
        )


def _verify_local_pari_payload(
    receipt: LocalH1Receipt,
    certificate: VerificationCertificate,
) -> None:
    payload = _certificate_payload(certificate)
    if (
        receipt.proof_context.get("completeness") == "complete"
        and certificate.witness.get("completeness") != "COMPLETE"
    ):
        raise ArithmeticCertificateError("nested PARI local evidence is only a candidate")
    if payload.get("field_id") != receipt.place.get("field_id"):
        raise ArithmeticCertificateError("PARI local evidence belongs to a different field")
    if payload.get("place_id") != receipt.place_id:
        raise ArithmeticCertificateError("PARI local evidence belongs to a different place")
    payload_complete = payload.get("complete")
    if not isinstance(payload_complete, bool):
        raise ArithmeticCertificateError("PARI local completeness flag is invalid")
    if receipt.proof_context.get("completeness") == "complete" and payload_complete is not True:
        raise ArithmeticCertificateError("PARI local squareclass search is only a candidate")
    representatives = tuple(
        _coefficient_vector(value, f"PARI local representative[{index}]")
        for index, value in enumerate(
            sequence(payload.get("representatives"), "PARI local representatives")
        )
    )
    basis = tuple(
        _element_coefficients(value, f"local basis[{index}]")
        for index, value in enumerate(receipt.basis)
    )
    payload_dimension = strict_integer(payload.get("dimension"), "PARI local dimension")
    if representatives != basis:
        raise ArithmeticCertificateError("PARI local basis differs from the receipt")
    if receipt.proof_context.get("completeness") == "complete":
        if payload_dimension != receipt.dimension:
            raise ArithmeticCertificateError("complete PARI local basis has the wrong dimension")
    elif payload_dimension < receipt.dimension:
        raise ArithmeticCertificateError(
            "candidate PARI local basis exceeds its expected dimension"
        )
    if receipt.place.get("type") != "arbogast.finite_place":
        raise ArithmeticCertificateError("PARI local squareclasses require a finite place")
    for payload_key, place_key in (
        ("rational_prime", "rational_prime"),
        ("ramification_index", "ramification_index"),
        ("residue_degree", "residue_degree"),
    ):
        if payload.get(payload_key) != receipt.place.get(place_key):
            raise ArithmeticCertificateError(
                f"PARI local {payload_key} differs from the exact place"
            )


def _valuation(value: int, prime: int) -> tuple[int, int]:
    exponent = 0
    remaining = abs(value)
    while remaining and remaining % prime == 0:
        exponent += 1
        remaining //= prime
    return exponent, remaining


def _q2_coordinates(value: Fraction) -> Vector:
    numerator_v, odd_numerator = _valuation(value.numerator, 2)
    denominator_v, odd_denominator = _valuation(value.denominator, 2)
    unit = odd_numerator * pow(odd_denominator, -1, 8) % 8
    if value < 0:
        unit = -unit % 8
    unit_coordinates = {1: (0, 0), 7: (1, 0), 5: (0, 1), 3: (1, 1)}
    minus_one, five = unit_coordinates[unit]
    return (minus_one, (numerator_v - denominator_v) % 2, five)


def _odd_qadic_coordinates(value: Fraction, prime: int) -> Vector:
    numerator_v, unit_numerator = _valuation(value.numerator, prime)
    denominator_v, unit_denominator = _valuation(value.denominator, prime)
    unit = unit_numerator * pow(unit_denominator, -1, prime) % prime
    if value < 0:
        unit = -unit % prime
    nonsquare = 0 if pow(unit, (prime - 1) // 2, prime) == 1 else 1
    return ((numerator_v - denominator_v) % 2, nonsquare)


def _verify_portable_rational_localization(receipt: LocalizationReceipt) -> None:
    witness = receipt.localization_witness
    if witness.get("method") != "portable-rational-localization-v1":
        raise ArithmeticCertificateError("unrecognized portable localization witness")
    if witness.get("domain_receipt") != receipt.domain.content_id:
        raise ArithmeticCertificateError("localization witness names a different domain")
    if witness.get("codomain_receipt") != receipt.codomain.content_id:
        raise ArithmeticCertificateError("localization witness names a different codomain")
    field = receipt.domain.field
    polynomial = integer_tuple(field.get("defining_polynomial"), "defining_polynomial")
    if len(polynomial) != 2:
        raise ArithmeticCertificateError("portable localization is only implemented over Q")
    values = tuple(_rational_constant(item) for item in receipt.domain.generators)
    if any(value == 0 for value in values):
        raise ArithmeticCertificateError("zero has no local squareclass")
    place = receipt.codomain.place
    columns: list[Vector]
    if place.get("type") == "arbogast.infinite_place":
        if place.get("kind") == "complex":
            columns = [() for _ in values]
        elif place.get("kind") == "real":
            columns = [(int(value < 0),) for value in values]
        else:
            raise ArithmeticCertificateError("portable localization has an unknown infinite place")
    elif place.get("type") == "arbogast.finite_place":
        rational_prime = strict_integer(place.get("rational_prime"), "rational_prime")
        columns = [
            _q2_coordinates(value)
            if rational_prime == 2
            else _odd_qadic_coordinates(value, rational_prime)
            for value in values
        ]
    else:
        raise ArithmeticCertificateError("portable localization has an invalid place")
    expected = tuple(
        tuple(column[row] for column in columns) for row in range(receipt.codomain.dimension)
    )
    if receipt.matrix != expected:
        raise ArithmeticCertificateError(
            "localization matrix differs from portable squareclass replay"
        )


def _verify_portable_complex_zero_localization(receipt: LocalizationReceipt) -> None:
    witness = receipt.localization_witness
    expected_keys = {"method", "domain_receipt", "codomain_receipt"}
    if set(witness) != expected_keys:
        raise ArithmeticCertificateError("complex zero localization witness has unexpected fields")
    if witness.get("method") != "portable-complex-zero-localization-v1":
        raise ArithmeticCertificateError("unrecognized complex zero localization witness")
    if witness.get("domain_receipt") != receipt.domain.content_id:
        raise ArithmeticCertificateError("localization witness names a different domain")
    if witness.get("codomain_receipt") != receipt.codomain.content_id:
        raise ArithmeticCertificateError("localization witness names a different codomain")
    if receipt.domain.prime != 2 or receipt.codomain.prime != 2:
        raise ArithmeticCertificateError("complex zero localization is only for mu2")
    place = receipt.codomain.place
    if place.get("type") != "arbogast.infinite_place" or place.get("kind") != "complex":
        raise ArithmeticCertificateError("complex zero localization requires a complex place")
    if receipt.codomain.dimension != 0 or receipt.codomain.basis or receipt.matrix:
        raise ArithmeticCertificateError(
            "complex local H1(mu2) localization must have zero-dimensional image"
        )


def _polynomial_interval(
    coefficients: tuple[Fraction, ...],
    lower: Fraction,
    upper: Fraction,
) -> tuple[Fraction, Fraction]:
    interval_lower = Fraction(0)
    interval_upper = Fraction(0)
    for coefficient in reversed(coefficients):
        products = (
            interval_lower * lower,
            interval_lower * upper,
            interval_upper * lower,
            interval_upper * upper,
        )
        interval_lower = min(products) + coefficient
        interval_upper = max(products) + coefficient
    return interval_lower, interval_upper


def _verify_portable_real_sign_localization(receipt: LocalizationReceipt) -> None:
    from .places import _sturm_sequence, _variations_at

    witness = receipt.localization_witness
    expected_keys = {
        "method",
        "domain_receipt",
        "codomain_receipt",
        "sign_witnesses",
    }
    if set(witness) != expected_keys:
        raise ArithmeticCertificateError("real sign localization witness has unexpected fields")
    if witness.get("method") != "portable-real-sign-localization-v1":
        raise ArithmeticCertificateError("unrecognized real sign localization witness")
    if witness.get("domain_receipt") != receipt.domain.content_id:
        raise ArithmeticCertificateError("localization witness names a different domain")
    if witness.get("codomain_receipt") != receipt.codomain.content_id:
        raise ArithmeticCertificateError("localization witness names a different codomain")
    if receipt.domain.prime != 2 or receipt.codomain.prime != 2:
        raise ArithmeticCertificateError("real sign localization is only for mu2")
    place = receipt.codomain.place
    if place.get("type") != "arbogast.infinite_place" or place.get("kind") != "real":
        raise ArithmeticCertificateError("real sign localization requires a real place")
    if (
        receipt.codomain.dimension != 1
        or receipt.codomain.presentation.get("method") != "portable-real-mu2-v1"
    ):
        raise ArithmeticCertificateError("real sign localization has the wrong local H1 basis")
    original_lower, original_upper = _fraction_vector(
        place.get("isolation"),
        "real place isolation",
        2,
    )
    polynomial = integer_tuple(
        receipt.domain.field.get("defining_polynomial"),
        "defining_polynomial",
    )
    sturm = _sturm_sequence(polynomial)
    raw_sign_witnesses = sequence(witness.get("sign_witnesses"), "sign_witnesses")
    if len(raw_sign_witnesses) != receipt.domain.dimension:
        raise ArithmeticCertificateError("real sign witness count differs from the global basis")
    coordinates: list[int] = []
    for index, (raw_witness, generator, generator_id) in enumerate(
        zip(
            raw_sign_witnesses,
            receipt.domain.generators,
            receipt.domain.generator_ids,
            strict=True,
        )
    ):
        entry = _mapping(raw_witness, f"sign_witnesses[{index}]")
        if set(entry) != {"generator_id", "isolation", "sign"}:
            raise ArithmeticCertificateError("real sign witness has unexpected fields")
        if entry.get("generator_id") != generator_id:
            raise ArithmeticCertificateError("real sign witness names a different generator")
        lower, upper = _fraction_vector(
            entry.get("isolation"),
            f"sign_witnesses[{index}].isolation",
            2,
        )
        if not original_lower <= lower < upper <= original_upper:
            raise ArithmeticCertificateError("real sign interval leaves the exact place")
        try:
            root_count = _variations_at(sturm, lower) - _variations_at(sturm, upper)
        except ValueError as error:
            raise ArithmeticCertificateError(
                "real sign interval has an invalid endpoint"
            ) from error
        if root_count != 1:
            raise ArithmeticCertificateError(
                "real sign interval does not isolate the declared embedding"
            )
        coefficients = tuple(
            Fraction(numerator, denominator)
            for numerator, denominator in _element_coefficients(
                generator,
                f"global generator[{index}]",
            )
        )
        value_lower, value_upper = _polynomial_interval(coefficients, lower, upper)
        expected_sign = 1 if value_lower > 0 else -1 if value_upper < 0 else 0
        advertised_sign = strict_integer(entry.get("sign"), "real sign")
        if expected_sign == 0 or advertised_sign != expected_sign:
            raise ArithmeticCertificateError(
                "real sign interval does not prove the advertised generator sign"
            )
        coordinates.append(int(expected_sign < 0))
    if receipt.matrix != (tuple(coordinates),):
        raise ArithmeticCertificateError("real localization matrix differs from sign replay")


def _verify_portable_localization(receipt: LocalizationReceipt) -> None:
    method = receipt.localization_witness.get("method")
    if method == "portable-rational-localization-v1":
        _verify_portable_rational_localization(receipt)
    elif method == "portable-complex-zero-localization-v1":
        _verify_portable_complex_zero_localization(receipt)
    elif method == "portable-real-sign-localization-v1":
        _verify_portable_real_sign_localization(receipt)
    else:
        raise ArithmeticCertificateError("unrecognized portable localization witness")


def _verify_localization_pari_payload(
    receipt: LocalizationReceipt,
    certificate: VerificationCertificate,
) -> None:
    payload = _certificate_payload(certificate)
    witness = receipt.localization_witness
    if witness.get("method") != "pari-localization-matrix-v1":
        raise ArithmeticCertificateError("unrecognized PARI localization witness")
    if witness.get("domain_receipt") != receipt.domain.content_id:
        raise ArithmeticCertificateError("PARI localization witness names another domain")
    if witness.get("codomain_receipt") != receipt.codomain.content_id:
        raise ArithmeticCertificateError("PARI localization witness names another codomain")
    if (
        receipt.proof_context.get("completeness") == "complete"
        and certificate.witness.get("completeness") != "COMPLETE"
    ):
        raise ArithmeticCertificateError("nested PARI localization is only a candidate")
    if payload.get("field_id") != receipt.domain.field_id:
        raise ArithmeticCertificateError("PARI localization belongs to a different field")
    if payload.get("place_id") != receipt.codomain.place_id:
        raise ArithmeticCertificateError("PARI localization belongs to a different place")
    if payload.get("complete") is not True:
        raise ArithmeticCertificateError("PARI localization payload is incomplete")
    if string_tuple(payload.get("generator_ids"), "PARI generator IDs") != (
        receipt.domain.generator_ids
    ):
        raise ArithmeticCertificateError("PARI localization uses a different global basis")
    payload_matrix = rows_tuple(payload.get("matrix"), "PARI localization matrix")
    if payload_matrix != receipt.matrix:
        raise ArithmeticCertificateError("PARI localization matrix differs from the receipt")
    local_basis = tuple(
        _coefficient_vector(value, f"PARI local basis[{index}]")
        for index, value in enumerate(sequence(payload.get("local_basis"), "PARI local basis"))
    )
    receipt_basis = tuple(
        _element_coefficients(value, f"local basis[{index}]")
        for index, value in enumerate(receipt.codomain.basis)
    )
    if local_basis != receipt_basis:
        raise ArithmeticCertificateError("PARI localization uses a different local basis")
    if payload.get("rational_prime") != receipt.codomain.place.get("rational_prime"):
        raise ArithmeticCertificateError("PARI localization uses a different rational prime")


@dataclass(frozen=True, slots=True, init=False)
class KummerReceipt:
    """Finite receipt for an S-Kummer space or one of its classes."""

    schema_version: ClassVar[str] = KUMMER_RECEIPT_SCHEMA

    object_type: str
    field: FrozenMap
    field_id: str
    prime: int
    places: tuple[FrozenMap, ...]
    place_ids: tuple[str, ...]
    generators: tuple[FrozenMap, ...]
    generator_ids: tuple[str, ...]
    coordinates: Vector | None
    proof_context: FrozenMap
    completeness_witness: FrozenMap
    proving_certificates: tuple[FrozenMap, ...]

    def __init__(
        self,
        *,
        object_type: str,
        field: Mapping[str, object],
        field_id: str,
        prime: int,
        places: tuple[Mapping[str, object], ...],
        place_ids: tuple[str, ...],
        generators: tuple[Mapping[str, object], ...],
        generator_ids: tuple[str, ...],
        coordinates: Vector | None,
        proof_context: Mapping[str, object],
        completeness_witness: Mapping[str, object] | None = None,
        proving_certificates: tuple[Mapping[str, object], ...] = (),
    ) -> None:
        object.__setattr__(self, "object_type", object_type)
        object.__setattr__(self, "field", freeze_mapping(field))
        object.__setattr__(self, "field_id", field_id)
        object.__setattr__(self, "prime", prime)
        object.__setattr__(self, "places", tuple(freeze_mapping(item) for item in places))
        object.__setattr__(self, "place_ids", tuple(place_ids))
        object.__setattr__(self, "generators", tuple(freeze_mapping(item) for item in generators))
        object.__setattr__(self, "generator_ids", tuple(generator_ids))
        object.__setattr__(self, "coordinates", coordinates)
        object.__setattr__(self, "proof_context", freeze_mapping(proof_context))
        object.__setattr__(self, "completeness_witness", freeze_mapping(completeness_witness))
        object.__setattr__(
            self,
            "proving_certificates",
            tuple(freeze_mapping(item) for item in proving_certificates),
        )

    @property
    def dimension(self) -> int:
        return len(self.generators)

    @property
    def content_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "field": self.field,
            "field_id": self.field_id,
            "prime": self.prime,
            "places": self.places,
            "place_ids": self.place_ids,
            "generators": self.generators,
            "generator_ids": self.generator_ids,
            "coordinates": self.coordinates,
            "proof_context": self.proof_context,
            "completeness_witness": self.completeness_witness,
            "proving_certificates": self.proving_certificates,
        }

    def to_dict(self) -> dict[str, object]:
        result = canonicalize(self.to_canonical())
        assert isinstance(result, dict)
        return cast(dict[str, object], result)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> KummerReceipt:
        required = {
            "schema_version",
            "object_type",
            "field",
            "field_id",
            "prime",
            "places",
            "place_ids",
            "generators",
            "generator_ids",
            "coordinates",
            "proof_context",
            "completeness_witness",
            "proving_certificates",
        }
        _require_fields(payload, required, record="Kummer receipt")
        if payload["schema_version"] != cls.schema_version:
            raise ValueError("unsupported Kummer receipt schema")
        return cls(
            object_type=strict_string(payload["object_type"], "object_type"),
            field=_mapping(payload["field"], "field"),
            field_id=strict_string(payload["field_id"], "field_id"),
            prime=strict_integer(payload["prime"], "prime"),
            places=tuple(item.to_dict() for item in _mapping_tuple(payload["places"], "places")),
            place_ids=string_tuple(payload["place_ids"], "place_ids"),
            generators=tuple(
                item.to_dict() for item in _mapping_tuple(payload["generators"], "generators")
            ),
            generator_ids=string_tuple(payload["generator_ids"], "generator_ids"),
            coordinates=_optional_coordinates(payload["coordinates"], "coordinates"),
            proof_context=_mapping(payload["proof_context"], "proof_context"),
            completeness_witness=_mapping(payload["completeness_witness"], "completeness_witness"),
            proving_certificates=tuple(
                item.to_dict()
                for item in _mapping_tuple(
                    payload["proving_certificates"],
                    "proving_certificates",
                )
            ),
        )

    def verify(self) -> bool:
        try:
            from ._common import prime_field

            prime_field(self.prime)
            if self.object_type not in {"space", "class"}:
                raise ArithmeticCertificateError("Kummer object type must be space or class")
            if self.field.get("type") != "arbogast.number_field":
                raise ArithmeticCertificateError("Kummer field snapshot has the wrong type")
            if len(self.places) != len(self.place_ids):
                raise ArithmeticCertificateError("Kummer place snapshots and IDs disagree")
            if len(set(self.place_ids)) != len(self.place_ids):
                raise ArithmeticCertificateError("Kummer place IDs must be unique")
            if self.place_ids != tuple(sorted(self.place_ids)):
                raise ArithmeticCertificateError("Kummer places are not canonically ordered")
            _content_bound(self.field_id, self.field, "Kummer field ID")
            for identifier, place in zip(self.place_ids, self.places, strict=True):
                _content_bound(identifier, place, "Kummer place ID")
                if place.get("type") not in {
                    "arbogast.finite_place",
                    "arbogast.infinite_place",
                }:
                    raise ArithmeticCertificateError("Kummer place snapshot has the wrong type")
                if place.get("field_id") != self.field_id:
                    raise ArithmeticCertificateError("Kummer place belongs to another field")
            if len(self.generators) != len(self.generator_ids):
                raise ArithmeticCertificateError("Kummer generator snapshots and IDs disagree")
            if len(set(self.generator_ids)) != len(self.generator_ids):
                raise ArithmeticCertificateError("Kummer generator IDs must be unique")
            for identifier, generator in zip(
                self.generator_ids,
                self.generators,
                strict=True,
            ):
                _content_bound(identifier, generator, "Kummer generator ID")
                if (
                    generator.get("type") != "arbogast.number_field_element"
                    or generator.get("field_id") != self.field_id
                ):
                    raise ArithmeticCertificateError("Kummer generator belongs to another field")
            if self.object_type == "space" and self.coordinates is not None:
                raise ArithmeticCertificateError("a Kummer space receipt cannot carry coordinates")
            if self.object_type == "class":
                if self.coordinates is None or len(self.coordinates) != self.dimension:
                    raise ArithmeticCertificateError(
                        "Kummer class coordinates have wrong dimension"
                    )
                if any(not 0 <= value < self.prime for value in self.coordinates):
                    raise ArithmeticCertificateError(
                        "Kummer coordinates are not canonical residues"
                    )
            context = self.proof_context
            completeness = context.get("completeness")
            requirements = _canonical_context_requirements(
                context,
                portable_verifier="galois.kummer.v1",
                allow_supplied_external=True,
            )
            if completeness == "complete":
                witness = self.completeness_witness
                method = witness.get("method")
                supplied_method = "certified-supplied-kummer-presentation-v1"
                required_witness = (
                    {
                        "field_id",
                        "generator_ids",
                        "method",
                        "place_ids",
                        "prime",
                        "relevant_place_set",
                    }
                    if method == supplied_method
                    else {
                        "method",
                        "place_ids",
                        "s_unit_generators",
                        "class_group_p_torsion",
                        "principalization_witnesses",
                    }
                )
                missing = required_witness - set(witness)
                if missing:
                    raise ArithmeticCertificateError(
                        f"complete Kummer receipt lacks witness fields: {sorted(missing)}"
                    )
                if tuple(sequence(witness["place_ids"], "witness.place_ids")) != self.place_ids:
                    raise ArithmeticCertificateError(
                        "Kummer completeness witness is bound to a different place set"
                    )
                if not requirements:
                    raise ArithmeticCertificateError(
                        "complete Kummer evidence must name its verification requirement"
                    )
                if method == supplied_method:
                    if set(witness) != required_witness:
                        raise ArithmeticCertificateError(
                            "certified supplied Kummer witness fields were altered"
                        )
                    if (
                        witness.get("field_id") != self.field_id
                        or strict_integer(witness.get("prime"), "witness.prime") != self.prime
                        or tuple(witness.get("generator_ids", ())) != self.generator_ids
                    ):
                        raise ArithmeticCertificateError(
                            "certified supplied Kummer witness is bound to different data"
                        )
                    certificate_payloads = tuple(
                        item.to_dict() for item in self.proving_certificates
                    )
                    _verify_supplied_presentation_certificate(
                        requirements=requirements,
                        proving_certificates=certificate_payloads,
                        operation="supplied_kummer_presentation",
                        expected_payload={
                            "field_id": self.field_id,
                            "generator_ids": self.generator_ids,
                            "place_ids": self.place_ids,
                            "prime": self.prime,
                            "relevant_place_set": witness.get("relevant_place_set"),
                        },
                    )
                    decoded = _decode_proving_certificates(certificate_payloads)
                    _verify_relevant_place_set_witness(self, decoded)
                elif any(item.get("trust") == "pinned-external" for item in requirements):
                    if self.completeness_witness.get("field_id") != self.field_id:
                        raise ArithmeticCertificateError(
                            "external Kummer witness is bound to a different field"
                        )
                    if tuple(self.completeness_witness.get("generator_ids", ())) != (
                        self.generator_ids
                    ):
                        raise ArithmeticCertificateError(
                            "external Kummer witness is bound to a different basis"
                        )
                    certificates = _verify_nested_pari_certificates(
                        context=context,
                        proving_certificates=tuple(
                            item.to_dict() for item in self.proving_certificates
                        ),
                        allowed_operations=(
                            "complex_root_isolation",
                            "field_invariants",
                            "prime_decomposition",
                            "s_unit_squareclasses",
                        ),
                        required_operations=("s_unit_squareclasses",),
                        repeatable_operations=(
                            "complex_root_isolation",
                            "prime_decomposition",
                        ),
                    )
                    _verify_kummer_pari_payloads(self, certificates)
                    _verify_relevant_place_set_witness(self, certificates)
                else:
                    if self.proving_certificates:
                        raise ArithmeticCertificateError(
                            "portable Kummer completeness cannot carry external proof evidence"
                        )
                    if self.completeness_witness.get("method") != ("portable-rational-s-kummer-v1"):
                        raise ArithmeticCertificateError(
                            "unrecognized portable Kummer completeness witness"
                        )
                    _verify_rational_kummer_witness(self)
                    _verify_relevant_place_set_witness(self)
            elif self.proving_certificates:
                certificates = _verify_nested_pari_certificates(
                    context=context,
                    proving_certificates=tuple(
                        item.to_dict() for item in self.proving_certificates
                    ),
                    allowed_operations=(
                        "complex_root_isolation",
                        "field_invariants",
                        "prime_decomposition",
                        "s_unit_squareclasses",
                    ),
                    repeatable_operations=(
                        "complex_root_isolation",
                        "prime_decomposition",
                    ),
                )
                _verify_kummer_pari_payloads(self, certificates)
                _verify_relevant_place_set_witness(self, certificates)
            else:
                _verify_relevant_place_set_witness(self)
            _reject_backend_leaks(self.to_canonical())
        except (TypeError, ValueError, KeyError) as error:
            if isinstance(error, ArithmeticCertificateError):
                raise
            raise ArithmeticCertificateError(str(error)) from error
        return True


@dataclass(frozen=True, slots=True, init=False)
class LocalH1Receipt:
    """Finite receipt for genuine ``H^1(K_v, mu_p)`` presentations."""

    schema_version: ClassVar[str] = LOCAL_H1_RECEIPT_SCHEMA

    object_type: str
    place: FrozenMap
    place_id: str
    prime: int
    basis: tuple[CanonicalValue, ...]
    basis_ids: tuple[str, ...]
    coordinates: Vector | None
    proof_context: FrozenMap
    presentation: FrozenMap
    proving_certificates: tuple[FrozenMap, ...]

    def __init__(
        self,
        *,
        object_type: str,
        place: Mapping[str, object],
        place_id: str,
        prime: int,
        basis: tuple[object, ...],
        basis_ids: tuple[str, ...],
        coordinates: Vector | None,
        proof_context: Mapping[str, object],
        presentation: Mapping[str, object] | None = None,
        proving_certificates: tuple[Mapping[str, object], ...] = (),
    ) -> None:
        object.__setattr__(self, "object_type", object_type)
        object.__setattr__(self, "place", freeze_mapping(place))
        object.__setattr__(self, "place_id", place_id)
        object.__setattr__(self, "prime", prime)
        object.__setattr__(self, "basis", tuple(canonicalize(item) for item in basis))
        object.__setattr__(self, "basis_ids", tuple(basis_ids))
        object.__setattr__(self, "coordinates", coordinates)
        object.__setattr__(self, "proof_context", freeze_mapping(proof_context))
        object.__setattr__(self, "presentation", freeze_mapping(presentation))
        object.__setattr__(
            self,
            "proving_certificates",
            tuple(freeze_mapping(item) for item in proving_certificates),
        )

    @property
    def dimension(self) -> int:
        return len(self.basis)

    @property
    def content_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "place": self.place,
            "place_id": self.place_id,
            "prime": self.prime,
            "basis": self.basis,
            "basis_ids": self.basis_ids,
            "coordinates": self.coordinates,
            "proof_context": self.proof_context,
            "presentation": self.presentation,
            "proving_certificates": self.proving_certificates,
        }

    def to_dict(self) -> dict[str, object]:
        result = canonicalize(self.to_canonical())
        assert isinstance(result, dict)
        return cast(dict[str, object], result)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> LocalH1Receipt:
        required = {
            "schema_version",
            "object_type",
            "place",
            "place_id",
            "prime",
            "basis",
            "basis_ids",
            "coordinates",
            "proof_context",
            "presentation",
            "proving_certificates",
        }
        _require_fields(payload, required, record="local H1 receipt")
        if payload["schema_version"] != cls.schema_version:
            raise ValueError("unsupported local H1 receipt schema")
        return cls(
            object_type=strict_string(payload["object_type"], "object_type"),
            place=_mapping(payload["place"], "place"),
            place_id=strict_string(payload["place_id"], "place_id"),
            prime=strict_integer(payload["prime"], "prime"),
            basis=tuple(sequence(payload["basis"], "basis")),
            basis_ids=string_tuple(payload["basis_ids"], "basis_ids"),
            coordinates=_optional_coordinates(payload["coordinates"], "coordinates"),
            proof_context=_mapping(payload["proof_context"], "proof_context"),
            presentation=_mapping(payload["presentation"], "presentation"),
            proving_certificates=tuple(
                item.to_dict()
                for item in _mapping_tuple(
                    payload["proving_certificates"],
                    "proving_certificates",
                )
            ),
        )

    def verify(self) -> bool:
        from ._common import prime_field

        prime_field(self.prime)
        if self.object_type not in {"space", "class"}:
            raise ArithmeticCertificateError("local H1 object type must be space or class")
        if len(self.basis) != len(self.basis_ids) or len(set(self.basis_ids)) != len(
            self.basis_ids
        ):
            raise ArithmeticCertificateError("local H1 basis IDs are not a unique binding")
        _content_bound(self.place_id, self.place, "local H1 place ID")
        if self.place.get("type") not in {
            "arbogast.finite_place",
            "arbogast.infinite_place",
        }:
            raise ArithmeticCertificateError("local H1 place snapshot has the wrong type")
        field_id = self.place.get("field_id")
        if not isinstance(field_id, str) or not field_id:
            raise ArithmeticCertificateError("local H1 place lacks its pinned field ID")
        for identifier, basis_item in zip(self.basis_ids, self.basis, strict=True):
            _content_bound(identifier, basis_item, "local H1 basis ID")
            basis_snapshot = _mapping(basis_item, "local H1 basis element")
            if (
                basis_snapshot.get("type") != "arbogast.number_field_element"
                or basis_snapshot.get("field_id") != field_id
            ):
                raise ArithmeticCertificateError("local H1 basis belongs to another field")
        if self.object_type == "space" and self.coordinates is not None:
            raise ArithmeticCertificateError("a local H1 space cannot carry coordinates")
        if self.object_type == "class":
            if self.coordinates is None or len(self.coordinates) != self.dimension:
                raise ArithmeticCertificateError("local H1 class coordinates have wrong dimension")
            if any(not 0 <= value < self.prime for value in self.coordinates):
                raise ArithmeticCertificateError("local H1 coordinates are not canonical residues")
        context = self.proof_context
        requirements = _canonical_context_requirements(
            context,
            portable_verifier="galois.local_h1.v1",
            allow_supplied_external=True,
        )
        if context.get("completeness") == "complete":
            if not self.presentation or not requirements:
                raise ArithmeticCertificateError("complete local H1 evidence needs a presentation")
            method = self.presentation.get("method")
            if method == "certified-supplied-local-h1-presentation-v1":
                required_presentation = {
                    "basis_ids",
                    "continuous_local_cohomology",
                    "method",
                    "place_id",
                    "prime",
                }
                if set(self.presentation) != required_presentation:
                    raise ArithmeticCertificateError(
                        "certified supplied local-H1 presentation fields were altered"
                    )
                if (
                    self.presentation.get("place_id") != self.place_id
                    or tuple(self.presentation.get("basis_ids", ())) != self.basis_ids
                    or strict_integer(self.presentation.get("prime"), "presentation.prime")
                    != self.prime
                    or self.presentation.get("continuous_local_cohomology") is not True
                ):
                    raise ArithmeticCertificateError(
                        "certified supplied local-H1 presentation is bound to different data"
                    )
                _verify_supplied_presentation_certificate(
                    requirements=requirements,
                    proving_certificates=tuple(
                        item.to_dict() for item in self.proving_certificates
                    ),
                    operation="supplied_local_h1_presentation",
                    expected_payload={
                        "basis_ids": self.basis_ids,
                        "place_id": self.place_id,
                        "prime": self.prime,
                    },
                )
            elif any(item.get("trust") == "pinned-external" for item in requirements):
                if self.presentation.get("place_id") != self.place_id:
                    raise ArithmeticCertificateError(
                        "external local witness is bound to a different place"
                    )
                if tuple(self.presentation.get("basis_ids", ())) != self.basis_ids:
                    raise ArithmeticCertificateError(
                        "external local witness is bound to a different basis"
                    )
                certificates = _verify_nested_pari_certificates(
                    context=context,
                    proving_certificates=tuple(
                        item.to_dict() for item in self.proving_certificates
                    ),
                    allowed_operations=("local_squareclasses",),
                    required_operations=("local_squareclasses",),
                )
                _verify_local_pari_payload(self, certificates[0])
            else:
                if self.proving_certificates:
                    raise ArithmeticCertificateError(
                        "portable local completeness cannot carry external proof evidence"
                    )
                _verify_portable_local_presentation(self)
        elif self.proving_certificates:
            certificates = _verify_nested_pari_certificates(
                context=context,
                proving_certificates=tuple(item.to_dict() for item in self.proving_certificates),
                allowed_operations=("local_squareclasses",),
            )
            _verify_local_pari_payload(self, certificates[0])
        _reject_backend_leaks(self.to_canonical())
        return True


@dataclass(frozen=True, slots=True, init=False)
class LocalizationReceipt:
    """Receipt for a matrix from a finite S-Kummer space to a local H1 space."""

    schema_version: ClassVar[str] = LOCALIZATION_RECEIPT_SCHEMA

    domain: KummerReceipt
    codomain: LocalH1Receipt
    matrix: Rows
    proof_context: FrozenMap
    localization_witness: FrozenMap
    proving_certificates: tuple[FrozenMap, ...]
    source_coordinates: Vector | None
    image_coordinates: Vector | None

    def __init__(
        self,
        *,
        domain: KummerReceipt,
        codomain: LocalH1Receipt,
        matrix: Rows,
        proof_context: Mapping[str, object],
        localization_witness: Mapping[str, object] | None = None,
        proving_certificates: tuple[Mapping[str, object], ...] = (),
        source_coordinates: Vector | None = None,
        image_coordinates: Vector | None = None,
    ) -> None:
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "codomain", codomain)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "proof_context", freeze_mapping(proof_context))
        object.__setattr__(
            self,
            "localization_witness",
            freeze_mapping(localization_witness),
        )
        object.__setattr__(
            self,
            "proving_certificates",
            tuple(freeze_mapping(item) for item in proving_certificates),
        )
        object.__setattr__(self, "source_coordinates", source_coordinates)
        object.__setattr__(self, "image_coordinates", image_coordinates)

    @property
    def content_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain.to_dict(),
            "codomain": self.codomain.to_dict(),
            "matrix": self.matrix,
            "proof_context": self.proof_context,
            "localization_witness": self.localization_witness,
            "proving_certificates": self.proving_certificates,
            "source_coordinates": self.source_coordinates,
            "image_coordinates": self.image_coordinates,
        }

    def to_dict(self) -> dict[str, object]:
        result = canonicalize(self.to_canonical())
        assert isinstance(result, dict)
        return cast(dict[str, object], result)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> LocalizationReceipt:
        required = {
            "schema_version",
            "domain",
            "codomain",
            "matrix",
            "proof_context",
            "localization_witness",
            "proving_certificates",
            "source_coordinates",
            "image_coordinates",
        }
        _require_fields(payload, required, record="localization receipt")
        if payload["schema_version"] != cls.schema_version:
            raise ValueError("unsupported localization receipt schema")
        return cls(
            domain=KummerReceipt.from_dict(_mapping(payload["domain"], "domain")),
            codomain=LocalH1Receipt.from_dict(_mapping(payload["codomain"], "codomain")),
            matrix=rows_tuple(payload["matrix"], "matrix"),
            proof_context=_mapping(payload["proof_context"], "proof_context"),
            localization_witness=_mapping(
                payload["localization_witness"],
                "localization_witness",
            ),
            proving_certificates=tuple(
                item.to_dict()
                for item in _mapping_tuple(
                    payload["proving_certificates"],
                    "proving_certificates",
                )
            ),
            source_coordinates=_optional_coordinates(
                payload["source_coordinates"], "source_coordinates"
            ),
            image_coordinates=_optional_coordinates(
                payload["image_coordinates"], "image_coordinates"
            ),
        )

    def verify(self) -> bool:
        self.domain.verify()
        self.codomain.verify()
        if self.domain.object_type != "space" or self.codomain.object_type != "space":
            raise ArithmeticCertificateError("localization endpoints must be space receipts")
        matrix = canonical_matrix(
            self.matrix,
            prime=self.domain.prime,
            nrows=self.codomain.dimension,
            ncols=self.domain.dimension,
        )
        if self.domain.prime != self.codomain.prime:
            raise ArithmeticCertificateError("localization coefficient primes differ")
        if self.codomain.place_id not in self.domain.place_ids:
            raise ArithmeticCertificateError("localization place is outside the declared S-set")
        context = self.proof_context
        completeness = context.get("completeness")
        requirements = _canonical_context_requirements(
            context,
            portable_verifier="galois.localization.v1",
            allow_supplied_external=True,
        )
        if completeness == "complete":
            if not requirements:
                raise ArithmeticCertificateError(
                    "complete localization must name its verification requirement"
                )
            method = self.localization_witness.get("method")
            if method == "certified-supplied-localization-presentation-v1":
                required_witness = {
                    "codomain_receipt",
                    "domain_receipt",
                    "method",
                    "prime",
                }
                if set(self.localization_witness) != required_witness:
                    raise ArithmeticCertificateError(
                        "certified supplied localization witness fields were altered"
                    )
                if (
                    self.localization_witness.get("domain_receipt") != self.domain.content_id
                    or self.localization_witness.get("codomain_receipt") != self.codomain.content_id
                    or strict_integer(
                        self.localization_witness.get("prime"),
                        "localization_witness.prime",
                    )
                    != self.domain.prime
                ):
                    raise ArithmeticCertificateError(
                        "certified supplied localization is bound to different endpoints"
                    )
                _verify_supplied_presentation_certificate(
                    requirements=requirements,
                    proving_certificates=tuple(
                        item.to_dict() for item in self.proving_certificates
                    ),
                    operation="supplied_localization_presentation",
                    expected_payload={
                        "codomain_receipt": self.codomain.content_id,
                        "domain_receipt": self.domain.content_id,
                        "matrix": self.matrix,
                        "prime": self.domain.prime,
                    },
                )
            elif any(item.get("trust") == "pinned-external" for item in requirements):
                certificates = _verify_nested_pari_certificates(
                    context=context,
                    proving_certificates=tuple(
                        item.to_dict() for item in self.proving_certificates
                    ),
                    allowed_operations=("localization_matrix",),
                    required_operations=("localization_matrix",),
                )
                _verify_localization_pari_payload(self, certificates[0])
            else:
                if self.proving_certificates:
                    raise ArithmeticCertificateError(
                        "portable localization cannot carry external proof evidence"
                    )
                _verify_portable_localization(self)
        elif self.proving_certificates:
            certificates = _verify_nested_pari_certificates(
                context=context,
                proving_certificates=tuple(item.to_dict() for item in self.proving_certificates),
                allowed_operations=("localization_matrix",),
            )
            _verify_localization_pari_payload(self, certificates[0])
        if (self.source_coordinates is None) != (self.image_coordinates is None):
            raise ArithmeticCertificateError(
                "localized class receipt requires both source and image coordinates"
            )
        if self.source_coordinates is not None and self.image_coordinates is not None:
            if len(self.source_coordinates) != matrix.ncols or any(
                not 0 <= value < self.domain.prime for value in self.source_coordinates
            ):
                raise ArithmeticCertificateError("localization source coordinates are invalid")
            if len(self.image_coordinates) != matrix.nrows or any(
                not 0 <= value < self.domain.prime for value in self.image_coordinates
            ):
                raise ArithmeticCertificateError("localized image coordinates are invalid")
            if matrix.matvec(self.source_coordinates) != self.image_coordinates:
                raise ArithmeticCertificateError(
                    "localized class does not equal matrix times source"
                )
        return True


@dataclass(frozen=True, slots=True, init=False)
class TwistReceipt:
    """Complete exhaustive nonabelian H1 cocycle-orbit receipt."""

    schema_version: ClassVar[str] = TWIST_RECEIPT_SCHEMA

    acting_elements: tuple[CanonicalValue, ...]
    acting_table: Rows
    acting_identity: int
    acting_inverses: Vector
    coefficient_elements: tuple[CanonicalValue, ...]
    coefficient_table: Rows
    coefficient_identity: int
    coefficient_inverses: Vector
    action_table: Rows
    cocycles: Rows
    orbits: tuple[Vector, ...]
    representatives: Vector
    assumptions: tuple[str, ...]

    def __init__(
        self,
        *,
        acting_elements: tuple[object, ...],
        acting_table: Rows,
        acting_identity: int,
        acting_inverses: Vector,
        coefficient_elements: tuple[object, ...],
        coefficient_table: Rows,
        coefficient_identity: int,
        coefficient_inverses: Vector,
        action_table: Rows,
        cocycles: Rows,
        orbits: tuple[Vector, ...],
        representatives: Vector,
        assumptions: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "acting_elements", tuple(canonicalize(x) for x in acting_elements))
        object.__setattr__(self, "acting_table", acting_table)
        object.__setattr__(self, "acting_identity", acting_identity)
        object.__setattr__(self, "acting_inverses", acting_inverses)
        object.__setattr__(
            self, "coefficient_elements", tuple(canonicalize(x) for x in coefficient_elements)
        )
        object.__setattr__(self, "coefficient_table", coefficient_table)
        object.__setattr__(self, "coefficient_identity", coefficient_identity)
        object.__setattr__(self, "coefficient_inverses", coefficient_inverses)
        object.__setattr__(self, "action_table", action_table)
        object.__setattr__(self, "cocycles", cocycles)
        object.__setattr__(self, "orbits", orbits)
        object.__setattr__(self, "representatives", representatives)
        object.__setattr__(self, "assumptions", assumptions)

    @property
    def content_id(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "acting_elements": self.acting_elements,
            "acting_table": self.acting_table,
            "acting_identity": self.acting_identity,
            "acting_inverses": self.acting_inverses,
            "coefficient_elements": self.coefficient_elements,
            "coefficient_table": self.coefficient_table,
            "coefficient_identity": self.coefficient_identity,
            "coefficient_inverses": self.coefficient_inverses,
            "action_table": self.action_table,
            "cocycles": self.cocycles,
            "orbits": self.orbits,
            "representatives": self.representatives,
            "assumptions": self.assumptions,
        }

    def to_dict(self) -> dict[str, object]:
        result = canonicalize(self.to_canonical())
        assert isinstance(result, dict)
        return cast(dict[str, object], result)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> TwistReceipt:
        required = {
            "schema_version",
            "acting_elements",
            "acting_table",
            "acting_identity",
            "acting_inverses",
            "coefficient_elements",
            "coefficient_table",
            "coefficient_identity",
            "coefficient_inverses",
            "action_table",
            "cocycles",
            "orbits",
            "representatives",
            "assumptions",
        }
        _require_fields(payload, required, record="twist receipt")
        if payload["schema_version"] != cls.schema_version:
            raise ValueError("unsupported twist receipt schema")
        return cls(
            acting_elements=tuple(sequence(payload["acting_elements"], "acting_elements")),
            acting_table=rows_tuple(payload["acting_table"], "acting_table"),
            acting_identity=strict_integer(payload["acting_identity"], "acting_identity"),
            acting_inverses=integer_tuple(payload["acting_inverses"], "acting_inverses"),
            coefficient_elements=tuple(
                sequence(payload["coefficient_elements"], "coefficient_elements")
            ),
            coefficient_table=rows_tuple(payload["coefficient_table"], "coefficient_table"),
            coefficient_identity=strict_integer(
                payload["coefficient_identity"], "coefficient_identity"
            ),
            coefficient_inverses=integer_tuple(
                payload["coefficient_inverses"], "coefficient_inverses"
            ),
            action_table=rows_tuple(payload["action_table"], "action_table"),
            cocycles=rows_tuple(payload["cocycles"], "cocycles"),
            orbits=tuple(
                integer_tuple(orbit, f"orbits[{index}]")
                for index, orbit in enumerate(sequence(payload["orbits"], "orbits"))
            ),
            representatives=integer_tuple(payload["representatives"], "representatives"),
            assumptions=string_tuple(payload["assumptions"], "assumptions"),
        )

    def _is_cocycle(self, values: Vector) -> bool:
        if len(values) != len(self.acting_table):
            return False
        if values[self.acting_identity] != self.coefficient_identity:
            return False
        return all(
            values[self.acting_table[left][right]]
            == self.coefficient_table[values[left]][self.action_table[left][values[right]]]
            for left in range(len(self.acting_table))
            for right in range(len(self.acting_table))
        )

    def _twist(self, cocycle: Vector, by: int) -> Vector:
        inverse = self.coefficient_inverses[by]
        return tuple(
            self.coefficient_table[inverse][
                self.coefficient_table[cocycle[group_index]][self.action_table[group_index][by]]
            ]
            for group_index in range(len(self.acting_table))
        )

    def verify(self) -> bool:
        validate_group_table(self.acting_table, self.acting_identity, self.acting_inverses)
        validate_group_table(
            self.coefficient_table,
            self.coefficient_identity,
            self.coefficient_inverses,
        )
        acting_size = len(self.acting_table)
        coefficient_size = len(self.coefficient_table)
        if len(self.acting_elements) != acting_size:
            raise ArithmeticCertificateError("acting element snapshots do not match group table")
        if len(self.coefficient_elements) != coefficient_size:
            raise ArithmeticCertificateError(
                "coefficient element snapshots do not match group table"
            )
        if len(self.action_table) != acting_size or any(
            len(row) != coefficient_size for row in self.action_table
        ):
            raise ArithmeticCertificateError("nonabelian action table has wrong dimensions")
        expected_range = tuple(range(coefficient_size))
        if any(tuple(sorted(row)) != expected_range for row in self.action_table):
            raise ArithmeticCertificateError("each acting element must permute coefficients")
        if self.action_table[self.acting_identity] != expected_range:
            raise ArithmeticCertificateError("identity does not act trivially")
        for left in range(acting_size):
            for right in range(acting_size):
                product = self.acting_table[left][right]
                for coefficient in range(coefficient_size):
                    if (
                        self.action_table[product][coefficient]
                        != self.action_table[left][self.action_table[right][coefficient]]
                    ):
                        raise ArithmeticCertificateError("action homomorphism law failed")
            for first in range(coefficient_size):
                for second in range(coefficient_size):
                    if (
                        self.action_table[left][self.coefficient_table[first][second]]
                        != (
                            self.coefficient_table[self.action_table[left][first]][
                                self.action_table[left][second]
                            ]
                        )
                    ):
                        raise ArithmeticCertificateError("action is not by automorphisms")

        free_indices = tuple(index for index in range(acting_size) if index != self.acting_identity)
        recomputed: list[Vector] = []
        for assignment in itertools.product(range(coefficient_size), repeat=len(free_indices)):
            values = [self.coefficient_identity] * acting_size
            for index, image in zip(free_indices, assignment, strict=True):
                values[index] = image
            candidate = tuple(values)
            if self._is_cocycle(candidate):
                recomputed.append(candidate)
        expected_cocycles = tuple(sorted(recomputed))
        if self.cocycles != expected_cocycles:
            raise ArithmeticCertificateError("cocycle list is not the complete exhaustive list")
        lookup = {cocycle: index for index, cocycle in enumerate(self.cocycles)}
        unseen = set(range(len(self.cocycles)))
        expected_orbits: list[Vector] = []
        identity_cocycle = (self.coefficient_identity,) * acting_size
        identity_index = lookup[identity_cocycle]
        identity_orbit = tuple(
            sorted(
                {
                    lookup[self._twist(identity_cocycle, coefficient)]
                    for coefficient in range(coefficient_size)
                }
            )
        )
        expected_orbits.append(identity_orbit)
        unseen.difference_update(identity_orbit)
        while unseen:
            seed = min(unseen)
            orbit = tuple(
                sorted(
                    {
                        lookup[self._twist(self.cocycles[seed], coefficient)]
                        for coefficient in range(coefficient_size)
                    }
                )
            )
            expected_orbits.append(orbit)
            unseen.difference_update(orbit)
        if self.orbits != tuple(expected_orbits):
            raise ArithmeticCertificateError("twist orbits do not match exhaustive replay")
        if self.representatives != tuple(orbit[0] for orbit in self.orbits):
            raise ArithmeticCertificateError("twist representatives are not canonical")
        if not self.cocycles or identity_index not in self.orbits[0]:
            raise ArithmeticCertificateError("first twist class is not the pointed identity")
        _reject_backend_leaks(self.to_canonical())
        return True


Receipt: Any = KummerReceipt | LocalH1Receipt | LocalizationReceipt | TwistReceipt


def proving_certificates(receipt: object) -> tuple[VerificationCertificate, ...]:
    """Return nested proving certificates committed by one domain receipt."""

    if isinstance(receipt, KummerReceipt):
        certificates = _decode_proving_certificates(
            tuple(item.to_dict() for item in receipt.proving_certificates)
        )
        return tuple(sorted(certificates, key=lambda item: item.certificate_id))
    if isinstance(receipt, LocalH1Receipt):
        certificates = _decode_proving_certificates(
            tuple(item.to_dict() for item in receipt.proving_certificates)
        )
        return tuple(sorted(certificates, key=lambda item: item.certificate_id))
    if isinstance(receipt, LocalizationReceipt):
        own = _decode_proving_certificates(
            tuple(item.to_dict() for item in receipt.proving_certificates)
        )
        combined = (
            *proving_certificates(receipt.domain),
            *proving_certificates(receipt.codomain),
            *own,
        )
        by_id = {certificate.certificate_id: certificate for certificate in combined}
        return tuple(by_id[key] for key in sorted(by_id))
    return ()


def _context_external_evidence_complete(
    context: Mapping[str, object],
    certificates: tuple[VerificationCertificate, ...],
) -> bool:
    requirements = tuple(
        item
        for item in sequence(
            context.get("verification_requirements", ()),
            "verification_requirements",
        )
        if isinstance(item, Mapping) and item.get("trust") == "pinned-external"
    )
    if not requirements:
        return True
    for requirement in requirements:
        capabilities = set(
            string_tuple(requirement.get("capabilities", ()), "requirement.capabilities")
        )
        matched = False
        for certificate in certificates:
            operation = certificate.witness.get("operation")
            version = certificate.witness.get("backend_version")
            if (
                certificate.verifier == requirement.get("verifier")
                and version == requirement.get("version")
                and isinstance(operation, str)
                and (operation in capabilities or operation.replace("_", "-") in capabilities)
            ):
                matched = True
                break
        if not matched:
            return False
    return True


def external_evidence_complete(receipt: object) -> bool:
    """Return whether every pinned requirement has replayable nested evidence."""

    if isinstance(receipt, KummerReceipt):
        return _context_external_evidence_complete(
            receipt.proof_context,
            proving_certificates(receipt),
        )
    if isinstance(receipt, LocalH1Receipt):
        return _context_external_evidence_complete(
            receipt.proof_context,
            proving_certificates(receipt),
        )
    if isinstance(receipt, LocalizationReceipt):
        own = _decode_proving_certificates(
            tuple(item.to_dict() for item in receipt.proving_certificates)
        )
        return (
            external_evidence_complete(receipt.domain)
            and external_evidence_complete(receipt.codomain)
            and _context_external_evidence_complete(receipt.proof_context, own)
        )
    return True


__all__ = [
    "ArithmeticCertificateError",
    "KummerReceipt",
    "LocalH1Receipt",
    "LocalizationReceipt",
    "Receipt",
    "TwistReceipt",
    "external_evidence_complete",
    "proving_certificates",
    "relevant_places_complete",
]
