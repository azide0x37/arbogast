"""Campaign strategies and exact preflight-gate contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from arbogast.cert import Certificate, CertificateLayer, CertificateRef
from arbogast.fleet import BackendRequirement, TaskSpec
from arbogast.formats import FrozenMapping, JSONValue, normalize_json

from .derive import TaskProvenance
from .errors import CampaignInvariantError, CampaignSerializationError
from .targets import TargetSpec

if TYPE_CHECKING:
    from .ledger import TargetLedger
    from .planner import CampaignTask


class GateDisposition(StrEnum):
    PASS = "PASS"
    PROVED_IMPOSSIBLE = "PROVED_IMPOSSIBLE"
    DEFER = "DEFER"


def _certificate_ref(value: Certificate | CertificateRef | None) -> CertificateRef | None:
    if value is None:
        return None
    if isinstance(value, CertificateRef):
        return value
    if isinstance(value, Certificate):
        return CertificateRef.from_certificate(value)
    raise CampaignInvariantError("gate certificate must implement the certificate protocol")


@dataclass(frozen=True, slots=True, init=False)
class GateDecision:
    """An exact preflight decision; impossibility is proof-carrying only."""

    disposition: GateDisposition
    reason: str
    certificate: Certificate | None
    certificate_ref: CertificateRef | None
    details: FrozenMapping

    def __init__(
        self,
        disposition: GateDisposition | str,
        reason: str,
        *,
        certificate: Certificate | CertificateRef | None = None,
        certificate_ref: CertificateRef | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not reason.strip():
            raise CampaignInvariantError("gate-decision reason cannot be blank")
        if certificate is not None and certificate_ref is not None:
            raise CampaignInvariantError("provide certificate or certificate_ref, not both")
        resolved_disposition = GateDisposition(disposition)
        actual_certificate = (
            certificate
            if certificate is not None and not isinstance(certificate, CertificateRef)
            else None
        )
        resolved_certificate = _certificate_ref(
            certificate if certificate is not None else certificate_ref
        )
        if resolved_disposition is GateDisposition.PROVED_IMPOSSIBLE:
            if actual_certificate is None or resolved_certificate is None:
                raise CampaignInvariantError(
                    "an exact gate requires an actual replayable certificate, not a bare reference"
                )
            if resolved_certificate.layer is not CertificateLayer.VERIFICATION:
                raise CampaignInvariantError(
                    "an exact gate can prove impossibility only with verification evidence"
                )
        object.__setattr__(self, "disposition", resolved_disposition)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "certificate", actual_certificate)
        object.__setattr__(self, "certificate_ref", resolved_certificate)
        object.__setattr__(self, "details", FrozenMapping(details))

    @classmethod
    def passed(cls, reason: str = "exact preflight passed") -> GateDecision:
        return cls(GateDisposition.PASS, reason)

    @classmethod
    def deferred(cls, reason: str) -> GateDecision:
        return cls(GateDisposition.DEFER, reason)

    @classmethod
    def impossible(
        cls,
        reason: str,
        certificate: Certificate | CertificateRef,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> GateDecision:
        return cls(
            GateDisposition.PROVED_IMPOSSIBLE,
            reason,
            certificate=certificate,
            details=details,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "certificate_ref": (
                None
                if self.certificate_ref is None
                else normalize_json(self.certificate_ref.to_dict())
            ),
            "certificate_payload": (
                None if self.certificate is None else normalize_json(self.certificate.to_dict())
            ),
            "details": self.details.to_dict(),
            "disposition": self.disposition.value,
            "reason": self.reason,
        }


@runtime_checkable
class ExactGate(Protocol):
    """Trusted runtime implementation of a named exact preflight."""

    @property
    def name(self) -> str: ...

    def evaluate(self, target: TargetSpec, ledger: TargetLedger) -> GateDecision: ...


@dataclass(frozen=True, slots=True)
class FunctionalGate:
    """Convenience adapter for a trusted local preflight function."""

    name: str
    evaluator: Callable[[TargetSpec, TargetLedger], GateDecision] = field(
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise CampaignInvariantError("gate name cannot be blank")

    def evaluate(self, target: TargetSpec, ledger: TargetLedger) -> GateDecision:
        decision = self.evaluator(target, ledger)
        if not isinstance(decision, GateDecision):
            raise CampaignInvariantError("exact gate must return GateDecision")
        return decision


class TaskFactory(Protocol):
    """Trusted factory for strategy-specific fleet or campaign tasks."""

    def __call__(
        self,
        target: TargetSpec,
        provenance: TaskProvenance,
        checkpoint_ref: str | None,
    ) -> TaskSpec | CampaignTask: ...


@dataclass(frozen=True, slots=True, init=False)
class Strategy:
    """A named mathematical attack, separate from campaign motivation."""

    name: str
    operation: str
    rationale: str
    parameters: FrozenMapping
    backend: BackendRequirement
    capability_requirements: tuple[str, ...]
    gate_name: str | None
    gate: ExactGate | None
    task_factory_name: str | None
    task_factory: TaskFactory | None
    verify_results: bool
    usefulness: int
    information_gain: int
    estimated_cost: int

    def __init__(
        self,
        name: str,
        operation: str,
        rationale: str,
        *,
        parameters: Mapping[str, Any] | None = None,
        backend: BackendRequirement | str = "python",
        capability_requirements: tuple[str, ...] = (),
        gate: ExactGate | str | None = None,
        task_factory: TaskFactory | None = None,
        task_factory_name: str | None = None,
        verify_results: bool = False,
        usefulness: int = 1,
        information_gain: int = 1,
        estimated_cost: int = 1,
    ) -> None:
        if not name.strip() or not operation.strip() or not rationale.strip():
            raise CampaignInvariantError("strategy name, operation, and rationale cannot be blank")
        requirements = tuple(sorted(set(capability_requirements)))
        if any(not item.strip() for item in requirements):
            raise CampaignInvariantError("strategy capabilities cannot be blank")
        if not isinstance(verify_results, bool):
            raise CampaignInvariantError("verify_results must be boolean")
        for field_name, value in {
            "usefulness": usefulness,
            "information_gain": information_gain,
            "estimated_cost": estimated_cost,
        }.items():
            minimum = 1 if field_name == "estimated_cost" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise CampaignInvariantError(f"{field_name} must be an integer >= {minimum}")
        if isinstance(gate, str):
            gate_name = gate
            gate_object = None
        elif gate is None:
            gate_name = None
            gate_object = None
        elif isinstance(gate, ExactGate):
            gate_name = gate.name
            gate_object = gate
        else:
            raise CampaignInvariantError("gate must be a gate name or ExactGate")
        if gate_name is not None and not gate_name.strip():
            raise CampaignInvariantError("gate name cannot be blank")
        resolved_factory_name = task_factory_name
        if task_factory is not None and resolved_factory_name is None:
            module = getattr(task_factory, "__module__", type(task_factory).__module__)
            qualname = getattr(
                task_factory,
                "__qualname__",
                type(task_factory).__qualname__,
            )
            resolved_factory_name = f"{module}:{qualname}"
        if resolved_factory_name is not None and (
            not isinstance(resolved_factory_name, str) or not resolved_factory_name.strip()
        ):
            raise CampaignInvariantError("task_factory_name cannot be blank")
        backend_requirement = (
            BackendRequirement(name=backend, capabilities=requirements)
            if isinstance(backend, str)
            else backend
        )
        combined_requirements = tuple(
            sorted(set((*requirements, *backend_requirement.capabilities)))
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "parameters", FrozenMapping(parameters))
        object.__setattr__(self, "backend", backend_requirement)
        object.__setattr__(self, "capability_requirements", combined_requirements)
        object.__setattr__(self, "gate_name", gate_name)
        object.__setattr__(self, "gate", gate_object)
        object.__setattr__(self, "task_factory_name", resolved_factory_name)
        object.__setattr__(self, "task_factory", task_factory)
        object.__setattr__(self, "verify_results", verify_results)
        object.__setattr__(self, "usefulness", usefulness)
        object.__setattr__(self, "information_gain", information_gain)
        object.__setattr__(self, "estimated_cost", estimated_cost)

    def resolve_gate(self, registry: Mapping[str, ExactGate]) -> ExactGate | None:
        if self.gate is not None:
            return self.gate
        if self.gate_name is None:
            return None
        try:
            gate = registry[self.gate_name]
        except KeyError as error:
            raise CampaignInvariantError(
                f"strategy {self.name!r} requires uninjected gate {self.gate_name!r}"
            ) from error
        if gate.name != self.gate_name:
            raise CampaignInvariantError(
                f"gate registry key {self.gate_name!r} does not match gate name {gate.name!r}"
            )
        return gate

    def bind_task_factory(self, factory: TaskFactory) -> Strategy:
        if self.task_factory_name is None:
            raise CampaignInvariantError(f"strategy {self.name!r} does not declare a task factory")
        return Strategy(
            self.name,
            self.operation,
            self.rationale,
            parameters=self.parameters,
            backend=self.backend,
            capability_requirements=self.capability_requirements,
            gate=self.gate if self.gate is not None else self.gate_name,
            task_factory=factory,
            task_factory_name=self.task_factory_name,
            verify_results=self.verify_results,
            usefulness=self.usefulness,
            information_gain=self.information_gain,
            estimated_cost=self.estimated_cost,
        )

    def build_task(
        self,
        target: TargetSpec,
        *,
        provenance: TaskProvenance | None = None,
        checkpoint_ref: str | None = None,
    ) -> CampaignTask:
        from .planner import CampaignTask

        resolved_provenance = TaskProvenance() if provenance is None else provenance
        if self.task_factory is None and self.task_factory_name is not None:
            raise CampaignInvariantError(
                f"strategy {self.name!r} requires uninjected task factory "
                f"{self.task_factory_name!r}"
            )
        if self.task_factory is None:
            parameters = self.parameters.to_dict()
            parameters["target"] = target.identity_dict()
            parameters["target_id"] = target.target_id
            produced: TaskSpec | CampaignTask = TaskSpec(
                operation=self.operation,
                parameters=parameters,
                backend=self.backend,
            )
        else:
            produced = self.task_factory(target, resolved_provenance, checkpoint_ref)
        if isinstance(produced, CampaignTask):
            if produced.target_id != target.target_id:
                raise CampaignInvariantError(
                    "strategy task factory returned a task for another target"
                )
            return produced.with_provenance(resolved_provenance)
        if not isinstance(produced, TaskSpec):
            raise CampaignInvariantError(
                "strategy task factory must return TaskSpec or CampaignTask"
            )
        return CampaignTask(
            task=produced,
            target=target,
            strategy=self.name,
            rationale=self.rationale,
            provenance=resolved_provenance,
            capability_requirements=self.capability_requirements,
            checkpoint_ref=checkpoint_ref,
            usefulness=self.usefulness,
            information_gain=self.information_gain,
            estimated_cost=self.estimated_cost,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "backend": self.backend.to_dict(),
            "capability_requirements": list(self.capability_requirements),
            "estimated_cost": self.estimated_cost,
            "gate_name": self.gate_name,
            "information_gain": self.information_gain,
            "name": self.name,
            "operation": self.operation,
            "parameters": self.parameters.to_dict(),
            "rationale": self.rationale,
            "schema": "arbogast.campaign.strategy.v1",
            "task_factory_name": self.task_factory_name,
            "usefulness": self.usefulness,
            "verify_results": self.verify_results,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Strategy:
        required = {
            "backend",
            "capability_requirements",
            "estimated_cost",
            "gate_name",
            "information_gain",
            "name",
            "operation",
            "parameters",
            "rationale",
            "schema",
            "task_factory_name",
            "usefulness",
            "verify_results",
        }
        if set(value) != required:
            raise CampaignSerializationError("strategy has missing or unknown fields")
        if value["schema"] != "arbogast.campaign.strategy.v1":
            raise CampaignSerializationError("unsupported strategy schema")
        for field_name in ("name", "operation", "rationale"):
            if not isinstance(value[field_name], str):
                raise CampaignSerializationError(f"strategy {field_name} must be a string")
        gate_name = value["gate_name"]
        if gate_name is not None and not isinstance(gate_name, str):
            raise CampaignSerializationError("gate_name must be a string or null")
        task_factory_name = value["task_factory_name"]
        if task_factory_name is not None and not isinstance(task_factory_name, str):
            raise CampaignSerializationError("task_factory_name must be a string or null")
        if not isinstance(value["verify_results"], bool):
            raise CampaignSerializationError("verify_results must be boolean")
        capabilities = value["capability_requirements"]
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            raise CampaignSerializationError("capabilities must be an array of strings")
        backend_value = value["backend"]
        parameters = value["parameters"]
        if not isinstance(backend_value, Mapping) or not isinstance(parameters, Mapping):
            raise CampaignSerializationError("strategy backend and parameters must be objects")
        backend_keys = {"capabilities", "name", "version"}
        if set(backend_value) != backend_keys:
            raise CampaignSerializationError("strategy backend has missing or unknown fields")
        backend_capabilities = backend_value["capabilities"]
        if not isinstance(backend_capabilities, list) or any(
            not isinstance(item, str) for item in backend_capabilities
        ):
            raise CampaignSerializationError("backend capabilities must be an array of strings")
        backend_name = backend_value["name"]
        backend_version = backend_value["version"]
        if not isinstance(backend_name, str) or (
            backend_version is not None and not isinstance(backend_version, str)
        ):
            raise CampaignSerializationError("invalid backend name/version")
        integers: dict[str, int] = {}
        for field_name in ("usefulness", "information_gain", "estimated_cost"):
            raw = value[field_name]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise CampaignSerializationError(f"{field_name} must be an integer")
            integers[field_name] = raw
        return cls(
            name=value["name"],
            operation=value["operation"],
            rationale=value["rationale"],
            parameters=parameters,
            backend=BackendRequirement(
                name=backend_name,
                version=backend_version,
                capabilities=tuple(backend_capabilities),
            ),
            capability_requirements=tuple(capabilities),
            gate=gate_name,
            task_factory_name=task_factory_name,
            verify_results=value["verify_results"],
            usefulness=integers["usefulness"],
            information_gain=integers["information_gain"],
            estimated_cost=integers["estimated_cost"],
        )


PreflightDecision = GateDecision
PreflightGate = ExactGate

__all__ = [
    "ExactGate",
    "FunctionalGate",
    "GateDecision",
    "GateDisposition",
    "PreflightDecision",
    "PreflightGate",
    "Strategy",
    "TaskFactory",
]
