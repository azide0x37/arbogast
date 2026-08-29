"""Replay the public exact M23 workflow and emit its certified ClaimGraph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflow import (
    DATASET,
    MANIFEST,
    OUTPUT_SCHEMA,
    PROVENANCE_ID,
    bind_projection_provenance,
    load_source_registry,
)

from arbogast.cert import canonicalize
from arbogast.hurwitz import (
    load_m23_exact_dataset,
    m23_certificates_for,
    m23_claim_graph_for,
    m23_verifier_registry,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("m23-claims.json"),
        help="path for the certified claim projection (default: m23-claims.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_m23_exact_dataset(MANIFEST, DATASET)
    graph = m23_claim_graph_for(dataset, provenance_record=PROVENANCE_ID)
    certificates = m23_certificates_for(dataset)
    graph_report = graph.verify(
        certificates,
        verifier_registry=m23_verifier_registry(dataset),
    )
    if not graph_report.verified:
        raise ValueError(graph_report.error or "public M23 ClaimGraph verification failed")
    sources = load_source_registry()
    bind_projection_provenance(sources, dataset, graph)
    report = dataset.verification
    output = {
        "schema_version": OUTPUT_SCHEMA,
        "source_manifest": "expected/manifest.json",
        "source_manifest_sha256": report.manifest_sha256,
        "source_dataset": "expected/dataset.json",
        "source_dataset_sha256": report.dataset_sha256,
        "source_context": "expected/sources.json",
        "fixture_verification": report.to_dict(),
        "hurwitz_dataset_certificate": dataset.certificate.to_dict(),
        "claim_graph_digest": graph.digest,
        "claim_graph": graph.to_dict(),
        "certificates": {
            certificate_id: certificate.to_dict()
            for certificate_id, certificate in sorted(certificates.items())
        },
        "source_registry_digest": sources.digest,
        "source_registry": sources.to_dict(),
        "provenance_record": PROVENANCE_ID,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(canonicalize(output), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "fixture verified through arbogast.hurwitz: "
        f"{report.component_cardinality} generating inner classes, "
        f"{report.c1_fixed} c=1, {report.inner_real_fixed} inner-real fixed"
    )
    print(
        "completeness: "
        f"{report.all_inner_orbits} product-one inner orbits = "
        f"{report.component_cardinality} generating + "
        f"{report.nongenerating_inner_orbits} intransitive"
    )
    print(f"claim graph: {len(graph)} computed, {len(certificates)} certified")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
