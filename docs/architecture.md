# Architecture

Arbogast is a Python control plane for finite exact mathematics. The package is organized
around mathematical objects and proof boundaries, not around whichever backend happens to
perform a search.

## Design goals

The 0.1 architecture has five non-negotiable properties:

1. **Canonical objects.** Equal supported objects have one stable external encoding.
2. **Exact operations.** Exact results do not depend on floating-point recognition.
3. **Search/verifier separation.** A compact verifier need not trust the discovery strategy.
4. **Semantic provenance.** Claims retain hypotheses, dependencies, evidence, and status.
5. **Backend independence.** Certificates contain mathematics, not opaque GAP or Sage state.

The package is not intended to replace a computer algebra system. External systems may discover
objects faster or support broader classes of input, but the public result is expressed in
Arbogast's canonical types and schemas.

## Claim ← Task ← Campaign

The product hierarchy follows mathematical custody:

```text
Campaign
  ├── objective, policy, budget, capability requirements, canonical plans
  ├── Task
  │     ├── canonical specification and dependencies
  │     ├── TASK_STARTED → Attempt history → resources/checkpoint custody
  │     └── Observation → candidates, result refs, certificate, terminal state
  └── campaign-owned ClaimGraph
          ├── imported/assumed starting claims
          └── verified closure → computed Claim + ledger binding
```

A **campaign** is the durable research program. A **task** is a canonical unit of intended work;
0.1 records canonical plans, start and observation events, first-class `AttemptRecord` state,
candidates, resource counters, and claim bindings. A retry or checkpoint resume may have a new
`CampaignTask` identity and must carry its provenance explicitly. A **claim** is a semantic
assertion supported by selected task evidence and explicit dependencies. The arrow
`Claim ← Task ← Campaign` means “produced within the custody of,” not that task completion alone
proves a claim.

The campaign ledger is authoritative. Processes and worker directories are transient views. A
ledger records targets, plans, planned tasks, starts, attempt transitions, observations,
candidates, outcomes, result and typed-checkpoint references, resources, embedded closure
certificates, and claim bindings so later planning does not infer state from stdout or a surviving
scratch directory. The surrounding campaign owns a canonical `ClaimGraph`. Accepting a verified
closing observation creates its narrowly scoped computed claim and records its ledger binding;
`export claims` returns that graph directly.

Candidate identity is mathematical data supplied by an operation. A `CandidateRecord` names its
canonical key, canonicalizer, and `TARGET` or `GLOBAL` equivalence scope. Preference is maintained
per named quality metric; the ledger refuses to manufacture a single ordering across unlike
metrics. Candidates remain observation-bound artifacts, distinct from the claims that state what
has actually been certified.

## Dependency direction

```text
                          ┌─────────────────────────┐
                          │ agents · papers · Lean  │
                          └────────────▲────────────┘
                                       │ export
                              ┌────────┴────────┐
                              │   ClaimGraph    │
                              └──────▲───▲──────┘
                                     │   │
                    theorem meaning  │   │ evidence
                                     │   │
             ┌───────────────────────┘   └──────────────────────┐
             │                                                   │
   ┌─────────┴──────────┐                              ┌─────────┴──────────┐
   │ mathematical layers│                              │ cert · provenance │
   │ groups · rep       │                              │ fleet · formats   │
   │ cohom · hurwitz    │                              └─────────▲──────────┘
   └─────────▲──────────┘                                        │
             │                                                    │
             └──────────────────┬─────────────────────────────────┘
                                │
                     ┌──────────┴───────────┐
                     │ core · exact linalg │
                     └──────────▲───────────┘
                                │ optional discovery
                     ┌──────────┴───────────┐
                     │ external backends   │
                     └──────────────────────┘
```

Lower layers do not import a paper exporter, a fleet scheduler, or a backend-specific session.
Claim graphs refer to content-addressed mathematical artifacts. Exporters are projections of a
claim graph and cannot strengthen a claim's status.

## The semantic center

The central artifact is a directed acyclic graph of mathematical claims. A node records:

- a stable identifier and formal statement;
- a claim kind such as imported or computed, plus a separate epistemic status;
- explicit dependencies;
- the derivation kind and operation contract;
- references to evidence and provenance;
- an optional `ProofGap` bound to the same claim ID, when formalization work remains.

Edges represent mathematical dependence. This theorem DAG is intentionally separate from the
code DAG. For example, a Hurwitz transitivity claim may depend mathematically on class-membership
witnesses and an orbit spanning tree, while its implementation depends on a permutation module
and a JSON decoder. Paper and Lean exports follow the theorem DAG.

## Four dependency surfaces, four meanings

Arbogast does not overload one graph with several kinds of dependency:

| Surface | Nodes and edges | What it is allowed to mean |
| --- | --- | --- |
| `ClaimGraph` | Claims linked by each claim's `why` references | Mathematical/theorem dependence |
| `CapabilityGraph` | Semantic input bundles linked to outputs by operation contracts | Available type transformations and the unimplemented frontier |
| `CodeDependencyGraph` | Operations, implementation modules, and backends | Declared software dependencies |
| `AgentTask.dependencies` | Content-addressed or named work packets | Scheduling/prerequisite relationships between agent assignments |

`CodeDependencyGraph` is a strict, content-addressed DAG. Its edges point from a dependent to its
dependency: an operation is `implemented_by` a module, a module `depends_on` another module, and
an operation may name a required or optional backend. The default graph is assembled only from
`OperationCodeDependencies` records in `DEFAULT_CODE_DEPENDENCIES`. It does not walk Python
imports, inspect callable `__module__` attributes, or infer that two mathematically related claims
share a code dependency. Unknown schema versions, dangling edges, duplicates, cycles, and a
mismatched content ID fail closed.

The capability graph is also not a proof planner. A route records contract-induced type
hyperedges. Every step names its complete conjunctive `required_inputs` bundle, and route search
may use only types supplied initially or produced by earlier steps. Alternative unary call shapes
are separate one-element bundles. A route still does not establish value-level preconditions,
execute any step, or certify the result. Implemented hyperedges are routes, while unimplemented
hyperedges stay visible as frontier edges. Neither kind becomes a theorem dependency unless a
`Claim` explicitly names it.

## Operation contracts

Public operations carry machine-readable contracts. A contract describes the mathematical
domain, accepted types, preconditions, guarantees, exactness, failure modes, certificate type,
and shard strategy. The CLI exposes this metadata:

```bash
arbogast describe cohom.h1 --json
```

An unsupported input is an explicit failure, not a request to guess a theorem. An absent route
is visible through the capability graph:

```bash
arbogast route --from NielsenClass --to ClaimGraph --json
```

For machine collaborators, `arbogast.agent.compact_context()` combines complete selected
operation contracts with matching hazards, direct capability routes and frontier edges, the
declared code DAG, module guardrails, and optional task packets. Explicitly requested semantic
records are atomic: if `max_chars` is too small, construction raises instead of returning a
misleading partial contract.

## Result and evidence flow

A normal exact computation passes through distinct states:

```text
validated input
    ↓
canonical mathematical object
    ↓
discovery work and DiscoveryReceipt
    ↓
VerificationCertificate
    ↓ independent verifier
verified computed Claim
    ↓ with imported assumptions and explicit deductions
derived Claim
    ↓
ClaimGraph exports
```

A receipt that merely says a backend found 1,428 objects is not a completeness certificate. A
complete finite enumeration needs enough evidence to check validity, uniqueness, and coverage.
The certificate schema records which of those guarantees is present.

## Canonicalization

Canonicalization is part of the mathematical contract. It is used for equality, deterministic
sharding, hashing, manifests, and portable certificates. Encodings are versioned, contain no
memory addresses or backend handles, use stable ordering, and reject ambiguous data.

Concrete group embeddings remain pinned. Arbogast does not silently identify two conjugate
permutation representations: any change of embedding requires an explicit transport map. This
prevents a canonical representative in an ambient symmetric group from being mistaken for an
element of the original concrete subgroup.

## Fleet execution

Fleet primitives distribute deterministic task specifications rather than arbitrary closures.
A task identifies its canonical inputs, operation contract, schema versions, and resource
requirements. Shards have stable IDs and reducers verify compatibility before combining them.

Dispatch, process exit, receipt collection, successful verification, and theorem acceptance are
separate states. Resuming a campaign does not turn an unverified partial shard into a completed
claim.

The 0.1.0 executors are local and deterministic. `WorkerPoolExecutor` matches declared backend
and resource requirements, records leases and attempts, and can replay typed cooperative
`CheckpointRef` or multi-shard `CheckpointManifest` custody. The basic `LocalExecutor` does not
persist scheduler custody; a checkpoint successor is a `SUSPEND` advisory and dispatch refuses
to call it a resume. Reload converts any orphaned `RUNNING` attempt to operational `UNKNOWN`
without creating mathematical evidence.

These are cooperative continuation semantics, not arbitrary process or host crash recovery.
Campaign and sink protocols are extension points for other environments, but the package does
not provide SSH deployment, Slurm control, cloud provisioning, remote license distribution, or
automatic reconstruction of worker hosts. The CLI's `run --fleet auto` uses a conservative local
worker pool and an audited registry containing only the non-closing `fleet.echo.v1` plumbing
operation; serialized campaign data never selects an arbitrary callable.

## Trusted computing base

The intended trusted base for a finite claim is:

- the certificate parser and canonical decoder;
- the small exact verifier for that certificate type;
- the explicitly imported mathematical facts named by the claim;
- the language runtime and ordinary machine arithmetic needed by that verifier.

The search planner, worker fleet, optional CAS, and discovery transcript should not be trusted
when the certificate contains enough independent evidence. A certificate may declare a larger
trusted base, but it must do so explicitly.

See [Claims and certificates](certificates-and-claims.md) for the evidence layers and
[Theorem boundaries](theorem-boundaries.md) for status semantics.
