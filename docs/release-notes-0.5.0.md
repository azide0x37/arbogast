# Arbogast 0.5.0 release notes

Arbogast 0.5.0 adds certified bounded p-adic arithmetic to the immutable finite-exact,
arithmetic, deformation, and numeric-to-exact layers from 0.1 through 0.4.

## Proof boundary first

This release computes in explicit finite quotients \(\mathcal O_K/\pi^N\). It does **not**
provide general infinite-precision p-adic arithmetic, automatic stable reduction, automatic
Wewers extraction, nontrivial arithmetic actions on lift models, or characteristic-zero descent.
Those are explicit non-features of 0.5. A finite exact receipt closes only the bounded claim it
replays; agreement with a stronger geometric story does not promote the result.

The four public result states preserve that line:

- `Certified[T]` is complete only for its displayed finite scope;
- `Partial` retains independently certified fragments and names every remaining proof obligation;
- `Unknown` records insufficient precision or missing witnesses without a negative theorem; and
- `Unsupported` certifies that a request is outside the implemented surface, not that the
  requested mathematical object does not exist.

Every substantial result still exposes `verify()`, `.certificate`, `.claim()`, and
`.claim_graph()`. P-adic receipts are nested inside the existing central
`VerificationCertificate`; no new evidence layer or incompatible claim schema is introduced.

## Exact finite local arithmetic

The public `arbogast.padic` package adds pinned rational, unramified, and Eisenstein local-field
presentations. A presentation binds the prime, monic polynomial, integral basis, uniformizer,
residue polynomial, ramification index, residue degree, and an exact presentation witness.
Embeddings bind exact generator images; finite-ring automorphisms bind forward and inverse images
of the integral basis. Neither uses backend handles or printed p-adic expansions.

`PAdicPrecisionRing(field, N)` is the literal finite chain ring
\(\mathcal O_K/\pi^N\). Exact elements, residue-class balls, matrices, modules, canonical
scalar-closed preimage-HNF submodules, embeddings, and automorphisms share parent identities and
fail closed on foreign or noncanonical transport. General `PAdicSubmodule` values are not called
saturated in the stronger module-theoretic sense. `PAdicBall` never denotes a chosen infinite
p-adic number.

## Frobenius, slopes, and finite inertia

`FrobeniusOperator` replays a supplied semilinear action \(v\mapsto A\sigma(v)\), including the
declared arithmetic or geometric convention. The coefficient automorphism is supplied either as
a pinned local-field self-embedding or a finite-ring `PAdicAutomorphism`; its declared finite
period is checked at the working precision. The linearized product yields a division-free
characteristic polynomial. `slopes` certifies Newton multiplicities only when the finite-precision
valuation intervals determine every required vertex; otherwise it returns `Unknown`.

A Newton polygon does not by itself construct a slope decomposition. `ordinary_part` therefore
requires an explicit saturated, Frobenius-stable slope-zero projector and a checked basis change.

`FiniteInertiaQuotient` and `InertiaFiltration` are finite group-theoretic inputs. They check their
enumeration, subgroup, tame/wild quotient, action, and optional Frobenius-relation identities.
They do not claim a continuous local Galois representation, arithmetic origin, or a complete
valuation-derived lower ramification filtration.

## A deliberately narrow reduction lane

`ThreePointCover` binds an exact normalized polynomial map, complete fibers above
\(0,1,\infty\), its finite critical divisor, generic degree, and a genus-zero
Riemann--Hurwitz witness. The automatic reduction lane supports exactly the displayed tame beta
map

\[
\beta(z)=\frac{27}{4}z^2(1-z)
\]

at \(p=5\). For this profile, `good_reduction`, `semistable_reduction`, and
`stable_reduction` separately certify the one-component marked model and its stability
inequalities. Other primes, other presentations, and reflected coordinates return typed
`Unsupported`; they do not prove bad or potentially bad reduction.

## Special-deformation identities, lifts, and descent

The rank-one special-deformation layer verifies logarithmic differentials, Cartier identities,
finite tame characters, and the implemented special-signature criterion. A directly supplied
`DeformationDatum` can therefore be certified for
`componentwise-rank-one-tame-formal-identities`. Version 0.5 does not identify signature labels
with points or the divisor of the differential, and it does not extract a Wewers datum from the
supported stable model. That geometric comparison remains a separate open obligation.

`LiftChart` and `LiftEnumerationWitness` exhaust one pinned monic equation over \(\mathbf F_p\)
and retain exactly its labeled polynomial models. This is complete in that finite chart, not a
global classification of lifts. `lift_galois_action` automatically closes only for a
computed-complete trivial finite Galois quotient, the identity permutation on lift classes, and
explicit identity transport on every exact model. Nontrivial arithmetic actions remain
`Unsupported`.

`fixed_lifts` reports fixed classes but explicitly makes no descent claim. `effective_descent`
requires independent automorphism-triviality, cocycle, coefficient, and two-sided base-change
witnesses. Its positive result is scoped to
`effective-descent-in-pinned-F_p-labeled-chart-model-category`: it is not characteristic-zero,
number-field, or geometric-cover descent.

## M23 remains a non-conclusion at the local-model boundary

The exact four-point M23 Hurwitz dataset continues to certify its finite Nielsen class, pure-braid
component, and real census. It contains no cover equation, local-field model, stable reduction,
special-deformation extraction, lift, or descent witness. `reduction_frontier` therefore returns
`Unsupported` for the public dataset. A separately certified complete factorization of one
displayed mod-23 polynomial is retained only as a `Partial` local fragment with explicit
obligations for cover binding, stable reduction, fixed lifts, and effective descent.

Local plausibility, a successful finite factorization, and an unsupported automatic lane never
become a global M23 model claim.

## Receipts, examples, and release integrity

P-adic objects and results use independently versioned canonical receipts, replayed through
exactly two portable verifier families: `padic.finite-exact.v1` and
`padic.three-point-exact.v1`. The operation catalog, capability graph, code-dependency DAG,
agent manifests, hazards, routes, exporters, and fresh-process verifier registry all include the
new public surface. The operations are deliberately non-shardable because each finite witness is
a globally coupled exact record.

Five backend-free journeys exercise both closing and non-closing branches:

- `examples/padic/frobenius_slopes/`;
- `examples/padic/three_point_good_reduction/`;
- `examples/padic/special_deformation_datum/`;
- `examples/padic/lifts_rigid_descent/`; and
- `examples/padic/m23_local_frontier/`.

The release checker and artifact qualifier require the full p-adic package, documentation,
examples, acceptance tests, and current notes in the wheel, sdist, and Git source archive as
appropriate. The newly frozen 0.4 fixture is re-derived from the exact public tag and records the
public release identity, three published asset hashes and sizes, API and CLI contracts, all 160
published schemas, a numerical recognition claim, and its separate exactification claim.

## Explicit deferrals

Arbogast 0.5 does not provide arbitrary infinite-precision p-adic arithmetic, automatic
local-field recognition, general Newton-slope submodule construction, wild or non-good stable
reduction discovery, automatic Wewers extraction, general p-adic Hensel lifting, nontrivial
arithmetic actions on lift models, characteristic-zero or number-field effective descent,
automatic cover construction from a Nielsen class, or an automatic M23 local/global model.
