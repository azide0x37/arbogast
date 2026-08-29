# Claims and certificates

Arbogast separates what was searched, what can be checked, and what mathematical conclusion is
licensed by that check.

## Three evidence layers

| Artifact | Audience | Meaning |
| --- | --- | --- |
| `DiscoveryReceipt` | operator and debugger | Records how candidate data was found, including backend and planning details. |
| `VerificationCertificate` | independent verifier | Contains finite witnesses sufficient for named checks. |
| theorem-level claim | mathematician, agent, exporter | States the conclusion justified by verified evidence and explicit dependencies. |

These are not interchangeable. A discovery receipt can be useful provenance without proving
completeness. A certificate can verify a finite table without justifying a global theorem whose
hypotheses are absent. A theorem claim may be conditional on imported literature even when all
of its local computations are exact.

## Claim graph

A `ClaimGraph` is a versioned directed acyclic graph. Every claim has, conceptually:

```json
{
  "id": "example.claim",
  "statement": {"type": "...", "parameters": {}},
  "kind": "computed",
  "status": "exact",
  "dependencies": ["source.claim"],
  "derivation": {"operation": "...", "artifact": "sha256:..."},
  "evidence": ["sha256:..."],
  "provenance": {"inputs": [], "software": []},
  "obligations": []
}
```

This fragment is explanatory rather than a substitute for the versioned runtime schema. Use the
library encoder to produce interchange files and reject unknown schema versions by default.

Claims answer five questions: what is asserted, why it follows, how it was obtained, which
evidence checks it, and where the inputs came from. Dependency cycles and missing references are
invalid.

## Claim kind is not epistemic status

The claim kind records the role of an assertion:

- `ASSUMED`: a hypothesis supplied for the current derivation;
- `IMPORTED`: a specifically identified external theorem or dataset assertion;
- `COMPUTED`: established by a supported exact operation and adequate certificate;
- `DERIVED`: follows from dependency claims by a recorded mathematical rule;
- `CONJECTURED`: proposed but not established by the graph.

The separate epistemic status is `EXACT`, `CERTIFIED`, `CONDITIONAL`, `NUMERICAL`, `HEURISTIC`,
or `UNKNOWN`. Kind does not erase conditionality: a `DERIVED` claim whose dependency is
`ASSUMED` remains conditional. Likewise, integrity-checking a file containing an `IMPORTED`
assertion does not promote that assertion to `COMPUTED` or its status to `CERTIFIED`.

## Content addressing

Canonical artifacts are serialized deterministically and identified by a cryptographic digest.
The digest binds the canonical payload and schema version; presentation whitespace, filesystem
paths, and backend session identifiers are not mathematical content. Verifiers recompute and
compare identifiers before checking witnesses.

Content identity establishes that two consumers received the same bytes under the same schema.
It does not by itself establish that the contents are mathematically true.

## What a verifier checks

A verifier first checks the envelope:

1. supported schema and certificate kind;
2. bounded sizes and well-formed canonical values;
3. content digests and referenced object identities;
4. compatibility of conventions and operation contract;
5. the finite witnesses required for the named mathematical guarantees.

For exact linear algebra, those witnesses may include matrices, kernel or image bases, quotient
maps, and rank identities. For an orbit computation, they may include canonical vertices,
generator edges, a spanning forest, stabilizers, and a coverage witness. For a finite Nielsen
class, completeness additionally needs evidence that every valid equivalence class appears.

The verifier returns a structured outcome. “The JSON parsed” and “the theorem is certified” are
different outcomes.

## Portable finite Hurwitz operations

`HurwitzOperationCertificate` is the fresh-process boundary for ordinary finite Hurwitz
workflows. Its `arbogast.hurwitz.operation/v1` payload embeds the complete portable Nielsen
enumeration receipt (including the finite multiplication table and ordered explicit classes),
the canonical inputs to one operation, and its advertised result. Verification first replays
Nielsen completeness and then recomputes the downstream result without reconstructing or
calling the discovery backend.

The registered verifier IDs are `hurwitz.braid_action`, `hurwitz.components`,
`hurwitz.real_structure`, `hurwitz.real_census`, `hurwitz.reduced`, `hurwitz.cusps`, and
`hurwitz.boundary`. `operation_certificate_for(result)` produces the specialized receipt;
`result.verification_certificate()`, `result.claim()`, and `result.claim_graph()` bind its one
canonical proposition to the central certificate and claim APIs. Serialized receipts and claim
graphs replay in a process that has none of the original group objects.

Promotion is intentionally narrower than in-memory computation:

- the source must be a computed-complete `NielsenClass`; an imported representative list is not
  a completeness proof;
- a real structure is portable only for the built-in straight transform or explicit signed
  slots; an opaque callable remains context-bound;
- a reduced result certifies exactly the finite orbits of the supplied explicit vertex
  permutations, not an unstated mapping-class quotient;
- a real census binds whether it searched one fixed involution or all involutions and whether
  simultaneous inner conjugates were searched;
- components, cusps, and boundary incidences are scoped to the exact named braid words,
  component, operators, and collisions carried by the receipt.

Because this generic format embeds a full multiplication table, it is intended for small finite
groups. The M23 example below uses its own public typed certificate and stabilizer-chain replay;
it does not pretend that a hash or context-bound receipt is a portable table certificate.

## The exact M23 example

The 0.1.0 repository includes complete finite witnesses for the generating inner Nielsen class
with class vector \((2A,3A,6A,2A)\). Its standard-library verifier independently checks the
pinned M23 embedding, class and product witnesses, inner canonicality, an exhaustive partition
of all 7,114 product-one inner orbits, braid transitions and transitivity, and the straight-real
action. GAP generated the fixture but is not invoked or trusted by verification.

This example illustrates why “precomputed” and “imported assertion” are different concepts. The
dataset arrives through precomputed custody, but sufficient finite witnesses let a fresh process
establish computed, certified claims. The supplied expected values and GAP receipt remain
discovery provenance; neither is accepted as proof by itself.

The verifier proves that 1,428 inner classes generate M23 and form one pure-braid component,
while all 5,686 remaining product-one inner orbits are intransitive. Its real-action certificate
distinguishes 70 inner-fixed generating classes from the 20 stricter \(c=1\) classes. The latter
exhaust the generating inner Nielsen class only: 212 strict \(c=1\) representatives exist in the
nongenerating complement and are recorded as a scope guardrail.

Six claim nodes bind these conclusions to verification-layer certificates and therefore have
kind `COMPUTED` and status `CERTIFIED`. See
[`examples/hurwitz/m23_real_component/`](../examples/hurwitz/m23_real_component/) for the witness
inventory, completeness argument, and exact theorem boundary.

## Compatibility

Certificate schemas are versioned independently of the package. A verifier may support multiple
old versions, but it must never guess how to reinterpret an unknown version. Changes to
canonicalization, mathematical convention, or witness semantics require a schema change and
release note.

The initial schema identifiers are:

| Schema | Artifact |
| --- | --- |
| `arbogast.cert.discovery/v1` | Search and discovery receipt |
| `arbogast.cert.verification/v1` | Independently checkable finite witness |
| `arbogast.cert.theorem/v1` | Binding from verified evidence to a theorem claim |
| `arbogast.claim/v1` | One semantic claim node |
| `arbogast.claim-graph/v1` | A validated theorem DAG |
| `arbogast.cohomology.v1` | Reconstructible normalized-bar cohomology certificate |
| `arbogast.hurwitz.operation/v1` | Backend-neutral finite Hurwitz operation replay |

Certificate JSON includes its semantic `layer`. The optional `certificate_id` is a
`sha256:<lowercase hex>` content address computed over the canonical payload without that ID.
Supplying a mismatching ID is an error, not a request to rewrite it.

## Verifier guidance

Independent verifiers should be deterministic, avoid network access, impose resource limits
before allocating from untrusted lengths, and return actionable failures. They should not execute
code embedded in certificates or ask the discovery backend to confirm its own output.
