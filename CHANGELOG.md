# Changelog

All notable changes to Arbogast are documented here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); because the public API is still
0.x, incompatible refinements may occur in minor releases and will be called out explicitly.

## [Unreleased]

## [0.3.0] - 2026-08-30

### Added

- A bounded exact deformation layer over prime fields with pinned finite Artin rings, ring maps,
  small extensions, three-term deformation complexes, and explicit deformation presentations.
- Certified gauge, tangent, and obstruction spaces; explicit framing; finite equivariant actions,
  invariant deformations, and supplied-projector decompositions.
- Finite lift outcomes that distinguish checked affine families, literal obstructions, and typed
  unknown results, together with separate uniqueness and rigidity computations.
- Certified fixed lifts from explicit endomorphisms and replayable contraction witnesses.
- Portable deformation examples covering exact spaces, framing and equivariance, solved and
  obstructed lifts, unique and non-unique branches, rigidity, fixed lifts, and claim graphs.

### Boundaries

- The deformation input is an explicit finite presentation. Arbogast does not infer a deformation
  complex, automorphism action, or obstruction theory from a general geometric object.
- A computed obstruction space is the obstruction space of the supplied complex; it is not an
  assertion that every geometric obstruction is represented without an additional comparison
  theorem.
- Fixed-lift certification requires a checked finite contraction witness. Convergence observed by
  iteration, numerical recognition, formal schemes, complete local rings, and general
  characteristic-zero or p-adic deformation theory remain outside this release.
- Deformation operations remain non-shardable because the supported kernels, quotients, and lift
  systems are globally coupled finite computations.

## [0.2.0] - 2026-08-29

### Added

- Canonical pinned number fields, exact field elements and embeddings, finite and infinite
  places, finite group maps and extensions, finite Galois quotients, and Galois modules.
- Exact real-root isolation and nested higher-degree complex-root certificates, with disjoint
  rectangles and signature exhaustion required before archimedean place coverage is complete.
- First-class certified restriction, inflation, and corestriction maps through degrees 0--2,
  together with transgression and an independently replayed five-term
  inflation--restriction sequence. The 0.1 `restrict` and `inflate` wrappers retain their
  signatures and return values.
- Finite (S\)-Kummer spaces for (p=2), genuine local \(H^1(K_v,\mu_2)\), separately named
  finite decomposition-quotient cohomology, canonical localization maps, and explicit
  completeness witnesses.
- Local conditions, candidate and complete Selmer kernels, Cartier duals, certified perfect
  local pairings, orthogonal dual local conditions, and dual-Selmer computations.
- Exact cocycle aiming with checked affine solution families or literal left-nullspace
  obstructions; finite nonabelian \(H^1\) and twist-class enumeration as pointed sets; and
  elementary Kummer/local-condition descent with `Realized`, `Obstructed`, and `Unknown`
  outcomes.
- A narrow operation-specific PARI/GP adapter for pinned versions
  `>=2.15.5,<2.18.0`, using fresh constrained processes, framed deterministic requests,
  content-addressed discovery receipts, algebraic capability probes, and no generic evaluator.
- Independently versioned Galois, Kummer, map, local-cohomology, Selmer, dual-Selmer, twist,
  and descent receipts nested inside the existing central verification-certificate boundary.
- Runnable arithmetic journeys for inflation--restriction, \(\mathbf Q(\{2,\infty\},2)\), a
  pinned quadratic field, both cocycle-aiming branches, finite nonabelian twists, and a bounded
  local/global campaign.
- Immutable 0.1.0 schema, certificate, release-note, and published-asset compatibility fixtures,
  plus archive safety checks and fresh wheel/sdist installation qualification with and without
  GP.

### Proof and compatibility boundaries

- Mathematical assumptions, verifier trust, and completeness are recorded independently. Any
  unresolved assumption makes a claim conditional; PARI-certified unconditional results remain
  non-portable unless a Python verifier also proves the arithmetic completeness facts.
- A candidate kernel is never promoted to `SelmerGroup` until the global space, local spaces,
  local conditions, and complete relevant place set have all been certified.
- `local_h1` is continuous local \(\mu_2\)-cohomology and is never silently identified with
  finite \(H^1(D_v,M)\). Automatic local arithmetic for \(p>2\) returns typed `Unsupported`.
- Nonabelian twist enumeration does not construct twisted models. Failed search, timeout, and
  local solubility alone do not become global descent conclusions.
- Every 0.1 public schema and representative certificate ID remains replayable unchanged; the
  0.1.0 release assets remain immutable inputs rather than rebuilt 0.2 artifacts.
- Composite \(n\), general continuous Galois cohomology, Poitou--Tate construction,
  abelian-variety Selmer groups, curve descent, automatic twisted models, stable reduction, and
  numerical recognition remain outside the implemented boundary.

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

[Unreleased]: https://github.com/azide0x37/arbogast/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/azide0x37/arbogast/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/azide0x37/arbogast/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/azide0x37/arbogast/releases/tag/v0.1.0
