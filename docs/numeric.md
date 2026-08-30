# Certified numeric-to-exact bridge

Arbogast 0.4 adds a bounded bridge between exact finite presentations and validated numerical
evidence. The public `arbogast.numeric` package does not accept ambient Python floats, run an
unbounded numerical solver, or promote a plausible decimal to an algebraic theorem. It records
exact dyadic input, closed certified enclosures, explicit witnesses, and the precise conclusion
that those witnesses replay.

## Canonical numerical data

`Dyadic(mantissa, exponent)` means exactly

\[
\mathtt{mantissa}\,2^{\mathtt{exponent}}.
\]

Nonzero mantissas are normalized to be odd. `ComplexDyadic` is a pair of exact dyadics;
`RealBall` and `ComplexBall` are closed enclosures with exact dyadic centers and radii. Binary and
decimal floating-point values are deliberately absent from the canonical boundary.

`ExactPolynomial`, `PolynomialSystem`, and `PolynomialFamily` retain ordered sparse terms,
variable names, and exact complex-dyadic coefficients. `ParameterPath` is an exact piecewise
linear path. `NumericPoint` binds closed coordinate balls to one exact system. `ExactCover` and
`NumericalCover` retain the cover degree, ordered branch divisor, ordered sheets, and their exact
or numerical branch data; reordering either order is a semantic change, not harmless presentation
cleanup.

The wire formats have explicit serialization caps: a normalized dyadic mantissa has at most 4,096
bits and its exponent has absolute value at most 1,000,000; a system has at most 64 variables and
256 equations, while each polynomial has at most 4,096 terms and total degree 256; a path or tube
has at most 4,096 vertices or
steps; recognition metadata can record degree at most 64 and height at most \(2^{256}\); and a
finite planning graph has at most 100,000 vertices and 1,000,000 directed generator edges. These
are transport limits, not promises that every operation supports the full serialized range.
The enclosing portable receipt is also bounded to 100,000 canonical nodes, nesting depth 128,
16,384 characters per text value or mapping key, 256 direct dependencies, and 256 assumptions.
Those global envelope bounds can make a composite object hit its limit before an individual
per-object maximum such as 4,096 tube steps or 100,000 graph vertices.

The automatic 0.4 operations are narrower. Certified covers are degree-two covers presented by
one monic quadratic equation in one sheet variable and one parameter; the exact discriminant must
factor over the complete declared finite branch divisor, and its degree parity determines whether
the projective branch at infinity is present. Automatic recognition accepts real-centered balls
only and exhausts degree at most 2 and height at most 16. Larger but serializable recognition
bounds return `UnsupportedNumeric`; they are not silently searched.

## Public operations

The 0.4 functions consume explicit data and witnesses:

| Operation | Certified scope |
| --- | --- |
| `continue_path(system, point, path, *, tube=...)` | Replays a supplied continuation tube and returns a validated numerical endpoint. |
| `condition_number(system, point, *, inverse_jacobian=...)` | Returns a certified `RealBall` condition bound; it does not infer global stability. |
| `branch_cycles(cover)` | Returns an `EXACT`, proof-bearing `NielsenTuple` subtype only after complete separated continuation replay yields one unambiguous discrete tuple. |
| `bind_vertex(cover, nielsen_class, *, vertex=...)` | Returns the exact canonical `NielsenVertex` only after that tuple literally matches one vertex of a computed-complete Nielsen class. |
| `braid_continue(cover, word, *, witness=...)` | Returns the input `NumericalCover` for the identity word and an exact `BraidContinuationResult` for a replayed normalized quadratic (B_2) generator or inverse. Absent, local-sheet-only, and general-word cases remain typed non-conclusions; a witness bound to a different cover or word is rejected as invalid input. |
| `recognize(ball, bounds=...)` | Returns a bounded compatible `AlgebraicCandidate` or a typed non-conclusion. |
| `exactify(point, *, candidate=..., bounds=...)` | Independently substitutes and checks a supplied candidate, or performs bounded recognition when only `bounds` is supplied. `candidate` and `bounds` are mutually exclusive. |
| `projection_degree(H, functions, *, regular_fiber_witness=..., generic_witness=...)` | Records a regular-fiber count or, only with the stronger exact witness, a certified generic degree. The regular-fiber and generic witnesses are mutually exclusive. |
| `weighted_braid_plan(action, source, target, costs)` | Finds and exactly replays a lowest-cost path in the supplied finite braid action and cost map. |

Every supported operation is non-shardable. The current objects and witnesses are bounded,
globally coupled records; splitting a polynomial, tube, or finite path into scheduler chunks would
not create independently meaningful mathematical claims.

## Continuation is numerical evidence

A `ContinuationTube` specifies the exact path segments, accepted enclosures, and separation or
correction bounds that make the numerical replay meaningful. Successful replay certifies the
stated tube and numerical endpoint. It does not prove that an independently named exact braid
target was reached. In particular, the local sheet-loop witnesses used to recover branch cycles
are not a homotopy of the cover coefficients. The 0.4 `braid_continue` implementation accepts the
identity word as a passthrough and has one genuine nontrivial exact slice: for the normalized
(x^2-t(t-1)) cover, `QuadraticB2Homotopy` replays explicit coefficient, branch, collision, and
sheet-path polynomial identities for one (\sigma_0) generator or inverse. It returns an exact
`BraidContinuationResult`. Missing witnesses, the older local-sheet witness, unwitnessed
unsupported covers, and general braid words remain `NumericUnknown` or `UnsupportedNumeric`.
A supplied witness whose cover, word, endpoints, or action do not match is rejected with
`NumericError`; malformed evidence is not a mathematical non-conclusion.

Increasing precision can narrow an enclosure or make a new witness available. Precision by
itself is not a proof rule. Likewise, numerically real branch coordinates do not imply that a
normalized exact cover has real coefficients or descends to a real model.

## Recognition and exactification

`recognize` searches only within explicit degree and height bounds. A returned
`AlgebraicCandidate` says
that one algebraic relation is compatible with the closed input ball and declared bounds. It is
not an exact value and cannot close an exact claim.

`exactify` is a separate operation. It binds the candidate to the requested coordinate and exact
polynomial system, substitutes the exact relation, and replays the resulting equalities. Failure
to isolate one candidate, insufficient precision, or an unsupported coefficient field returns
`NumericUnknown` or `UnsupportedNumeric`; it is never rephrased as nonexistence.

## Regular fibers and generic degree

For a projection, the number of distinct solutions in one supplied regular fiber is a theorem
about that fiber. It may be useful numerical or exact evidence, but it is not automatically the
generic degree of the projection. `RegularFiberDegree` and `DegreeResult` retain that distinction.
The generic conclusion is present only when an exact generic witness establishes the
required algebraic nondegeneracy and completeness conditions.

## Weighted braid planning

`weighted_braid_plan` operates on a supplied finite `BraidAction`. It exactly compares accumulated
nonnegative generator costs, returns the selected word and vertex path, and replays that word to
the target. Its optimality is relative to that action graph and cost map. It does not claim a
geometric shortest path or alter the existing `arbogast.hurwitz.weighted_braid_path` API.

## Certificates, claims, and typed non-conclusions

Substantial results expose `verify()`, `certificate`, `claim()`, and `claim_graph()`. Their local
`arbogast.numeric.*-receipt/v1` proving receipt is nested in the unchanged central
`VerificationCertificate` and replayed by the allowlisted `numeric.exact-bridge.v1` verifier.

Claim status describes the conclusion, not merely whether receipt replay succeeded:

- validated balls, condition bounds, continuation endpoints, raw branch trackings, numerical
  covers, and recognition candidates are `NUMERICAL`;
- independently replayed exactification, complete discrete `BranchCycleTuple`, literal complete
  `NielsenVertex` binding, `QuadraticB2Homotopy` results, generic-degree witnesses, and finite
  weighted-action proofs may be `EXACT`;
- unresolved assumptions remain `CONDITIONAL`; and
- `NumericUnknown` remains `UNKNOWN` while `UnsupportedNumeric` certifies only its refusal scope.

The three runnable journeys are
[`two_sheet_cover`](../examples/numeric/two_sheet_cover/),
[`sqrt2_exactification`](../examples/numeric/sqrt2_exactification/), and
[`weighted_braid_plan`](../examples/numeric/weighted_braid_plan/).
