<p align="center">
  <img src="assets/arbogast-wordmark.png" alt="Arbogast" width="720">
</p>

<p align="center">
  <strong>Certificate-first computational mathematics for finite cohomology,
  deformation, validated numerics, symmetry, and Hurwitz arithmetic.</strong>
</p>

> “What does this?” she said at last. She’d meant it as a rhetorical question. Of course there
> was no answer. No force known to humanity could do what had just been done.

<p align="center">
  <a href="https://github.com/azide0x37/arbogast/actions/workflows/ci.yml"><img
    src="https://github.com/azide0x37/arbogast/actions/workflows/ci.yml/badge.svg"
    alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img
    src="https://img.shields.io/badge/Python-3.11--3.14-3776AB.svg"
    alt="Python 3.11 through 3.14"></a>
</p>

Arbogast is for computations that are finite enough to check, large enough to distribute,
and delicate enough that “the script returned this” is not an acceptable proof boundary.
It keeps exact computations, validated numerical evidence, imported facts, deductions, and
conjectures separate, then joins them in a machine-readable **claim graph**.

```text
mathematical input
       │
       ▼
decompose → aim → obstruct → frame → certify
                                         │
                                         ▼
                                    ClaimGraph
                                  ╱      │      ╲
                         cheap verifier paper   agent / Lean export
```

Discovery may be expensive. Verification should not be.

## The motivating workflow: Antieau, Klüners, and Malle

The supplied Antieau interview describes a Klüners--Malle research workflow around explicit
polynomials and the database built from that work. Arbogast uses that account as a motivating
case study rather than attributing a new polynomial request to Antieau: begin with a precisely
scoped arithmetic target, import only the prior-work claims actually supported by the
[Klüners--Malle database](https://galoisdb.math.uni-paderborn.de/), and turn construction,
bounded search, and exact verification into auditable tasks. A modern campaign needs more than a
database lookup or a long-running process.

Arbogast models the work in three durable layers:

```text
Claim  ←  Task  ←  Campaign
  │         │          │
  │         │          ├── objective, budget, capability requirements, policy
  │         ├───────────── canonical inputs, operation contract, checkpoints, receipts
  └─────────────────────── statement, derivation, evidence, source, theorem status
```

The campaign first imports the exact Klüners--Malle assertion it is allowed to use, then
decomposes the target into construction, search, and exact-verification tasks. A candidate
polynomial is not the claim. A worker exit is not the claim. Even a correct finite certificate is
not the whole claim until its hypotheses, derivation, and imported dependencies are bound in the
claim graph.

This matters most when no polynomial is found. The ledger records **mathematical outcome**
separately from **operational state**; an interrupted worker cannot become a negative theorem.
Compact campaign reports use the following explicit classifications. Exact outcomes also carry an
`outcome_scope`: `TASK_LOCAL` records what one planned branch established, while
`TARGET_GLOBAL` asserts that the target's full success or closure criterion was checked. Only a
replay-verified `TARGET_GLOBAL` exact outcome closes the target, stops alternate strategies, or
creates a computed campaign claim.

| State | Mathematical meaning |
| --- | --- |
| `FOUND` | A replayable certificate verifies a witness; only `TARGET_GLOBAL` says it meets the complete target criterion. |
| `PROVED_IMPOSSIBLE` | A certificate proves nonexistence in its explicit task-local or target-global scope. |
| `SEARCH_EXHAUSTED` | A declared finite search domain was completely checked; task-local exhaustion leaves other strategies open. |
| `BUDGET_EXHAUSTED` | Work stopped at its recorded resource limit; the unexplored region remains open. |
| `PREEMPTED` | Execution was interrupted; resume requires a typed checkpoint and an executor that owns its custody. |
| `FAILED` | Software, input, or environment failed; this has no negative theorem content. |
| `UNKNOWN` | Available evidence does not justify a stronger classification. |

The authoritative research state is the campaign ledger: targets, canonical plans, planned task
specs, task and attempt events, per-metric candidates, resource use, result and typed-checkpoint
references, outcomes and their canonical scopes, embedded outcome certificates, and claim
bindings. Scope is part of the certificate subject and the observation content identity, so a
task-local result cannot be relabeled as target-global during replay. The surrounding `Campaign`
owns the canonical `ClaimGraph`; accepting a verified target-global closing observation creates
and binds its computed claim. Task capability requirements and the campaign's declared local
capability set feed planning; 0.1 reports incompatible tasks through status and explanation
blockers without inventing a failure event for work that never started. Later planners can
consume recorded provenance as algorithm input, so a bounded negative result can rule out a
repeated strategy or sharpen the next task rather than disappearing into logs.

Successful operations may return the strict
`arbogast.campaign.execution-telemetry.v1` envelope for operation-reported progress, resource, and
spend counters. These are supplied measurements, not values inferred from requested resources,
worker count, or elapsed timestamps. An absent envelope remains absent; an explicit zero remains
zero in the observation, attempt ledger, status totals, and replay.

Arbogast 0.1.0 includes deterministic local executors and extension protocols. Cooperative
operations can yield typed single- or multi-shard checkpoint manifests to
`WorkerPoolExecutor`; the basic `LocalExecutor` deliberately cannot replay checkpoint custody, so
its checkpoint successor is reported as `SUSPEND`, not `RESUME`. This is not arbitrary process
or host crash recovery. The release does not claim built-in SSH deployment, Slurm orchestration,
cloud provisioning, remote license handling, or workstation reconstruction. Reproducibility
means another machine can recover the same canonical claim and verify its evidence; it need not
recreate the original workstation or repeat an expensive discovery schedule. See
[Research campaigns](docs/research-campaigns.md).

## Certified arithmetic in 0.2

Arbogast 0.2 is an additive, bounded arithmetic slice over the immutable 0.1 finite-exact core.
The abstract machinery remains prime-field generic for supplied finite presentations. Automatic
number-field arithmetic is intentionally focused on \(p=2\): finite \(S\)-Kummer spaces, genuine
local \(H^1(K_v,\mu _2)\), Hilbert pairings, localization maps, 2-Selmer kernels, cocycle aiming,
finite nonabelian twist classes, and elementary Kummer/local-condition descent.

The arithmetic proof model has three independent axes:

| Axis | Boundary |
| --- | --- |
| assumptions | An unresolved label such as `GRH` makes the semantic claim `CONDITIONAL`. |
| verifier trust | Portable Python replay and pinned PARI replay are distinct requirements. |
| completeness | A `CANDIDATE` kernel is never named or promoted as a complete `SelmerGroup`. |

A successful pinned PARI certification may therefore be unconditional while remaining
non-portable. PARI discovery state never appears in a canonical mathematical object: field
identities bind defining polynomials and bases; finite places bind ideal HNF data; infinite
places bind exact embeddings and isolating data. Session handles, printed \(p\)-adics, and
implicit `polredbest` identifications do not cross the boundary.

Substantial arithmetic results provide `verify()`, `certificate`, `claim()`, and `claim_graph()`.
Their versioned proving receipt is nested inside the existing central
`VerificationCertificate`; 0.1 claim and certificate schemas remain valid and replayable.
Read [Certified arithmetic](docs/certified-arithmetic.md) for the complete theorem and trust
boundary.

## Certified deformation in 0.3

Arbogast 0.3 adds a bounded finite-exact deformation slice. It starts from an
explicit three-term complex over a prime field and a pinned finite presentation; Arbogast then
computes gauge, tangent, and obstruction spaces by exact linear algebra. Framing and equivariance
are supplied as explicit maps, so a result never infers an automorphism action or a geometric
deformation problem from an opaque Python object.

Finite lifting problems are similarly literal. A small extension, base lift, linearized lift map,
and target are part of the input. The result is a checked affine lift family, a checked
left-nullspace obstruction, or a typed refusal. Uniqueness is a separate computation. A fixed
lift is certified only from an explicit endomorphism and a replayed contraction witness; merely
iterating to an apparent fixed point is not proof.

Every substantial result within the portable receipt limits retains the established `verify()`,
`certificate`, `claim()`, and `claim_graph()` boundary. The 0.3 operations are intentionally
non-shardable: the implemented problems are small globally coupled finite linear systems, and
splitting them would not create independently meaningful proof tasks. Read
[Certified deformation](docs/deformation.md) for the exact limits, supported inputs, and
deferrals.

## Certified numeric-to-exact bridge in 0.4

Arbogast 0.4 adds exact dyadics and closed real and complex balls, bounded polynomial systems,
witnessed continuation, exact discrete branch-cycle recovery, exact Nielsen-vertex binding,
bounded algebraic
recognition and exactification, projection-degree witnesses, and weighted braid planning over a
supplied finite action.

The automatic cover slice is deliberately small: one monic quadratic in one sheet variable and
one parameter, with a completely replayed discriminant divisor and projective infinity parity.
Automatic recognition is limited to real-centered balls, degree at most 2, and height at most 16;
larger serialized bounds produce `UnsupportedNumeric` rather than an unbounded search.

The proof levels remain separate. A replayed ball or continuation tube is certified numerical
evidence, not an exact algebraic value or an exact braid target. A recognition candidate becomes
exact only after `exactify` independently substitutes it into the pinned exact system. A count in
one supplied regular fiber is not called a generic degree unless a stronger exact generic witness
is present. Likewise, numerically real branch coordinates do not prove that a normalized exact
cover is defined over the reals. Raw trackings and a `NumericalCover` remain `NUMERICAL`; they
cross to an exact discrete `BranchCycleTuple` only after complete separated continuation replay,
and to an exact `NielsenVertex` only after a literal match in a computed-complete Nielsen class.
Incomplete or ambiguous paths cannot cross either boundary.

The public `braid_continue` boundary keeps local sheet loops separate from coefficient homotopy.
It passes through the identity word and supports one genuine nontrivial exact slice: an explicit
`QuadraticB2Homotopy` for the normalized (x^2-t(t-1)) cover and one (\sigma_0) generator or
inverse. Absent witnesses, unwitnessed unsupported covers, the older local-sheet witness, and
general words remain `NumericUnknown` or `UnsupportedNumeric`; a supplied witness bound to a
different cover, word, endpoint, or action is rejected as invalid input.

Numeric operations return typed unknown or unsupported outcomes when precision, witness data, or
scope is insufficient. The portable surface requires no external numerical backend and exposes no
generic evaluator. Read [Certified numeric-to-exact bridge](docs/numeric.md) for the complete
boundary and the three runnable journeys.

## Certified bounded p-adic arithmetic

The additive p-adic layer performs finite-exact arithmetic in pinned quotients
\(\mathcal O_K/\pi^N\), replays supplied semilinear Frobenius and finite inertia actions, and
certifies one deliberately narrow tame three-point reduction profile. `PAdicBall` remains a
finite-precision residue class, never a selected infinite p-adic number. An `InertiaFiltration`
is only a declared finite group-theoretic series satisfying its listed tame/wild quotient
identities: it records that neither arithmetic origin nor a valuation-derived complete lower
numbering is claimed.

Every operation returns a proof-bearing `Certified`, `Partial`, `Unknown`, or `Unsupported`
boundary. Good, semistable, and stable reduction remain distinct. A complete factorization of one
displayed mod-\(p\) polynomial is only a `LocalFactorizationFragment`, not a local cover model.
Lift enumeration is complete only in one pinned finite chart; the supported arithmetic lift action
uses a computed-complete trivial quotient and explicit identity transports on every exact model.
A fixed lift does not prove descent, and the positive rigid descent result is only an exact
coefficient vector in the pinned \(\mathbf F_p\) chart-model category—not a characteristic-zero,
number-field, or geometric cover.

The public four-point M23 dataset therefore returns `Unsupported` at the automatic reduction
boundary. Supplying an independently certified local factorization fragment returns `Partial`
with explicit obligations rather than a global model. All p-adic operations are non-shardable and
use exactly the portable verifier families `padic.finite-exact.v1` and
`padic.three-point-exact.v1`. Read [Certified bounded p-adic arithmetic](docs/padic.md) for the
complete supported slices and deferrals.

## What 0.1.0 is—and is not

Arbogast 0.1.0 is an alpha **finite exact core**. It provides canonical finite objects, exact
linear algebra and finite-group computations, explicit low-degree cohomology,
finite Nielsen and braid-action machinery, certificates, claim graphs, deterministic work
planning, and export surfaces. The pure-Python path is intentionally small and auditable.

The release does **not** claim a general computer algebra system, a general
Galois-cohomology engine, a deformation-theory solver, or an automatic theorem prover. It does
not promote
floating-point evidence to exact mathematics. Lean export produces structured finite proof
obligations; it does not mean that every exported claim is already a Lean theorem. External
systems such as GAP, FLINT, PARI/GP, SageMath, and Magma are optional capabilities: Arbogast
detects them and reports their absence rather than bundling or impersonating them.

The five verbs are a research workflow, not a claim that every future mathematical domain is
implemented in 0.1.0:

- **decompose** an object into exact, symmetry-adapted pieces;
- **aim** a witness at stated local, isotypic, or combinatorial constraints;
- **obstruct** an impossible aim with an explicit finite witness;
- **frame** choices so automorphisms and conventions cannot silently move the problem;
- **certify** the result in a compact, independently checkable form.

See [the theorem boundary](docs/theorem-boundaries.md) for the exact epistemic contract.

## Install

Arbogast 0.4.0 requires Python 3.11 or newer. Pin the exact GitHub source tag with
[uv](https://docs.astral.sh/uv/):

```bash
uv add "arbogast @ git+https://github.com/azide0x37/arbogast.git@v0.4.0"
```

For a contributor checkout:

```bash
git clone https://github.com/azide0x37/arbogast.git
cd arbogast
uv sync --extra dev
uv run arbogast version
```

No external algebra backend is required for the portable examples. If an operation can use an
external backend, install that system independently and inspect capability discovery before
depending on it. The 0.4.0 surface retains the narrow FLINT matrix and GAP permutation-group
discovery adapters, the closed operation-specific PARI arithmetic adapter, the portable
finite-exact deformation layer, and the backend-free validated numeric-to-exact bridge. The PARI
path keeps explicit portable-versus-pinned verification
requirements; see [Optional backends](docs/optional-backends.md),
[Certified arithmetic](docs/certified-arithmetic.md), and
[Certified deformation](docs/deformation.md), and
[Certified numeric-to-exact bridge](docs/numeric.md).

## Thirty-second tour

The smallest complete example computes \(H^1(C_5, M)\) over \(\mathbf F_{11}\), inspects
representatives, and verifies the quotient certificate:

```bash
uv run python examples/group_cohomology/cyclic_action_h1.py
```

The same example through the public API:

```python
from arbogast.cohom import h1
from arbogast.linalg import DenseMatrix, FiniteField
from arbogast.rep import CyclicGroup, Representation

group = CyclicGroup(5)
field = FiniteField(11)
generator_action = DenseMatrix(
    field,
    ((1, 0, 0), (0, 3, 0), (0, 0, 4)),
)
module = Representation.from_generators(group, field, (generator_action,))

weights = module.weight_spaces()
result = h1(group, module)

print(result.dimension)
for cocycle in result.representatives:
    print(cocycle)

result.verify()  # reconstructs and checks the finite certificate
claim = result.claim()  # records the computed assertion and evidence
claim.verify()
```

Here `result.dimension == 0`: because 5 is invertible modulo 11, positive-degree cohomology
vanishes. The runnable example also shows that \(Z^1\) and \(B^1\) both have dimension 2 and
checks the split weights 1, 3, and 4. Result objects carry mathematical data and provenance;
public computations do not return unexplained tuples of matrices and dimensions.

## Claim graphs are the centerpiece

A transcript tells you what a program printed. A claim graph tells you what mathematics was
asserted, why, from which inputs, and with what evidence.

Every claim answers five questions:

| Field | Question |
| --- | --- |
| `what` | What precise mathematical fact is asserted? |
| `why` | Which earlier claims does it use? |
| `how` | Was it imported, computed, or derived? |
| `evidence` | Which content-addressed certificate checks it? |
| `source` | Which source objects or literature records does it import? |

Claim kinds are data, not prose decoration: `ASSUMED`, `IMPORTED`, `COMPUTED`, `DERIVED`, and
`CONJECTURED` are never silently interchanged. A separate epistemic status records `EXACT`,
`CERTIFIED`, `CONDITIONAL`, `NUMERICAL`, `HEURISTIC`, or `UNKNOWN`. A computation can be exact
while a theorem derived from an imported hypothesis remains conditional; those are different
axes.

```bash
# List only theorem holes in a saved graph.
uv run arbogast claims claim-graph.json --kind conjectured

# Summarize the obligations between a claim and a machine proof.
uv run arbogast proof-gap claim-graph.json --claim claim.id
```

`proof-gap` accepts only canonical `arbogast.claim-graph/v1`, `arbogast.claim/v1`, or
`arbogast.proof-gap/v1` documents. A `ProofGap` is bound to the same claim ID and contributes to
that claim's canonical digest; it describes formalization work without changing mathematical
status. Ad-hoc JSON with an `obligations` field is rejected.

Read [Claims and certificates](docs/certificates-and-claims.md) for the schema and trust
boundary.

## CLI

The CLI is intentionally inspection- and verification-oriented:

```text
arbogast version [--json]
arbogast backends [--name NAME] [--json]
arbogast describe OPERATION [--json]
arbogast verify CERTIFICATE [--verifier NAME] [--json]
arbogast claims FILE [--status STATUS] [--kind KIND] [--json]
arbogast proof-gap FILE [--claim CLAIM_ID] [--json]
arbogast route --from TYPE --to TYPE [--include-unimplemented] [--json]
arbogast campaign init NAME FILE [--objective TEXT] [--success-criterion TEXT ...] [--json]
arbogast plan FILE [--limit N] [--json]
arbogast run FILE [--fleet {off,auto}] [--limit N] [--json]
arbogast status FILE [--json]
arbogast target FILE TARGET --explain [--json]
arbogast harvest FILE [--observation OBSERVATION_JSON] [--json]
arbogast export claims FILE [OUTPUT] [--json]
```

Examples:

```bash
uv run arbogast describe cohom.h1 --json
uv run arbogast route --from NielsenClass --to ClaimGraph
uv run arbogast verify certificate.json
```

`describe` exposes mathematical preconditions, guarantees, failure modes, exactness, shard
strategy, certificate type, and alternative required input bundles. `route` searches a capability
hypergraph: every operation step requires its complete conjunctive input bundle, while genuine
alternative unary inputs remain separate routes. It is not a promise that value-level
preconditions hold; missing transformations are reported as missing capabilities.

Campaign files serialize specifications, their campaign-owned `ClaimGraph`, and the authoritative
event ledger, never executable Python callables. With the default `--fleet off`, `run` fails
closed if the current runtime has no injected implementation for a named operation.
`--fleet auto` creates an audited local worker pool and registry. In 0.4.0 that registry contains
the non-closing `fleet.echo.v1` plumbing plus declared local-`H^1`, localization, Selmer assembly,
PARI replay, and portable Python certificate-replay tasks. Registry membership never turns a
scheduler outcome into mathematics or executes a callable named by JSON. The runnable campaign
example shows trusted local operation injection through the Python API. `harvest` accepts only a
strict `Observation` document, not arbitrary worker JSON. `export claims` emits the directly replayable
canonical `arbogast.claim-graph/v1` owned by the campaign. Lower-level closure-candidate receipts
remain an explicit Python audit surface; they are not the exported theorem graph.

## Python API

The public surface is organized by mathematical layer:

| Layer | Purpose |
| --- | --- |
| `arbogast.core` | Immutable canonical objects, encodings, artifacts, and hashes |
| `arbogast.linalg` | Exact dense and sparse linear algebra over supported finite fields |
| `arbogast.rep` | Finite groups, permutations, representations, invariants, and decompositions |
| `arbogast.cohom` | Cochain complexes and explicit \(H^0\), \(H^1\), \(H^2\) results |
| `arbogast.galois` | Pinned number fields, places, finite Galois quotients, Kummer spaces, local cohomology, and twist classes |
| `arbogast.arithmetic` | Local conditions, Selmer kernels and groups, duality, aiming, and elementary descent outcomes |
| `arbogast.deform` | Explicit finite deformation complexes, framed/equivariant spaces, finite lifts, rigidity, and certified fixed lifts |
| `arbogast.hurwitz` | Nielsen classes, braid orbits, real structures, and components |
| `arbogast.numeric` | Exact dyadics and balls, witnessed continuation, exactification, cover bindings, projection degree, and weighted braid plans |
| `arbogast.padic` | Finite-precision local arithmetic, supplied Frobenius/inertia actions, bounded three-point reduction, chart-local lifts, and rigid finite-field descent |
| `arbogast.claims` | Typed claims, theorem dependencies, and epistemic status |
| `arbogast.cert` | Discovery receipts and independent verification certificates |
| `arbogast.fleet` | Deterministic task specs, shards, artifact stores, and reduction |
| `arbogast.campaign` | Campaign-owned claim graphs, plans, tasks, attempts, candidates, observations, and policies |
| `arbogast.sinks` | Authoritative local campaign-ledger sinks and readback |
| `arbogast.backends` | Honest capability probes for optional external systems |
| `arbogast.agent` | Bounded operation contexts, module manifests, hazards, capability routes, and a declared code DAG |
| `arbogast.export` | Stable JSON, agent, paper, and Lean-facing representations |

For architecture and dependency direction, see [Architecture](docs/architecture.md).

## Runnable examples

### Exact group cohomology

[`examples/group_cohomology/cyclic_action_h1.py`](examples/group_cohomology/cyclic_action_h1.py)
is the sub-second hello world. It constructs a cyclic action over \(\mathbf F_{11}\), computes
\(H^1\), exposes explicit representatives and quotient data, and verifies the result.

### An exact M23 real-component certificate

[`examples/hurwitz/m23_real_component/`](examples/hurwitz/m23_real_component/) is the flagship
finite certificate. A checked-in witness dataset exhausts 7,114 product-one inner orbits for the
passport \((2A,3A,6A,2A)\): exactly 1,428 generate the pinned M23 and the other 5,686 are
intransitive. Six standard pure-braid generators act transitively on the generating class.

A separate standard-library verifier checks the M23 Schreier chain, class and product witnesses,
the exhaustive inner-orbit partition, 8,568 serialized forward braid transitions, their inverse
closure, and the complete straight-real action. The fixture manifest binds the actual public
`arbogast.hurwitz.m23_exact` verifier source by SHA-256 and byte length, in addition to binding
the witness dataset and compatibility entrypoint. Verification runs without GAP and without
repeating the search, then emits six `COMPUTED`, `CERTIFIED` claim nodes.

The real census preserves its exact scope: the real involution fixes 70 generating inner classes,
while 20 satisfy the stricter literal \(c=1\) condition. Those 20 exhaust the generating inner
Nielsen class, not all product-one tuples; the fixture explicitly verifies 212 strict \(c=1\)
representatives in the nongenerating complement. GAP generation remains discovery provenance,
not part of the verifier's trusted base.

### Prove without search

[`examples/certificates/prove_without_search/`](examples/certificates/prove_without_search/)
contains two programs. `discover.py` searches for a witness and writes a certificate.
`verify.py` intentionally knows nothing about the search strategy and checks only the emitted
finite evidence. This is the core design in miniature.

### A local research campaign

[`examples/campaigns/antieau_klueners_malle/`](examples/campaigns/antieau_klueners_malle/)
runs a small deterministic local analogue of the motivating workflow. It records imported prior
work, a persisted plan, capability matching, attempt states, a canonical target-scoped candidate,
and an explicit terminal state in an authoritative ledger. The imported statement starts in the
campaign-owned graph; the verified closure observation automatically adds and binds the computed
claim. The example independently replays both the registered residue-scan certificate and the
campaign claim envelope, then reloads the same graph from the campaign snapshot. It does not
contact the Klüners--Malle database or a remote scheduler at runtime.

## Certified arithmetic journeys

The 0.2 examples are finite, deterministic, and safe to run without GP. Where PARI can discover
the same data, the portable lane replays the normalized witness rather than rerunning discovery.

- [`aim_a_cocycle`](examples/arithmetic/aim_a_cocycle/) verifies both a solved affine family and
  an inconsistent target with a literal left-nullspace separator, then combines both claims in a
  claim graph.
- [`inflation_restriction`](examples/arithmetic/inflation_restriction/) checks the five-term
  sequence for the nonsplit extension \(C_2\to C_4\to C_2\), including transgression and exactness.
- [`q_kummer_selmer`](examples/arithmetic/q_kummer_selmer/) certifies
  \(\mathbf Q(\{2,\infty\},2)=\langle[-1],[2]\rangle\), its real and \(2\)-adic localizations,
  and a one-dimensional complete local-condition kernel.
- [`quadratic_field`](examples/arithmetic/quadratic_field/) keeps the pinned presentation
  \(t^2-t-1\) and verifies \(\operatorname N(t)=-1\) and \((2t-1)^2=5\).
- [`nonabelian_twists`](examples/arithmetic/nonabelian_twists/) exhausts the pointed
  \(H^1(C_2,S_3)\) for the trivial action, yielding exactly the identity and transposition
  classes without pretending that the result is a vector space or a twisted model.
- The additive
  [`local_global.py`](examples/campaigns/antieau_klueners_malle/local_global.py) campaign runs
  cheap local obstruction tasks before provenance-driven global aiming. “Locally unobstructed”
  remains non-closing; failed search, timeout, and missing capabilities remain `Unknown`.

## Exact deformation journeys

The 0.3 development examples are portable finite computations and require no external algebra
backend.

- [`exact_spaces`](examples/deformation/exact_spaces/) constructs a three-term deformation
  complex, verifies its gauge, tangent, and obstruction spaces, then checks framing,
  equivariance, invariant deformations, rigidity, and the resulting claim graphs.
- [`finite_lifts`](examples/deformation/finite_lifts/) exercises a solved affine lift family, a
  literal obstruction, separate unique and non-unique outcomes, and a fixed lift backed by an
  explicit contraction certificate.

## Certified numeric-to-exact journeys

The 0.4 examples are portable and require no external numerical or algebra backend.

- [`two_sheet_cover`](examples/numeric/two_sheet_cover/) validates the two finite branch points of
  the cover \(x^2-t(t-1)\), replays separated sheet continuations, recovers the branch cycles, and
  binds them to one exact Nielsen vertex. It then proves the supported normalized quadratic
  \(B_2\) generator homotopy while retaining absent-witness and general-word continuations as
  `NumericUnknown`.
- [`sqrt2_exactification`](examples/numeric/sqrt2_exactification/) keeps bounded recognition
  separate from exact polynomial substitution, retains the ambiguous branch as `NumericUnknown`,
  and rejects a damaged receipt.
- [`weighted_braid_plan`](examples/numeric/weighted_braid_plan/) proves exact cost optimality in a
  supplied finite action while showing that the selected word alone authorizes neither a numerical
  endpoint nor an exact cover target.

## Bounded p-adic journeys

The five p-adic examples are portable finite replays and require no external p-adic backend.

- [`frobenius_slopes`](examples/padic/frobenius_slopes/) certifies a supplied arithmetic
  Frobenius and its Newton multiplicities, then keeps the ordinary summand `Unknown` until an exact
  saturated projector is supplied.
- [`three_point_good_reduction`](examples/padic/three_point_good_reduction/) certifies the displayed
  tame beta model at \(p=5\) through good, semistable, and stable reduction, while other primes
  remain `Unsupported` rather than proofs of bad reduction.
- [`special_deformation_datum`](examples/padic/special_deformation_datum/) separates certified
  componentwise formal identities from an unproved geometric Wewers extraction.
- [`lifts_rigid_descent`](examples/padic/lifts_rigid_descent/) exhausts one pinned chart, rejects a
  label-only action, computes fixed classes, and closes only the rigid pinned
  \(\mathbf F_p\)-chart descent witnessed by exact coefficients and two-sided base change.
- [`m23_local_frontier`](examples/padic/m23_local_frontier/) keeps the public four-point M23 request
  `Unsupported` and a separate exact mod-23 factorization `Partial` with four open obligations.

## Reproducibility and theorem boundaries

Arbogast distinguishes these layers:

```text
source/input → canonical object → discovery receipt → verification certificate
                                                       │
                                                       ▼
                                                   computed claim
                                                       │
                                      imported claims ─┤
                                                       ▼
                                                   derived claim
```

- A successful search is not yet a verified result.
- A verified finite result is not automatically a published theorem.
- A field of moduli is not silently treated as a field of definition.
- Real branch data is not silently promoted to a rational model.
- Source-curve genus and Hurwitz-component genus are different invariants.
- Backend discovery does not make the backend part of the verifier's trusted base.

The conventions that make certificates portable are recorded in
[Mathematical conventions](docs/mathematical-conventions.md).

## Agents, papers, and Lean

Claim graphs can be projected into small, task-oriented views:

- generated module manifests name purpose, types, operations, invariants, `do_not` guardrails,
  and declared code-dependency nodes;
- bounded agent contexts add complete operation contracts, resolved hazards, implemented routes,
  unimplemented frontier edges, the separate code DAG, and acceptance-bearing task packets;
- paper exports separate assumptions, computational propositions, and deductions;
- Lean-facing exports render claim and proof-obligation records, preserving classifications,
  hypotheses, context, evidence, and discharge metadata.

The theorem `ClaimGraph`, semantic `CapabilityGraph`, declared `CodeDependencyGraph`, and
`AgentTask.dependencies` have different meanings and are never inferred from one another. Code
dependencies come from explicit operation/module/backend declarations, not Python import scans.
Explicit context records are atomic under `max_chars`: an undersized budget raises instead of
silently dropping a guarantee or guardrail.

The 0.1.0 Lean exporter emits structured obligation data, claim annotations, and theorem axioms
only when the conclusion and every hypothesis supply explicit Lean renderings; emitted axioms
retain those hypotheses as implications. It does not invoke Lean, translate
arbitrary matrix or orbit certificates, or claim that an axiom has been proved. Rich finite
witness bridges—such as rank witnesses, orbit trees, and completeness partitions—remain explicit
future work. See [Agent and Lean exports](docs/agent-and-lean-exports.md).

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
```

CI runs lint, formatting, strict typing, the complete test suite, and core examples without GP on
Python 3.11, 3.12, 3.13, and 3.14. A separate Python 3.11 release lane installs the exact wheel and
sdist and runs every packaged example; pinned PARI lanes replay that same candidate trio with GP.
Contributions must preserve deterministic serialization and theorem boundaries; start with
[CONTRIBUTING.md](CONTRIBUTING.md).

## License boundary

No open-source license has been selected for Arbogast. The public source and release artifacts are
therefore source-visible but all rights are reserved unless and until the copyright holder grants
additional permission.

## Status and citation

Arbogast 0.4.0 is alpha research software. Certificate verification is intended to be small
and inspectable, but users remain responsible for auditing the hypotheses and imported facts
of any theorem they rely on. See [SECURITY.md](SECURITY.md) for reporting integrity or
parser issues and [CITATION.cff](CITATION.cff) for citation metadata.

Release history is in [CHANGELOG.md](CHANGELOG.md).
