"""Typed epistemic boundaries with no implicit assurance promotion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeAlias, TypeVar, cast, runtime_checkable

from arbogast.cert.canonical import validate_content_address


class EpistemicBoundaryError(TypeError):
    """Raised when a value crosses an epistemic boundary without explicit evidence."""


class EpistemicStatus(StrEnum):
    """Mutually distinct epistemic states.

    These values are not an ordering.  In particular, ``Certified[T]`` is not silently
    accepted where ``Exact[T]`` is required, and neither is a numerical value promoted by
    merely changing an enum.
    """

    EXACT = "exact"
    CERTIFIED = "certified"
    CONDITIONAL = "conditional"
    NUMERICAL = "numerical"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class EpistemicValue(Protocol[T_co]):
    """Protocol common to all typed epistemic wrappers."""

    @property
    def status(self) -> EpistemicStatus:
        """Return the exact epistemic boundary."""

    def to_canonical(self) -> object:
        """Return a stable semantic representation."""


@dataclass(frozen=True)
class Exact(Generic[T]):
    """A value produced by exact mathematical operations."""

    value: T

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.EXACT

    def to_canonical(self) -> dict[str, object]:
        return {"status": self.status.value, "value": self.value}


@dataclass(frozen=True)
class Certified(Generic[T]):
    """A value supported by one or more independently checkable certificates."""

    value: T
    certificates: tuple[str, ...]
    verifier: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "certificates", tuple(self.certificates))
        if not self.certificates or any(
            not isinstance(item, str) or not item.strip() for item in self.certificates
        ):
            raise ValueError("Certified values require non-empty certificate references")
        for certificate in self.certificates:
            validate_content_address(certificate)
        if self.verifier is not None and (
            not isinstance(self.verifier, str) or not self.verifier.strip()
        ):
            raise ValueError("verifier must be a non-blank string")

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.CERTIFIED

    def to_canonical(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "value": self.value,
            "certificates": self.certificates,
            "verifier": self.verifier,
        }


@dataclass(frozen=True)
class Conditional(Generic[T]):
    """A value valid only under explicit hypotheses."""

    value: T
    conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "conditions", tuple(self.conditions))
        if not self.conditions or any(
            not isinstance(condition, str) or not condition.strip() for condition in self.conditions
        ):
            raise ValueError("Conditional values require explicit non-empty conditions")

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.CONDITIONAL

    def to_canonical(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "value": self.value,
            "conditions": self.conditions,
        }


@dataclass(frozen=True)
class Numerical(Generic[T]):
    """A numerical value with an explicit precision or error statement."""

    value: T
    precision_bits: int | None = None
    error_bound: str | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        if self.precision_bits is None and self.error_bound is None:
            raise ValueError("Numerical values require precision_bits or an error_bound")
        if self.precision_bits is not None and (
            isinstance(self.precision_bits, bool)
            or not isinstance(self.precision_bits, int)
            or self.precision_bits <= 0
        ):
            raise ValueError("precision_bits must be positive")
        if self.error_bound is not None and (
            not isinstance(self.error_bound, str) or not self.error_bound.strip()
        ):
            raise ValueError("error_bound must be a non-blank string")
        if self.method is not None and (
            not isinstance(self.method, str) or not self.method.strip()
        ):
            raise ValueError("numerical method must be a non-blank string")

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.NUMERICAL

    def to_canonical(self) -> dict[str, object]:
        value: object = self.value
        if isinstance(value, float):
            value = {"$numerical_float_hex": value.hex()}
        return {
            "status": self.status.value,
            "value": value,
            "precision_bits": self.precision_bits,
            "error_bound": self.error_bound,
            "method": self.method,
        }


@dataclass(frozen=True)
class Heuristic(Generic[T]):
    """A candidate or estimate produced without a completeness guarantee."""

    value: T
    rationale: str
    method: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("Heuristic values require a rationale")
        if self.method is not None and (
            not isinstance(self.method, str) or not self.method.strip()
        ):
            raise ValueError("heuristic method must be a non-blank string")

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.HEURISTIC

    def to_canonical(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "value": self.value,
            "rationale": self.rationale,
            "method": self.method,
        }


@dataclass(frozen=True)
class Unknown(Generic[T]):
    """An explicit absence of a justified value."""

    reason: str
    attempted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Unknown values require a reason")
        object.__setattr__(self, "attempted", tuple(self.attempted))
        if any(not isinstance(attempt, str) or not attempt.strip() for attempt in self.attempted):
            raise ValueError("Unknown attempted operations must be non-blank strings")

    @property
    def status(self) -> EpistemicStatus:
        return EpistemicStatus.UNKNOWN

    def to_canonical(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "attempted": self.attempted,
        }


AnyEpistemic: TypeAlias = (
    Exact[T] | Certified[T] | Conditional[T] | Numerical[T] | Heuristic[T] | Unknown[T]
)


def require_exact(value: AnyEpistemic[T]) -> T:
    """Return an exact value, rejecting every other wrapper without coercion."""

    if not isinstance(value, Exact):
        raise EpistemicBoundaryError(f"Exact required, received {value.status.value}")
    return value.value


def require_certified(value: AnyEpistemic[T]) -> T:
    """Return a certified value; exact values are not an implicit substitute."""

    if not isinstance(value, Certified):
        raise EpistemicBoundaryError(f"Certified required, received {value.status.value}")
    return value.value


def require_status(value: AnyEpistemic[T], status: EpistemicStatus) -> T:
    """Unwrap only when the requested and actual statuses are identical."""

    if value.status is not status:
        raise EpistemicBoundaryError(f"{status.value} required, received {value.status.value}")
    if isinstance(value, Unknown):
        raise EpistemicBoundaryError(f"unknown value has no payload: {value.reason}")
    return value.value


def epistemic_from_dict(value: Mapping[str, object]) -> AnyEpistemic[object]:
    """Strictly decode a typed epistemic wrapper."""

    raw_status = value.get("status")
    if not isinstance(raw_status, str):
        raise EpistemicBoundaryError("valid epistemic status is required")
    try:
        status = EpistemicStatus(raw_status)
    except ValueError as exc:
        raise EpistemicBoundaryError("valid epistemic status is required") from exc
    allowed_by_status = {
        EpistemicStatus.EXACT: {"status", "value"},
        EpistemicStatus.CERTIFIED: {"status", "value", "certificates", "verifier"},
        EpistemicStatus.CONDITIONAL: {"status", "value", "conditions"},
        EpistemicStatus.NUMERICAL: {
            "status",
            "value",
            "precision_bits",
            "error_bound",
            "method",
        },
        EpistemicStatus.HEURISTIC: {"status", "value", "rationale", "method"},
        EpistemicStatus.UNKNOWN: {"status", "reason", "attempted"},
    }
    unexpected = sorted(set(value) - allowed_by_status[status])
    if unexpected:
        raise EpistemicBoundaryError(
            f"unexpected {status.value} wrapper fields: {', '.join(unexpected)}"
        )
    if status is EpistemicStatus.UNKNOWN:
        reason = value.get("reason")
        if not isinstance(reason, str):
            raise EpistemicBoundaryError("unknown wrapper reason must be a string")
        return Unknown(
            reason=reason,
            attempted=_string_tuple(value.get("attempted", ())),
        )
    if "value" not in value:
        raise EpistemicBoundaryError(f"{status.value} wrapper requires a value")
    payload = value["value"]
    if status is EpistemicStatus.EXACT:
        return Exact(payload)
    if status is EpistemicStatus.CERTIFIED:
        verifier = value.get("verifier")
        if verifier is not None and not isinstance(verifier, str):
            raise EpistemicBoundaryError("verifier must be a string or null")
        return Certified(
            payload,
            _string_tuple(value.get("certificates", ())),
            verifier,
        )
    if status is EpistemicStatus.CONDITIONAL:
        return Conditional(payload, _string_tuple(value.get("conditions", ())))
    if status is EpistemicStatus.NUMERICAL:
        raw_precision = value.get("precision_bits")
        if raw_precision is not None and (
            isinstance(raw_precision, bool) or not isinstance(raw_precision, int)
        ):
            raise EpistemicBoundaryError("precision_bits must be an integer")
        error_bound = value.get("error_bound")
        method = value.get("method")
        if error_bound is not None and not isinstance(error_bound, str):
            raise EpistemicBoundaryError("error_bound must be a string or null")
        if method is not None and not isinstance(method, str):
            raise EpistemicBoundaryError("method must be a string or null")
        return Numerical(
            payload,
            precision_bits=raw_precision,
            error_bound=error_bound,
            method=method,
        )
    rationale = value.get("rationale")
    method = value.get("method")
    if not isinstance(rationale, str):
        raise EpistemicBoundaryError("heuristic rationale must be a string")
    if method is not None and not isinstance(method, str):
        raise EpistemicBoundaryError("method must be a string or null")
    return Heuristic(
        payload,
        rationale=rationale,
        method=method,
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise EpistemicBoundaryError("expected a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise EpistemicBoundaryError("expected a sequence of strings")
    return tuple(cast(Sequence[str], value))


__all__ = [
    "AnyEpistemic",
    "Certified",
    "Conditional",
    "EpistemicBoundaryError",
    "EpistemicStatus",
    "EpistemicValue",
    "Exact",
    "Heuristic",
    "Numerical",
    "Unknown",
    "epistemic_from_dict",
    "require_certified",
    "require_exact",
    "require_status",
]
