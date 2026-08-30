# Arbogast 0.2.0 release notes

Arbogast 0.2.0 adds a bounded certified-arithmetic vertical slice above the immutable 0.1.0
finite-exact core. The automatic arithmetic path is intentionally concentrated on pinned number
fields, squareclasses, local \(\mu_2\)-cohomology, Hilbert pairings, and finite 2-Selmer problems.
The underlying exact linear algebra and low-degree finite-group cohomology remain prime-field
generic.

## Compatibility first

The 0.1 interfaces are compatibility fixtures, not historical suggestions. The `restrict` and
`inflate` convenience functions retain their signatures and values; every v1 claim, certificate,
and interchange schema remains accepted; and a checked-in 0.1.0 \(H^1(C_2,\mathbf F_2)\)
certificate and claim graph replay in a fresh process under 0.2. The release gate also binds the
published 0.1.0 wheel and source archive by their original names, sizes, and SHA-256 digests. It
never rebuilds those published files.

The new map APIs return explicit certified induced-map objects through degrees 0--2.
Corestriction replays a complete-transversal transfer formula. The five-term
inflation--restriction sequence recomputes zero composites and every interior image/kernel
equality rather than trusting serialized dimensions.

## Canonical arithmetic and the hybrid proof boundary

`NumberField`, `NumberFieldElement`, `FieldEmbedding`, `FinitePlace`, and `InfinitePlace` bind
defining polynomials, exact rational coordinates, integral bases, embedding images, ideal HNF
data, and exact place data. Finite group maps, extensions, Galois quotients, and modules likewise
bind complete finite presentations. Backend handles, session indices, printed \(p\)-adics, and
implicit polynomial-reduction identifications never enter canonical identities.

Real places use exact Sturm isolation. Higher-degree complex places replay rational Rouché
witnesses from nested PARI discovery certificates; complete archimedean coverage also checks
pairwise-disjoint rectangles against the independently certified field signature.

Every substantial arithmetic result exposes `verify()`, `certificate`, `claim()`, and
`claim_graph()`. Its result-specific receipt is nested in the existing central v1 verification
certificate. Three axes remain independent:

- assumptions determine whether the mathematical claim is unconditional or conditional;
- verifier trust records whether portable Python or a pinned PARI verifier is required;
- completeness records `CANDIDATE` or `COMPLETE` without promoting one into the other.

A successful PARI certification can remove a GRH assumption while still leaving PARI in the
trusted replay boundary. If unconditional certification exhausts its budget, the default result
is `UNKNOWN` with `BUDGET_EXHAUSTED`; accepting a GRH-conditional result is an explicit caller
choice.

## Kummer, local cohomology, and Selmer problems

The finite global object is \(K(S,2)\), not unrestricted \(K^\times/K^{\times2}\). Completeness
binds the declared \(S\)-unit generators, class-group 2-torsion, principalization witnesses, and
complete place set. Archimedean, ramified, and dyadic places are explicit.

`local_h1` denotes certified continuous \(H^1(K_v,\mu_2)\). The finite calculation
\(H^1(D_v,M)\) is exposed separately as `decomposition_quotient_h1`. Automatic \(p>2\) local
arithmetic is a typed unsupported operation in this release, although supplied finite
\(\mathbf F_p\)-presentations may still use the generic exact machinery.

`selmer` always computes a `SelmerKernel` for the supplied finite localization problem. It is
promoted to `SelmerGroup` only after the global Kummer space, all local spaces and conditions,
and the relevant place set are complete. `dual_selmer` additionally verifies a Cartier dual,
perfect local pairings, and orthogonality before accepting dual local conditions.

## Aiming, twists, and elementary descent

`aim` has two certified exact outcomes: an affine solution family with a checked representative
and uniqueness data, or a literal left-nullspace separator proving inconsistency. The reserved
`aim_a_cocycle` journey exercises both branches and combines their statements in a claim graph.

Finite nonabelian \(H^1\) is enumerated as cocycle orbits in a pointed set. For trivial
\(C_2\)-action on \(S_3\), exhaustive replay gives exactly the identity class and the conjugacy
class of transpositions. No vector-space operations or automatic twisted models are implied.

Elementary descent means Kummer/local-condition descent followed by cocycle aiming. Its terminal
values are `Realized(witness)`, `Obstructed(certificate)`, and `Unknown(reason)`. Incomplete
search, timeout, and local solubility by themselves never assert a global conclusion.

## Narrow PARI adapter

PARI/GP is optional and not bundled. The adapter generates only fixed templates for field
invariants, prime decomposition, \(S\)-unit squareclasses, class-group 2-torsion, local
squareclasses, localization matrices, relative norms, and quadratic Hilbert pairings. It exposes
no generic evaluator. Each call uses a fresh process, ignores startup files, validates exact
integer and rational inputs, applies time/resource/output limits, uses framed JSON and a
deterministic seed, and records a content-addressed receipt.

Supported versions are `>=2.15.5,<2.18.0`, with live qualification anchors at 2.15.5 and 2.17.4.
Detailed capabilities are available through `arbogast backends --name pari --json` only after
algebraic smoke tests pass. Absence, hostile startup configuration, malformed or truncated
output, mismatched request IDs, timeout, output caps, and unsupported versions fail closed.

## Runnable qualification journeys

The source archive includes bounded backend-free journeys for:

- split and nonsplit inflation--restriction behavior;
- \(\mathbf Q(\{2,\infty\},2)=\langle[-1],[2]\rangle\), its real and 2-adic localizations, and
  a one-dimensional local-condition kernel;
- \(\mathbf Q[t]/(t^2-t-1)\), including \(N(t)=-1\) and \((2t-1)^2=5\);
- solved and obstructed cocycle aiming;
- the two nonabelian twist classes for trivial \(C_2\)-action on \(S_3\);
- a local/global campaign that preserves the distinction between locally unobstructed and
  globally realized.

The release workflow runs Python 3.11 through 3.14 without requiring GP, then separately
qualifies live supported PARI versions. It builds one exact wheel, source distribution, and
commit-bound Git source archive; records their hashes and sizes in a retained qualification
report; installs the same wheel and source distribution in fresh environments with and without
GP; and runs the examples from the packaged source distribution. The live lanes also exercise the
quadratic-field journey's closed PARI discovery branch.

## Explicit deferrals

This release does not implement composite \(n\), automatic \(p>2\) local arithmetic, general
continuous \(H^1(G_K,M)\), Poitou--Tate construction, abelian-variety Selmer groups,
elliptic or hyperelliptic descent, automatic twisted models, general field-of-definition
machinery, stable reduction, or numerical recognition.

No license change or package-index publication is implied. GitHub remains the default release
destination, but the final wheel, source distribution, source archive, hashes, sizes, and release
metadata require fresh explicit approval before any publication action.
