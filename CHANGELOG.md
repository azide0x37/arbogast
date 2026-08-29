# Changelog

All notable changes to Arbogast are documented here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); because the public API is still
0.x, incompatible refinements may occur in minor releases and will be called out explicitly.

## [Unreleased]

No user-visible changes have been recorded since 0.1.0.

## [0.1.0] - 2026-08-28

### Added

- Immutable, canonical mathematical objects and deterministic encodings.
- Exact finite-field linear algebra with explicit verification witnesses and sparse elimination
  paths that do not first densify the input matrix.
- Finite groups, permutation representations, and representation utilities.
- Explicit low-degree finite group cohomology results through \(H^2\).
- Finite Nielsen classes, braid actions, real structures, and component invariants.
- Discovery receipts, compact verification certificates, and content addressing.
- Claim graphs with assumed, imported, computed, derived, and conjectured boundaries.
- Agent, JSON, paper-oriented, and Lean-obligation export surfaces, including conditional
  hypothesis/context preservation and discharge metadata.
- Deterministic task planning, sharding, artifact storage, and reduction primitives.
- Generated per-module agent manifests, bounded coherent contexts, regression hazards, capability
  frontiers, acceptance-bearing task packets, and a strict declared code-dependency DAG distinct
  from theorem and capability graphs.
- Research campaigns with a campaign-owned canonical `ClaimGraph`, persisted plans, first-class
  attempt histories, observation-bound candidates, per-metric best-known selection, explicit
  canonicalizers/equivalence scopes, typed checkpoints, resource accounting,
  declared-capability filtering, value policy, and authoritative local ledger sinks.
- Honest capability probes for GAP, FLINT, PARI/GP, SageMath, and Magma, plus narrow typed
  discovery adapters for FLINT matrix rank/determinant and GAP permutation-group order.
- CLI inspection commands for operations, certificates, claims, strict claim-bound proof gaps,
  routes, and campaign control, including the audited `run --fleet auto` local mode.
- Runnable cohomology, exact M23 Hurwitz, campaign, and search/verifier-separation examples.
- Tested support for Python 3.11 through 3.14.

### Boundaries

- External computer algebra systems are detected but not bundled.
- The M23 example independently verifies a complete 1,428-class generating inner Nielsen class,
  its pure-braid transitivity, and its 70-inner-fixed/20-strict-\(c=1\) real census from checked-in
  finite witnesses. The 20 count is scoped to the generating class; 212 strict \(c=1\)
  representatives in the nongenerating complement are retained as a guardrail. Its manifest
  binds the actual public verifier source by SHA-256 and byte length.
- Lean export emits structured obligations and declarations, not a blanket formal-proof claim.
- Numerical recognition, general Galois cohomology, general deformation theory, and automatic
  theorem proving are outside the 0.1.0 implementation boundary.
- Campaign checkpoints are cooperative typed custody, not arbitrary process or host crash
  recovery. `WorkerPoolExecutor` can replay persisted typed manifests; `LocalExecutor` checkpoint
  successors suspend. SSH, Slurm, cloud provisioning, and remote-license automation are extension
  points rather than bundled 0.1.0 features.

[Unreleased]: https://github.com/azide0x37/arbogast/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/azide0x37/arbogast/releases/tag/v0.1.0
