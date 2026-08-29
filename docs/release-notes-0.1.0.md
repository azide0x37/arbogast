# Arbogast 0.1.0 release notes

Arbogast 0.1.0 establishes the finite exact, certificate-first foundation. It is an alpha for
inspectable research computations and API feedback, not a claim that the larger cohomology,
deformation, or arithmetic roadmap is complete.

## Highlights

### A mathematical claim graph

Results can carry a theorem dependency graph rather than ending as unstructured logs. Imported,
computed, derived, assumed, and conjectural statements remain visibly distinct, and exporters
consume the same semantic object.

### Search and proof are separate programs

Discovery receipts record how candidates were found. Verification certificates contain compact
finite witnesses. The bundled `prove_without_search` example demonstrates that its verifier has
no access to the discovery algorithm.

### A finite exact core

The release covers canonical finite objects, exact linear algebra, finite groups and
representations, low-degree group cohomology, and finite Hurwitz combinatorics. Public results
retain explicit maps, representatives, and certificate material. Sparse rank, row-space,
nullspace, determinant, and multiplication paths operate on sparse rows without first converting
the input matrix to a dense matrix. Optional narrow adapters expose FLINT matrix rank/determinant
and GAP permutation-group order as typed discovery receipts; they do not silently promote an
external result into verified theorem evidence.

### Agent-native inspection

The CLI can describe mathematical operation contracts, filter claim graphs, report proof gaps,
and expose supported routes. Lean-facing exports classify obligations and emit declarations; they
do not run Lean or imply that generated axioms are already formal proofs. Obligation contexts,
claim hypotheses, and discharge metadata survive the projection; axioms are conditional on every
explicitly rendered hypothesis and are omitted when a condition has no Lean rendering.

`ProofGap` is a canonical, claim-bound formalization frontier: its claim ID must match the owning
`Claim`, and it changes the claim digest without changing mathematical status. The `proof-gap`
CLI accepts only strict claim-graph, claim, or proof-gap schemas and rejects ad-hoc objects that
merely contain an `obligations` field.

The Python agent surface adds generated module manifests and bounded, strict `AgentContext`
packets containing complete selected contracts, regression hazards, implemented routes,
unimplemented frontier edges, task acceptance surfaces, and a content-addressed code dependency
DAG. The code DAG declares operation → implementation module/backend edges and module → module
dependencies; it is separate from the theorem and capability graphs and is never guessed from
runtime imports.
Explicit context records fail closed when `max_chars` cannot hold them intact.

### Campaigns with durable research state

The product hierarchy is `Claim ← Task ← Campaign`. A deterministic local engine records
canonical plans, planned task specs, start and observation events, first-class attempt state,
per-metric candidates, resource counters, result and typed-checkpoint references, terminal
outcomes, embedded closure certificates, and claim bindings in an authoritative ledger. Declared
capabilities and a value policy guide planning. It stores **mathematical outcome** separately from
**operational state**. `FOUND`, `PROVED_IMPOSSIBLE`, `SEARCH_EXHAUSTED`, `BUDGET_EXHAUSTED`,
`PREEMPTED`, `FAILED`, and `UNKNOWN` remain distinct classifications with different mathematical
meanings.

Provenance is available to later planning as structured input, so bounded negatives and failures
can sharpen the next algorithm. `Campaign` owns its canonical `ClaimGraph`; accepting a verified
closing observation automatically adds its computed claim envelope and ledger binding. The CLI's
claim export emits that directly replayable graph. Candidate records separately name a
canonicalizer, target-local or global equivalence scope, evidence level, and quality metric;
best-known ordering never compares unlike metrics.

`WorkerPoolExecutor` provides declared worker/resource matching and typed cooperative single- or
multi-shard checkpoint replay. The basic `LocalExecutor` cannot replay scheduler custody, so a
checkpoint successor is a `SUSPEND` advisory. Snapshot reload marks orphaned `RUNNING` attempts
operationally `UNKNOWN` without inventing an observation. These contracts do not provide
arbitrary process or host crash recovery. `run --fleet auto` supplies a conservative local pool
and an audited registry containing only `fleet.echo.v1`, which returns `UNKNOWN`; it never loads a
callable named by campaign JSON. Remote execution protocols remain extension points, and 0.1.0
does not bundle SSH deployment, Slurm orchestration, cloud provisioning, or remote license
automation.

### Honest optional backends

GAP, FLINT, PARI/GP, SageMath, and Magma are optional external capabilities. They are not bundled
or silently substituted, and discovery provenance remains separate from the verifier's trusted
base.

## Flagship exact M23 certificate

The M23 example ships a versioned finite witness dataset for the inner passport
\((2A,3A,6A,2A)\) and a separate standard-library verifier. The verifier exhausts 7,114
product-one inner orbits, proves that exactly 1,428 generate the pinned M23 while 5,686 are
intransitive, and checks that the six standard pure-braid generators act transitively on the
generating class. It validates 8,568 serialized forward braid transitions and their conjugators;
bijectivity supplies the inverse moves without duplicating them in the fixture.

The straight-real certificate deliberately distinguishes 70 inner-fixed generating classes from
the 20 stricter literal \(c=1\) classes. Those 20 exhaust only the generating inner Nielsen class.
The verifier also records 212 strict \(c=1\) representatives in the nongenerating complement, so
an unqualified no-hidden-\(c=1\) claim is rejected by the evidence itself.

GAP is used only to regenerate the discovery fixture. Fresh verification does not invoke GAP or
repeat the search, and the resulting six claim nodes are `COMPUTED` and `CERTIFIED`. The
manifest binds the actual public `arbogast.hurwitz.m23_exact` verifier source by SHA-256 and byte
length, as well as the witness data and compatibility entrypoint. The certificate does not
construct equations for a Hurwitz curve, identify a field of definition, compute a component
genus, or establish literature novelty.

## Compatibility

- Python 3.11, 3.12, 3.13, and 3.14 are supported.
- Certificate and canonical encoding schemas are versioned.
- The public API is typed, but as a 0.1 alpha it may receive incompatible refinements before
  1.0. Such changes will be documented in the changelog.
- No open-source license has been selected for 0.1.0; publication is source-visible and does not
  itself grant reuse rights beyond applicable law.

## Verification

The release gate runs Ruff lint and formatting checks, strict mypy, the complete test suite,
wheel and source builds, and every example under all four supported Python versions.
