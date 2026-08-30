# Certified arithmetic in 0.2

Arbogast 0.2 adds a bounded arithmetic layer above the 0.1 finite-exact core. The abstract
linear algebra and low-degree cohomology remain valid for finite modules over prime fields. The
automatic arithmetic path is deliberately narrower: number fields with pinned presentations,
squareclasses and local \(\mu _2\)-cohomology, Hilbert pairings, and 2-Selmer kernels.

This is a hybrid proof boundary. Portable Python verifiers replay every finite witness that the
certificate contains. Some completeness facts about units, ideal classes, prime decomposition,
or local fields currently require a supported, pinned PARI/GP verifier. A PARI-backed result can
be unconditional without being portable; those are separate properties.

## Three independent evidence axes

Every substantial arithmetic result records three independent axes.

| Axis | Values | Meaning |
| --- | --- | --- |
| Mathematical assumptions | `()` or labels such as `("GRH",)` | Any unresolved assumption makes the resulting claim `CONDITIONAL`. |
| Verifier trust | portable Python or a pinned external verifier | This says which implementation must be trusted to replay the certificate. It does not add or remove a mathematical assumption. |
| Completeness | `CANDIDATE` or `COMPLETE` | This says whether the declared finite object or kernel is exhaustive. A candidate is never renamed as its complete counterpart. |

For example, a successful `bnfcertify` run may remove the default GRH assumption from a
class-group computation while leaving `pari` in the verification requirement. Conversely, a
portable finite linear-algebra certificate can verify the kernel of a supplied localization
matrix without proving that the supplied global generators exhaust the arithmetic Kummer space.

The default arithmetic mode asks for an unconditional result. If the required certification
does not finish within its budget, the result is `UNKNOWN` with reason `BUDGET_EXHAUSTED`.
Callers may explicitly opt into a GRH-conditional computation; Arbogast never turns a timeout
into permission to assume GRH.

## Canonical arithmetic inputs

Canonical identities bind the mathematical presentation rather than a backend session:

- `NumberField` binds the monic defining polynomial and declared integral basis; its
  `generator_name` is display-only and does not change mathematical identity;
- `NumberFieldElement` binds exact rational coordinates in that pinned power basis;
- `FieldEmbedding` binds explicit images of the pinned generator;
- `FinitePlace` binds the rational prime, ideal HNF relative to the pinned integral basis,
  declared residue-degree and ramification-index data, and its residue-field primality witness;
- `InfinitePlace` binds an embedding and exact real isolating data or a pinned complex place;
- `FiniteGroupMap` and `FiniteGroupExtension` bind complete multiplication-table snapshots and
  every map image;
- Galois modules and finite quotients bind their concrete group actions and coefficient prime.

PARI handles, printed \(p\)-adics, stack indices, and implicit `polredbest` identifications are
not canonical data and never cross the backend boundary. A reduced polynomial may be used only
after an explicit `FieldEmbedding` transports the pinned presentation.

Degree-two and degree-three irreducibility replay portably. Higher-degree fields require an
explicit modular irreducibility witness or a pinned external verification requirement. Real
places use portable Sturm isolating data. Quadratic complex places replay exact inequalities;
higher-degree complex places carry nested PARI discovery certificates whose rational
Rouché witnesses are replayed exactly. A complete archimedean place set additionally proves
that those rectangles are pairwise disjoint and exhaust the independently certified field
signature.

## Result lifecycle

Substantial `arbogast.galois` and `arbogast.arithmetic` results expose the same four inspection
surfaces:

```python
result.verify()  # replay the result-specific witness
result.certificate  # central arbogast.verification-certificate/v1 envelope
result.claim()  # one narrowly stated semantic assertion
result.claim_graph()  # the assertion and its explicit mathematical dependencies
```

The result-specific receipt is nested inside the existing central verification certificate.
There is no parallel arithmetic evidence layer, and the 0.1 claim and central-certificate
schemas are unchanged.

The cohomological induced-map and five-term objects preserve their domain receipt at
`.certificate`; their central envelope is returned by `.verification_certificate()`. They still
provide `.verify()`, `.claim()`, and `.claim_graph()`.

The progression is intentionally one-way:

```text
backend discovery receipt
          |
          v
canonical finite witness --portable replay--> verified arithmetic result
          |                                      |
          |                                      +--> candidate or complete
          +--pinned PARI completeness replay----+--> unconditional or conditional
                                                     |
                                                     v
                                               ClaimGraph node
```

A discovery receipt records how a witness was found. It is not mathematical evidence merely
because the process exited successfully.

## Kummer spaces and local cohomology

`kummer_space` constructs the finite \(S\)-Kummer space

\[
K(S,2)=\{a\in K^\times/K^{\times 2}:v_{\mathfrak p}(a)=0\bmod 2
\text{ for }\mathfrak p\notin S\}.
\]

It does not present unrestricted \(K^\times/K^{\times 2}\) as a finite vector space.
Completeness is bound to the declared \(S\)-unit generators, class-group 2-torsion,
principalization witnesses, and the complete declared set of places. Places above 2,
ramified places, and archimedean places are explicit inputs rather than implicit conventions.

`local_h1` is reserved for genuine certified continuous \(H^1(K_v,\mu _2)\). The finite group
calculation \(H^1(D_v,M)\) for a supplied decomposition quotient is available separately as
`decomposition_quotient_h1`; Arbogast never silently identifies those two objects.

Automatic local arithmetic for \(p>2\) is outside 0.2. A certified finite presentation over
\(\mathbf F_p\) may still use the generic exact machinery, but an automatic request returns a
typed `Unsupported` result.

## Selmer kernels, duality, and aiming

A `SelmerKernel` is the exact kernel of the global-to-local quotient map for the supplied data.
It is promoted to `SelmerGroup` only when all of the following are complete:

- the global Kummer space;
- every local \(H^1\) space;
- every local condition;
- the relevant place set.

Thus the useful finite statement “these supplied matrices have this kernel” remains available
without being mislabeled as a complete Selmer computation.

`dual_selmer` additionally requires the Cartier dual \(M^\vee(1)\), a certified perfect local
Tate or Hilbert pairing at every declared place, and checked orthogonality of the paired local
conditions. Pairing nondegeneracy is verified before an orthogonal complement is accepted.

`aim` solves one finite affine local-condition problem. It has two exact branches:

- a solved branch contains a checked representative, a basis for the homogeneous family, and
  explicit uniqueness data;
- an obstructed branch contains a literal left-nullspace vector separating the target from the
  localization image.

Failed search is neither branch. See
[`examples/arithmetic/aim_a_cocycle/`](../examples/arithmetic/aim_a_cocycle/) for a runnable
journey that verifies both outcomes and combines their claims in one graph.

## Twists and elementary descent

`nonabelian_h1` exhaustively enumerates cocycles and conjugacy orbits only when the supplied
groups are finite. Its result is a pointed set, not a vector space. `twist_classes` exposes those
orbits as abstract twist classes; it does not construct equations for twisted varieties.

In 0.2, elementary descent means Kummer/local-condition descent followed by cocycle aiming. Its
terminal values are deliberately literal:

- `Realized(witness)` carries a globally checked witness;
- `Obstructed(certificate)` carries a replayable obstruction;
- `Unknown(reason)` records why neither conclusion was justified.

Local solubility alone, an incomplete place set, a failed search, or a timeout cannot become a
global existence or nonexistence claim.

## PARI boundary

The PARI adapter exposes only fixed operation-specific templates for field invariants, prime
decomposition, \(S\)-unit squareclasses, class-group 2-torsion, local squareclasses,
localization matrices, relative norms, and quadratic Hilbert pairings. There is no public generic
`gp_eval` escape hatch.

Each request uses a fresh process with startup files ignored, validated integer and rational
inputs, deterministic seeds, strict framed JSON, resource and output limits, and a
content-addressed discovery receipt. Capabilities are advertised only after algebraic smoke
tests. Supported 0.2 versions are PARI `>=2.15.5,<2.18.0`; mathematical payloads are required to
agree across the pinned CI anchors even though discovery receipts record the actual PARI version.

Inspect the detailed probe with:

```bash
uv run arbogast backends --name pari --json
```

Absence, a hostile startup configuration, malformed or truncated output, a mismatched request
identifier, a timeout, an output cap, or an unsupported version all fail closed.

## Explicit boundary of 0.2

Arbogast 0.2 does not implement composite \(n\), automatic \(p>2\) local arithmetic, general
continuous \(H^1(G_K,M)\), Poitou--Tate construction, abelian-variety Selmer groups,
elliptic or hyperelliptic descent, automatic twisted models, general field-of-definition
machinery, stable reduction, or numerical recognition. Those are deferrals, not implicit
fallbacks.

The examples index in the [README](../README.md#certified-arithmetic-journeys) links the bounded
executable workflows supplied with the source distribution.
