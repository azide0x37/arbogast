from __future__ import annotations

import sys

import pytest

from arbogast.cert import VerificationCertificate, VerifierRegistry
from arbogast.cert.registry import UnknownVerifierError
from arbogast.fleet import (
    FleetOperationRegistry,
    FleetOperationRegistryError,
    FunctionalOperation,
)
from arbogast.formats import canonical_sha256, normalize_json

_VERIFIER_GLOBAL_MAPPING = {"enabled": True, "revision": 1}
_VERIFIER_GLOBAL_FLAG = True
_VERIFIER_GLOBAL_TEXT = "stable"
_OPERATION_GLOBAL_MAPPING = {"revision": 1}
_OPERATION_GLOBAL_FLAG = True
_OPERATION_GLOBAL_TEXT = "stable"
_CYCLIC_GLOBAL: dict[str, object] = {}
_CYCLIC_GLOBAL["self"] = _CYCLIC_GLOBAL


class _ExplosiveGlobal:
    def __getattribute__(self, _name: str) -> object:
        raise AssertionError("readiness fingerprint executed referenced state")


_EXPLOSIVE_GLOBAL = _ExplosiveGlobal()


def _module_global_verifier(_certificate: VerificationCertificate) -> bool:
    return bool(
        _VERIFIER_GLOBAL_MAPPING["enabled"] and _VERIFIER_GLOBAL_FLAG and _VERIFIER_GLOBAL_TEXT
    )


def _module_global_planner(_task: object) -> tuple[str, ...]:
    if not _OPERATION_GLOBAL_FLAG:
        return ()
    return (f"{_OPERATION_GLOBAL_TEXT}-{_OPERATION_GLOBAL_MAPPING['revision']}",)


def _cyclic_global_verifier(_certificate: VerificationCertificate) -> bool:
    return bool(_CYCLIC_GLOBAL)


def _explosive_global_verifier(_certificate: VerificationCertificate) -> bool:
    return _EXPLOSIVE_GLOBAL is not None


def _operation(marker: str, *, verified: bool = False) -> FunctionalOperation[object, object]:
    def planner(_task: object) -> tuple[str, ...]:
        return (marker,)

    def runner(_task: object, shard: object) -> dict[str, object]:
        return {"marker": marker, "shard": str(shard)}

    def reducer(_task: object, partials: object) -> dict[str, object]:
        return {"marker": marker, "partials": str(partials)}

    def verifier(_task: object, result: object) -> bool:
        return result is not None

    return FunctionalOperation(
        planner=planner,
        runner=runner,
        reducer=reducer,
        verifier=verifier if verified else None,
    )


def _digest_without_digest(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "digest"}
    return f"sha256:{canonical_sha256(payload)}"


def test_operation_readiness_manifest_binds_contract_code_and_closure_state() -> None:
    first_registry = FleetOperationRegistry(
        {
            "tests.second": _operation("second", verified=True),
            "tests.first": _operation("first"),
        }
    )
    second_registry = FleetOperationRegistry({"tests.first": _operation("changed")})

    manifest = first_registry.readiness_manifest()
    repeated = first_registry.readiness_manifest()
    changed = second_registry.readiness_manifest()

    assert manifest == repeated
    assert normalize_json(manifest) == manifest
    assert manifest["digest"] == _digest_without_digest(manifest)
    assert [entry["name"] for entry in manifest["operations"]] == [
        "tests.first",
        "tests.second",
    ]
    first = manifest["operations"][0]
    assert first["contract"] == {
        "schema": "arbogast.fleet.operation-contract.v1",
        "required_methods": ["plan", "run", "reduce"],
        "optional_methods": [],
        "closure_verifiers": [],
    }
    assert first["certifiable"] is True
    assert first["reason"] is None
    assert first["implementation"]["methods"]["plan"]["code_sha256"].startswith("sha256:")
    assert first["implementation_digest"] != changed["operations"][0]["implementation_digest"]
    assert first_registry.to_dict() == {
        "names": ["tests.first", "tests.second"],
        "schema": "arbogast.fleet.operation-registry.v1",
    }


def test_operation_readiness_manifest_reports_uncertifiable_bound_values() -> None:
    opaque = object()

    def planner(_task: object) -> tuple[str, ...]:
        return ("only" if opaque is not None else "unreachable",)

    operation = FunctionalOperation(
        planner=planner,
        runner=lambda _task, _shard: None,
        reducer=lambda _task, _partials: None,
    )
    entry = FleetOperationRegistry({"tests.opaque": operation}).readiness_manifest()["operations"][
        0
    ]

    assert entry["certifiable"] is False
    assert "unsupported referenced value type" in entry["reason"]


def test_operation_contract_binds_declared_closure_verifiers() -> None:
    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=lambda _task, _shard: None,
        reducer=lambda _task, _partials: None,
        closure_verifiers=("tests.closure",),
    )

    entry = FleetOperationRegistry({"tests.closing": operation}).readiness_manifest()["operations"][
        0
    ]

    assert entry["contract"]["closure_verifiers"] == ["tests.closure"]
    assert entry["certifiable"] is True


def test_verifier_readiness_manifest_is_deterministic_and_preserves_describe() -> None:
    registry = VerifierRegistry()

    def verify(_certificate: VerificationCertificate) -> bool:
        return True

    registry.register("tests.verifier", VerificationCertificate, verify)
    description = registry.describe("tests.verifier")
    manifest = registry.readiness_manifest(("tests.verifier",))

    assert registry.describe("tests.verifier") == description
    assert normalize_json(manifest) == manifest
    assert manifest["digest"] == _digest_without_digest(manifest)
    assert manifest["verifiers"][0]["certificate_type"] == (
        "arbogast.cert.verification.VerificationCertificate"
    )
    assert manifest["verifiers"][0]["certifiable"] is True
    assert manifest["verifiers"][0]["reason"] is None
    assert manifest == registry.readiness_manifest(("tests.verifier",))


def test_verifier_manifest_changes_for_mutable_module_global_state() -> None:
    global _VERIFIER_GLOBAL_FLAG, _VERIFIER_GLOBAL_TEXT

    registry = VerifierRegistry()
    registry.register(
        "tests.module-globals",
        VerificationCertificate,
        _module_global_verifier,
    )
    original_mapping = dict(_VERIFIER_GLOBAL_MAPPING)
    original_flag = _VERIFIER_GLOBAL_FLAG
    original_text = _VERIFIER_GLOBAL_TEXT
    try:
        initial = registry.readiness_manifest()["digest"]
        _VERIFIER_GLOBAL_MAPPING["revision"] = 2
        mapping_changed = registry.readiness_manifest()["digest"]
        _VERIFIER_GLOBAL_FLAG = False
        flag_changed = registry.readiness_manifest()["digest"]
        _VERIFIER_GLOBAL_TEXT = "changed"
        text_changed = registry.readiness_manifest()["digest"]
    finally:
        _VERIFIER_GLOBAL_MAPPING.clear()
        _VERIFIER_GLOBAL_MAPPING.update(original_mapping)
        _VERIFIER_GLOBAL_FLAG = original_flag
        _VERIFIER_GLOBAL_TEXT = original_text

    assert len({initial, mapping_changed, flag_changed, text_changed}) == 4


def test_operation_manifest_changes_for_mutable_module_global_state() -> None:
    global _OPERATION_GLOBAL_FLAG, _OPERATION_GLOBAL_TEXT

    operation = FunctionalOperation(
        planner=_module_global_planner,
        runner=lambda _task, _shard: None,
        reducer=lambda _task, _partials: None,
    )
    registry = FleetOperationRegistry({"tests.module-globals": operation})
    original_mapping = dict(_OPERATION_GLOBAL_MAPPING)
    original_flag = _OPERATION_GLOBAL_FLAG
    original_text = _OPERATION_GLOBAL_TEXT
    try:
        initial = registry.readiness_manifest()["digest"]
        _OPERATION_GLOBAL_MAPPING["revision"] = 2
        mapping_changed = registry.readiness_manifest()["digest"]
        _OPERATION_GLOBAL_FLAG = False
        flag_changed = registry.readiness_manifest()["digest"]
        _OPERATION_GLOBAL_TEXT = "changed"
        text_changed = registry.readiness_manifest()["digest"]
    finally:
        _OPERATION_GLOBAL_MAPPING.clear()
        _OPERATION_GLOBAL_MAPPING.update(original_mapping)
        _OPERATION_GLOBAL_FLAG = original_flag
        _OPERATION_GLOBAL_TEXT = original_text

    assert len({initial, mapping_changed, flag_changed, text_changed}) == 4


def test_self_referential_global_state_is_cycle_safe_and_bound() -> None:
    registry = VerifierRegistry()
    registry.register(
        "tests.cyclic-global",
        VerificationCertificate,
        _cyclic_global_verifier,
    )
    before = registry.readiness_manifest()
    try:
        _CYCLIC_GLOBAL["revision"] = 1
        after = registry.readiness_manifest()
    finally:
        _CYCLIC_GLOBAL.pop("revision", None)

    assert before["verifiers"][0]["certifiable"] is True
    assert before["digest"] != after["digest"]


def test_unsupported_global_fails_closed_without_executing_it() -> None:
    registry = VerifierRegistry()
    registry.register(
        "tests.explosive-global",
        VerificationCertificate,
        _explosive_global_verifier,
    )

    entry = registry.readiness_manifest()["verifiers"][0]

    assert entry["certifiable"] is False
    assert "_ExplosiveGlobal" in entry["reason"]


def test_private_verifier_registry_loads_only_fixed_builtin_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = VerifierRegistry()
    name = "cohom.normalized_bar.v1"
    manifest = registry.readiness_manifest((name,), load_builtins=True)

    assert [entry["name"] for entry in manifest["verifiers"]] == [name]
    assert registry.describe(name)["name"] == name

    imported = set(sys.modules)
    with pytest.raises(UnknownVerifierError):
        registry.readiness_manifest(("not.a.builtin.verifier",), load_builtins=True)
    assert set(sys.modules) == imported


def test_readiness_manifest_selection_rejects_strings_duplicates_and_unknowns() -> None:
    operation_registry = FleetOperationRegistry({"tests.one": _operation("one")})
    verifier_registry = VerifierRegistry()

    with pytest.raises(FleetOperationRegistryError, match="iterable"):
        operation_registry.readiness_manifest("tests.one")
    with pytest.raises(FleetOperationRegistryError, match="unique"):
        operation_registry.readiness_manifest(("tests.one", "tests.one"))
    with pytest.raises(LookupError):
        operation_registry.readiness_manifest(("tests.missing",))
    with pytest.raises(ValueError, match="iterable"):
        verifier_registry.readiness_manifest("tests.one")
    with pytest.raises(ValueError, match="unique"):
        verifier_registry.readiness_manifest(("tests.one", "tests.one"))
    with pytest.raises(LookupError):
        verifier_registry.readiness_manifest(("tests.missing",))
