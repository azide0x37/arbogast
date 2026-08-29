# Theorem boundaries

Arbogast is designed to make overclaiming mechanically awkward. This document states the
boundary promised by 0.1.0.

## Evidence axes

Several independent questions apply to every result:

1. Is the underlying value exact, conditional, numerical, heuristic, or unknown?
2. Is the assertion assumed, imported, computed, derived, or conjectured?
3. Was only discovery recorded, or did an independent verifier accept a sufficient witness?
4. Does the certificate prove validity only, or also uniqueness and completeness?
5. Which literature theorems and concrete conventions remain in the trusted base?

No single “verified” boolean answers all five.

## Allowed promotions

An exact operation may create a `COMPUTED` claim only after its input contract is satisfied and
it records a concrete derivation plus nonempty evidence. `CERTIFIED` additionally requires a
verification- or theorem-layer certificate. A derivation may create a `DERIVED` claim only from
named dependencies and a supported inference rule. An imported source remains `IMPORTED` even
after its file hash and citation metadata are validated.

There is no implicit promotion from:

- numerical recognition to an exact algebraic value;
- a successful search to an exhaustive enumeration;
- object validity to orbit transitivity;
- class rationality to component rationality;
- field of moduli to field of definition;
- a real point criterion to a rational point theorem;
- source genus to Hurwitz-component genus;
- a Lean export to a checked Lean proof.

## Exact finite scope

The 0.1.0 guarantee applies only to supported finite representations and schemas. It does not
extend a finite computation to an infinite family without a recorded theorem. “Exact” means
exact relative to the validated input, stated conventions, implemented operation contract, and
explicit imported dependencies.

Unsupported characteristics, coefficient rings, equivalence relations, group encodings, or
certificate versions must raise or return an explicit unsupported/unknown outcome. Falling back
to a nearby problem is not permitted.

## Imported sources and datasets

An imported claim should identify the exact assertion consumed, not merely a bibliography entry.
When possible, provenance includes a stable source identifier, version, page or theorem locator,
and content digest. The graph can reason conditionally from imported claims, but Arbogast does not
claim to have independently proved them.

Precomputed data follows the same rule. A fixture with full finite witnesses may be independently
verified and support computed claims. A manifest containing only asserted totals can be validated
for integrity but remains imported.

## Formalization status

Proof obligations are classified separately from claim status:

| Class | Meaning |
| --- | --- |
| `DECIDABLE` | A proof assistant can evaluate the finite proposition directly. |
| `CERTIFICATE` | A finite witness and verifier theorem are required. |
| `LIBRARY_THEOREM` | An existing formal theorem should discharge the step. |
| `MISSING_LEMMA` | The mathematics is expected but the formal bridge is absent. |
| `EXTERNAL_THEOREM` | A literature result remains an imported formal assumption. |
| `OPEN` | The obligation is not established. |

A claim graph may be mathematically useful with `MISSING_LEMMA` or `EXTERNAL_THEOREM`
obligations. Exporters must show those gaps.

## Failure is a result

An obstruction, unsupported case, missing capability, inconsistent certificate, or unknown
theorem status is a legitimate structured outcome. It should preserve diagnostics and provenance
without being presented as a positive theorem. This fail-closed behavior is part of the public
contract.
