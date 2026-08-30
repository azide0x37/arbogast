from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arbogast.backends import (
    PARI_CAPABILITIES,
    BackendStatus,
    PariArithmeticResult,
    PariBackend,
    PariCompleteness,
    PariOutcome,
    PariOutputLimitError,
    PariProtocolError,
    PariTimeoutError,
    decode_pari_arithmetic_result,
    normalize_pari_version,
)
from arbogast.backends.pari import _ARITHMETIC_CAPABILITIES, PARI_TEMPLATE_VERSION, _request_seed
from arbogast.backends.pari_certificate import (
    create_pari_operational_certificate,
    create_pari_verification_certificate,
)
from arbogast.backends.pari_protocol import (
    BEGIN_PREFIX,
    END_PREFIX,
    RESPONSE_SCHEMA,
    ProcessOutput,
    framed_program,
    parse_framed_response,
    run_secure_process,
)
from arbogast.cert import (
    CertificateLayer,
    CertificateRef,
    DiscoveryReceipt,
    VerificationCertificate,
    content_address,
    verify_certificate,
)
from arbogast.cert.registry import CertificateVerificationError
from arbogast.claims import EpistemicStatus
from arbogast.galois import (
    Completeness,
    FinitePlace,
    InfinitePlace,
    NumberField,
    Unsupported,
    kummer_space,
    local_h1,
    localize,
)

REQUEST_ID = "sha256:" + "1" * 64


def _frame(payload: str, *, request_id: str = REQUEST_ID) -> ProcessOutput:
    text = (
        f"{BEGIN_PREFIX}{request_id}\n"
        f'{{"ok":true,"request_id":"{request_id}","result":{payload},'
        f'"schema":"{RESPONSE_SCHEMA}"}}\n'
        f"{END_PREFIX}{request_id}\n"
    )
    return ProcessOutput(0, text.encode(), b"")


class _SmokeBackend(PariBackend):
    def _execute(
        self,
        executable: str,
        request: dict[str, object],
        body: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del executable, request, body, timeout_seconds
        return {name: True for name in _ARITHMETIC_CAPABILITIES}


class _StubBackend(PariBackend):
    def status(self) -> BackendStatus:
        return BackendStatus(
            "pari",
            True,
            PARI_CAPABILITIES,
            version="2.17.4",
            executable="/test/gp",
        )

    def _execute(
        self,
        executable: str,
        request: dict[str, object],
        body: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del executable, body, timeout_seconds
        operation = request["operation"]
        allow_grh = bool(dict(request.get("parameters", {})).get("allow_grh", False))
        responses: dict[object, dict[str, Any]] = {
            "field_invariants": {
                "degree": 1,
                "discriminant": 1,
                "index": 1,
                "integral_basis": [[[1, 1]]],
                "signature": [1, 0],
            },
            "prime_decomposition": {
                "prime_ideals": [
                    {
                        "ideal_hnf": [[2]],
                        "norm": 2,
                        "ramification_index": 1,
                        "residue_degree": 1,
                    }
                ],
                "rational_prime": 2,
            },
            "s_unit_squareclasses": {
                "certified": not allow_grh,
                "complete": True,
                "prime_ideal_hnfs": [[[2]]],
                "representatives": [[[-1, 1]], [[2, 1]]],
                "roots_of_unity_order": 2,
                "s_class_2_torsion": [],
                "s_class_group_cyclic_orders": [],
                "s_unit_rank": 2,
            },
            "class_group_2_torsion": {
                "certified": not allow_grh,
                "class_group_cyclic_orders": [],
                "two_torsion": [],
            },
            "complex_root_isolation": {
                "embedding_index": 0,
                "isolation": [[-1, 4], [1, 4], [3, 4], [5, 4]],
                "kind": "complex",
                "ordering": "pari-polroots-positive-imaginary",
                "root_count": 1,
                "rouche_witness": {
                    "center": [[0, 1], [1, 1]],
                    "inner_margin": [7, 16],
                    "inner_radius": [1, 4],
                    "outer_margin": [3, 4],
                    "outer_radius": [1, 2],
                },
            },
            "local_squareclasses": {
                "complete": True,
                "dimension": 3,
                "ramification_index": 1,
                "rational_prime": 2,
                "representatives": [[[-1, 1]], [[2, 1]], [[5, 1]]],
                "residue_degree": 1,
                "tested_candidates": 9,
            },
            "localization_matrix": {
                "complete": True,
                "local_basis": [[[-1, 1]], [[2, 1]], [[5, 1]]],
                "matrix": [[1, 0], [0, 1], [0, 0]],
                "rational_prime": 2,
            },
            "relative_norm": {"base_field": "Q", "norm": [-1, 1]},
            "quadratic_hilbert_pairing": {"place_kind": "finite", "symbol": -1},
        }
        return responses[operation]


def test_pari_version_normalization_and_supported_smoke_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arbogast.backends.pari.shutil.which", lambda name: "/test/gp")
    monkeypatch.setattr(
        "arbogast.backends.pari.run_secure_process",
        lambda *args, **kwargs: ProcessOutput(0, b"2.17.4\n", b""),
    )
    probe = _SmokeBackend().probe()
    assert normalize_pari_version("GP/PARI CALCULATOR Version 2.15.5 (released)") == "2.15.5"
    assert normalize_pari_version("2.17.4") == "2.17.4"
    assert normalize_pari_version("2.17") is None
    assert probe.status.available
    assert probe.normalized_version == "2.17.4"
    assert tuple(probe.smoke_tests.values()) == (True,) * len(_ARITHMETIC_CAPABILITIES)


def test_pari_probe_rejects_absence_and_unsupported_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arbogast.backends.pari.shutil.which", lambda name: None)
    assert not PariBackend().probe().status.available
    monkeypatch.setattr("arbogast.backends.pari.shutil.which", lambda name: "/test/gp")
    for version in ("2.15.4", "2.18.0"):
        monkeypatch.setattr(
            "arbogast.backends.pari.run_secure_process",
            lambda *args, _version=version, **kwargs: ProcessOutput(
                0, f"{_version}\n".encode(), b""
            ),
        )
        probe = PariBackend().probe()
        assert not probe.status.available
        assert probe.status.capabilities == ()
        assert "unsupported PARI version" in (probe.status.reason or "")


def test_absent_pari_fails_closed_through_public_arithmetic_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arbogast.backends.pari.shutil.which", lambda name: None)
    field = NumberField((-1, -1, 1), generator_name="t")
    two_adic = FinitePlace(field, 2, ((2, 0), (0, 2)), 1, 2)

    automatic_global = kummer_space(field, (two_adic,))
    automatic_local = local_h1(two_adic)
    supplied_global = kummer_space(
        field,
        (two_adic,),
        generators=(field.generator,),
        completeness=Completeness.CANDIDATE,
    )
    automatic_localization = localize(supplied_global, two_adic)

    assert isinstance(automatic_global, Unsupported)
    assert isinstance(automatic_local, Unsupported)
    assert isinstance(automatic_localization, Unsupported)
    assert automatic_global.verify()
    assert automatic_local.verify()
    assert automatic_localization.verify()


def test_strict_framed_json_rejects_malformed_truncated_wrong_id_and_foreign_output() -> None:
    assert parse_framed_response(_frame('{"answer":5}'), REQUEST_ID) == {"answer": 5}
    wrong = "sha256:" + "2" * 64
    with pytest.raises(PariProtocolError, match="request-bound"):
        parse_framed_response(_frame('{"answer":5}', request_id=wrong), REQUEST_ID)
    with pytest.raises(PariProtocolError, match="request-bound"):
        parse_framed_response(ProcessOutput(0, _frame("{}").stdout[:-10], b""), REQUEST_ID)
    with pytest.raises(PariProtocolError, match="strict JSON"):
        parse_framed_response(_frame('{"answer":1.5}'), REQUEST_ID)
    with pytest.raises(PariProtocolError, match="strict JSON"):
        parse_framed_response(_frame('{"answer":1,"answer":2}'), REQUEST_ID)
    with pytest.raises(PariProtocolError, match="unexpected stderr"):
        parse_framed_response(ProcessOutput(0, _frame("{}").stdout, b"warning"), REQUEST_ID)
    foreign = ProcessOutput(0, b"banner\n" + _frame("{}").stdout, b"")
    with pytest.raises(PariProtocolError, match="request-bound"):
        parse_framed_response(foreign, REQUEST_ID)


def test_framed_program_has_fixed_protocol_and_no_generic_eval_surface() -> None:
    source = framed_program(REQUEST_ID, 7, 'arb_emit(Str("{\\"answer\\":5}"));')
    assert b"setrand(7)" in source
    assert b"default(secure, 1)" in source
    assert REQUEST_ID.encode() in source
    assert not hasattr(PariBackend, "gp_eval")
    assert not hasattr(PariBackend, "eval")


def test_secure_process_enforces_timeout_output_cap_and_ignored_startup(
    tmp_path: Path,
) -> None:
    hostile = tmp_path / "hostile-gp"
    hostile.write_text('#!/bin/sh\nprintf \'ok:%s:%s:%s\\n\' "$1" "$2" "$HOME"\n')
    hostile.chmod(0o700)
    output = run_secure_process(
        str(hostile),
        (),
        input_bytes=None,
        timeout_seconds=5,
        output_limit_bytes=4096,
        memory_limit_bytes=268_435_456,
        cpu_limit_seconds=5,
    )
    rendered = output.stdout.decode()
    assert rendered.startswith("ok:-f:-q:")
    assert str(Path.home()) not in rendered

    sleeper = tmp_path / "slow-gp"
    sleeper.write_text("#!/bin/sh\nsleep 2\n")
    sleeper.chmod(0o700)
    with pytest.raises(PariTimeoutError):
        run_secure_process(
            str(sleeper),
            (),
            input_bytes=None,
            timeout_seconds=0.05,
            output_limit_bytes=4096,
            memory_limit_bytes=268_435_456,
            cpu_limit_seconds=2,
        )

    noisy = tmp_path / "noisy-gp"
    noisy.write_text("#!/bin/sh\nyes x | head -c 8192\n")
    noisy.chmod(0o700)
    with pytest.raises(PariOutputLimitError):
        run_secure_process(
            str(noisy),
            (),
            input_bytes=None,
            timeout_seconds=2,
            output_limit_bytes=1024,
            memory_limit_bytes=268_435_456,
            cpu_limit_seconds=2,
        )


def test_all_closed_pari_operations_return_typed_receipts_and_central_certificates() -> None:
    backend = _StubBackend()
    results = (
        backend.field_invariants((0, 1)),
        backend.prime_decomposition((0, 1), 2),
        backend.complex_root_isolation((1, 0, 1), 0),
        backend.s_unit_squareclasses((0, 1), (2,)),
        backend.class_group_2_torsion((0, 1)),
        backend.local_squareclasses((0, 1), 2),
        backend.localization_matrix((0, 1), ((-1,), (2,)), 2),
        backend.relative_norm((0, 1), (3,)),
        backend.quadratic_hilbert_pairing((0, 1), (-1,), (-1,), 2),
    )
    assert {result.operation for result in results} == set(_ARITHMETIC_CAPABILITIES) - {
        "quadratic-hilbert-pairings",
        "relative-norms",
        "localization-matrices",
        "prime-decomposition",
        "field-invariants",
        "class-group-2-torsion",
        "complex-root-isolation",
        "local-squareclasses",
        "s-unit-squareclasses",
    } | {
        "field_invariants",
        "prime_decomposition",
        "s_unit_squareclasses",
        "class_group_2_torsion",
        "complex_root_isolation",
        "local_squareclasses",
        "localization_matrix",
        "relative_norm",
        "quadratic_hilbert_pairing",
    }
    for result in results:
        assert result.outcome is PariOutcome.SUCCESS
        assert result.certificate is not None
        assert result.certificate.verifier == "arbogast.backends.pari.v1"
        assert result.receipt.backend_version == "2.17.4"
        assert result.proof_context().verify()


def test_grh_is_explicit_and_certification_timeout_is_nonclosing() -> None:
    conditional = _StubBackend().s_unit_squareclasses((0, 1), (2,), allow_grh=True)
    assert conditional.assumptions == ("GRH",)
    assert conditional.completeness is PariCompleteness.COMPLETE
    assert conditional.certificate is not None

    class TimedOut(_StubBackend):
        def _run_operation(self, *args: object, **kwargs: object) -> Any:
            raise PariTimeoutError("budget")

    unknown = TimedOut().class_group_2_torsion((0, 1))
    assert unknown.outcome is PariOutcome.BUDGET_EXHAUSTED
    assert unknown.completeness is PariCompleteness.CANDIDATE
    assert unknown.assumptions == ()
    assert unknown.certificate is not None
    assert unknown.certificate.verifier == "arbogast.backends.pari.operational.v1"
    assert unknown.verify().valid

    assert conditional.claim().status is EpistemicStatus.CONDITIONAL
    assert unknown.claim().status is EpistemicStatus.UNKNOWN
    assert unknown.claim().verify().verified
    unconditional = _StubBackend().field_invariants((0, 1))
    claim = unconditional.claim()
    assert claim.status is EpistemicStatus.CERTIFIED
    assert claim.evidence[0].ref == unconditional.certificate.certificate_id
    assert unconditional.certificate.claim_id == claim.id
    assert unconditional.certificate.statement_hash == claim.statement.statement_hash
    assert unconditional.certificate.claim_boundary_hash == claim.boundary_hash
    assert unconditional.claim_graph().ids() == (claim.id,)


def test_public_kummer_preserves_budget_exhaustion_as_unknown() -> None:
    class TimedOut(_StubBackend):
        def _run_operation(self, *args: object, **kwargs: object) -> Any:
            raise PariTimeoutError("budget")

    field = NumberField((5, 0, 1), generator_name="u")
    infinity = InfinitePlace(field, "complex", (-1, 1, 2, 3))
    result = kummer_space(field, (infinity,), backend=TimedOut())

    assert isinstance(result, PariArithmeticResult)
    assert result.outcome is PariOutcome.BUDGET_EXHAUSTED
    assert result.claim().status is EpistemicStatus.UNKNOWN
    assert result.verify().valid


def test_s_class_two_torsion_lift_extends_complete_kummer_basis() -> None:
    class EvenSClass(_StubBackend):
        def _execute(
            self,
            executable: str,
            request: dict[str, object],
            body: str,
            *,
            timeout_seconds: float,
        ) -> dict[str, Any]:
            result = super()._execute(
                executable,
                request,
                body,
                timeout_seconds=timeout_seconds,
            )
            if request["operation"] == "s_unit_squareclasses":
                result = {
                    **result,
                    "complete": True,
                    "representatives": [*result["representatives"], [[3, 1]]],
                    "s_class_2_torsion": [
                        {
                            "cyclic_order": 2,
                            "ideal_hnf": [[2]],
                            "principalization_generator": [[3, 1]],
                            "s_prime_exponents": [0],
                        }
                    ],
                    "s_class_group_cyclic_orders": [2],
                }
            return result

    complete = EvenSClass().s_unit_squareclasses((0, 1), (2,))
    assert complete.outcome is PariOutcome.SUCCESS
    assert complete.completeness is PariCompleteness.COMPLETE
    assert complete.payload.to_dict()["representatives"][-1] == [[3, 1]]
    assert complete.payload.to_dict()["s_class_2_torsion"][0]["s_prime_exponents"] == [0]


def test_complex_isolation_replays_exact_rouche_margins() -> None:
    result = _StubBackend().complex_root_isolation((1, 0, 1), 0)
    assert result.payload.to_dict()["root_count"] == 1
    assert result.payload.to_dict()["isolation"] == [
        [-1, 4],
        [1, 4],
        [3, 4],
        [5, 4],
    ]
    assert result.completeness is PariCompleteness.COMPLETE

    class WrongMargin(_StubBackend):
        def _execute(
            self,
            executable: str,
            request: dict[str, object],
            body: str,
            *,
            timeout_seconds: float,
        ) -> dict[str, Any]:
            response = super()._execute(
                executable,
                request,
                body,
                timeout_seconds=timeout_seconds,
            )
            if request["operation"] == "complex_root_isolation":
                witness = dict(response["rouche_witness"])
                witness["inner_margin"] = [1, 2]
                response = {**response, "rouche_witness": witness}
            return response

    with pytest.raises(PariProtocolError, match="margins"):
        WrongMargin().complex_root_isolation((1, 0, 1), 0)


def test_pari_certificate_tampering_fails_before_external_promotion() -> None:
    certificate = _StubBackend().relative_norm((0, 1), (3,)).certificate
    assert certificate is not None
    witness = certificate.witness.to_dict()
    expected = dict(witness["expected_payload"])
    expected["norm"] = [10, 1]
    witness["expected_payload"] = expected
    forged = VerificationCertificate.create(
        certificate.subject,
        certificate.verifier,
        witness=witness,
        checks=certificate.checks,
        guarantees=certificate.guarantees,
    )
    with pytest.raises(CertificateVerificationError, match="payload ID"):
        verify_certificate(forged)


def _forged_bound_certificate(
    certificate: VerificationCertificate,
    *,
    replay: dict[str, object],
    expected: dict[str, object],
    request: dict[str, object],
) -> VerificationCertificate:
    witness = certificate.witness.to_dict()
    request_id = content_address(request)
    return create_pari_verification_certificate(
        str(witness["operation"]),
        replay=replay,
        expected_payload=expected,
        backend_version=str(witness["backend_version"]),
        request_id=request_id,
        deterministic_seed=_request_seed(request_id),
        proof_mode=str(witness["proof_mode"]),
        limits=dict(witness["limits"]),
        completeness=str(witness["completeness"]),
    )


def test_canonical_field_element_and_place_id_tampering_fails_before_gp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _StubBackend()
    field = NumberField.rationals()
    element = field.element((3,))
    place = FinitePlace(field, 2, ((2,),), 1, 1)
    fake_field_id = "sha256:" + "a" * 64
    fake_element_id = "sha256:" + "b" * 64
    fake_place_id = "sha256:" + "c" * 64

    field_certificate = backend.field_invariants(field).certificate
    assert field_certificate is not None
    field_witness = field_certificate.witness.to_dict()
    field_replay = dict(field_witness["replay"])
    field_spec = dict(field_replay["field"])
    field_spec["field_id"] = fake_field_id
    field_replay["field"] = field_spec
    field_expected = dict(field_witness["expected_payload"])
    field_expected["field_id"] = fake_field_id
    forged_field = _forged_bound_certificate(
        field_certificate,
        replay=field_replay,
        expected=field_expected,
        request={
            "field": fake_field_id,
            "inputs": {},
            "operation": "field_invariants",
            "parameters": {},
            "protocol": RESPONSE_SCHEMA,
            "template": PARI_TEMPLATE_VERSION,
        },
    )

    element_certificate = backend.relative_norm(field, element).certificate
    assert element_certificate is not None
    element_witness = element_certificate.witness.to_dict()
    element_replay = dict(element_witness["replay"])
    element_arguments = dict(element_replay["arguments"])
    element_spec = dict(element_arguments["element"])
    element_spec["element_id"] = fake_element_id
    element_arguments["element"] = element_spec
    element_replay["arguments"] = element_arguments
    element_expected = dict(element_witness["expected_payload"])
    element_expected["element_id"] = fake_element_id
    forged_element = _forged_bound_certificate(
        element_certificate,
        replay=element_replay,
        expected=element_expected,
        request={
            "field": field.field_id,
            "inputs": {"element": fake_element_id},
            "operation": "relative_norm",
            "parameters": {"base_field": "Q"},
            "protocol": RESPONSE_SCHEMA,
            "template": PARI_TEMPLATE_VERSION,
        },
    )

    place_certificate = backend.local_squareclasses(field, place).certificate
    assert place_certificate is not None
    place_witness = place_certificate.witness.to_dict()
    place_replay = dict(place_witness["replay"])
    place_arguments = dict(place_replay["arguments"])
    place_spec = dict(place_arguments["place"])
    place_spec["place_id"] = fake_place_id
    place_arguments["place"] = place_spec
    place_replay["arguments"] = place_arguments
    place_expected = dict(place_witness["expected_payload"])
    place_expected["place_id"] = fake_place_id
    forged_place = _forged_bound_certificate(
        place_certificate,
        replay=place_replay,
        expected=place_expected,
        request={
            "field": field.field_id,
            "inputs": {"place": fake_place_id},
            "operation": "local_squareclasses",
            "parameters": {"max_candidates": 4096, "search_bound": 4},
            "protocol": RESPONSE_SCHEMA,
            "template": PARI_TEMPLATE_VERSION,
        },
    )

    def no_probe(_self: PariBackend) -> object:
        raise AssertionError("identity preflight must fail before GP probe")

    monkeypatch.setattr(PariBackend, "probe", no_probe)
    for forged, pattern in (
        (forged_field, "field identity"),
        (forged_element, "element identity"),
        (forged_place, "finite-place identity"),
    ):
        with pytest.raises(CertificateVerificationError, match=pattern):
            verify_certificate(forged)


def test_pari_certificate_exactly_binds_central_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _StubBackend().field_invariants((0, 1)).certificate
    assert certificate is not None

    def rebuild(**changes: object) -> VerificationCertificate:
        values: dict[str, object] = {
            "subject": certificate.subject,
            "verifier": certificate.verifier,
            "claim_id": certificate.claim_id,
            "statement_hash": certificate.statement_hash,
            "claim_boundary_hash": certificate.claim_boundary_hash,
            "claim_dependencies": certificate.claim_dependencies,
            "witness": certificate.witness,
            "checks": certificate.checks,
            "dependencies": certificate.dependencies,
            "guarantees": certificate.guarantees,
        }
        values.update(changes)
        return VerificationCertificate.create(**values)  # type: ignore[arg-type]

    stronger = rebuild(guarantees=(*certificate.guarantees, "the field is globally unique"))
    fake_dependency = CertificateRef(
        certificate.certificate_id,
        CertificateLayer.VERIFICATION,
        VerificationCertificate.schema_version,
    )
    dependent = rebuild(dependencies=(fake_dependency,))
    rebound = rebuild(claim_id=f"{certificate.claim_id}.forged")

    def no_probe(_self: PariBackend) -> object:
        raise AssertionError("envelope validation must fail before GP probe")

    monkeypatch.setattr(PariBackend, "probe", no_probe)
    for forged, pattern in (
        (stronger, "guarantees"),
        (dependent, "dependencies"),
        (rebound, "claim envelope"),
    ):
        with pytest.raises(CertificateVerificationError, match=pattern):
            verify_certificate(forged)


def test_operational_certificate_and_public_result_decoder_reject_tampering() -> None:
    class TimedOut(_StubBackend):
        def _run_operation(self, *args: object, **kwargs: object) -> Any:
            raise PariTimeoutError("budget")

    result = TimedOut().class_group_2_torsion((0, 1))
    decoded = decode_pari_arithmetic_result(result.to_dict())
    assert decoded.to_dict() == result.to_dict()
    assert decoded.verify().valid

    parameters = result.receipt.parameters.to_dict()
    parameters["completeness"] = PariCompleteness.COMPLETE.value
    forged_receipt = DiscoveryReceipt.create(
        result.receipt.operation,
        inputs=result.receipt.inputs,
        parameters=parameters,
        result=result.receipt.result,
        backend=result.receipt.backend,
        backend_version=result.receipt.backend_version,
        notes=result.receipt.notes,
    )
    forged = create_pari_operational_certificate(
        result.operation,
        payload=result.payload,
        receipt=forged_receipt,
        outcome=result.outcome,
    )
    with pytest.raises(CertificateVerificationError, match="parameters"):
        verify_certificate(forged)


def test_operational_certificate_replays_via_lazy_registry_in_fresh_python(
    tmp_path: Path,
) -> None:
    class TimedOut(_StubBackend):
        def _run_operation(self, *args: object, **kwargs: object) -> Any:
            raise PariTimeoutError("budget")

    certificate = TimedOut().class_group_2_torsion((0, 1)).certificate
    assert certificate is not None
    code = """
import json
import sys
from arbogast.cert import VerificationCertificate, verify_certificate
certificate = VerificationCertificate.from_dict(json.load(sys.stdin))
report = verify_certificate(certificate)
print(report.verifier)
"""
    environment = {**os.environ, "PYTHONPATH": ""}
    completed = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(certificate.to_dict()),
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "arbogast.backends.pari.operational.v1"


def test_closed_inputs_reject_source_injection_and_inexact_or_foreign_values() -> None:
    backend = _StubBackend()
    with pytest.raises(ValueError, match="integers, Fractions"):
        backend.field_invariants(("x;system", 1))
    with pytest.raises(ValueError, match="Fractions"):
        backend.field_invariants((0.5, 1))
    with pytest.raises(ValueError, match="positive prime"):
        backend.prime_decomposition((0, 1), 4)
    with pytest.raises(ValueError, match="nonzero"):
        backend.quadratic_hilbert_pairing((0, 1), (0,), (1,), 2)
    assert os.environ.get("HOME") is not None
