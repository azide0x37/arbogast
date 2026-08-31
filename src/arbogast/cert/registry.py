"""Fail-closed registry for independent certificate verifiers."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import marshal
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import (
    BuiltinFunctionType,
    BuiltinMethodType,
    CodeType,
    FunctionType,
    MethodType,
    ModuleType,
)
from typing import Any, TypeAlias, TypeVar, cast

from arbogast.formats import JSONValue, canonical_sha256

from .base import Certificate, CertificateError
from .canonical import FrozenMap, freeze_mapping


class UnknownVerifierError(LookupError):
    """Raised when no explicitly registered verifier can check a certificate."""


class CertificateVerificationError(CertificateError):
    """Raised when a verifier rejects or cannot completely check evidence."""


@dataclass(frozen=True)
class VerificationReport:
    """Machine-readable outcome of independent certificate verification."""

    valid: bool
    verifier: str
    certificate_id: str
    checks: tuple[str, ...] = ()
    details: FrozenMap = field(default_factory=FrozenMap)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.verifier.strip():
            raise CertificateVerificationError("report verifier cannot be blank")
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "details", freeze_mapping(self.details))
        if self.valid and self.error is not None:
            raise CertificateVerificationError("a valid report cannot carry an error")
        if not self.valid and not self.error:
            raise CertificateVerificationError("an invalid report must explain the failure")

    def require_valid(self) -> VerificationReport:
        if not self.valid:
            raise CertificateVerificationError(self.error or "certificate verification failed")
        return self

    def to_canonical(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "verifier": self.verifier,
            "certificate_id": self.certificate_id,
            "checks": self.checks,
            "details": self.details,
            "error": self.error,
        }


VerifierReturn: TypeAlias = VerificationReport | bool
Verifier: TypeAlias = Callable[[Certificate], VerifierReturn]
C = TypeVar("C", bound=Certificate)


@dataclass(frozen=True)
class _RegisteredVerifier:
    name: str
    certificate_type: type[Any]
    function: Verifier


def _sha256(value: object) -> str:
    return f"sha256:{canonical_sha256(value)}"


def _stable_code(code: CodeType) -> CodeType:
    constants = tuple(
        _stable_code(item) if isinstance(item, CodeType) else item for item in code.co_consts
    )
    return code.replace(co_consts=constants, co_filename="", co_firstlineno=1)


def _source_identity(value: object) -> tuple[str | None, str | None]:
    """Return a relocation-stable source label and hash without importing code."""

    module = getattr(value, "__module__", None)
    try:
        filename = inspect.getsourcefile(cast(Callable[..., object], value))
    except TypeError:
        filename = None
    source_label = None
    if isinstance(module, str) and module:
        basename = (
            filename.replace("\\", "/").rsplit("/", 1)[-1]
            if isinstance(filename, str) and filename
            else "<builtin-or-extension>"
        )
        source_label = f"{module}:{basename}"
    try:
        source = inspect.getsource(cast(Callable[..., object], value))
    except (OSError, TypeError):
        source = None
    source_digest = (
        "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source is not None
        else None
    )
    return source_label, source_digest


def _reference_identity(
    value: object,
    *,
    manifest_registry: VerifierRegistry,
    active: dict[int, str],
    path: str,
) -> tuple[JSONValue, bool, str | None]:
    """Project one referenced value without invoking user-controlled behavior."""

    if value is manifest_registry:
        return (
            {
                "$verifier_registry": "self",
                "schema": "arbogast.cert.verifier-registry-runtime.v1",
            },
            True,
            None,
        )
    if value is None or type(value) in (bool, int, str):
        return cast(JSONValue, value), True, None

    object_id = id(value)
    if object_id in active:
        return {"$cycle": active[object_id]}, True, None

    value_type = type(value)
    if value_type in (FunctionType, MethodType):
        identity, valid, reason = _callable_identity(
            value,
            manifest_registry=manifest_registry,
            _active=active,
            _anchor=path,
            _bind_references=False,
        )
        return {"$function": identity}, valid, reason

    if value_type in (BuiltinFunctionType, BuiltinMethodType):
        module = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if not isinstance(module, str) or not module or not isinstance(qualname, str):
            return {}, False, f"{path} has no stable builtin callable identity"
        source, source_sha256 = _source_identity(value)
        return (
            {
                "$builtin": f"{module}.{qualname}",
                "source": source,
                "source_sha256": source_sha256,
            },
            True,
            None,
        )

    if issubclass(value_type, type):
        module = type.__getattribute__(value, "__module__")
        qualname = type.__getattribute__(value, "__qualname__")
        if not isinstance(module, str) or not module or not isinstance(qualname, str):
            return {}, False, f"{path} has no stable class identity"
        return (
            {
                "$class": f"{module}.{qualname}",
                "source": f"{module}:<class>",
                "source_sha256": None,
            },
            True,
            None,
        )

    if issubclass(value_type, ModuleType):
        name = ModuleType.__getattribute__(value, "__name__")
        if not isinstance(name, str) or not name:
            return {}, False, f"{path} has no stable module identity"
        filename = ModuleType.__getattribute__(value, "__dict__").get("__file__")
        basename = (
            filename.replace("\\", "/").rsplit("/", 1)[-1]
            if isinstance(filename, str) and filename
            else None
        )
        return {"$module": name, "source": basename}, True, None

    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(not isinstance(key, str) for key in mapping):
            return {}, False, f"{path} mapping has a non-string key"
        string_mapping = cast(dict[str, object], mapping)
        active[object_id] = path
        projected: dict[str, JSONValue] = {}
        reasons: list[str] = []
        valid = True
        try:
            for key in sorted(string_mapping):
                item, item_valid, reason = _reference_identity(
                    string_mapping[key],
                    manifest_registry=manifest_registry,
                    active=active,
                    path=f"{path}.{key}",
                )
                projected[key] = item
                valid = valid and item_valid
                if reason is not None:
                    reasons.append(reason)
        finally:
            active.pop(object_id, None)
        return {"$mapping": projected}, valid, "; ".join(reasons) or None

    if type(value) in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        active[object_id] = path
        projected_items: list[JSONValue] = []
        reasons = []
        valid = True
        try:
            for index, item_value in enumerate(sequence):
                item, item_valid, reason = _reference_identity(
                    item_value,
                    manifest_registry=manifest_registry,
                    active=active,
                    path=f"{path}[{index}]",
                )
                projected_items.append(item)
                valid = valid and item_valid
                if reason is not None:
                    reasons.append(reason)
        finally:
            active.pop(object_id, None)
        tag = "$tuple" if type(value) is tuple else "$list"
        return {tag: projected_items}, valid, "; ".join(reasons) or None

    if type(value) in (set, frozenset):
        unordered = cast(set[object] | frozenset[object], value)
        projected_items = []
        for index, item_value in enumerate(unordered):
            item, item_valid, reason = _reference_identity(
                item_value,
                manifest_registry=manifest_registry,
                active=active,
                path=f"{path}{{{index}}}",
            )
            if not item_valid:
                return {}, False, reason
            projected_items.append(item)
        projected_items.sort(key=canonical_sha256)
        tag = "$frozenset" if type(value) is frozenset else "$set"
        return {tag: projected_items}, True, None

    return (
        {},
        False,
        f"{path} has unsupported referenced value type "
        f"{type(value).__module__}.{type(value).__qualname__}",
    )


def _callable_identity(
    function: object,
    *,
    manifest_registry: VerifierRegistry,
    _active: dict[int, str] | None = None,
    _anchor: str | None = None,
    _bind_references: bool = True,
) -> tuple[dict[str, JSONValue], bool, str | None]:
    """Describe code and every effective global/nonlocal value it references."""

    function_type = type(function)
    if function_type not in (FunctionType, MethodType):
        type_module = type.__getattribute__(function_type, "__module__")
        type_qualname = type.__getattribute__(function_type, "__qualname__")
        return (
            {
                "module": type_module if isinstance(type_module, str) else None,
                "qualname": type_qualname if isinstance(type_qualname, str) else None,
                "source": None,
                "source_sha256": None,
                "code_sha256": None,
                "bound_values_digest": None,
                "references": {"globals": {}, "nonlocals": {}, "unbound": []},
            },
            False,
            "callable implementation is not a Python function or bound method",
        )
    target = cast(MethodType, function).__func__ if function_type is MethodType else function
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    references: dict[str, JSONValue] = {
        "globals": {},
        "nonlocals": {},
        "unbound": [],
    }
    identity: dict[str, JSONValue] = {
        "module": module if isinstance(module, str) else None,
        "qualname": qualname if isinstance(qualname, str) else None,
        "source": None,
        "source_sha256": None,
        "code_sha256": None,
        "bound_values_digest": None,
        "references": references,
    }
    code = getattr(target, "__code__", None)
    if not isinstance(module, str) or not module or not isinstance(qualname, str) or not qualname:
        return identity, False, "callable has no stable module and qualified name"
    if not isinstance(code, CodeType):
        return identity, False, "callable has no inspectable Python code object"

    active = {} if _active is None else _active
    anchor = _anchor or f"function:{module}.{qualname}"
    object_id = id(target)
    active[object_id] = anchor
    reasons: list[str] = []
    certifiable = True
    try:
        identity["source"], identity["source_sha256"] = _source_identity(target)
        identity["code_sha256"] = (
            "sha256:" + hashlib.sha256(marshal.dumps(_stable_code(code))).hexdigest()
        )

        bound_values: dict[str, JSONValue] = {}
        defaults = getattr(target, "__defaults__", None)
        if defaults:
            projected, valid, reason = _reference_identity(
                defaults,
                manifest_registry=manifest_registry,
                active=active,
                path=f"{anchor}.defaults",
            )
            bound_values["defaults"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        keyword_defaults = getattr(target, "__kwdefaults__", None)
        if keyword_defaults:
            projected, valid, reason = _reference_identity(
                keyword_defaults,
                manifest_registry=manifest_registry,
                active=active,
                path=f"{anchor}.keyword_defaults",
            )
            bound_values["keyword_defaults"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        closure = getattr(target, "__closure__", None)
        if closure:
            try:
                closure_values = tuple(cell.cell_contents for cell in closure)
            except ValueError:
                return identity, False, "callable contains an empty closure cell"
            projected, valid, reason = _reference_identity(
                closure_values,
                manifest_registry=manifest_registry,
                active=active,
                path=f"{anchor}.closure",
            )
            bound_values["closure"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        identity["bound_values_digest"] = _sha256(bound_values)

        if _bind_references:
            closure_variables = inspect.getclosurevars(cast(Callable[..., object], target))
            for group_name, group in (
                ("globals", closure_variables.globals),
                ("nonlocals", closure_variables.nonlocals),
            ):
                projected_group: dict[str, JSONValue] = {}
                for name in sorted(group):
                    projected, valid, reason = _reference_identity(
                        group[name],
                        manifest_registry=manifest_registry,
                        active=active,
                        path=f"{anchor}.{group_name}.{name}",
                    )
                    projected_group[name] = projected
                    certifiable = certifiable and valid
                    if reason is not None:
                        reasons.append(reason)
                references[group_name] = projected_group
            references["unbound"] = [
                cast(JSONValue, name) for name in sorted(closure_variables.unbound)
            ]
    finally:
        active.pop(object_id, None)
    return identity, certifiable, "; ".join(reasons) or None


def _verifier_manifest_entry(
    registered: _RegisteredVerifier,
    *,
    manifest_registry: VerifierRegistry,
) -> dict[str, JSONValue]:
    certificate_type = registered.certificate_type
    certificate_type_name = f"{certificate_type.__module__}.{certificate_type.__qualname__}"
    implementation, certifiable, reason = _callable_identity(
        registered.function,
        manifest_registry=manifest_registry,
    )
    contract: dict[str, JSONValue] = {
        "schema": "arbogast.cert.verifier-contract.v1",
        "certificate_type": certificate_type_name,
    }
    return {
        "name": registered.name,
        "certificate_type": certificate_type_name,
        "contract_digest": _sha256(contract),
        "implementation": implementation,
        "implementation_digest": _sha256(implementation),
        "certifiable": certifiable,
        "reason": None if certifiable else reason,
    }


class VerifierRegistry:
    """Explicit verifier dispatch with no permissive fallback."""

    def __init__(self) -> None:
        self._verifiers: dict[str, _RegisteredVerifier] = {}

    def register(
        self,
        name: str,
        certificate_type: type[C],
        function: Callable[[C], VerifierReturn],
    ) -> None:
        if not name.strip():
            raise ValueError("verifier name cannot be blank")
        existing = self._verifiers.get(name)
        erased = cast(Verifier, function)
        candidate = _RegisteredVerifier(name, certificate_type, erased)
        if existing is not None and existing != candidate:
            raise ValueError(f"verifier already registered: {name}")
        self._verifiers[name] = candidate

    def unregister(self, name: str) -> None:
        if name not in self._verifiers:
            raise UnknownVerifierError(name)
        del self._verifiers[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._verifiers))

    def describe(self, name: str) -> dict[str, str]:
        registered = self._verifiers.get(name)
        if registered is None and self is default_verifiers:
            registered = _load_builtin_verifier(name)
        if registered is None:
            raise UnknownVerifierError(name)
        certificate_type = registered.certificate_type
        return {
            "name": name,
            "certificate_type": f"{certificate_type.__module__}.{certificate_type.__qualname__}",
            "callable": (
                f"{registered.function.__module__}."
                f"{getattr(registered.function, '__qualname__', registered.function.__name__)}"
            ),
        }

    def readiness_manifest(
        self,
        names: Iterable[str] | None = None,
        *,
        load_builtins: bool = False,
    ) -> dict[str, JSONValue]:
        """Bind selected verifier contracts to exact executable identities.

        ``load_builtins`` imports only modules in the fixed built-in allowlist.
        A verifier name can therefore never select an arbitrary import target.
        When called on a private registry, exact built-in registrations are
        copied from :data:`default_verifiers` after their audited modules load.
        """

        if isinstance(names, str):
            raise ValueError("manifest names must be an iterable of names")
        if names is None:
            selected = set(self.names())
            if load_builtins:
                selected.update(_BUILTIN_VERIFIER_MODULES)
        else:
            selected_items = tuple(names)
            if any(not isinstance(name, str) or not name.strip() for name in selected_items):
                raise ValueError("manifest names must be non-empty strings")
            if len(selected_items) != len(set(selected_items)):
                raise ValueError("manifest names must be unique")
            selected = set(selected_items)

        if load_builtins:
            for name in sorted(selected):
                if name not in _BUILTIN_VERIFIER_MODULES:
                    continue
                registered = _load_builtin_verifier(name)
                if registered is None:
                    raise UnknownVerifierError(name)
                if self is not default_verifiers:
                    self.register(
                        name,
                        registered.certificate_type,
                        registered.function,
                    )

        entries: list[JSONValue] = []
        for name in sorted(selected):
            registered = self._verifiers.get(name)
            if registered is None:
                raise UnknownVerifierError(name)
            entries.append(_verifier_manifest_entry(registered, manifest_registry=self))
        payload: dict[str, JSONValue] = {
            "schema": "arbogast.cert.verifier-registry-manifest.v1",
            "verifiers": entries,
        }
        payload["digest"] = _sha256(payload)
        return payload

    def verify(
        self,
        certificate: Certificate,
        *,
        verifier_name: str | None = None,
        raise_on_failure: bool = True,
    ) -> VerificationReport:
        certificate.verify_integrity() if hasattr(certificate, "verify_integrity") else None
        name = verifier_name or getattr(certificate, "verifier", None)
        if not isinstance(name, str) or not name:
            raise UnknownVerifierError("certificate has no verifier name; select one explicitly")
        registered = self._verifiers.get(name)
        if registered is None and self is default_verifiers:
            registered = _load_builtin_verifier(name)
        if registered is None:
            raise UnknownVerifierError(name)
        if not isinstance(certificate, registered.certificate_type):
            raise CertificateVerificationError(
                f"verifier {name} expects {registered.certificate_type.__qualname__}, "
                f"got {type(certificate).__qualname__}"
            )
        try:
            raw = registered.function(certificate)
        except CertificateVerificationError:
            raise
        except Exception as exc:
            raise CertificateVerificationError(
                f"verifier {name} raised {type(exc).__name__}: {exc}"
            ) from exc
        if isinstance(raw, bool):
            report = VerificationReport(
                valid=raw,
                verifier=name,
                certificate_id=certificate.certificate_id,
                error=None if raw else f"verifier {name} rejected the certificate",
            )
        elif isinstance(raw, VerificationReport):
            if raw.certificate_id != certificate.certificate_id:
                raise CertificateVerificationError(
                    "verifier report is bound to a different certificate"
                )
            if raw.verifier != name:
                raise CertificateVerificationError("verifier report names a different verifier")
            report = raw
        else:
            raise CertificateVerificationError(
                f"verifier {name} returned unsupported result {type(raw).__qualname__}"
            )
        if raise_on_failure:
            report.require_valid()
        return report


default_verifiers = VerifierRegistry()

_BUILTIN_VERIFIER_MODULES = {
    "arbogast.bootstrap.readiness.v1": "arbogast.bootstrap.semantic",
    "arbogast.backends.pari.operational.v1": "arbogast.backends.pari_certificate",
    "arbogast.backends.pari.v1": "arbogast.backends.pari_certificate",
    "campaign.claim-closure.v1": "arbogast.campaign.claims",
    "cohom.induced_map.v1": "arbogast.cohom.map_certificate",
    "cohom.inflation_restriction.v1": "arbogast.cohom.five_term",
    "cohom.normalized_bar.v1": "arbogast.cohom.semantic",
    "deform.finite-exact.v1": "arbogast.deform.semantic",
    "galois.kummer.v1": "arbogast.galois.semantic",
    "galois.finite_quotient.v1": "arbogast.galois.groups",
    "galois.local_h1.v1": "arbogast.galois.semantic",
    "galois.localization.v1": "arbogast.galois.semantic",
    "galois.module.v1": "arbogast.galois.modules",
    "galois.quotient_presentation.v1": "arbogast.galois.groups",
    "galois.twists.v1": "arbogast.galois.semantic",
    "galois.unsupported.v1": "arbogast.galois.proof",
    "arithmetic.finite-linear.v1": "arbogast.arithmetic.semantic",
    "hurwitz.nielsen_class": "arbogast.hurwitz.claims",
    "hurwitz.braid_action": "arbogast.hurwitz.claims",
    "hurwitz.components": "arbogast.hurwitz.claims",
    "hurwitz.real_structure": "arbogast.hurwitz.claims",
    "hurwitz.real_census": "arbogast.hurwitz.claims",
    "hurwitz.reduced": "arbogast.hurwitz.claims",
    "hurwitz.cusps": "arbogast.hurwitz.claims",
    "hurwitz.boundary": "arbogast.hurwitz.claims",
    "numeric.exact-bridge.v1": "arbogast.numeric.semantic",
    "padic.finite-exact.v1": "arbogast.padic.semantic",
    "padic.three-point-exact.v1": "arbogast.padic.semantic",
}


def _load_builtin_verifier(name: str) -> _RegisteredVerifier | None:
    """Import only the fixed module assigned to a known verifier name.

    This is intentionally not a prefix convention or an entry-point scan.  A
    certificate cannot select an arbitrary module, and importing a module does
    not make verification permissive: the module must still register the exact
    requested name and certificate type.
    """

    module_name = _BUILTIN_VERIFIER_MODULES.get(name)
    if module_name is None:
        return None
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        # A partial/minimal installation reports an unknown verifier cleanly.
        # Missing dependencies *inside* an installed verifier are programming
        # errors and remain visible rather than being mistaken for absence.
        missing = error.name or ""
        if missing == module_name or module_name.startswith(missing + "."):
            return None
        raise
    return default_verifiers._verifiers.get(name)


def verifier(
    name: str,
    *,
    certificate_type: type[C],
    registry: VerifierRegistry = default_verifiers,
) -> Callable[[Callable[[C], VerifierReturn]], Callable[[C], VerifierReturn]]:
    """Register a typed verifier function."""

    def decorate(function: Callable[[C], VerifierReturn]) -> Callable[[C], VerifierReturn]:
        registry.register(name, certificate_type, function)
        return function

    return decorate


def verify_certificate(
    certificate: Certificate,
    *,
    verifier_name: str | None = None,
    registry: VerifierRegistry = default_verifiers,
    raise_on_failure: bool = True,
) -> VerificationReport:
    """Verify a certificate through an explicitly registered independent checker."""

    return registry.verify(
        certificate,
        verifier_name=verifier_name,
        raise_on_failure=raise_on_failure,
    )


__all__ = [
    "CertificateVerificationError",
    "UnknownVerifierError",
    "VerificationReport",
    "VerifierRegistry",
    "default_verifiers",
    "verifier",
    "verify_certificate",
]
