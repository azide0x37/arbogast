"""Portable, fail-closed receipts for the bounded p-adic proof layer."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import ClassVar, Literal, TypeAlias, cast

from arbogast.cert import (
    CertificateLayer,
    ContentAddressedCertificate,
    FrozenMap,
    VerificationCertificate,
    content_address,
    freeze_mapping,
    verify_certificate,
)
from arbogast.claims import Claim, ClaimGraph
from arbogast.galois.proof import (
    Completeness,
    ProofContext,
    VerificationRequirement,
    VerifierTrust,
)

from ._schema import (
    MAX_ASSUMPTIONS,
    MAX_RECEIPT_DEPENDENCIES,
    PAdicSchemaObject,
    canonical_label,
    ensure_canonical_envelope,
    strict_canonical_equal,
    strict_canonical_mapping,
)
from .errors import PAdicCertificateError, PAdicResourceError, PAdicVerificationError

FINITE_EXACT_VERIFIER = "padic.finite-exact.v1"
THREE_POINT_EXACT_VERIFIER = "padic.three-point-exact.v1"
PORTABLE_TRUST = "portable-python"

FINITE_EXACT_KINDS = frozenset(
    {
        "field",
        "precision-ring",
        "local-field-embedding",
        "automorphism",
        "module",
        "submodule",
        "frobenius",
        "slope-decomposition",
        "ordinary-part",
        "inertia-representation",
        "local-factorization-fragment",
        "finite-partial",
        "finite-unknown",
        "finite-unsupported",
    }
)
THREE_POINT_EXACT_KINDS = frozenset(
    {
        "good-reduction",
        "semistable-reduction",
        "stable-reduction",
        "deformation-datum",
        "lift-set",
        "lift-action",
        "fixed-lift-set",
        "descended-model",
        "three-point-partial",
        "three-point-unknown",
        "three-point-unsupported",
    }
)
RECEIPT_KINDS = FINITE_EXACT_KINDS | THREE_POINT_EXACT_KINDS

KIND_VERIFIERS: dict[str, str] = {
    **{kind: FINITE_EXACT_VERIFIER for kind in FINITE_EXACT_KINDS},
    **{kind: THREE_POINT_EXACT_VERIFIER for kind in THREE_POINT_EXACT_KINDS},
}
RECEIPT_SCHEMAS: dict[str, str] = {
    kind: f"arbogast.padic.{kind}-receipt/v1" for kind in RECEIPT_KINDS
}

ReceiptClosure: TypeAlias = Literal["certified", "partial", "unknown", "unsupported"]

_CLOSURE_KINDS: dict[ReceiptClosure, frozenset[str]] = {
    "certified": frozenset(
        kind
        for kind in RECEIPT_KINDS
        if not kind.endswith(("-partial", "-unknown", "-unsupported"))
    ),
    "partial": frozenset({"finite-partial", "three-point-partial"}),
    "unknown": frozenset({"finite-unknown", "three-point-unknown"}),
    "unsupported": frozenset({"finite-unsupported", "three-point-unsupported"}),
}

_KIND_MODULES: dict[str, str] = {
    "field": "arbogast.padic.fields",
    "precision-ring": "arbogast.padic.fields",
    "local-field-embedding": "arbogast.padic.fields",
    "automorphism": "arbogast.padic.fields",
    "module": "arbogast.padic.modules",
    "submodule": "arbogast.padic.modules",
    "frobenius": "arbogast.padic.frobenius",
    "slope-decomposition": "arbogast.padic.frobenius",
    "ordinary-part": "arbogast.padic.frobenius",
    "inertia-representation": "arbogast.padic.inertia",
    "local-factorization-fragment": "arbogast.padic.covers",
    "good-reduction": "arbogast.padic.reduction",
    "semistable-reduction": "arbogast.padic.reduction",
    "stable-reduction": "arbogast.padic.reduction",
    "deformation-datum": "arbogast.padic.wewers",
    "lift-set": "arbogast.padic.lifts",
    "lift-action": "arbogast.padic.lifts",
    "fixed-lift-set": "arbogast.padic.lifts",
    "descended-model": "arbogast.padic.descent",
}


@dataclass(frozen=True, slots=True)
class PAdicPayloadReplay:
    """Exact checks and the complete evidence set consumed by payload replay."""

    checks: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.checks or any(
            not isinstance(item, str) or not item.strip() for item in self.checks
        ):
            raise PAdicCertificateError("payload replay checks must be nonempty strings")
        if len(set(self.checks)) != len(self.checks):
            raise PAdicCertificateError("payload replay checks must be unique")
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise PAdicCertificateError("consumed evidence IDs must be sorted and unique")


PayloadVerifier: TypeAlias = Callable[
    [Mapping[str, object], tuple[VerificationCertificate, ...]],
    PAdicPayloadReplay,
]
_PAYLOAD_VERIFIERS: dict[str, PayloadVerifier] = {}


def padic_payload_verifier(kind: str) -> Callable[[PayloadVerifier], PayloadVerifier]:
    """Register one fixed-kind portable payload replay function."""

    if kind not in RECEIPT_KINDS or kind.endswith(("-partial", "-unknown", "-unsupported")):
        raise PAdicCertificateError(f"cannot register unsupported p-adic receipt kind {kind!r}")

    def decorator(callback: PayloadVerifier) -> PayloadVerifier:
        incumbent = _PAYLOAD_VERIFIERS.get(kind)
        if incumbent is not None and incumbent is not callback:
            raise PAdicCertificateError(f"p-adic payload verifier already registered for {kind}")
        _PAYLOAD_VERIFIERS[kind] = callback
        return callback

    return decorator


def replay_schema_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
    *,
    decoder: Callable[[Mapping[str, object]], PAdicSchemaObject],
    checks: Sequence[str],
    evidence_ids: Sequence[str] = (),
) -> PAdicPayloadReplay:
    """Strictly decode the standard ``{"result": schema-document}`` payload."""

    raw = _raw_object(payload, "certified p-adic payload")
    _exact_keys(raw, {"result"}, "certified p-adic payload")
    raw_result = _raw_object(raw["result"], "certified p-adic result")
    result = decoder(raw_result)
    if not isinstance(result, PAdicSchemaObject) or result.verify() is not True:
        raise PAdicVerificationError("certified p-adic result replay returned false")
    if not strict_canonical_equal(raw_result, result.to_schema_document()):
        raise PAdicVerificationError("certified p-adic result is not strict canonical transport")
    available = {item.certificate_id for item in evidence}
    consumed = tuple(sorted(evidence_ids))
    if not set(consumed).issubset(available):
        raise PAdicVerificationError("payload replay names unavailable evidence")
    return PAdicPayloadReplay(tuple(checks), consumed)


def _raw_object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicCertificateError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _raw_array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicCertificateError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise PAdicCertificateError(
            f"{name} fields mismatch; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def verifier_for_kind(kind: str) -> str:
    try:
        return KIND_VERIFIERS[kind]
    except KeyError as exc:
        raise PAdicCertificateError(f"unsupported p-adic receipt kind: {kind!r}") from exc


def nonconclusion_kind(family: str, closure: ReceiptClosure) -> str:
    if family == "finite":
        prefix = "finite"
    elif family == "three-point":
        prefix = "three-point"
    else:
        raise PAdicCertificateError("p-adic family must be finite or three-point")
    if closure not in {"partial", "unknown", "unsupported"}:
        raise PAdicCertificateError("nonconclusion kind requires a non-success closure")
    return f"{prefix}-{closure}"


def _proof_context(
    kind: str,
    *,
    completeness: Completeness,
    assumptions: Iterable[str],
    verification_requirements: Iterable[VerificationRequirement],
) -> ProofContext:
    family_requirement = VerificationRequirement.portable_python(verifier_for_kind(kind))
    requirements = tuple(verification_requirements)
    if family_requirement not in requirements:
        requirements = (*requirements, family_requirement)
    return ProofContext(assumptions, requirements, completeness)


def complete_proof_context(
    kind: str,
    *,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
) -> ProofContext:
    return _proof_context(
        kind,
        completeness=Completeness.COMPLETE,
        assumptions=assumptions,
        verification_requirements=verification_requirements,
    )


def candidate_proof_context(
    kind: str,
    *,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
) -> ProofContext:
    return _proof_context(
        kind,
        completeness=Completeness.CANDIDATE,
        assumptions=assumptions,
        verification_requirements=verification_requirements,
    )


def _require_family_context(kind: str, context: ProofContext) -> None:
    family_requirement = VerificationRequirement.portable_python(verifier_for_kind(kind))
    if family_requirement not in context.verification_requirements:
        raise PAdicCertificateError(
            "p-adic proof context omits its portable receipt verifier requirement"
        )


def _reject_backend_leaks(value: object) -> None:
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        dangerous = (
            "backend",
            "handle",
            "session",
            "transcript",
            "raw_output",
            "printed_padic",
            "pari_stack",
        )
        for key in mapping:
            normalized = key.casefold().replace("-", "_")
            if any(token in normalized for token in dangerous):
                raise PAdicVerificationError(
                    f"backend-local field crossed the p-adic proof boundary: {key!r}"
                )
        for item in mapping.values():
            _reject_backend_leaks(item)
    elif type(value) is list:
        for item in cast(list[object], value):
            _reject_backend_leaks(item)


def _requirement_from_dict(value: object, name: str) -> VerificationRequirement:
    raw = _raw_object(value, name)
    _exact_keys(raw, {"capabilities", "trust", "type", "verifier", "version"}, name)
    if raw["type"] != "arbogast.verification_requirement":
        raise PAdicCertificateError(f"{name} has the wrong type tag")
    capabilities = _raw_array(raw["capabilities"], f"{name}.capabilities")
    if any(type(item) is not str for item in capabilities):
        raise PAdicCertificateError(f"{name}.capabilities must contain strings")
    verifier = raw["verifier"]
    trust = raw["trust"]
    version = raw["version"]
    if type(verifier) is not str or type(trust) is not str:
        raise PAdicCertificateError(f"{name} verifier and trust must be strings")
    if version is not None and type(version) is not str:
        raise PAdicCertificateError(f"{name}.version must be a string or null")
    result = VerificationRequirement(
        verifier,
        trust,
        version=version,
        capabilities=cast(list[str], capabilities),
    )
    if not strict_canonical_equal(raw, result.to_dict()):
        raise PAdicCertificateError(f"{name} is not strict canonical transport")
    return result


def _proof_context_from_dict(value: object) -> ProofContext:
    raw = _raw_object(value, "p-adic proof context")
    _exact_keys(
        raw,
        {"assumptions", "completeness", "type", "verification_requirements"},
        "p-adic proof context",
    )
    if raw["type"] != "arbogast.proof_context":
        raise PAdicCertificateError("p-adic proof context has the wrong type tag")
    assumptions = _raw_array(raw["assumptions"], "p-adic assumptions")
    requirements = _raw_array(
        raw["verification_requirements"],
        "p-adic verification requirements",
    )
    if len(assumptions) > MAX_ASSUMPTIONS:
        raise PAdicCertificateError("p-adic proof context has too many assumptions")
    if any(type(item) is not str for item in assumptions):
        raise PAdicCertificateError("p-adic assumptions must contain strings")
    completeness = raw["completeness"]
    if type(completeness) is not str:
        raise PAdicCertificateError("p-adic completeness must be a string")
    context = ProofContext(
        cast(list[str], assumptions),
        tuple(
            _requirement_from_dict(item, f"verification requirement[{index}]")
            for index, item in enumerate(requirements)
        ),
        completeness,
    )
    if not strict_canonical_equal(raw, context.to_dict()):
        raise PAdicCertificateError("p-adic proof context is not strict canonical transport")
    return context


@dataclass(frozen=True)
class PAdicReceipt(ContentAddressedCertificate):
    """One canonical p-adic result receipt with explicit proof axes."""

    kind: str
    closure: ReceiptClosure
    payload: FrozenMap
    proof_context: ProofContext
    evidence: tuple[VerificationCertificate, ...] = ()

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION

    def __post_init__(self) -> None:
        if self.kind not in RECEIPT_KINDS:
            raise PAdicCertificateError(f"unsupported p-adic receipt kind: {self.kind!r}")
        if self.closure not in _CLOSURE_KINDS or self.kind not in _CLOSURE_KINDS[self.closure]:
            raise PAdicCertificateError("p-adic receipt kind and closure are inconsistent")
        raw_payload = (
            self.payload.to_dict() if isinstance(self.payload, FrozenMap) else self.payload
        )
        if not isinstance(raw_payload, Mapping):
            raise PAdicCertificateError("p-adic receipt payload must be a mapping")
        normalized_payload = strict_canonical_mapping(
            cast(Mapping[str, object], raw_payload),
            "p-adic receipt payload",
        )
        _reject_backend_leaks(normalized_payload)
        object.__setattr__(self, "payload", freeze_mapping(normalized_payload))
        if not isinstance(self.proof_context, ProofContext) or not self.proof_context.verify():
            raise PAdicCertificateError("p-adic receipt requires a valid ProofContext")
        _require_family_context(self.kind, self.proof_context)
        expected_completeness = (
            Completeness.COMPLETE if self.closure == "certified" else Completeness.CANDIDATE
        )
        if self.proof_context.completeness is not expected_completeness:
            raise PAdicCertificateError(
                f"{self.closure} p-adic receipt has incompatible completeness"
            )
        evidence = tuple(self.evidence)
        if len(evidence) > MAX_RECEIPT_DEPENDENCIES:
            raise PAdicCertificateError("p-adic receipt has too many evidence certificates")
        if any(not isinstance(item, VerificationCertificate) for item in evidence):
            raise PAdicCertificateError(
                "p-adic receipt evidence must contain VerificationCertificate values"
            )
        evidence_ids = tuple(item.certificate_id for item in evidence)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise PAdicCertificateError("p-adic receipt evidence must be ID-sorted and unique")
        object.__setattr__(self, "evidence", evidence)
        ensure_canonical_envelope(self.to_dict(), "p-adic receipt")

    @property
    def schema_version(self) -> str:
        return RECEIPT_SCHEMAS[self.kind]

    @property
    def verifier(self) -> str:
        return verifier_for_kind(self.kind)

    @property
    def object_id(self) -> str:
        return content_address(self.payload)

    def to_canonical(self) -> dict[str, object]:
        return {
            "closure": self.closure,
            "evidence": [item.to_dict() for item in self.evidence],
            "kind": self.kind,
            "layer": self.layer.value,
            "payload": self.payload.to_dict(),
            "proof_context": self.proof_context.to_dict(),
            "schema_version": self.schema_version,
            "verifier": self.verifier,
        }

    @classmethod
    def create(
        cls,
        kind: str,
        closure: ReceiptClosure,
        payload: Mapping[str, object],
        *,
        proof_context: ProofContext,
        evidence: Sequence[VerificationCertificate] = (),
    ) -> PAdicReceipt:
        normalized = strict_canonical_mapping(payload, "p-adic receipt payload")
        typed_evidence = tuple(evidence)
        if any(not isinstance(item, VerificationCertificate) for item in typed_evidence):
            raise PAdicCertificateError(
                "p-adic receipt evidence must contain VerificationCertificate values"
            )
        return cls(
            kind=kind,
            closure=closure,
            payload=freeze_mapping(normalized),
            proof_context=proof_context,
            evidence=tuple(sorted(typed_evidence, key=lambda item: item.certificate_id)),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PAdicReceipt:
        raw = _raw_object(value, "p-adic receipt")
        allowed = {
            "certificate_id",
            "closure",
            "evidence",
            "kind",
            "layer",
            "payload",
            "proof_context",
            "schema_version",
            "verifier",
        }
        if set(raw) != allowed:
            raise PAdicCertificateError("p-adic receipt fields do not match the v1 schema")
        kind = raw["kind"]
        closure = raw["closure"]
        if type(kind) is not str or kind not in RECEIPT_KINDS:
            raise PAdicCertificateError("unsupported p-adic receipt kind")
        if type(closure) is not str or closure not in _CLOSURE_KINDS:
            raise PAdicCertificateError("unsupported p-adic receipt closure")
        typed_kind = kind
        if raw["schema_version"] != RECEIPT_SCHEMAS[typed_kind]:
            raise PAdicCertificateError("unsupported p-adic receipt schema")
        if raw["layer"] != CertificateLayer.VERIFICATION.value:
            raise PAdicCertificateError("p-adic receipt has the wrong evidence layer")
        if raw["verifier"] != verifier_for_kind(typed_kind):
            raise PAdicCertificateError("p-adic receipt verifier family was altered")
        payload = _raw_object(raw["payload"], "p-adic receipt payload")
        strict_canonical_mapping(payload, "p-adic receipt payload")
        raw_evidence = _raw_array(raw["evidence"], "p-adic receipt evidence")
        if len(raw_evidence) > MAX_RECEIPT_DEPENDENCIES:
            raise PAdicCertificateError("p-adic receipt has too many evidence certificates")
        evidence = tuple(
            VerificationCertificate.from_dict(_raw_object(item, f"p-adic evidence[{index}]"))
            for index, item in enumerate(raw_evidence)
        )
        receipt = cls(
            kind=typed_kind,
            closure=closure,
            payload=freeze_mapping(payload),
            proof_context=_proof_context_from_dict(raw["proof_context"]),
            evidence=evidence,
        )
        expected_id = raw["certificate_id"]
        if type(expected_id) is not str:
            raise PAdicCertificateError("p-adic receipt certificate_id must be a string")
        receipt.verify_integrity(expected_id)
        if not strict_canonical_equal(raw, receipt.to_dict()):
            raise PAdicCertificateError("p-adic receipt is not strict canonical transport")
        return receipt

    def verify(self) -> tuple[str, ...]:
        return verify_padic_receipt(self)

    @property
    def certificate(self) -> VerificationCertificate:
        semantic = import_module("arbogast.padic.semantic")
        return cast(
            VerificationCertificate,
            semantic.verification_certificate_for_receipt(self),
        )

    def claim(self) -> Claim:
        semantic = import_module("arbogast.padic.semantic")
        return cast(Claim, semantic.claim_for_receipt(self))

    def claim_graph(self) -> ClaimGraph:
        semantic = import_module("arbogast.padic.semantic")
        return cast(ClaimGraph, semantic.claim_graph_for_receipt(self))


def _requirement_evidence_ids(receipt: PAdicReceipt) -> tuple[str, ...]:
    family = VerificationRequirement.portable_python(receipt.verifier)
    requirements = tuple(
        requirement
        for requirement in receipt.proof_context.verification_requirements
        if requirement != family
    )
    if not requirements:
        return ()
    reports = tuple((item, verify_certificate(item)) for item in receipt.evidence)
    used: set[str] = set()
    for requirement in requirements:
        matched = False
        for certificate, report in reports:
            if report.verifier != requirement.verifier:
                continue
            details = report.details.to_dict()
            if (
                requirement.trust is VerifierTrust.PINNED_EXTERNAL
                and details.get("version") != requirement.version
            ):
                continue
            raw_capabilities = details.get("capabilities", [])
            if type(raw_capabilities) is not list or any(
                type(item) is not str for item in cast(list[object], raw_capabilities)
            ):
                continue
            if not set(requirement.capabilities).issubset(cast(set[str], set(raw_capabilities))):
                continue
            used.add(certificate.certificate_id)
            matched = True
            break
        if not matched:
            raise PAdicVerificationError(
                f"unsatisfied typed verification requirement: {requirement.verifier}"
            )
    return tuple(sorted(used))


def _partial_replay(receipt: PAdicReceipt) -> PAdicPayloadReplay:
    from .results import ProofObligation

    payload = receipt.payload.to_dict()
    _exact_keys(payload, {"fragments", "obligations", "operation", "reason"}, "partial payload")
    canonical_label(payload["operation"], "partial operation")
    canonical_label(payload["reason"], "partial reason")
    fragments = _raw_array(payload["fragments"], "partial fragments")
    obligations = _raw_array(payload["obligations"], "partial obligations")
    if not fragments or not obligations:
        raise PAdicVerificationError("partial receipt requires fragments and obligations")
    evidence_by_id = {item.certificate_id: item for item in receipt.evidence}
    fragment_ids: list[str] = []
    for index, item in enumerate(fragments):
        fragment = _raw_object(item, f"partial fragment[{index}]")
        _exact_keys(
            fragment,
            {"certificate_id", "claim_id", "result_id", "result_schema"},
            f"partial fragment[{index}]",
        )
        for field in ("certificate_id", "claim_id", "result_id", "result_schema"):
            canonical_label(fragment[field], f"partial fragment[{index}].{field}")
        certificate_id = cast(str, fragment["certificate_id"])
        dependency = evidence_by_id.get(certificate_id)
        if dependency is None:
            raise PAdicVerificationError("partial fragment certificate evidence is missing")
        if dependency.claim_id != fragment["claim_id"]:
            raise PAdicVerificationError("partial fragment claim binding was altered")
        witness = dependency.witness.to_dict()
        if set(witness) != {"padic_receipt"} or type(witness["padic_receipt"]) is not dict:
            raise PAdicVerificationError("partial fragment is not a p-adic result certificate")
        nested = PAdicReceipt.from_dict(cast(dict[str, object], witness["padic_receipt"]))
        if nested.closure != "certified":
            raise PAdicVerificationError("partial fragment is not independently certified")
        nested_payload = nested.payload.to_dict()
        if set(nested_payload) != {"result"} or type(nested_payload["result"]) is not dict:
            raise PAdicVerificationError("partial fragment result payload is malformed")
        result_document = cast(dict[str, object], nested_payload["result"])
        result_schema = result_document.get("schema")
        if result_schema != fragment["result_schema"]:
            raise PAdicVerificationError("partial fragment result schema was altered")
        result_payload = dict(result_document)
        del result_payload["schema"]
        if content_address(result_payload) != fragment["result_id"]:
            raise PAdicVerificationError("partial fragment result identity was altered")
        fragment_ids.append(certificate_id)
    if tuple(fragment_ids) != tuple(sorted(set(fragment_ids))):
        raise PAdicVerificationError("partial fragments are not unique and ID-sorted")
    obligation_ids: list[str] = []
    for index, item in enumerate(obligations):
        obligation = ProofObligation.from_dict(_raw_object(item, f"partial obligation[{index}]"))
        obligation_ids.append(obligation.obligation_id)
    if tuple(obligation_ids) != tuple(sorted(set(obligation_ids))):
        raise PAdicVerificationError("partial obligations are not unique and ID-sorted")
    return PAdicPayloadReplay(
        checks=(
            "independent-certified-fragments",
            "canonical-open-proof-obligations",
            "no-complete-result-promotion",
        ),
        evidence_ids=tuple(fragment_ids),
    )


def _unknown_replay(receipt: PAdicReceipt) -> PAdicPayloadReplay:
    payload = receipt.payload.to_dict()
    _exact_keys(
        payload,
        {"operation", "reason", "reason_code", "requested"},
        "unknown payload",
    )
    for field in ("operation", "reason", "reason_code"):
        canonical_label(payload[field], f"unknown {field}")
    if type(payload["requested"]) is not dict:
        raise PAdicVerificationError("unknown requested boundary must be an object")
    return PAdicPayloadReplay(
        checks=("canonical-unknown-boundary", "no-mathematical-conclusion"),
    )


def _unsupported_replay(receipt: PAdicReceipt) -> PAdicPayloadReplay:
    payload = receipt.payload.to_dict()
    _exact_keys(
        payload,
        {"operation", "reason", "reason_code", "requested", "supported"},
        "unsupported payload",
    )
    for field in ("operation", "reason", "reason_code"):
        canonical_label(payload[field], f"unsupported {field}")
    if type(payload["requested"]) is not dict:
        raise PAdicVerificationError("unsupported requested boundary must be an object")
    supported = _raw_array(payload["supported"], "supported capabilities")
    if any(type(item) is not str for item in supported):
        raise PAdicVerificationError("supported capabilities must contain strings")
    if tuple(supported) != tuple(sorted(set(cast(list[str], supported)))):
        raise PAdicVerificationError("supported capabilities must be sorted and unique")
    return PAdicPayloadReplay(
        checks=("canonical-software-boundary", "no-mathematical-conclusion"),
    )


def _payload_replay(receipt: PAdicReceipt) -> PAdicPayloadReplay:
    try:
        if receipt.closure == "partial":
            return _partial_replay(receipt)
        if receipt.closure == "unknown":
            return _unknown_replay(receipt)
        if receipt.closure == "unsupported":
            return _unsupported_replay(receipt)
        module_name = _KIND_MODULES.get(receipt.kind)
        if module_name is None:
            raise PAdicVerificationError(f"no fixed payload module for {receipt.kind}")
        import_module(module_name)
        callback = _PAYLOAD_VERIFIERS.get(receipt.kind)
        if callback is None:
            raise PAdicVerificationError(
                f"{module_name} did not register the {receipt.kind} payload verifier"
            )
        replay = callback(receipt.payload.to_dict(), receipt.evidence)
        if not isinstance(replay, PAdicPayloadReplay):
            raise PAdicVerificationError("p-adic payload verifier returned the wrong result type")
        return replay
    except PAdicResourceError:
        raise
    except PAdicVerificationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PAdicVerificationError(
            f"{receipt.kind} payload replay rejected malformed canonical data"
        ) from exc


def verify_padic_receipt(receipt: PAdicReceipt) -> tuple[str, ...]:
    """Replay one p-adic receipt with complete, typed evidence reachability."""

    if not isinstance(receipt, PAdicReceipt):
        raise TypeError("receipt must be a PAdicReceipt")
    receipt.verify_integrity()
    ensure_canonical_envelope(receipt.to_dict(), "p-adic receipt transport")
    if not receipt.proof_context.verify():
        raise PAdicVerificationError("p-adic proof context replay returned false")
    for item in receipt.evidence:
        report = verify_certificate(item)
        if not report.valid:
            raise PAdicVerificationError("p-adic evidence verification returned invalid")
    requirement_ids = set(_requirement_evidence_ids(receipt))
    replay = _payload_replay(receipt)
    consumed = requirement_ids | set(replay.evidence_ids)
    available = {item.certificate_id for item in receipt.evidence}
    if consumed != available:
        missing = sorted(consumed - available)
        foreign = sorted(available - consumed)
        raise PAdicVerificationError(
            f"p-adic evidence closure mismatch; missing={missing}, foreign={foreign}"
        )
    return (
        "receipt-integrity",
        "strict-canonical-resource-envelope",
        "typed-proof-context",
        "dependency-closed-exact-evidence",
        *replay.checks,
    )


__all__ = [
    "FINITE_EXACT_KINDS",
    "FINITE_EXACT_VERIFIER",
    "KIND_VERIFIERS",
    "PORTABLE_TRUST",
    "RECEIPT_KINDS",
    "RECEIPT_SCHEMAS",
    "THREE_POINT_EXACT_KINDS",
    "THREE_POINT_EXACT_VERIFIER",
    "PAdicPayloadReplay",
    "PAdicReceipt",
    "ReceiptClosure",
    "candidate_proof_context",
    "complete_proof_context",
    "nonconclusion_kind",
    "padic_payload_verifier",
    "replay_schema_payload",
    "verifier_for_kind",
    "verify_padic_receipt",
]
