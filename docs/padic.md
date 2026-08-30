# Certified bounded p-adic arithmetic

Arbogast 0.5 is a finite-exact p-adic vertical slice.  It certifies arithmetic
in explicitly presented quotients \(\mathcal O_K/\pi^N\), supplied semilinear
Frobenius and inertia actions, one narrow tame three-point reduction profile,
internal rank-one special deformation identities, finite lift witnesses, and
fully witnessed descent in one pinned \(\mathbf F_p\) labeled-chart category.
It is not an infinite-precision p-adic CAS or an automatic stable-reduction and
lifting engine.

The central rule is simple: finite exact evidence may close exactly the claim
it replays.  It does not acquire a stronger geometric origin merely because it
is consistent with one.

## Canonical local arithmetic

`PAdicField` pins a monogenic presentation of \(K/\mathbf Q_p\): the prime,
monic defining polynomial, unimodular integral basis, uniformizer coordinates,
residue polynomial, ramification index, residue degree, and a rational,
unramified, or Eisenstein presentation witness.  `LocalFieldEmbedding` binds
its domain and codomain and the exact image of the pinned generator.

`PAdicPrecisionRing(field, N)` is the literal finite chain ring
\(\mathcal O_K/\pi^N\).  Its ideal lattice is stored in canonical Hermite normal
form and its independently checked cardinality is

\[
\#(\mathcal O_K/\pi^N)=p^{fN}.
\]

For example, an unramified quadratic presentation over \(\mathbf Q_3\) at
precision two has 81 elements, while the quadratic Eisenstein presentation
\(x^2-3\) at precision three has 27.  `PAdicBall` is one residue class in such
a finite ring.  It is not a selected infinite p-adic number.  Printed p-adic
expansions, backend handles, mutable session indices, and implicit changes of
presentation do not cross the canonical boundary.

`PAdicModule`, `PAdicSubmodule`, `PAdicMatrix`, and `PAdicAutomorphism` retain
the same parent identities and column-vector convention.  Parent mismatches,
noncanonical transport, or a supplied inverse/action that fails exact replay
are invalid witnesses, not mathematical non-conclusions.

## Four result states

Public computations return one of four proof-bearing variants:

| Result | Meaning |
| --- | --- |
| `Certified[T]` | The displayed bounded result is complete for its stated scope and has a `COMPLETE` proof context. |
| `Partial` | Every listed fragment is independently certified, but explicit `ProofObligation` objects block the requested conclusion. |
| `Unknown` | No mathematical conclusion was established, for example because precision or a witness is missing. |
| `Unsupported` | The exact request lies outside the implemented software surface.  This certifies a refusal boundary, not impossibility. |

A partial result with no independently certified fragment is automatically
demoted to `Unknown`.  `Partial`, `Unknown`, and `Unsupported` all carry
`CANDIDATE` completeness and cannot be renamed as successful geometric
results.  Malformed, foreign, or internally inconsistent exact witnesses raise
a validation or verification error instead of being softened into one of
these states.

Every substantial result exposes `verify()`, `.certificate`, `.claim()`, and
`.claim_graph()`.  The local receipt is nested in the existing central
`VerificationCertificate`.  It keeps mathematical assumptions, verifier
requirements, and completeness independent: a portable receipt can still be
conditional, and a successfully replayed non-conclusion is still not a
theorem about existence or nonexistence.

## Frobenius, Newton slopes, and ordinary parts

`FrobeniusOperator` binds a finite free module, an exact matrix \(A\), a pinned
finite-ring automorphism \(\sigma\), and either the arithmetic or geometric
Frobenius convention.  The action is the column-semilinear map

\[
F(v)=A\,\sigma(v).
\]

For residue degree \(f\), the implementation checks \(\sigma^f=1\) at the
declared precision and forms the linearized product
\(A\sigma(A)\cdots\sigma^{f-1}(A)\).  `slopes` uses the division-free
characteristic polynomial of that product.  Coefficients carry exact valuation
intervals; if finite precision does not determine every necessary
Newton-polygon vertex, the answer is `Unknown` with reason
`ambiguous-newton-polygon`.

Slope normalization uses \(v_p(p)=1\) and divides the Newton slopes of the
linearized characteristic polynomial by the semilinear period.  The selected
arithmetic/geometric convention is never silently inverted.

A certified Newton polygon proves multiplicities, not a direct-sum
decomposition.  `ordinary_part` therefore requires an explicit saturated,
Frobenius-stable slope-zero `SlopeProjector`, including an invertible basis
change and its inverse.  Without it the result is `Unknown` with reason
`missing-saturated-projector`.  The
[`frobenius_slopes`](../examples/padic/frobenius_slopes/) journey exercises both
branches.

## Finite inertia is not a recovered local ramification filtration

`FiniteInertiaQuotient` pins one explicitly enumerated finite group, residue
characteristic and degree, source/place labels, and exact multiplication data.
It records `arithmetic_origin_claimed == False`: no local extension, valuation,
or decomposition-group presentation is reconstructed from those labels.

`InertiaFiltration` is a declared finite group-theoretic series. It checks the
listed nested normal subgroups, the tame quotient order, and the implemented
tame/wild quotient identities, but records
`arithmetic_lower_numbering_claimed == False`. Consequently its display label
`numbering="declared-indexed-series"` keeps the supplied finite levels from
masquerading as a theorem that every valuation-defined lower ramification group
has been found.
`inertia_action` exhaustively replays the matrix action of that pinned quotient
and, when supplied, the exact Frobenius--tame-generator relation. It does not
claim a continuous inertia, Weil, or decomposition-group representation.

## Exact three-point covers and tame good reduction

`ThreePointCover` is an exact normalized polynomial map with complete rational
linear factorizations of the fibres above \(0,1,\infty\), a complete finite
critical divisor, its generic degree, and a genus-zero Riemann--Hurwitz witness.
The constructor does not infer missing projective points or accept a matching
cycle-shape label in place of exact factorization.

The automatic 0.5 geometry lane is intentionally narrow.  For

\[
\beta(z)=\frac{27}{4}z^2(1-z)
\]

at \(p=5\), `good_reduction`, `semistable_reduction`, and
`stable_reduction` certify the displayed good model, its one source and one
target component, its marked ramification points, zero nodes, and the exact
stability inequalities.  The ramification profiles are
\((2,1),(2,1),(3)\), so the cover is tame at five.

This lane does not discover extensions, perform blowups, contract components,
or construct a non-good semistable model.  Other primes, other presentations,
and even a coordinate-reflected beta presentation at five return `Unsupported`
with reason `outside-beta-p5-certified-slice`.  `Unknown` is reserved for a
sufficient-check failure inside the exact supported profile.  Neither outcome
proves bad or potentially bad reduction.  See
[`three_point_good_reduction`](../examples/padic/three_point_good_reduction/).

## Special deformation data: internal identities versus origin

`RationalDifferential(p, u)` stores the literal logarithmic form \(du/u\) for
a square-free monic \(u\in\mathbf F_p[x]\); its numerator, denominator, and
Cartier identity are recomputed.  `DeformationSignature` stores exact critical
triples \((\text{label},m,h)\) and \(\sigma=h/m\).  `SpecialityWitness` replays
the implemented normalized numerical criterion at the labels zero, one, and
infinity.  A direct `DeformationDatum` also checks its finite tame character.

Such a datum may be `Certified` with completeness scope
`componentwise-rank-one-tame-formal-identities`.  That means each logarithmic,
Cartier, character, and special-signature component passes its internal
equations.  The object also records
`differential_signature_relation_claimed == False` and
`componentwise-formal-identities-no-divisor-or-point-binding`: version 0.5
does not identify the signature labels with points or the divisor of the
differential.  It does **not** mean that the datum was extracted from a stable
cover.

Geometric extraction is a separate `deformation_datum(stable, witness=...)`
operation.  The 0.5 stable-reduction profile contains marked components but no
group action, inertia character, differential extraction rule, or Wewers
comparison theorem.  Without a witness the result is `Unknown`; an ID-bound
synthetic witness cannot bridge the missing profile and remains `Unsupported`.
The distinction is executable in
[`special_deformation_datum`](../examples/padic/special_deformation_datum/).

## Finite lifts and rigid descent

The lift layer starts from a certified internal deformation datum and a
`LiftChart`: one monic equation over \(\mathbf F_p\) plus labeled polynomial
model coordinates in its parameter.  `LiftEnumerationWitness` exhausts every
field element, retains exactly the roots, and evaluates every displayed model.
`lift_set` is therefore complete only in that pinned chart.  It deduplicates
only literal labeled-model equality and never calls this a global Wewers lift
classification.

`FiniteLiftAction` is a checked group homomorphism into permutations of that
finite set; it is not yet arithmetic.  The positive 0.5
`lift_galois_action` lane accepts only a `COMPLETE` certified **trivial**
`FiniteGaloisQuotient`, the identity permutation of lift classes, and one exact
identity model-coordinate permutation per lift.  Missing coordinate maps
return `Unknown` with reason `unverified-arithmetic-model-transport`;
nontrivial complete quotients are `Unsupported`.  Transport labels never prove
an action on model coefficients.  `fixed_lifts` then exhausts the fixed classes
but records `descent_claimed == False`.

Rigid descent is another independent step.  A fixed lift is not automatically
a descended model: `AutomorphismTrivialityWitness` exhausts automorphisms in
the pinned label-preserving coordinate category; `DescentCocycle` supplies one
invertible isomorphism per arithmetic quotient element and checks the group
law; `RigidDescentWitness` adds an explicit coefficient vector and two-sided
base change.  Missing descent data make `effective_descent` `Unknown`.  Only a
fully replayed witness returns `Certified[DescendedModel]`, and that result is
scoped to `prime-field-F_p-chart-coefficients` and
`effective-descent-in-pinned-F_p-labeled-chart-model-category`.  It explicitly
sets characteristic-zero, number-field, and geometric-cover descent claims to
false.

The exact constructors and both closing and non-closing branches are shown in
[`lifts_rigid_descent`](../examples/padic/lifts_rigid_descent/).

## The M23 local frontier

The checked-in M23 Hurwitz dataset remains a complete finite theorem about the
pinned permutation group and passport: it verifies 7,114 product-one inner
orbits, 1,428 generating inner Nielsen classes, one pure-braid component, and
the exact real census.  None of those finite facts supplies an equation for a
cover, a local field model, stable reduction, a Wewers datum, a lift, or a
descent witness.

`reduction_frontier(m23_dataset, prime=...)` first replays the exact dataset and
then returns `Unsupported`: the public fixture is four-point finite data, while
the automatic reduction lane requires an explicit three-point equation and
local witnesses.  By contrast, a certified `LocalFactorizationFragment`
returns `Partial`; its complete displayed mod-\(p\) factorization survives as a
certified fragment, alongside exact obligations for cover binding, stable
reduction, fixed lifts, and effective descent.  Locally plausible fragments
and unsupported automation never become a global M23 model.  The
[`m23_local_frontier`](../examples/padic/m23_local_frontier/) journey makes that
boundary machine-checkable.

## Resource and fleet boundary

Canonical p-adic transports are fail-closed and bounded.  The shared envelope
allows 256-bit primes, local degrees and module dimensions at most 64, finite
precision at most 4,096 uniformizer powers, and lift collections at most 4,096
entries.  The initial local-field constructors are narrower: the prime is at
most 2,147,483,647, degree at most 16, and precision at most 256; the direct
deformation-datum slice caps its finite-field prime at 65,537.  Composite
receipts also enforce bounded size, depth, dependencies, assumptions, and proof
obligations.  These are serialization ceilings, not a claim that every public
operation supports the full range; individual lanes are frequently narrower.

The 0.5 p-adic operations are non-shardable.  Their local-field, reduction,
lifting, and descent witnesses are globally coupled exact records; splitting
one by coefficient or matrix row would create scheduler tasks rather than
independent mathematical claims.

## Explicit deferrals

Version 0.5 does not provide arbitrary infinite-precision p-adic arithmetic,
automatic local-field recognition, general Newton-slope submodule
construction, wild or non-good stable-reduction discovery, automatic Wewers
extraction, general p-adic Hensel lifting, nontrivial arithmetic actions on lift
models, characteristic-zero or number-field effective descent, automatic cover
construction from a Nielsen class, or an automatic M23 local/global model.  A
future implementation of any of these needs a new exact proof boundary; it
cannot be inferred from a successful bounded receipt.
