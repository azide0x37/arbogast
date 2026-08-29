"""Fresh-process replay of the public exact M23 dataset and claim projection."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from workflow import OUTPUT_SCHEMA, build_public_workflow, require_mapping

from arbogast.cert import VerificationCertificate, canonicalize
from arbogast.claims import ClaimGraph, ClaimKind, EpistemicStatus
from arbogast.hurwitz import (
    M23ExactCertificate,
    M23ExactVerificationError,
    m23_verifier_registry,
)
from arbogast.hurwitz.m23_exact import load_strict_json
from arbogast.sources import SourceRegistry

_PROJECTION_FIELDS = {
    "schema_version",
    "source_manifest",
    "source_manifest_sha256",
    "source_dataset",
    "source_dataset_sha256",
    "source_context",
    "fixture_verification",
    "hurwitz_dataset_certificate",
    "claim_graph_digest",
    "claim_graph",
    "certificates",
    "source_registry_digest",
    "source_registry",
    "provenance_record",
}


def _decode_certificates(value: object) -> dict[str, VerificationCertificate]:
    raw_certificates = require_mapping(value, "certificates")
    certificates: dict[str, VerificationCertificate] = {}
    for certificate_id, raw_certificate in raw_certificates.items():
        certificate = VerificationCertificate.from_dict(
            require_mapping(raw_certificate, f"certificates.{certificate_id}")
        )
        if certificate.certificate_id != certificate_id:
            raise ValueError("certificate map key does not match its content address")
        certificates[certificate_id] = certificate
    return certificates


def validate_projection(document: Mapping[str, object]) -> tuple[ClaimGraph, int]:
    """Rebuild the public workflow, then bind every transported semantic object to it."""

    if set(document) != _PROJECTION_FIELDS:
        raise ValueError("M23 claim projection has noncanonical top-level fields")
    if document.get("schema_version") != OUTPUT_SCHEMA:
        raise ValueError("unsupported M23 claim-projection schema")
    expected = build_public_workflow()
    report = expected.dataset.verification
    if document.get("source_manifest") != "expected/manifest.json":
        raise ValueError("claim projection names a different fixture manifest")
    if document.get("source_dataset") != "expected/dataset.json":
        raise ValueError("claim projection names a different fixture dataset")
    if document.get("source_context") != "expected/sources.json":
        raise ValueError("claim projection names a different source sidecar")
    if document.get("source_manifest_sha256") != report.manifest_sha256:
        raise ValueError("claim projection is bound to a different fixture manifest")
    if document.get("source_dataset_sha256") != report.dataset_sha256:
        raise ValueError("claim projection is bound to a different fixture dataset")
    if canonicalize(document.get("fixture_verification")) != canonicalize(report.to_dict()):
        raise ValueError("serialized fixture-verification summary does not match replay")

    specialized = M23ExactCertificate.from_dict(
        require_mapping(document.get("hurwitz_dataset_certificate"), "dataset certificate")
    )
    if specialized != expected.dataset.certificate or not specialized.verify(expected.dataset):
        raise ValueError("dataset certificate is not bound to the full finite replay")

    certificates = _decode_certificates(document.get("certificates"))
    expected_certificates = expected.certificates
    if {key: value.to_dict() for key, value in certificates.items()} != {
        key: value.to_dict() for key, value in expected_certificates.items()
    }:
        raise ValueError("certificate inventory does not match the verified fixture")

    graph = ClaimGraph.from_dict(require_mapping(document.get("claim_graph"), "claim_graph"))
    if document.get("claim_graph_digest") != graph.digest:
        raise ValueError("claim-graph digest mismatch")
    if graph.digest != expected.graph.digest:
        raise ValueError("claim graph does not state exactly the verified M23 conclusions")
    for claim in graph:
        if claim.kind is not ClaimKind.COMPUTED:
            raise ValueError(f"claim {claim.id} is not explicitly COMPUTED")
        if claim.status is not EpistemicStatus.CERTIFIED:
            raise ValueError(f"claim {claim.id} is not explicitly CERTIFIED")

    sources = SourceRegistry.from_dict(
        require_mapping(document.get("source_registry"), "source registry")
    )
    if document.get("source_registry_digest") != sources.digest:
        raise ValueError("source-registry digest mismatch")
    if sources.to_dict() != expected.sources.to_dict():
        raise ValueError("source/provenance registry does not match the public workflow")
    provenance_id = document.get("provenance_record")
    if not isinstance(provenance_id, str):
        raise ValueError("projection provenance record must be a string")
    sources.provenance(provenance_id)
    for claim in graph:
        for source_id in claim.source:
            sources.reference(source_id)

    graph_report = graph.verify(
        certificates,
        verifier_registry=m23_verifier_registry(expected.dataset),
        source_registry=sources,
    )
    if not graph_report.verified:
        raise ValueError(graph_report.error or "claim graph failed certificate replay")
    return graph, len(certificates)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projection", type=Path, help="claim projection emitted by compute.py")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        document = require_mapping(
            load_strict_json(args.projection.read_bytes(), "projection"), "projection"
        )
        graph, certificate_count = validate_projection(document)
        report = require_mapping(document["fixture_verification"], "fixture_verification")
        print(
            "fixture verification: valid through arbogast.hurwitz "
            f"({report['component_cardinality']} generating, "
            f"{report['nongenerating_inner_orbits']} nongenerating)"
        )
        print(
            "real census: "
            f"{report['c1_fixed']} generating c=1; "
            f"{report['nongenerating_c1']} nongenerating c=1 guardrail; "
            f"{report['inner_real_fixed']} inner-real fixed"
        )
        print(f"claim graph: {len(graph)} computed, {certificate_count} certified")
        return 0
    except (OSError, ValueError, KeyError, M23ExactVerificationError) as error:
        print(f"M23 verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
