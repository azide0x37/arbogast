"""Closed, receipt-bearing PARI/GP arithmetic adapter.

Only the operation-specific methods below cross the process boundary. Caller
text is never evaluated as GP source; exact integers and rational coefficient
vectors are validated and rendered by private fixed templates.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import comb
from typing import Any, Protocol, cast, runtime_checkable

from arbogast.cert import DiscoveryReceipt, FrozenMap, content_address, freeze_mapping

from .base import BackendStatus, BackendUnavailableError, ExecutableBackend
from .pari_protocol import (
    RESPONSE_SCHEMA,
    PariOperationError,
    PariOutputLimitError,
    PariProtocolError,
    PariTimeoutError,
    framed_program,
    parse_framed_response,
    run_secure_process,
)
from .pari_results import (
    PariArithmeticResult,
    PariCompleteness,
    PariOutcome,
    PariProbeResult,
    PariVerificationRequirement,
)

PARI_MINIMUM_VERSION = (2, 15, 5)
PARI_EXCLUSIVE_MAXIMUM_VERSION = (2, 18, 0)
PARI_SUPPORTED_RANGE = ">=2.15.5,<2.18.0"
PARI_TEMPLATE_VERSION = "arbogast.pari.closed-templates/v1"

_COMPATIBILITY_CAPABILITIES = (
    "class-groups",
    "local-fields",
    "number-fields",
    "padic-arithmetic",
)
_ARITHMETIC_CAPABILITIES = (
    "class-group-2-torsion",
    "complex-root-isolation",
    "field-invariants",
    "local-squareclasses",
    "localization-matrices",
    "prime-decomposition",
    "quadratic-hilbert-pairings",
    "relative-norms",
    "s-unit-squareclasses",
)
PARI_CAPABILITIES = tuple(sorted((*_COMPATIBILITY_CAPABILITIES, *_ARITHMETIC_CAPABILITIES)))
_VERSION_RE = re.compile(r"(?<![0-9])(\d+)\.(\d+)\.(\d+)(?![0-9])")


@runtime_checkable
class _NumberFieldLike(Protocol):
    defining_polynomial: Sequence[object]
    integral_basis: Sequence[Sequence[object]] | None
    field_id: str


@runtime_checkable
class _NumberFieldElementLike(Protocol):
    coefficients: Sequence[object]
    field: object
    element_id: str


@dataclass(frozen=True, slots=True)
class _FieldInput:
    polynomial: tuple[Fraction, ...]
    integral_basis: tuple[tuple[Fraction, ...], ...] | None
    field_id: str
    identity: FrozenMap

    @property
    def degree(self) -> int:
        return len(self.polynomial) - 1


@dataclass(frozen=True, slots=True)
class _ElementInput:
    coefficients: tuple[Fraction, ...]
    element_id: str
    identity: FrozenMap


@dataclass(frozen=True, slots=True)
class _FinitePlaceInput:
    rational_prime: int
    ideal_hnf: tuple[tuple[int, ...], ...] | None
    ramification_index: int | None
    residue_degree: int | None
    place_id: str
    identity: FrozenMap


@dataclass(frozen=True, slots=True)
class _InfinitePlaceInput:
    kind: str
    isolation: tuple[Fraction, ...]
    embedding_index: int
    place_id: str
    identity: FrozenMap


class PariBackend(ExecutableBackend):
    """Narrow PARI adapter with version gating and algebraic capability smoke tests."""

    certification_timeout_seconds: float
    output_limit_bytes: int
    memory_limit_bytes: int
    pari_stack_bytes: int
    cpu_limit_seconds: int

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        certification_timeout_seconds: float = 60.0,
        output_limit_bytes: int = 2_000_000,
        memory_limit_bytes: int = 1_073_741_824,
        pari_stack_bytes: int = 268_435_456,
        cpu_limit_seconds: int = 60,
    ) -> None:
        super().__init__(
            name="pari",
            executables=("gp",),
            capabilities=PARI_CAPABILITIES,
            version_args=("--version-short",),
            timeout_seconds=timeout_seconds,
        )
        numeric = (
            ("certification_timeout_seconds", certification_timeout_seconds),
            ("output_limit_bytes", output_limit_bytes),
            ("memory_limit_bytes", memory_limit_bytes),
            ("pari_stack_bytes", pari_stack_bytes),
            ("cpu_limit_seconds", cpu_limit_seconds),
        )
        for name, value in numeric:
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise ValueError(f"PARI {name} must be positive")
        for name, value in numeric[1:]:
            if not isinstance(value, int):
                raise ValueError(f"PARI {name} must be an integer")
        if pari_stack_bytes > memory_limit_bytes:
            raise ValueError("PARI stack size cannot exceed its process memory cap")
        object.__setattr__(self, "certification_timeout_seconds", certification_timeout_seconds)
        object.__setattr__(self, "output_limit_bytes", output_limit_bytes)
        object.__setattr__(self, "memory_limit_bytes", memory_limit_bytes)
        object.__setattr__(self, "pari_stack_bytes", pari_stack_bytes)
        object.__setattr__(self, "cpu_limit_seconds", cpu_limit_seconds)

    def status(self) -> BackendStatus:
        """Preserve the 0.1 status API as a projection of the detailed probe."""

        return self.probe().status

    def probe(self) -> PariProbeResult:
        """Probe a supported normalized version and operation-level algebra smoke tests."""

        executable = shutil.which("gp")
        if executable is None:
            reason = "no executable found on PATH (tried: gp)"
            status = BackendStatus("pari", False, (), reason=reason)
            receipt = _probe_receipt("not-found", {}, supported=False, reason=reason)
            return PariProbeResult(status, None, None, PARI_SUPPORTED_RANGE, {}, receipt)
        try:
            version_output = run_secure_process(
                executable,
                ("--version-short",),
                input_bytes=None,
                timeout_seconds=self.timeout_seconds,
                output_limit_bytes=min(self.output_limit_bytes, 65_536),
                memory_limit_bytes=self.memory_limit_bytes,
                cpu_limit_seconds=min(self.cpu_limit_seconds, 5),
            )
        except (PariOperationError, PariOutputLimitError, PariTimeoutError) as exc:
            reason = f"hardened version probe failed: {exc}"
            status = BackendStatus(
                "pari",
                False,
                (),
                executable=executable,
                reason=reason,
            )
            receipt = _probe_receipt("probe-failed", {}, supported=False, reason=reason)
            return PariProbeResult(status, None, None, PARI_SUPPORTED_RANGE, {}, receipt)
        raw_version = version_output.stdout.decode("utf-8", errors="replace").strip()
        if version_output.returncode != 0 or version_output.stderr.strip():
            detail = version_output.stderr.decode("utf-8", errors="replace").strip()
            reason = f"version probe unsuccessful: {detail or version_output.returncode}"
            status = BackendStatus(
                "pari",
                False,
                (),
                executable=executable,
                reason=reason,
            )
            receipt = _probe_receipt("probe-failed", {}, supported=False, reason=reason)
            return PariProbeResult(
                status,
                None,
                raw_version or None,
                PARI_SUPPORTED_RANGE,
                {},
                receipt,
            )
        normalized = normalize_pari_version(raw_version)
        if normalized is None:
            reason = "PARI returned an unrecognized version"
            status = BackendStatus(
                "pari",
                False,
                (),
                executable=executable,
                reason=reason,
            )
            receipt = _probe_receipt("unrecognized", {}, supported=False, reason=reason)
            return PariProbeResult(
                status,
                None,
                raw_version or None,
                PARI_SUPPORTED_RANGE,
                {},
                receipt,
            )
        if not (
            PARI_MINIMUM_VERSION <= _version_tuple(normalized) < PARI_EXCLUSIVE_MAXIMUM_VERSION
        ):
            reason = f"unsupported PARI version {normalized}; required {PARI_SUPPORTED_RANGE}"
            receipt = _probe_receipt(normalized, {}, supported=False, reason=reason)
            status = BackendStatus(
                "pari",
                False,
                (),
                version=normalized,
                executable=executable,
                reason=reason,
            )
            return PariProbeResult(
                status,
                normalized,
                raw_version,
                PARI_SUPPORTED_RANGE,
                {},
                receipt,
            )
        request = {
            "operation": "capability_probe",
            "protocol": RESPONSE_SCHEMA,
            "template": PARI_TEMPLATE_VERSION,
            "version": normalized,
        }
        try:
            smoke = self._execute(
                executable,
                request,
                _capability_probe_body(),
                timeout_seconds=self.timeout_seconds,
            )
            _validate_smoke_result(smoke)
        except (
            PariOperationError,
            PariOutputLimitError,
            PariProtocolError,
            PariTimeoutError,
        ) as exc:
            reason = f"algebra smoke tests failed: {exc}"
            receipt = _probe_receipt(normalized, {}, supported=True, reason=reason)
            status = BackendStatus(
                "pari",
                False,
                (),
                version=normalized,
                executable=executable,
                reason=reason,
            )
            return PariProbeResult(
                status,
                normalized,
                raw_version,
                PARI_SUPPORTED_RANGE,
                {},
                receipt,
            )
        smoke_tests = cast(dict[str, bool], smoke)
        all_passed = all(smoke_tests.values())
        smoke_reason = None if all_passed else "one or more algebra smoke tests failed"
        receipt = _probe_receipt(normalized, smoke_tests, supported=True, reason=smoke_reason)
        status = BackendStatus(
            "pari",
            all_passed,
            PARI_CAPABILITIES if all_passed else (),
            version=normalized,
            executable=executable,
            reason=smoke_reason,
        )
        return PariProbeResult(
            status,
            normalized,
            raw_version,
            PARI_SUPPORTED_RANGE,
            smoke_tests,
            receipt,
        )

    def field_invariants(self, field: _NumberFieldLike | Sequence[object]) -> PariArithmeticResult:
        """Return degree, discriminant, signature, index, and pinned integral basis."""

        normalized = _field_input(field)
        result, status, request_id, seed = self._run_operation(
            "field_invariants",
            normalized,
            inputs={},
            parameters={},
            body=_field_invariants_body(normalized),
        )
        _validate_field_invariants(result, normalized.degree)
        payload = {**result, "field_id": normalized.field_id}
        return self._success_result(
            "field_invariants",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id},
            parameters={},
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(normalized, {}),
        )

    def prime_decomposition(
        self,
        field: _NumberFieldLike | Sequence[object],
        rational_prime: int,
    ) -> PariArithmeticResult:
        """Return canonical prime-ideal HNFs above one rational prime."""

        normalized = _field_input(field)
        prime = _rational_prime(rational_prime)
        result, status, request_id, seed = self._run_operation(
            "prime_decomposition",
            normalized,
            inputs={},
            parameters={"rational_prime": prime},
            body=_prime_decomposition_body(normalized, prime),
        )
        _validate_prime_decomposition(result, normalized.degree, prime)
        prime_ideals = cast(list[dict[str, object]], result["prime_ideals"])
        for record in prime_ideals:
            record["place_id"] = content_address(
                {
                    "field_id": normalized.field_id,
                    "ideal_hnf": record["ideal_hnf"],
                    "ramification_index": record["ramification_index"],
                    "rational_prime": prime,
                    "residue_degree": record["residue_degree"],
                    "type": "arbogast.finite-place/v1",
                }
            )
        prime_ideals.sort(key=lambda item: cast(str, item["place_id"]))
        payload = {
            "field_id": normalized.field_id,
            "prime_ideals": prime_ideals,
            "rational_prime": prime,
        }
        return self._success_result(
            "prime_decomposition",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id},
            parameters={"rational_prime": prime},
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(normalized, {"rational_prime": prime}),
        )

    def complex_root_isolation(
        self,
        field: _NumberFieldLike | Sequence[object],
        embedding_index: int,
        *,
        max_bits: int = 160,
    ) -> PariArithmeticResult:
        """Isolate one positive-imaginary root in an exact rational rectangle."""

        normalized = _field_input(field)
        if normalized.degree < 2:
            raise ValueError("complex root isolation requires a field of degree at least two")
        index = _nonnegative_integer(embedding_index, "embedding_index", maximum=63)
        bits = _positive_integer(max_bits, "max_bits", maximum=512)
        if bits < 8:
            raise ValueError("max_bits must be at least 8")
        result, status, request_id, seed = self._run_operation(
            "complex_root_isolation",
            normalized,
            inputs={},
            parameters={"embedding_index": index, "max_bits": bits},
            body=_complex_root_isolation_body(normalized, index, bits),
        )
        _validate_complex_root_isolation(result, normalized, index)
        payload = {**result, "field_id": normalized.field_id}
        return self._success_result(
            "complex_root_isolation",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id},
            parameters={"embedding_index": index, "max_bits": bits},
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(
                normalized,
                {"embedding_index": index, "max_bits": bits},
            ),
        )

    def s_unit_squareclasses(
        self,
        field: _NumberFieldLike | Sequence[object],
        places: Sequence[object],
        *,
        allow_grh: bool = False,
    ) -> PariArithmeticResult:
        """Return a complete K(S,2) basis with explicit S-class 2-torsion lifts."""

        normalized = _field_input(field)
        selected = _finite_places(normalized, places, allow_rational_prime=True)
        return self._bnf_operation(
            "s_unit_squareclasses",
            normalized,
            inputs={"places": [place.place_id for place in selected]},
            parameters={"allow_grh": _boolean(allow_grh)},
            body=_s_unit_squareclasses_body(normalized, selected, certify=not allow_grh),
            validator=lambda value: _validate_s_unit_result(value, normalized.degree),
            allow_grh=allow_grh,
            completeness_from_result=True,
            replay=_replay_spec(
                normalized,
                {"places": [_place_replay(place) for place in selected]},
            ),
        )

    def class_group_2_torsion(
        self,
        field: _NumberFieldLike | Sequence[object],
        *,
        allow_grh: bool = False,
    ) -> PariArithmeticResult:
        """Return order-two ideal classes with square-principalization witnesses."""

        normalized = _field_input(field)
        return self._bnf_operation(
            "class_group_2_torsion",
            normalized,
            inputs={},
            parameters={"allow_grh": _boolean(allow_grh)},
            body=_class_group_2_torsion_body(normalized, certify=not allow_grh),
            validator=lambda value: _validate_class_2_result(value, normalized.degree),
            allow_grh=allow_grh,
            replay=_replay_spec(normalized, {}),
        )

    def local_squareclasses(
        self,
        field: _NumberFieldLike | Sequence[object],
        place: object,
        *,
        search_bound: int = 4,
        max_candidates: int = 4096,
    ) -> PariArithmeticResult:
        """Enumerate and certify a finite basis for ``K_v^*/K_v^{*2}``."""

        normalized = _field_input(field)
        selected = _finite_place(normalized, place)
        bound = _positive_integer(search_bound, "search_bound", maximum=64)
        candidates = _positive_integer(max_candidates, "max_candidates", maximum=1_000_000)
        result, status, request_id, seed = self._run_operation(
            "local_squareclasses",
            normalized,
            inputs={"place": selected.place_id},
            parameters={"max_candidates": candidates, "search_bound": bound},
            body=_local_squareclasses_body(normalized, selected, bound, candidates),
        )
        _validate_local_squareclasses(result, normalized.degree, selected.rational_prime)
        payload = {
            **result,
            "field_id": normalized.field_id,
            "place_id": selected.place_id,
        }
        return self._success_result(
            "local_squareclasses",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id, "place": selected.place_id},
            parameters={"max_candidates": candidates, "search_bound": bound},
            completeness=(
                PariCompleteness.COMPLETE
                if bool(result["complete"])
                else PariCompleteness.CANDIDATE
            ),
            replay=_replay_spec(
                normalized,
                {
                    "max_candidates": candidates,
                    "place": _place_replay(selected),
                    "search_bound": bound,
                },
            ),
        )

    def localization_matrix(
        self,
        field: _NumberFieldLike | Sequence[object],
        generators: Sequence[_NumberFieldElementLike | Sequence[object]],
        place: object,
        *,
        search_bound: int = 4,
        max_candidates: int = 4096,
    ) -> PariArithmeticResult:
        """Express exact global squareclasses in a certified local basis."""

        normalized = _field_input(field)
        elements = _elements(normalized, generators, nonzero=True)
        if not elements:
            raise ValueError("localization requires at least one global generator")
        selected = _finite_place(normalized, place)
        bound = _positive_integer(search_bound, "search_bound", maximum=64)
        candidates = _positive_integer(max_candidates, "max_candidates", maximum=1_000_000)
        inputs = {
            "generators": [element.element_id for element in elements],
            "place": selected.place_id,
        }
        parameters = {"max_candidates": candidates, "search_bound": bound}
        result, status, request_id, seed = self._run_operation(
            "localization_matrix",
            normalized,
            inputs=inputs,
            parameters=parameters,
            body=_localization_matrix_body(normalized, elements, selected, bound, candidates),
        )
        _validate_localization_matrix(result, normalized.degree, len(elements))
        payload = {
            **result,
            "field_id": normalized.field_id,
            "generator_ids": [element.element_id for element in elements],
            "place_id": selected.place_id,
        }
        return self._success_result(
            "localization_matrix",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id, **inputs},
            parameters=parameters,
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(
                normalized,
                {
                    "generators": [_element_replay(element) for element in elements],
                    "max_candidates": candidates,
                    "place": _place_replay(selected),
                    "search_bound": bound,
                },
            ),
        )

    def relative_norm(
        self,
        field: _NumberFieldLike | Sequence[object],
        element: _NumberFieldElementLike | Sequence[object],
    ) -> PariArithmeticResult:
        """Return the exact norm to Q for an element of the pinned presentation."""

        normalized = _field_input(field)
        value = _element(normalized, element, nonzero=False)
        result, status, request_id, seed = self._run_operation(
            "relative_norm",
            normalized,
            inputs={"element": value.element_id},
            parameters={"base_field": "Q"},
            body=_relative_norm_body(normalized, value),
        )
        _validate_relative_norm(result)
        payload = {
            **result,
            "element_id": value.element_id,
            "field_id": normalized.field_id,
        }
        return self._success_result(
            "relative_norm",
            payload,
            status,
            request_id,
            seed,
            inputs={"element": value.element_id, "field": normalized.field_id},
            parameters={"base_field": "Q"},
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(normalized, {"element": _element_replay(value)}),
        )

    def quadratic_hilbert_pairing(
        self,
        field: _NumberFieldLike | Sequence[object],
        left: _NumberFieldElementLike | Sequence[object],
        right: _NumberFieldElementLike | Sequence[object],
        place: object | None = None,
    ) -> PariArithmeticResult:
        """Return the exact quadratic Hilbert symbol globally or at one exact place."""

        normalized = _field_input(field)
        left_value = _element(normalized, left, nonzero=True)
        right_value = _element(normalized, right, nonzero=True)
        selected = None if place is None else _place(normalized, place)
        place_id = "global" if selected is None else selected.place_id
        inputs = {
            "left": left_value.element_id,
            "place": place_id,
            "right": right_value.element_id,
        }
        result, status, request_id, seed = self._run_operation(
            "quadratic_hilbert_pairing",
            normalized,
            inputs=inputs,
            parameters={},
            body=_quadratic_hilbert_body(normalized, left_value, right_value, selected),
        )
        _validate_hilbert_result(result)
        payload = {
            **result,
            "field_id": normalized.field_id,
            "left_element_id": left_value.element_id,
            "place_id": place_id,
            "right_element_id": right_value.element_id,
        }
        return self._success_result(
            "quadratic_hilbert_pairing",
            payload,
            status,
            request_id,
            seed,
            inputs={"field": normalized.field_id, **inputs},
            parameters={},
            completeness=PariCompleteness.COMPLETE,
            replay=_replay_spec(
                normalized,
                {
                    "left": _element_replay(left_value),
                    "place": None if selected is None else _place_replay(selected),
                    "right": _element_replay(right_value),
                },
            ),
        )

    quadratic_hilbert = quadratic_hilbert_pairing

    def _bnf_operation(
        self,
        operation: str,
        field: _FieldInput,
        *,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
        body: str,
        validator: Callable[[Mapping[str, object]], None],
        allow_grh: bool,
        replay: Mapping[str, object],
        completeness_from_result: bool = False,
    ) -> PariArithmeticResult:
        timeout = self.timeout_seconds if allow_grh else self.certification_timeout_seconds
        try:
            result, status, request_id, seed = self._run_operation(
                operation,
                field,
                inputs=inputs,
                parameters=parameters,
                body=body,
                timeout_seconds=timeout,
            )
        except PariTimeoutError:
            status = self._require_status()
            request = _operation_request(operation, field, inputs, parameters)
            request_id = content_address(request)
            return self._budget_exhausted_result(
                operation,
                field,
                status,
                inputs=inputs,
                parameters={**parameters, "timeout_seconds": _exact_decimal(timeout)},
                request=request,
                request_id=request_id,
                seed=_request_seed(request_id),
            )
        validator(result)
        if result.get("certified") is not (not allow_grh):
            raise PariProtocolError("PARI certification flag did not match the requested mode")
        completeness = (
            PariCompleteness.COMPLETE
            if not completeness_from_result or result.get("complete") is True
            else PariCompleteness.CANDIDATE
        )
        return self._success_result(
            operation,
            {**result, "field_id": field.field_id},
            status,
            request_id,
            seed,
            inputs={"field": field.field_id, **inputs},
            parameters=parameters,
            assumptions=("GRH",) if allow_grh else (),
            completeness=completeness,
            replay=replay,
        )

    def _run_operation(
        self,
        operation: str,
        field: _FieldInput,
        *,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
        body: str,
        timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], BackendStatus, str, int]:
        status = self._require_status()
        assert status.executable is not None
        request = _operation_request(operation, field, inputs, parameters)
        request_id = content_address(request)
        seed = _request_seed(request_id)
        result = self._execute(
            status.executable,
            request,
            body,
            timeout_seconds=self.timeout_seconds if timeout_seconds is None else timeout_seconds,
        )
        return result, status, request_id, seed

    def _execute(
        self,
        executable: str,
        request: Mapping[str, object],
        body: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request_id = content_address(request)
        output = run_secure_process(
            executable,
            (),
            input_bytes=framed_program(request_id, _request_seed(request_id), body),
            timeout_seconds=timeout_seconds,
            output_limit_bytes=self.output_limit_bytes,
            memory_limit_bytes=self.memory_limit_bytes,
            cpu_limit_seconds=min(self.cpu_limit_seconds, max(1, int(timeout_seconds) + 1)),
            pari_stack_bytes=self.pari_stack_bytes,
        )
        return parse_framed_response(output, request_id)

    def _require_status(self) -> BackendStatus:
        status = self.status()
        if not status.available or status.executable is None or status.version is None:
            raise BackendUnavailableError(status.reason or "PARI is unavailable")
        return status

    def _success_result(
        self,
        operation: str,
        payload: Mapping[str, object],
        status: BackendStatus,
        request_id: str,
        seed: int,
        *,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
        completeness: PariCompleteness,
        assumptions: tuple[str, ...] = (),
        verification_requirement: PariVerificationRequirement | None = None,
        replay: Mapping[str, object],
    ) -> PariArithmeticResult:
        assert status.version is not None
        requirement = verification_requirement or PariVerificationRequirement.pari(status.version)
        receipt = DiscoveryReceipt.create(
            f"backends.pari.{operation}",
            inputs={**inputs, "request": request_id},
            parameters={
                **parameters,
                "assumptions": list(assumptions),
                "completeness": completeness.value,
                "deterministic_seed": seed,
                "protocol": RESPONSE_SCHEMA,
                "template": PARI_TEMPLATE_VERSION,
                "verification_requirement": requirement.to_dict(),
            },
            result={"outcome": PariOutcome.SUCCESS.value, "payload": content_address(payload)},
            backend="pari",
            backend_version=status.version,
            notes=(
                "fresh-process closed-template result",
                "discovery receipt is not itself a portable verification certificate",
            ),
        )
        from .pari_certificate import create_pari_verification_certificate

        certificate = create_pari_verification_certificate(
            operation,
            replay=replay,
            expected_payload=payload,
            backend_version=status.version,
            request_id=request_id,
            deterministic_seed=seed,
            proof_mode="grh-conditional" if assumptions else "unconditional",
            completeness=completeness.value,
            limits={
                "certification_timeout_seconds": _exact_decimal(self.certification_timeout_seconds),
                "cpu_limit_seconds": self.cpu_limit_seconds,
                "memory_limit_bytes": self.memory_limit_bytes,
                "output_limit_bytes": self.output_limit_bytes,
                "pari_stack_bytes": self.pari_stack_bytes,
                "timeout_seconds": _exact_decimal(self.timeout_seconds),
            },
        )
        return PariArithmeticResult(
            operation,
            cast(Any, payload),
            receipt,
            assumptions=assumptions,
            completeness=completeness,
            verification_requirement=requirement,
            certificate=certificate,
        )

    def _budget_exhausted_result(
        self,
        operation: str,
        field: _FieldInput,
        status: BackendStatus,
        *,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
        request: Mapping[str, object],
        request_id: str,
        seed: int,
    ) -> PariArithmeticResult:
        assert status.version is not None
        payload = {
            "budget": {"timeout_seconds": parameters["timeout_seconds"]},
            "field_id": field.field_id,
            "reason": "PARI certification exceeded its resource budget",
            "request": dict(request),
            "request_id": request_id,
        }
        receipt = DiscoveryReceipt.create(
            f"backends.pari.{operation}",
            inputs={"field": field.field_id, **inputs, "request": request_id},
            parameters={
                **parameters,
                "assumptions": [],
                "completeness": PariCompleteness.CANDIDATE.value,
                "deterministic_seed": seed,
                "protocol": RESPONSE_SCHEMA,
                "supported_range": PARI_SUPPORTED_RANGE,
                "template": PARI_TEMPLATE_VERSION,
            },
            result={
                "outcome": PariOutcome.BUDGET_EXHAUSTED.value,
                "payload": content_address(payload),
            },
            backend="pari",
            backend_version=status.version,
            notes=("certification timeout is non-closing; no GRH assumption was inferred",),
        )
        from .pari_certificate import create_pari_operational_certificate

        certificate = create_pari_operational_certificate(
            operation,
            payload=payload,
            receipt=receipt,
            outcome=PariOutcome.BUDGET_EXHAUSTED,
        )
        return PariArithmeticResult(
            operation,
            cast(Any, payload),
            receipt,
            completeness=PariCompleteness.CANDIDATE,
            outcome=PariOutcome.BUDGET_EXHAUSTED,
            certificate=certificate,
        )


def normalize_pari_version(value: str) -> str | None:
    """Extract one exact three-component PARI version from known banner forms."""

    if not isinstance(value, str):
        return None
    matches = _VERSION_RE.findall(value)
    if len(matches) != 1:
        return None
    major, minor, patch = (int(part) for part in matches[0])
    return f"{major}.{minor}.{patch}"


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError("normalized PARI version is malformed")
    return cast(tuple[int, int, int], tuple(int(part) for part in match.groups()))


def _probe_receipt(
    version: str,
    smoke_tests: Mapping[str, bool],
    *,
    supported: bool,
    reason: str | None,
) -> DiscoveryReceipt:
    return DiscoveryReceipt.create(
        "backends.pari.probe",
        parameters={
            "protocol": RESPONSE_SCHEMA,
            "supported_range": PARI_SUPPORTED_RANGE,
            "template": PARI_TEMPLATE_VERSION,
        },
        result={
            "reason": reason,
            "smoke_tests": dict(smoke_tests),
            "supported_version": supported,
        },
        backend="pari",
        backend_version=version,
        notes=("capabilities are advertised only after algebraic smoke tests",),
    )


def _capability_probe_body() -> str:
    entries = ',",",'.join(f'"\\"{key}\\":",arb_jbool(ok)' for key in _ARITHMETIC_CAPABILITIES)
    return f"""
arb_jbool(v)=if(v,"true","false");
P=x^2-x-1;
nf=nfinit(P);
D=idealprimedec(nf,2);
bnf=bnfinit(P,1);
su=bnfsunit(bnf,D);
ok=(nf.disc==5 && nf.sign==[2,0] && #nf.zk==2);
ok=ok && (#D==1 && D[1][3]==1 && D[1][4]==2);
ok=ok && (type(bnf.cyc)=="t_VEC" && type(su[1])=="t_VEC");
ok=ok && (nfislocalpower(nf,D[1],1,2)==1);
ok=ok && (nfeltnorm(nf,Mod(x,P))==-1);
ok=ok && (abs(nfhilbert(nf,-1,-1,D[1]))==1);
complex_roots=polroots(x^2+1);
ok=ok && (#complex_roots==2 && imag(complex_roots[2])>0);
arb_emit(Str("{{",{entries},"}}"));
"""


def _field_setup(field: _FieldInput) -> str:
    pinned = "IB" if field.integral_basis is None else _gp_matrix(field.integral_basis)
    return f"""
P={_gp_polynomial(field.polynomial)};
if(poldegree(P)!={field.degree} || !polisirreducible(P),error("invalid number field polynomial"));
nf=nfinit(P);
IB=arb_power_basis_matrix(nf,{field.degree});
PB={pinned};
T=PB^-1*IB;
if(denominator(T)!=1 || abs(matdet(T))!=1,error("pinned basis is not the integral basis"));
arb_hnf(id)=mathnf(T*idealhnf(nf,id));
"""


def _field_invariants_body(field: _FieldInput) -> str:
    return (
        _field_setup(field)
        + f"""
arb_emit(Str("{{\\"degree\\":",{field.degree},",\\"discriminant\\":",nf.disc,",\\"index\\":",nf.index,",\\"integral_basis\\":",arb_jqmat(mattranspose(PB)),",\\"signature\\":",arb_jintvec(nf.sign),"}}"));
"""
    )


def _prime_decomposition_body(field: _FieldInput, prime: int) -> str:
    return (
        _field_setup(field)
        + f"""
D=idealprimedec(nf,{prime});
records=vector(#D,i,Str("{{\\"ideal_hnf\\":",arb_jintmat(arb_hnf(D[i])),",\\"norm\\":",idealnorm(nf,D[i]),",\\"ramification_index\\":",D[i][3],",\\"residue_degree\\":",D[i][4],"}}"));
arb_emit(Str("{{\\"prime_ideals\\":[",strjoin(records,","),"],\\"rational_prime\\":",{prime},"}}"));
"""
    )


def _complex_root_isolation_body(
    field: _FieldInput,
    embedding_index: int,
    max_bits: int,
) -> str:
    return (
        _field_setup(field)
        + f"""
default(realprecision,256);
roots=Vec(polroots(P));
upper_roots=select(z->imag(z)>0,roots);
if({embedding_index + 1}>#upper_roots,error("complex embedding index is out of range"));
selected_root=upper_roots[{embedding_index + 1}];
arb_l1(z)=abs(real(z))+abs(imag(z));
arb_rouche_margin(center,radius)={{
  my(expanded,linear_lower,remainder_upper);
  expanded=subst(P,x,y+center);
  linear_lower=max(abs(real(polcoef(expanded,1,y))),abs(imag(polcoef(expanded,1,y))))*radius;
  remainder_upper=arb_l1(polcoef(expanded,0,y));
  for(k=2,{field.degree},remainder_upper+=arb_l1(polcoef(expanded,k,y))*radius^k);
  linear_lower-remainder_upper;
}};
arb_try_isolation_bits(bit_count)={{
  my(denominator_value,center_real,center_imag,inner_radius,outer_radius,center,inner_margin,outer_margin);
  denominator_value=2^bit_count;
  center_real=round(real(selected_root)*denominator_value)/denominator_value;
  center_imag=round(imag(selected_root)*denominator_value)/denominator_value;
  inner_radius=2/denominator_value;
  outer_radius=2*inner_radius;
  if(center_imag<=inner_radius,return(0));
  center=center_real+center_imag*I;
  inner_margin=arb_rouche_margin(center,inner_radius);
  outer_margin=arb_rouche_margin(center,outer_radius);
  if(inner_margin>0 && outer_margin>0,
    [center_real,center_imag,inner_radius,outer_radius,inner_margin,outer_margin],
    0);
}};
isolation_data=0;
for(bit_count=8,{max_bits},candidate=arb_try_isolation_bits(bit_count);if(type(candidate)=="t_VEC",isolation_data=candidate;break));
if(type(isolation_data)!="t_VEC",error("exact complex root isolation budget exhausted"));
center_real=isolation_data[1];
center_imag=isolation_data[2];
inner_radius=isolation_data[3];
outer_radius=isolation_data[4];
inner_margin=isolation_data[5];
outer_margin=isolation_data[6];
isolation=[center_real-inner_radius,center_real+inner_radius,center_imag-inner_radius,center_imag+inner_radius];
arb_emit(Str("{{\\"embedding_index\\":",{embedding_index},",\\"isolation\\":",arb_jqvec(isolation),",\\"kind\\":\\"complex\\",\\"ordering\\":\\"pari-polroots-positive-imaginary\\",\\"root_count\\":1,\\"rouche_witness\\":{{\\"center\\":",arb_jqvec([center_real,center_imag]),",\\"inner_margin\\":",arb_jq(inner_margin),",\\"inner_radius\\":",arb_jq(inner_radius),",\\"outer_margin\\":",arb_jq(outer_margin),",\\"outer_radius\\":",arb_jq(outer_radius),"}}}}"));
"""
    )


def _place_selection(field: _FieldInput, place: _FinitePlaceInput) -> str:
    del field
    if place.ideal_hnf is None:
        selection = 'if(#D!=1,error("rational prime does not determine a unique place"));pr=D[1];'
    else:
        selection = f"""
TARGET={_gp_integer_matrix(place.ideal_hnf)};
found=0;
for(i=1,#D,if(arb_hnf(D[i])==TARGET,if(found,error("duplicate place match"),found=i)));
if(!found,error("declared finite place HNF was not found"));
pr=D[found];
"""
    return f"D=idealprimedec(nf,{place.rational_prime});\n{selection}\n"


def _s_places_selection(places: tuple[_FinitePlaceInput, ...]) -> str:
    chunks = ["Slist=List();"]
    for place in places:
        chunks.append(f"D=idealprimedec(nf,{place.rational_prime});")
        if place.ideal_hnf is None:
            chunks.append("for(j=1,#D,listput(Slist,D[j]));")
        else:
            chunks.extend(
                (
                    f"TARGET={_gp_integer_matrix(place.ideal_hnf)};",
                    "found=0;",
                    "for(j=1,#D,if(arb_hnf(D[j])==TARGET,"
                    'if(found,error("duplicate place match"),found=j)));',
                    'if(!found,error("declared finite place HNF was not found"));',
                    "listput(Slist,D[found]);",
                )
            )
    chunks.append("S=Vec(Slist);")
    return "\n".join(chunks)


def _certification_code(certify: bool) -> str:
    if certify:
        return 'certified=(bnfcertify(bnf)==1);if(!certified,error("bnfcertify failed"));'
    return "certified=0;"


def _s_unit_squareclasses_body(
    field: _FieldInput,
    places: tuple[_FinitePlaceInput, ...],
    *,
    certify: bool,
) -> str:
    return (
        _field_setup(field)
        + "\nbnf=bnfinit(P,1);\n"
        + _certification_code(certify)
        + "\n"
        + _s_places_selection(places)
        + f"""
su=bnfsunit(bnf,S);
unit_reps=concat([bnf.tu[2]],concat(bnf.fu,su[1]));
prime_hnfs=vector(#S,i,arb_jintmat(arb_hnf(S[i])));
sclass_records=List();
sclass_lifts=List();
arb_solve_sclass_nonempty(class_vector)={{
  my(class_matrix,solution);
  class_matrix=matrix(#bnf.cyc,#S,r,c,bnfisprincipal(bnf,S[c],0)[r]);
  solution=matsolvemod(class_matrix,Vec(bnf.cyc)~,-class_vector);
  if(type(solution)=="t_INT",error("S-class 2-torsion lift did not solve"));
  solution;
}};
arb_solve_sclass_empty(class_vector)={{
  if(vecsum(abs(class_vector)),error("S-class lift unexpectedly nonprincipal"));
  []~;
}};
arb_append_sclass_lift(i)={{
  my(cyclic_order,jj,jj_square,class_vector,s_exponents,adjusted,principal,alpha);
  cyclic_order=su[5][2][i];
  jj=idealpow(nf,su[5][3][i],cyclic_order/2);
  jj_square=idealpow(nf,jj,2);
  class_vector=bnfisprincipal(bnf,jj_square,0);
  s_exponents=if(#S,arb_solve_sclass_nonempty(class_vector),arb_solve_sclass_empty(class_vector));
  adjusted=jj_square;
  for(j=1,#S,adjusted=idealmul(nf,adjusted,idealpow(nf,S[j],s_exponents[j])));
  principal=bnfisprincipal(bnf,adjusted,1);
  if(vecsum(abs(principal[1])),error("S-class lift did not principalize"));
  alpha=nfbasistoalg(nf,principal[2]);
  if(arb_hnf(adjusted)!=arb_hnf(alpha),error("S-class principalization equality failed"));
  listput(sclass_lifts,alpha);
  listput(sclass_records,Str("{{\\"cyclic_order\\":",cyclic_order,",\\"ideal_hnf\\":",arb_jintmat(arb_hnf(jj)),",\\"principalization_generator\\":",arb_jelt(alpha,{field.degree}),",\\"s_prime_exponents\\":",arb_jintvec(Vec(s_exponents)),"}}"));
}};
for(i=1,#su[5][2],if(su[5][2][i]%2==0,arb_append_sclass_lift(i)));
sclass_lifts=Vec(sclass_lifts);
sclass_records=Vec(sclass_records);
reps=concat(unit_reps,sclass_lifts);
arb_emit(Str("{{\\"certified\\":",if(certified,"true","false"),",\\"complete\\":true,\\"prime_ideal_hnfs\\":[",strjoin(prime_hnfs,","),"],\\"representatives\\":",arb_jelts(reps,{field.degree}),",\\"roots_of_unity_order\\":",bnf.tu[1],",\\"s_class_2_torsion\\":[",strjoin(sclass_records,","),"],\\"s_class_group_cyclic_orders\\":",arb_jintvec(su[5][2]),",\\"s_unit_rank\\":",#unit_reps,"}}"));
"""
    )


def _class_group_2_torsion_body(field: _FieldInput, *, certify: bool) -> str:
    return (
        _field_setup(field)
        + "\nbnf=bnfinit(P,1);\n"
        + _certification_code(certify)
        + f"""
records=List();
for(i=1,#bnf.cyc,if(bnf.cyc[i]%2==0,{{
  jj=idealpow(nf,bnf.gen[i],bnf.cyc[i]/2);
  principal=bnfisprincipal(bnf,idealpow(nf,jj,2),1);
  if(vecsum(abs(principal[1]))!=0,error("2-torsion square did not principalize"));
  alpha=nfbasistoalg(nf,principal[2]);
  listput(records,Str("{{\\"cyclic_order\\":",bnf.cyc[i],",\\"ideal_hnf\\":",arb_jintmat(arb_hnf(jj)),",\\"square_generator\\":",arb_jelt(alpha,{field.degree}),"}}"));
}}));
records=Vec(records);
arb_emit(Str("{{\\"certified\\":",if(certified,"true","false"),",\\"class_group_cyclic_orders\\":",arb_jintvec(bnf.cyc),",\\"two_torsion\\":[",strjoin(records,","),"]}}"));
"""
    )


def _local_basis_code(
    field: _FieldInput,
    place: _FinitePlaceInput,
    search_bound: int,
    max_candidates: int,
) -> str:
    return (
        _field_setup(field)
        + _place_selection(field, place)
        + f"""
local_dimension=if({place.rational_prime}==2,pr[3]*pr[4]+2,2);
arb_maskprod(B,m,j)=if(j>#B,1,if(bittest(m,j-1),B[j],1)*arb_maskprod(B,m,j+1));
arb_inspan(B,c,m)=if(m>=2^#B,0,if(nfislocalpower(nf,pr,c*arb_maskprod(B,m,1),2),1,arb_inspan(B,c,m+1)));
arb_extend(B,c)=if(c==0 || #B>=local_dimension || arb_inspan(B,c,0),B,concat(B,[c]));
B=[];
B=arb_extend(B,-1);
uniformizer=idealappr(nf,pr);if(type(uniformizer)=="t_COL",uniformizer=nfbasistoalg(nf,uniformizer));B=arb_extend(B,uniformizer);
B=arb_extend(B,5);
width=2*{search_bound}+1;
tested=min(width^{field.degree},{max_candidates});
candidates=vector(tested,code,nfbasistoalg(nf,vector({field.degree},j,((code-1)\\width^(j-1))%width-{search_bound})~));
for(code=1,#candidates,B=arb_extend(B,candidates[code]));
local_complete=(#B==local_dimension);
"""
    )


def _local_squareclasses_body(
    field: _FieldInput,
    place: _FinitePlaceInput,
    search_bound: int,
    max_candidates: int,
) -> str:
    return (
        _local_basis_code(field, place, search_bound, max_candidates)
        + f"""
arb_emit(Str("{{\\"complete\\":",if(local_complete,"true","false"),",\\"dimension\\":",local_dimension,",\\"ramification_index\\":",pr[3],",\\"rational_prime\\":",{place.rational_prime},",\\"representatives\\":",arb_jelts(B,{field.degree}),",\\"residue_degree\\":",pr[4],",\\"tested_candidates\\":",tested,"}}"));
"""
    )


def _localization_matrix_body(
    field: _FieldInput,
    elements: tuple[_ElementInput, ...],
    place: _FinitePlaceInput,
    search_bound: int,
    max_candidates: int,
) -> str:
    values = ",".join(_gp_element(element.coefficients) for element in elements)
    return (
        _local_basis_code(field, place, search_bound, max_candidates)
        + f"""
if(!local_complete,error("local squareclass basis search was incomplete"));
A=[{values}];
arb_findmask(B,c,m)=if(m>=2^#B,-1,if(nfislocalpower(nf,pr,c*arb_maskprod(B,m,1),2),m,arb_findmask(B,c,m+1)));
masks=vector(#A,c,arb_findmask(B,A[c],0));
if(vecmin(masks)<0,error("global generator not represented in local basis"));
M=matrix(local_dimension,#A,r,c,bittest(masks[c],r-1));
arb_emit(Str("{{\\"complete\\":true,\\"local_basis\\":",arb_jelts(B,{field.degree}),",\\"matrix\\":",arb_jintmat(M),",\\"rational_prime\\":",{place.rational_prime},"}}"));
"""
    )


def _relative_norm_body(field: _FieldInput, element: _ElementInput) -> str:
    return (
        _field_setup(field)
        + f"""
a={_gp_element(element.coefficients)};
n=nfeltnorm(nf,a);
arb_emit(Str("{{\\"base_field\\":\\"Q\\",\\"norm\\":",arb_jq(n),"}}"));
"""
    )


def _quadratic_hilbert_body(
    field: _FieldInput,
    left: _ElementInput,
    right: _ElementInput,
    place: _FinitePlaceInput | _InfinitePlaceInput | None,
) -> str:
    setup = (
        _field_setup(field)
        + f"\na={_gp_element(left.coefficients)};\nb={_gp_element(right.coefficients)};\n"
    )
    if place is None:
        operation = 'symbol=nfhilbert(nf,a,b);place_kind="global";'
    elif isinstance(place, _FinitePlaceInput):
        operation = (
            _place_selection(field, place) + '\nsymbol=nfhilbert(nf,a,b,pr);place_kind="finite";'
        )
    elif place.kind == "complex":
        operation = 'symbol=1;place_kind="complex";'
    else:
        lower, upper = place.isolation
        operation = f"""
lo={_gp_rational(lower)};hi={_gp_rational(upper)};
if(!(lo<hi) || polsturm(P,[lo,hi])!=1,error("invalid real-place isolation"));
aa=lift(a);bb=lift(b);
if(polresultant(P,aa)==0 || polresultant(P,bb)==0,error("Hilbert arguments must be nonzero"));
for(iter=1,4096,
  if(polsturm(aa,[lo,hi])==0 && polsturm(bb,[lo,hi])==0,break);
  mid=(lo+hi)/2;
  if(polsturm(P,[lo,mid])==1,hi=mid,lo=mid);
);
if(polsturm(aa,[lo,hi]) || polsturm(bb,[lo,hi]),error("real sign isolation budget exhausted"));
mid=(lo+hi)/2;
symbol=if(subst(aa,x,mid)<0 && subst(bb,x,mid)<0,-1,1);
place_kind="real";
"""
    return (
        setup
        + operation
        + """
if(abs(symbol)!=1,error("invalid Hilbert symbol"));
arb_emit(Str("{\\"place_kind\\":\\"",place_kind,"\\",\\"symbol\\":",symbol,"}"));
"""
    )


def _field_input(value: _NumberFieldLike | Sequence[object]) -> _FieldInput:
    if isinstance(value, _NumberFieldLike):
        polynomial = _rational_vector(value.defining_polynomial, "defining polynomial")
        degree = len(polynomial) - 1
        basis = (
            None
            if value.integral_basis is None
            else _rational_matrix(value.integral_basis, degree, "integral basis")
        )
        if not isinstance(value.field_id, str) or not value.field_id:
            raise ValueError("number field ID must be a non-empty string")
        internal = _internal_identity(value)
        if internal is None:
            if basis is None:
                identity_data: Mapping[str, object] = _raw_field_identity(polynomial)
            else:
                if any(coefficient.denominator != 1 for coefficient in polynomial):
                    raise ValueError(
                        "canonical number-field polynomials must have integer coefficients"
                    )
                identity_data = {
                    "defining_polynomial": [coefficient.numerator for coefficient in polynomial],
                    "integral_basis": [
                        [_rational_pair(coefficient) for coefficient in row] for row in basis
                    ],
                    "irreducibility_requirement": _optional_canonical_attribute(
                        value,
                        "irreducibility_requirement",
                        "irreducibility requirement",
                    ),
                    "irreducibility_witness": _optional_canonical_attribute(
                        value,
                        "irreducibility_witness",
                        "irreducibility witness",
                    ),
                    "type": "arbogast.number_field",
                }
                _require_declared_canonical_data(value, identity_data, "number field")
            identity = _bound_identity(identity_data, value.field_id, "number field")
        else:
            identity = _bound_identity(internal, value.field_id, "number field")
        _validate_field_identity(identity, polynomial, basis)
        return _validated_field(polynomial, basis, value.field_id, identity)
    polynomial = _rational_vector(value, "defining polynomial")
    identity_data = _raw_field_identity(polynomial)
    field_id = content_address(identity_data)
    identity = _bound_identity(identity_data, field_id, "raw number field")
    return _validated_field(polynomial, None, field_id, identity)


def _validated_field(
    polynomial: tuple[Fraction, ...],
    basis: tuple[tuple[Fraction, ...], ...] | None,
    field_id: str,
    identity: FrozenMap,
) -> _FieldInput:
    if len(polynomial) < 2 or polynomial[-1] == 0:
        raise ValueError("defining polynomial must have positive degree and nonzero leading term")
    if len(polynomial) - 1 > 64:
        raise ValueError("PARI adapter bounds number-field degree at 64")
    return _FieldInput(polynomial, basis, field_id, identity)


def _element(
    field: _FieldInput,
    value: _NumberFieldElementLike | Sequence[object],
    *,
    nonzero: bool,
) -> _ElementInput:
    if isinstance(value, _NumberFieldElementLike):
        coefficients = _rational_vector(value.coefficients, "element coefficients")
        if getattr(value.field, "field_id", None) != field.field_id:
            raise ValueError("number-field element belongs to a different pinned field")
        if not isinstance(value.element_id, str) or not value.element_id:
            raise ValueError("number-field element ID must be non-empty")
        element_id = value.element_id
    else:
        coefficients = _rational_vector(value, "element coefficients", allow_empty=True)
        element_id = ""
    if len(coefficients) > field.degree:
        raise ValueError("element coefficient vector exceeds the pinned power-basis degree")
    coefficients += (Fraction(0),) * (field.degree - len(coefficients))
    raw_identity = {
        "coefficients": [_rational_pair(item) for item in coefficients],
        "field_id": field.field_id,
        "type": "arbogast.pari.raw-number-field-element/v1",
    }
    if element_id:
        internal = _internal_identity(value)
        if internal is None:
            identity_data: Mapping[str, object] = {
                **raw_identity,
                "type": "arbogast.number_field_element",
            }
            _require_declared_canonical_data(value, identity_data, "number-field element")
        else:
            identity_data = internal
        identity = _bound_identity(identity_data, element_id, "number-field element")
    else:
        element_id = content_address(raw_identity)
        identity = _bound_identity(raw_identity, element_id, "raw number-field element")
    _validate_element_identity(identity, field.field_id, coefficients)
    if nonzero and not any(coefficients):
        raise ValueError("operation requires a nonzero number-field element")
    return _ElementInput(coefficients, element_id, identity)


def _elements(
    field: _FieldInput,
    values: Sequence[_NumberFieldElementLike | Sequence[object]],
    *,
    nonzero: bool,
) -> tuple[_ElementInput, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("elements must be an exact coefficient-vector sequence")
    return tuple(_element(field, value, nonzero=nonzero) for value in values)


def _place(field: _FieldInput, value: object) -> _FinitePlaceInput | _InfinitePlaceInput:
    if isinstance(value, int) and not isinstance(value, bool):
        return _finite_place(field, value)
    kind_value = getattr(value, "kind", None)
    if kind_value is None:
        return _finite_place(field, value)
    kind = str(getattr(kind_value, "value", kind_value)).lower()
    if kind not in {"real", "complex"}:
        raise ValueError("infinite place kind must be real or complex")
    if getattr(getattr(value, "field", None), "field_id", None) != field.field_id:
        raise ValueError("infinite place belongs to a different pinned field")
    isolation = _rational_vector(getattr(value, "isolation", ()), "place isolation")
    expected = 2 if kind == "real" else 4
    if len(isolation) != expected:
        raise ValueError(f"{kind} place isolation must have {expected} rational endpoints")
    place_id = getattr(value, "place_id", getattr(value, "content_id", None))
    if not isinstance(place_id, str) or not place_id:
        raise ValueError("infinite place ID must be non-empty")
    embedding_index = getattr(value, "embedding_index", None)
    if (
        isinstance(embedding_index, bool)
        or not isinstance(embedding_index, int)
        or embedding_index < 0
    ):
        raise ValueError("infinite place embedding index must be a nonnegative integer")
    internal = _internal_identity(value)
    if internal is None:
        identity_data: Mapping[str, object] = {
            "embedding_index": embedding_index,
            "field_id": field.field_id,
            "isolation": [_rational_pair(item) for item in isolation],
            "kind": kind,
            "type": "arbogast.infinite_place",
            "verification_requirement": _optional_canonical_attribute(
                value,
                "verification_requirement",
                "infinite-place verification requirement",
            ),
        }
        _require_declared_canonical_data(value, identity_data, "infinite place")
    else:
        identity_data = internal
    identity = _bound_identity(identity_data, place_id, "infinite place")
    _validate_infinite_place_identity(identity, field.field_id, kind, isolation, embedding_index)
    return _InfinitePlaceInput(kind, isolation, embedding_index, place_id, identity)


def _finite_place(field: _FieldInput, value: object) -> _FinitePlaceInput:
    if isinstance(value, int) and not isinstance(value, bool):
        prime = _rational_prime(value)
        selector_identity = _raw_finite_place_identity(field.field_id, prime)
        place_id = content_address(selector_identity)
        identity = _bound_identity(selector_identity, place_id, "finite-place selector")
        return _FinitePlaceInput(prime, None, None, None, place_id, identity)
    if getattr(getattr(value, "field", None), "field_id", None) != field.field_id:
        raise ValueError("finite place belongs to a different pinned field")
    prime = _rational_prime(getattr(value, "rational_prime", None))
    ideal_hnf = _integer_matrix(getattr(value, "ideal_hnf", None), field.degree, "ideal HNF")
    candidate_place_id = getattr(value, "place_id", getattr(value, "content_id", None))
    if not isinstance(candidate_place_id, str) or not candidate_place_id:
        raise ValueError("finite place ID must be non-empty")
    ramification_index = _positive_place_integer(
        getattr(value, "ramification_index", None), "ramification index"
    )
    residue_degree = _positive_place_integer(
        getattr(value, "residue_degree", None), "residue degree"
    )
    internal = _internal_identity(value)
    exact_identity: Mapping[str, object]
    if internal is None:
        residue_witness = _required_canonical_attribute(
            value,
            "residue_field_witness",
            "residue-field witness",
        )
        exact_identity = {
            "field_id": field.field_id,
            "ideal_hnf": [list(row) for row in ideal_hnf],
            "ramification_index": ramification_index,
            "rational_prime": prime,
            "residue_degree": residue_degree,
            "residue_field_witness": residue_witness,
            "type": "arbogast.finite_place",
            "verification_requirement": _optional_canonical_attribute(
                value,
                "verification_requirement",
                "finite-place verification requirement",
            ),
        }
        _require_declared_canonical_data(value, exact_identity, "finite place")
    else:
        exact_identity = internal
    identity = _bound_identity(exact_identity, candidate_place_id, "finite place")
    _validate_finite_place_identity(
        identity,
        field.field_id,
        prime,
        ideal_hnf,
        ramification_index,
        residue_degree,
    )
    return _FinitePlaceInput(
        prime,
        ideal_hnf,
        ramification_index,
        residue_degree,
        candidate_place_id,
        identity,
    )


def _finite_places(
    field: _FieldInput,
    values: Sequence[object],
    *,
    allow_rational_prime: bool,
) -> tuple[_FinitePlaceInput, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("places must be a finite sequence")
    result: list[_FinitePlaceInput] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, int) and not allow_rational_prime:
            raise ValueError("this operation requires exact finite places")
        place = _finite_place(field, value)
        if place.place_id in seen:
            raise ValueError("declared place set contains a duplicate")
        seen.add(place.place_id)
        result.append(place)
    return tuple(sorted(result, key=lambda item: item.place_id))


def _raw_field_identity(polynomial: tuple[Fraction, ...]) -> dict[str, object]:
    return {
        "defining_polynomial": [_rational_pair(item) for item in polynomial],
        "type": "arbogast.pari.raw-number-field/v1",
    }


def _raw_finite_place_identity(field_id: str, prime: int) -> dict[str, object]:
    return {
        "field_id": field_id,
        "rational_prime": prime,
        "selection": "unique-prime-above",
        "type": "arbogast.pari.finite-place-selector/v1",
    }


def _internal_identity(value: object) -> Mapping[str, object] | None:
    identity = getattr(value, "_arbogast_canonical_identity", None)
    if identity is None:
        return None
    if isinstance(identity, FrozenMap):
        return identity.to_dict()
    if not isinstance(identity, Mapping) or any(not isinstance(key, str) for key in identity):
        raise ValueError("internal canonical identity must be a string-keyed mapping")
    return cast(Mapping[str, object], identity)


def _bound_identity(
    value: Mapping[str, object],
    claimed_id: str,
    name: str,
) -> FrozenMap:
    identity = freeze_mapping(value)
    if content_address(identity.to_dict()) != claimed_id:
        raise ValueError(f"{name} ID does not match its complete canonical presentation")
    return identity


def _canonical_attribute(value: object, label: str) -> object:
    method = getattr(value, "to_canonical_data", None)
    if callable(method):
        payload = method()
    else:
        method = getattr(value, "to_dict", None)
        if callable(method):
            payload = method()
        elif isinstance(value, Mapping):
            payload = value
        else:
            raise ValueError(f"{label} does not expose canonical data")
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{label} canonical data must be a string-keyed mapping")
    return freeze_mapping(cast(Mapping[str, object], payload)).to_dict()


def _optional_canonical_attribute(value: object, attribute: str, label: str) -> object:
    item = getattr(value, attribute, None)
    return None if item is None else _canonical_attribute(item, label)


def _required_canonical_attribute(value: object, attribute: str, label: str) -> object:
    item = getattr(value, attribute, None)
    if item is None:
        raise ValueError(f"{label} is required to reproduce the canonical place ID")
    return _canonical_attribute(item, label)


def _require_declared_canonical_data(
    value: object,
    expected: Mapping[str, object],
    name: str,
) -> None:
    method = getattr(value, "to_canonical_data", None)
    if not callable(method):
        return
    declared = method()
    if not isinstance(declared, Mapping) or any(not isinstance(key, str) for key in declared):
        raise ValueError(f"{name} canonical data must be a string-keyed mapping")
    if freeze_mapping(cast(Mapping[str, object], declared)) != freeze_mapping(expected):
        raise ValueError(f"{name} attributes disagree with its canonical presentation")


def _validate_field_identity(
    identity: FrozenMap,
    polynomial: tuple[Fraction, ...],
    basis: tuple[tuple[Fraction, ...], ...] | None,
) -> None:
    payload = identity.to_dict()
    kind = payload.get("type")
    if kind == "arbogast.pari.raw-number-field/v1":
        expected = _raw_field_identity(polynomial)
        if basis is not None or payload != expected:
            raise ValueError("raw number-field identity disagrees with its coefficient vector")
        return
    expected_keys = {
        "defining_polynomial",
        "integral_basis",
        "irreducibility_requirement",
        "irreducibility_witness",
        "type",
    }
    if kind != "arbogast.number_field" or set(payload) != expected_keys or basis is None:
        raise ValueError("canonical number-field identity has an unsupported shape")
    if any(coefficient.denominator != 1 for coefficient in polynomial):
        raise ValueError("canonical number-field polynomial is not integral")
    if payload["defining_polynomial"] != [item.numerator for item in polynomial]:
        raise ValueError("number-field identity polynomial does not match replay data")
    expected_basis = [[_rational_pair(item) for item in row] for row in basis]
    if payload["integral_basis"] != expected_basis:
        raise ValueError("number-field identity basis does not match replay data")


def _validate_element_identity(
    identity: FrozenMap,
    field_id: str,
    coefficients: tuple[Fraction, ...],
) -> None:
    payload = identity.to_dict()
    expected_keys = {"coefficients", "field_id", "type"}
    if set(payload) != expected_keys or payload.get("type") not in {
        "arbogast.number_field_element",
        "arbogast.pari.raw-number-field-element/v1",
    }:
        raise ValueError("number-field element identity has an unsupported shape")
    if payload["field_id"] != field_id:
        raise ValueError("number-field element identity names a different field")
    if payload["coefficients"] != [_rational_pair(item) for item in coefficients]:
        raise ValueError("number-field element identity coefficients do not match replay data")


def _validate_finite_place_identity(
    identity: FrozenMap,
    field_id: str,
    prime: int,
    ideal_hnf: tuple[tuple[int, ...], ...] | None,
    ramification_index: int | None,
    residue_degree: int | None,
) -> None:
    payload = identity.to_dict()
    if payload.get("type") == "arbogast.pari.finite-place-selector/v1":
        expected = _raw_finite_place_identity(field_id, prime)
        if (
            ideal_hnf is not None
            or ramification_index is not None
            or residue_degree is not None
            or payload != expected
        ):
            raise ValueError("finite-place selector identity disagrees with replay data")
        return
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
    if payload.get("type") != "arbogast.finite_place" or set(payload) != expected_keys:
        raise ValueError("finite-place identity has an unsupported shape")
    if (
        ideal_hnf is None
        or ramification_index is None
        or residue_degree is None
        or payload["field_id"] != field_id
        or payload["rational_prime"] != prime
        or payload["ideal_hnf"] != [list(row) for row in ideal_hnf]
        or payload["ramification_index"] != ramification_index
        or payload["residue_degree"] != residue_degree
    ):
        raise ValueError("finite-place identity does not match replay data")


def _validate_infinite_place_identity(
    identity: FrozenMap,
    field_id: str,
    kind: str,
    isolation: tuple[Fraction, ...],
    embedding_index: int,
) -> None:
    payload = identity.to_dict()
    expected_keys = {
        "embedding_index",
        "field_id",
        "isolation",
        "kind",
        "type",
        "verification_requirement",
    }
    if payload.get("type") != "arbogast.infinite_place" or set(payload) != expected_keys:
        raise ValueError("infinite-place identity has an unsupported shape")
    if (
        payload["field_id"] != field_id
        or payload["kind"] != kind
        or payload["isolation"] != [_rational_pair(item) for item in isolation]
        or payload["embedding_index"] != embedding_index
    ):
        raise ValueError("infinite-place identity does not match replay data")


def _positive_place_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"finite place {name} must be a positive integer")
    return value


def _rational_vector(
    values: object,
    name: str,
    *,
    allow_empty: bool = False,
) -> tuple[Fraction, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence of exact rationals")
    result = tuple(_rational(value, name) for value in values)
    if not result and not allow_empty:
        raise ValueError(f"{name} cannot be empty")
    return result


def _rational_matrix(values: object, size: int, name: str) -> tuple[tuple[Fraction, ...], ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be an exact square matrix")
    rows = tuple(_rational_vector(row, name) for row in values)
    if len(rows) != size or any(len(row) != size for row in rows):
        raise ValueError(f"{name} must be a {size} by {size} matrix")
    return rows


def _integer_matrix(values: object, size: int, name: str) -> tuple[tuple[int, ...], ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be an integer square matrix")
    rows: list[tuple[int, ...]] = []
    for row in values:
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
            raise ValueError(f"{name} rows must be integer sequences")
        normalized = tuple(row)
        if any(isinstance(item, bool) or not isinstance(item, int) for item in normalized):
            raise ValueError(f"{name} entries must be integers")
        rows.append(cast(tuple[int, ...], normalized))
    if len(rows) != size or any(len(row) != size for row in rows):
        raise ValueError(f"{name} must be a {size} by {size} matrix")
    return tuple(rows)


def _rational(value: object, name: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{name} cannot contain booleans")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        pair = tuple(value)
        if (
            len(pair) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) for item in pair)
            and pair[1] != 0
        ):
            return Fraction(cast(int, pair[0]), cast(int, pair[1]))
    raise ValueError(f"{name} accepts only integers, Fractions, or [numerator, denominator]")


def _rational_prime(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not _is_prime(value):
        raise ValueError("rational prime must be a positive prime integer")
    return value


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    divisor = 3
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += 2
    return True


def _positive_integer(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _nonnegative_integer(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [0, {maximum}]")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("allow_grh must be boolean")
    return value


def _gp_rational(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def _gp_polynomial(coefficients: tuple[Fraction, ...]) -> str:
    terms = [f"({_gp_rational(value)})*x^{power}" for power, value in enumerate(coefficients)]
    return "(" + "+".join(terms) + ")"


def _gp_element(coefficients: tuple[Fraction, ...]) -> str:
    return f"Mod({_gp_polynomial(coefficients)},P)"


def _gp_matrix(rows: tuple[tuple[Fraction, ...], ...]) -> str:
    columns = zip(*rows, strict=True)
    rendered = ",".join(
        "[" + ",".join(_gp_rational(value) for value in column) + "]~" for column in columns
    )
    return f"Mat([{rendered}])"


def _gp_integer_matrix(rows: tuple[tuple[int, ...], ...]) -> str:
    return _gp_matrix(tuple(tuple(Fraction(item) for item in row) for row in rows))


def _rational_pair(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _replay_spec(field: _FieldInput, arguments: Mapping[str, object]) -> dict[str, object]:
    integral_basis = (
        None
        if field.integral_basis is None
        else [[_rational_pair(value) for value in row] for row in field.integral_basis]
    )
    return {
        "arguments": dict(arguments),
        "field": {
            "defining_polynomial": [_rational_pair(value) for value in field.polynomial],
            "field_id": field.field_id,
            "identity": field.identity.to_dict(),
            "integral_basis": integral_basis,
        },
    }


def _element_replay(element: _ElementInput) -> dict[str, object]:
    return {
        "coefficients": [_rational_pair(value) for value in element.coefficients],
        "element_id": element.element_id,
        "identity": element.identity.to_dict(),
    }


def _place_replay(place: _FinitePlaceInput | _InfinitePlaceInput) -> dict[str, object]:
    if isinstance(place, _FinitePlaceInput):
        return {
            "ideal_hnf": (
                None if place.ideal_hnf is None else [list(row) for row in place.ideal_hnf]
            ),
            "identity": place.identity.to_dict(),
            "place_id": place.place_id,
            "ramification_index": place.ramification_index,
            "rational_prime": place.rational_prime,
            "residue_degree": place.residue_degree,
        }
    return {
        "embedding_index": place.embedding_index,
        "identity": place.identity.to_dict(),
        "isolation": [_rational_pair(value) for value in place.isolation],
        "kind": place.kind,
        "place_id": place.place_id,
    }


def _operation_request(
    operation: str,
    field: _FieldInput,
    inputs: Mapping[str, object],
    parameters: Mapping[str, object],
) -> dict[str, object]:
    return {
        "field": field.field_id,
        "inputs": dict(inputs),
        "operation": operation,
        "parameters": dict(parameters),
        "protocol": RESPONSE_SCHEMA,
        "template": PARI_TEMPLATE_VERSION,
    }


def _request_seed(request_id: str) -> int:
    return int(request_id.split(":", 1)[1][:15], 16) + 1


def _exact_decimal(value: float) -> str:
    return format(value, ".17g")


def _validate_smoke_result(value: Mapping[str, object]) -> None:
    if set(value) != set(_ARITHMETIC_CAPABILITIES) or any(
        not isinstance(item, bool) for item in value.values()
    ):
        raise PariProtocolError("PARI smoke response had the wrong capability shape")


def _validate_field_invariants(value: Mapping[str, object], degree: int) -> None:
    _exact_keys(value, {"degree", "discriminant", "index", "integral_basis", "signature"})
    if value["degree"] != degree:
        raise PariProtocolError("PARI field degree did not match the pinned polynomial")
    _integer(value["discriminant"], "field discriminant")
    if _integer(value["index"], "field index") <= 0:
        raise PariProtocolError("PARI field index must be positive")
    signature = _integer_list(value["signature"], "field signature")
    if len(signature) != 2 or signature[0] + 2 * signature[1] != degree:
        raise PariProtocolError("PARI field signature does not match the degree")
    _rational_pair_matrix(value["integral_basis"], degree, degree, "integral basis")


def _validate_prime_decomposition(value: Mapping[str, object], degree: int, prime: int) -> None:
    _exact_keys(value, {"prime_ideals", "rational_prime"})
    if value["rational_prime"] != prime:
        raise PariProtocolError("PARI prime decomposition returned the wrong rational prime")
    records = _object_list(value["prime_ideals"], "prime ideals")
    if not records:
        raise PariProtocolError("PARI prime decomposition cannot be empty")
    local_degree = 0
    for record in records:
        _exact_keys(record, {"ideal_hnf", "norm", "ramification_index", "residue_degree"})
        _integer_matrix_shape(record["ideal_hnf"], degree, degree, "prime ideal HNF")
        norm = _integer(record["norm"], "prime ideal norm")
        e = _integer(record["ramification_index"], "ramification index")
        f = _integer(record["residue_degree"], "residue degree")
        if norm != prime**f or e <= 0 or f <= 0:
            raise PariProtocolError("PARI returned inconsistent prime-ideal invariants")
        local_degree += e * f
    if local_degree != degree:
        raise PariProtocolError("PARI prime decomposition does not account for the field degree")


def _validate_complex_root_isolation(
    value: Mapping[str, object],
    field: _FieldInput,
    embedding_index: int,
) -> None:
    _exact_keys(
        value,
        {
            "embedding_index",
            "isolation",
            "kind",
            "ordering",
            "root_count",
            "rouche_witness",
        },
    )
    if value["embedding_index"] != embedding_index:
        raise PariProtocolError("PARI isolated the wrong complex embedding index")
    if value["kind"] != "complex" or value["root_count"] != 1:
        raise PariProtocolError("PARI complex isolation did not certify exactly one root")
    if value["ordering"] != "pari-polroots-positive-imaginary":
        raise PariProtocolError("PARI complex embedding ordering changed")
    raw_isolation = _list(value["isolation"], "complex isolation")
    if len(raw_isolation) != 4:
        raise PariProtocolError("PARI complex isolation must have four rational endpoints")
    isolation = tuple(_fraction_pair(item, "complex isolation") for item in raw_isolation)
    real_lower, real_upper, imaginary_lower, imaginary_upper = isolation
    if real_lower >= real_upper or not 0 < imaginary_lower < imaginary_upper:
        raise PariProtocolError("PARI complex isolation rectangle is not canonical")
    raw_witness = value["rouche_witness"]
    if not isinstance(raw_witness, dict):
        raise PariProtocolError("PARI Rouche witness must be an object")
    witness = cast(dict[str, object], raw_witness)
    _exact_keys(
        witness,
        {
            "center",
            "inner_margin",
            "inner_radius",
            "outer_margin",
            "outer_radius",
        },
    )
    raw_center = _list(witness["center"], "Rouche center")
    if len(raw_center) != 2:
        raise PariProtocolError("PARI Rouche center must have two rational coordinates")
    center = (
        _fraction_pair(raw_center[0], "Rouche center"),
        _fraction_pair(raw_center[1], "Rouche center"),
    )
    inner_radius = _fraction_pair(witness["inner_radius"], "inner radius")
    outer_radius = _fraction_pair(witness["outer_radius"], "outer radius")
    inner_margin = _fraction_pair(witness["inner_margin"], "inner margin")
    outer_margin = _fraction_pair(witness["outer_margin"], "outer margin")
    if inner_radius <= 0 or outer_radius != 2 * inner_radius:
        raise PariProtocolError("PARI Rouche radii do not bind the isolation square")
    if (
        real_lower != center[0] - inner_radius
        or real_upper != center[0] + inner_radius
        or imaginary_lower != center[1] - inner_radius
        or imaginary_upper != center[1] + inner_radius
    ):
        raise PariProtocolError("PARI Rouche witness does not bind the isolation rectangle")
    coefficients = _gaussian_taylor_coefficients(field.polynomial, center)
    expected_inner = _rouche_margin(coefficients, inner_radius)
    expected_outer = _rouche_margin(coefficients, outer_radius)
    if inner_margin != expected_inner or outer_margin != expected_outer:
        raise PariProtocolError("PARI Rouche margins do not replay exactly")
    if inner_margin <= 0 or outer_margin <= 0:
        raise PariProtocolError("PARI Rouche witness does not isolate one simple root")


def _gaussian_taylor_coefficients(
    polynomial: tuple[Fraction, ...],
    center: tuple[Fraction, Fraction],
) -> tuple[tuple[Fraction, Fraction], ...]:
    degree = len(polynomial) - 1
    result: list[tuple[Fraction, Fraction]] = []
    for exponent in range(degree + 1):
        total = (Fraction(0), Fraction(0))
        for source_exponent in range(exponent, degree + 1):
            power = _gaussian_power(center, source_exponent - exponent)
            scalar = polynomial[source_exponent] * comb(source_exponent, exponent)
            total = (total[0] + scalar * power[0], total[1] + scalar * power[1])
        result.append(total)
    return tuple(result)


def _gaussian_power(
    value: tuple[Fraction, Fraction],
    exponent: int,
) -> tuple[Fraction, Fraction]:
    result = (Fraction(1), Fraction(0))
    factor = value
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _gaussian_multiply(result, factor)
        factor = _gaussian_multiply(factor, factor)
        remaining >>= 1
    return result


def _gaussian_multiply(
    left: tuple[Fraction, Fraction],
    right: tuple[Fraction, Fraction],
) -> tuple[Fraction, Fraction]:
    return (
        left[0] * right[0] - left[1] * right[1],
        left[0] * right[1] + left[1] * right[0],
    )


def _rouche_margin(
    coefficients: tuple[tuple[Fraction, Fraction], ...],
    radius: Fraction,
) -> Fraction:
    linear = max(abs(coefficients[1][0]), abs(coefficients[1][1])) * radius
    remainder = abs(coefficients[0][0]) + abs(coefficients[0][1])
    for exponent, coefficient in enumerate(coefficients[2:], start=2):
        remainder += (abs(coefficient[0]) + abs(coefficient[1])) * radius**exponent
    return linear - remainder


def _validate_s_unit_result(value: Mapping[str, object], degree: int) -> None:
    _exact_keys(
        value,
        {
            "certified",
            "complete",
            "prime_ideal_hnfs",
            "representatives",
            "roots_of_unity_order",
            "s_class_2_torsion",
            "s_class_group_cyclic_orders",
            "s_unit_rank",
        },
    )
    _bool(value["certified"], "certification flag")
    complete = _bool(value["complete"], "S-Kummer completeness flag")
    prime_hnfs = _list(value["prime_ideal_hnfs"], "prime ideal HNFs")
    for matrix in prime_hnfs:
        _integer_matrix_shape(matrix, degree, degree, "prime ideal HNF")
    representatives = _list(value["representatives"], "S-Kummer representatives")
    for representative in representatives:
        _rational_pair_vector(representative, degree, "S-Kummer representative")
    order = _integer(value["roots_of_unity_order"], "roots of unity order")
    rank = _integer(value["s_unit_rank"], "S-unit rank")
    if order <= 0 or rank < 0:
        raise PariProtocolError("PARI returned inconsistent S-unit data")
    s_class_orders = _positive_integer_list(
        value["s_class_group_cyclic_orders"], "S-class group orders"
    )
    torsion = _object_list(value["s_class_2_torsion"], "S-class 2-torsion")
    even_orders = [cyclic_order for cyclic_order in s_class_orders if cyclic_order % 2 == 0]
    if len(torsion) != len(even_orders):
        raise PariProtocolError("PARI omitted an S-class 2-torsion lift")
    if len(representatives) != rank + len(torsion):
        raise PariProtocolError("PARI S-Kummer basis has the wrong number of lifts")
    for index, record in enumerate(torsion):
        _exact_keys(
            record,
            {
                "cyclic_order",
                "ideal_hnf",
                "principalization_generator",
                "s_prime_exponents",
            },
        )
        cyclic_order = _integer(record["cyclic_order"], "S-class cyclic order")
        if cyclic_order != even_orders[index]:
            raise PariProtocolError("PARI S-class lift has the wrong cyclic order")
        _integer_matrix_shape(record["ideal_hnf"], degree, degree, "S-class lift HNF")
        _rational_pair_vector(
            record["principalization_generator"],
            degree,
            "S-class principalization generator",
        )
        exponents = _integer_list(record["s_prime_exponents"], "S-prime exponents")
        if len(exponents) != len(prime_hnfs):
            raise PariProtocolError("S-class lift has the wrong S-prime exponent count")
        if representatives[rank + index] != record["principalization_generator"]:
            raise PariProtocolError("S-class lift is not appended to the Kummer basis")
    if complete is not True:
        raise PariProtocolError("PARI returned an incomplete S-Kummer presentation")


def _validate_class_2_result(value: Mapping[str, object], degree: int) -> None:
    _exact_keys(value, {"certified", "class_group_cyclic_orders", "two_torsion"})
    _bool(value["certified"], "certification flag")
    orders = _positive_integer_list(value["class_group_cyclic_orders"], "class group orders")
    records = _object_list(value["two_torsion"], "class-group 2-torsion")
    if len(records) != sum(order % 2 == 0 for order in orders):
        raise PariProtocolError("PARI returned the wrong number of 2-torsion generators")
    for record in records:
        _exact_keys(record, {"cyclic_order", "ideal_hnf", "square_generator"})
        order = _integer(record["cyclic_order"], "class cyclic order")
        if order <= 0 or order % 2:
            raise PariProtocolError("PARI 2-torsion record has an odd cyclic order")
        _integer_matrix_shape(record["ideal_hnf"], degree, degree, "2-torsion ideal HNF")
        _rational_pair_vector(record["square_generator"], degree, "principalization witness")


def _validate_local_squareclasses(value: Mapping[str, object], degree: int, prime: int) -> None:
    _exact_keys(
        value,
        {
            "complete",
            "dimension",
            "ramification_index",
            "rational_prime",
            "representatives",
            "residue_degree",
            "tested_candidates",
        },
    )
    complete = _bool(value["complete"], "local completeness")
    dimension = _integer(value["dimension"], "local squareclass dimension")
    if value["rational_prime"] != prime or dimension <= 0:
        raise PariProtocolError("PARI returned inconsistent local squareclass data")
    representatives = _list(value["representatives"], "local representatives")
    if len(representatives) > dimension or (complete and len(representatives) != dimension):
        raise PariProtocolError("PARI local basis size does not match its completeness claim")
    for representative in representatives:
        _rational_pair_vector(representative, degree, "local representative")
    if _integer(value["ramification_index"], "ramification index") <= 0:
        raise PariProtocolError("PARI local ramification index must be positive")
    if _integer(value["residue_degree"], "residue degree") <= 0:
        raise PariProtocolError("PARI local residue degree must be positive")
    if _integer(value["tested_candidates"], "tested candidates") < 0:
        raise PariProtocolError("PARI tested-candidate count must be nonnegative")


def _validate_localization_matrix(
    value: Mapping[str, object], degree: int, generator_count: int
) -> None:
    _exact_keys(value, {"complete", "local_basis", "matrix", "rational_prime"})
    if _bool(value["complete"], "localization completeness") is not True:
        raise PariProtocolError("PARI localization matrix must use a complete local basis")
    basis = _list(value["local_basis"], "local basis")
    for representative in basis:
        _rational_pair_vector(representative, degree, "local basis representative")
    matrix = _list(value["matrix"], "localization matrix")
    if len(matrix) != len(basis):
        raise PariProtocolError("PARI localization row count does not match local basis")
    for row in matrix:
        entries = _integer_list(row, "localization row")
        if len(entries) != generator_count or any(entry not in {0, 1} for entry in entries):
            raise PariProtocolError("PARI localization matrix is not binary with pinned shape")
    _rational_prime(value["rational_prime"])


def _validate_relative_norm(value: Mapping[str, object]) -> None:
    _exact_keys(value, {"base_field", "norm"})
    if value["base_field"] != "Q":
        raise PariProtocolError("PARI relative norm returned the wrong base field")
    _rational_pair_value(value["norm"], "relative norm")


def _validate_hilbert_result(value: Mapping[str, object]) -> None:
    _exact_keys(value, {"place_kind", "symbol"})
    if value["place_kind"] not in {"global", "finite", "real", "complex"}:
        raise PariProtocolError("PARI Hilbert result returned an invalid place kind")
    if value["symbol"] not in {-1, 1}:
        raise PariProtocolError("PARI Hilbert symbol must be -1 or 1")


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise PariProtocolError("PARI operation response has missing or foreign fields")


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PariProtocolError(f"PARI {name} must be an integer")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise PariProtocolError(f"PARI {name} must be boolean")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise PariProtocolError(f"PARI {name} must be a list")
    return value


def _object_list(value: object, name: str) -> list[dict[str, object]]:
    values = _list(value, name)
    if any(not isinstance(item, dict) for item in values):
        raise PariProtocolError(f"PARI {name} must contain objects")
    return cast(list[dict[str, object]], values)


def _integer_list(value: object, name: str) -> list[int]:
    values = _list(value, name)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise PariProtocolError(f"PARI {name} must contain integers")
    return cast(list[int], values)


def _positive_integer_list(value: object, name: str) -> list[int]:
    values = _integer_list(value, name)
    if any(item <= 0 for item in values):
        raise PariProtocolError(f"PARI {name} must contain positive integers")
    return values


def _integer_matrix_shape(value: object, rows: int, columns: int, name: str) -> None:
    matrix = _list(value, name)
    if len(matrix) != rows:
        raise PariProtocolError(f"PARI {name} has the wrong row count")
    for row in matrix:
        if len(_integer_list(row, name)) != columns:
            raise PariProtocolError(f"PARI {name} has the wrong column count")


def _rational_pair_value(value: object, name: str) -> None:
    values = _integer_list(value, name)
    if len(values) != 2 or values[1] <= 0:
        raise PariProtocolError(f"PARI {name} is not a normalized rational pair")
    if Fraction(values[0], values[1]).denominator != values[1]:
        raise PariProtocolError(f"PARI {name} rational pair is not reduced")


def _fraction_pair(value: object, name: str) -> Fraction:
    _rational_pair_value(value, name)
    numerator, denominator = _integer_list(value, name)
    return Fraction(numerator, denominator)


def _rational_pair_vector(value: object, length: int, name: str) -> None:
    vector = _list(value, name)
    if len(vector) != length:
        raise PariProtocolError(f"PARI {name} has the wrong length")
    for item in vector:
        _rational_pair_value(item, name)


def _rational_pair_matrix(value: object, rows: int, columns: int, name: str) -> None:
    matrix = _list(value, name)
    if len(matrix) != rows:
        raise PariProtocolError(f"PARI {name} has the wrong row count")
    for row in matrix:
        _rational_pair_vector(row, columns, name)


PARI = PariBackend()

__all__ = [
    "PARI",
    "PARI_CAPABILITIES",
    "PARI_EXCLUSIVE_MAXIMUM_VERSION",
    "PARI_MINIMUM_VERSION",
    "PARI_SUPPORTED_RANGE",
    "PariBackend",
    "normalize_pari_version",
]
