from __future__ import annotations

import json
import subprocess
import sys

from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    CapabilityGraph,
    compact_context,
    describe_operation,
    module_manifest,
    operation_descriptions,
)
from arbogast.bootstrap import (
    READINESS_VERIFIER,
    DispatchReadinessReceipt,
    EnvironmentSnapshot,
    ReadinessObligation,
    ReadinessProfile,
    ReadinessReceipt,
    RuntimeBinding,
    certify_campaign_readiness,
)
from arbogast.formats import (
    DISPATCH_READINESS_RECEIPT_SCHEMA,
    ENVIRONMENT_READINESS_RECEIPT_SCHEMA,
    ENVIRONMENT_SNAPSHOT_SCHEMA,
    READINESS_OBLIGATION_SCHEMA,
    READINESS_PROFILE_SCHEMA,
    RUNTIME_BINDING_SCHEMA,
    schema_document,
    schema_ids,
)
from arbogast.specs import default_operations


def test_bootstrap_certifier_has_one_truthful_live_operation_contract() -> None:
    spec = default_operations.describe("bootstrap.certify_campaign_readiness")

    assert default_operations.function(spec.name) is certify_campaign_readiness
    assert spec.python_qualified_name == ("arbogast.bootstrap.readiness.certify_campaign_readiness")
    assert spec.input_types == ("EnvironmentSnapshot", "ReadinessProfile")
    assert spec.output_type == (
        "CertifiedReady | CertifiedBlocked | Partial | Unknown | Unsupported"
    )
    assert spec.exact
    assert "non-mathematical" in spec.mathematical_domain
    assert any("never establishes a mathematical conclusion" in item for item in spec.ensures)

    description = describe_operation(spec.name)
    assert description.implemented
    assert description.inputs == spec.input_types
    assert description.outputs == (spec.output_type,)


def test_bootstrap_agent_manifest_hazards_and_code_dependencies_are_declared() -> None:
    manifest = module_manifest("arbogast.bootstrap")
    assert manifest.operations == ("bootstrap.certify_campaign_readiness",)
    assert {
        "EnvironmentSnapshot",
        "DispatchReadinessReceipt",
        "ReadinessProfile",
        "ReadinessReceipt",
        "RuntimeBinding",
        "CertifiedReady",
        "CertifiedBlocked",
        "Partial",
        "Unknown",
        "Unsupported",
    } <= set(manifest.primary_types)
    assert any("ENVIRONMENTAL" in invariant for invariant in manifest.invariants)

    declaration = DEFAULT_CODE_DEPENDENCIES.get("bootstrap.certify_campaign_readiness")
    assert declaration.implementation_module == "arbogast.bootstrap"
    assert declaration.module_dependencies == (
        "arbogast.cert",
        "arbogast.claims",
        "arbogast.formats",
    )
    assert declaration.required_backends == ("python",)

    context = compact_context(("bootstrap.certify_campaign_readiness",))
    assert context.undeclared_code_dependencies == ()
    assert {
        "bootstrap.certificate-vs-live-dispatch",
        "bootstrap.readiness-vs-mathematical-closure",
    } <= {hazard.id for hazard in context.hazards}
    for hazard in context.hazards:
        if hazard.id.startswith("bootstrap."):
            assert "DispatchReadinessReceipt" in hazard.triggered_by

    graph = CapabilityGraph.from_operations(operation_descriptions())
    assert any(
        edge.operation == "bootstrap.certify_campaign_readiness"
        and edge.required_inputs == ("EnvironmentSnapshot", "ReadinessProfile")
        and edge.target == "CertifiedReady"
        for edge in graph.edges
    )


def test_bootstrap_canonical_schemas_are_in_the_public_catalog() -> None:
    expected = {
        RUNTIME_BINDING_SCHEMA: (RuntimeBinding.schema_version, "runtime_id"),
        DISPATCH_READINESS_RECEIPT_SCHEMA: (
            DispatchReadinessReceipt.schema_version,
            "receipt_id",
        ),
        ENVIRONMENT_SNAPSHOT_SCHEMA: (
            EnvironmentSnapshot.schema_version,
            "environment_id",
        ),
        READINESS_PROFILE_SCHEMA: (ReadinessProfile.schema_version, "profile_id"),
        READINESS_OBLIGATION_SCHEMA: (
            ReadinessObligation.schema_version,
            "evidence",
        ),
        ENVIRONMENT_READINESS_RECEIPT_SCHEMA: (
            ReadinessReceipt.schema_version,
            "receipt_id",
        ),
    }
    assert set(expected) <= set(schema_ids())
    for identifier, (model_identifier, identity_field) in expected.items():
        document = schema_document(identifier)
        assert model_identifier == identifier
        assert document["$id"] == identifier
        required = document["required"]
        assert isinstance(required, list)
        assert "schema_version" in required
        assert identity_field in required


def test_readiness_verifier_is_allowlisted_and_discoverable_in_a_fresh_process() -> None:
    code = """
import json
import sys

assert "arbogast.bootstrap" not in sys.modules
from arbogast.cert import VerifierRegistry, default_verifiers
assert "arbogast.bootstrap" not in sys.modules
description = default_verifiers.describe("arbogast.bootstrap.readiness.v1")
assert description["callable"] == (
    "arbogast.bootstrap.readiness.verify_readiness_certificate"
)
private = VerifierRegistry()
manifest = private.readiness_manifest(
    ("arbogast.bootstrap.readiness.v1",),
    load_builtins=True,
)
assert manifest["verifiers"][0]["certifiable"] is True
print(json.dumps({"description": description, "manifest": manifest}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    description = payload["description"]
    assert description["name"] == READINESS_VERIFIER
    assert description["certificate_type"].endswith(".VerificationCertificate")
    assert payload["manifest"]["verifiers"][0]["name"] == READINESS_VERIFIER
