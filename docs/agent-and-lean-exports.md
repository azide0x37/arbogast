# Agent and Lean exports

Arbogast exports projections of the same claim graph for coding agents, paper workflows, and
formalization. None of these consumers should reconstruct mathematics from terminal output.

## Agent manifests

An agent-facing manifest is intentionally smaller than the repository. `AgentManifest` is the
generated, scope-labelled equivalent of a compact `AGENT.md`; it records package/version, scope,
purpose, operation names, primary types, invariants, `do_not` guardrails, and declared code
dependency node IDs. It is not a second operation catalog and does not pretend that names alone
are complete contracts.

`module_manifest()` provides the generated-equivalent API for public modules. Static generated
`AGENT.md` copies are not checked in because they would drift from the operation registry and
dependency declarations:

```python
from arbogast.agent import AgentManifest, module_manifest

manifest = module_manifest("arbogast.hurwitz")
assert "Do not confuse source genus" in " ".join(manifest.do_not)
assert AgentManifest.from_json(manifest.to_json()) == manifest
```

For example, the Hurwitz profile names its primary types and warns that source genus and
Hurwitz-component genus are different. The relevant machine-readable `Hazard` also warns that an
ambient symmetric-group conjugate need not belong to a pinned concrete group embedding.

## Bounded complete contexts

`AgentContext` expands a manifest into the task-facing packet. It contains the complete selected
`OperationDescription` records—including preconditions, guarantees, failure modes, exactness,
certificate type, shard policy, complexity, examples, and declared hazards—plus resolved hazard
records, implemented capability routes, unimplemented frontier edges, a declared
`CodeDependencyGraph`, and optional `AgentTask` packets with acceptance tests. Cross-references are
validated: a context cannot contain a route, task API reference, hazard ID, or code node whose
operation contract is absent.

`arbogast describe OPERATION --json` and `arbogast route --from TYPE --to TYPE --json` are the
smallest discovery surfaces. Their JSON output is meant to be consumed directly rather than
scraped from human help text.

The Python surface builds bounded canonical JSON without truncating individual semantic records:

```python
from arbogast.agent import AgentContext, compact_context

context = compact_context(("cohom.h1",), max_chars=16_000)
payload = context.to_json()
assert AgentContext.from_json(payload) == context
```

When operation names or other semantic records are supplied explicitly, they are atomic. If the
whole coherent packet does not fit `max_chars`, `compact_context()` raises `ValueError`; it never
drops a guarantee, hazard, frontier edge, code dependency, invariant, or acceptance test to make
the JSON fit. Only implicit all-operation discovery may omit whole operation records and their
dependent surfaces, and the `omitted` counters make that loss explicit.

## Code DAG and capability frontier

The code graph is distinct from both the theorem `ClaimGraph` and the semantic
`CapabilityGraph`. It is built from explicit `OperationCodeDependencies` declarations, never by
scanning imports:

```python
from arbogast.agent import DEFAULT_CODE_DEPENDENCIES, CodeDependencyGraph

code_graph = DEFAULT_CODE_DEPENDENCIES.graph(("cohom.h1",))
dependencies = code_graph.transitive_dependencies("operation:cohom.h1")
assert CodeDependencyGraph.from_json(code_graph.to_json()) == code_graph
```

Operation, module, and backend nodes are serialized under
`arbogast.agent.code-dependency-graph.v1` with a content ID. The separate
`arbogast.agent.operation-code-dependencies.v1` declaration says which module implements an
operation, its internal module dependencies, and its required and optional backends. A registry
lookup fails when an implemented operation has no declaration; it does not guess from a runtime
callable.

Capability routes come from operation type ports. Each contract declares alternative
`input_bundles`; the types within one bundle are conjunctive requirements, while separate bundles
are alternative call shapes. Route search accumulates initial and produced types and cannot fire
an operation from only one member of a multi-input bundle. Direct implemented unary hyperedges
appear in a context's `capability_routes`; direct unimplemented hyperedges appear in
`capability_frontier`, including their full `required_inputs`. A route does not prove value-level
preconditions, execute the operations, or provide evidence for a claim. The frontier is an honest
list of missing semantic/software transformations, not a list of failed theorems.

## Task-sized work packets

`AgentTask` carries an objective, input references, expected output, relevant API names,
work-packet dependencies, acceptance tests, maximum-context references, and immutable metadata.
Its `packet_id` binds every one of those fields. `AgentTask.dependencies` describes work
prerequisites; it is not a code dependency or a theorem edge. When included in an `AgentContext`,
every `relevant_api` name must have its complete contract in the same packet.

## Paper exports

The current Markdown and LaTeX projections preserve a claim's statement, kind, status,
dependencies, derivation, evidence, and imported sources where the selected format supports
them. A complete paper workflow should separately record:

- theorem statement and hypotheses;
- imported literature claims;
- exact computational propositions;
- derived claims and proof dependencies;
- open or conjectural steps;
- certificate identifiers and reproduction commands.

The generic exporter does not invent reproduction commands. Generated prose is a starting point
for mathematical editing, not a mechanism for promoting status. It can format the dependency
graph, but it cannot label a claim “new” or “proved” without the corresponding metadata and
evidence.

## Lean-facing obligations

Lean export is intended as a bridge toward proof-carrying computation. Expensive discovery stays
outside the proof assistant.

The 0.1.0 exporter accepts `Claim`, `ClaimGraph`, `ProofObligation`, and `ProofGap` values. It
emits a `ProofObligationData` list with context, dependencies, evidence, discharge references,
and notes. Claim hypotheses remain a separate data projection. An axiom is emitted only when the
conclusion and every hypothesis have explicit Lean renderings; its type is the corresponding
implication, never an unconditional conclusion with silently dropped context. If any condition
is still prose, the exporter retains the data and omits the axiom. It does not run Lean or
discharge any generated axiom.

```python
# Given a ClaimGraph named claim_graph; formats are json, markdown, latex, lean, and agent.
lean_source = claim_graph.export("lean", destination="claims.lean")
```

Future typed certificate bridges may add finite payloads such as:

- a permutation's finite image vector and bijectivity obligation;
- a Nielsen tuple's class-membership, product-one, and generation obligations;
- an orbit's vertex table, generator edges, and spanning tree;
- a linear map's matrix, kernel and image bases, and rank identities;
- a quotient's well-definedness and universal-property obligations.

Those payload bridges are not part of the current generic exporter. Each obligation is
classified as `DECIDABLE`, `CERTIFICATE`, `LIBRARY_THEOREM`, `MISSING_LEMMA`,
`EXTERNAL_THEOREM`, or `OPEN`. Formalization distance is descriptive planning metadata; it is
not a proof score.

A claim's optional `formalization` field is a full `ProofGap` whose `claim_id` must equal the
owning claim ID. It participates in canonical claim serialization and the claim digest, but open
formalization work neither weakens a verified finite certificate nor promotes an unverified
mathematical status. Foreign, untyped, or internally inconsistent gap data fails strict replay.

## Stable and deliberately boring data

Lean-facing claim and obligation records avoid backend internals. `Claim.id` and
`ProofObligation.id` are stable validated labels, not content addresses. Claim, graph, and proof
gap digests, certificate references, and explicitly content-addressed artifact references are the
content-addressed values; collections have canonical ordering. Any future permutation or matrix
bridge must use stable finite tables and coefficient presentations; it must not serialize a GAP
object number, Python memory address, or an unstated choice of group embedding.

## What export does not mean

- Exporting a claim to Lean does not assert that Lean accepted it.
- A generated axiom preserves all explicitly recorded hypotheses; an unformalized hypothesis
  suppresses that axiom instead of being discarded.
- A generated theorem skeleton is not a theorem certificate.
- A `DECIDABLE` label still requires the corresponding formal definition and evaluation.
- An external theorem remains an axiom/import until formally reconstructed.
- A missing lemma or open obligation remains visible in every downstream projection.

Use `arbogast proof-gap FILE --claim CLAIM_ID` to inspect this boundary before assigning a
formalization task. The command accepts only strict `arbogast.claim-graph/v1`,
`arbogast.claim/v1`, or `arbogast.proof-gap/v1` input. It never guesses a proof frontier from an
arbitrary JSON object's field names, and `--claim` must match the selected claim or gap.
