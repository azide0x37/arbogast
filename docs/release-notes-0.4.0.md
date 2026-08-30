# Arbogast 0.4.0 release notes

Arbogast 0.4.0 adds a bounded, certificate-first numeric-to-exact bridge to the immutable 0.1
finite-exact core and the additive 0.2 arithmetic and 0.3 deformation layers.

## Release scope

The public `arbogast.numeric` package adds:

- canonical exact dyadics, complex dyadics, and closed real and complex balls;
- sparse exact polynomial systems and families, exact parameter paths, numerical points, and
  exact and numerical cover presentations;
- witnessed continuation tubes and local condition bounds;
- exact discrete branch-cycle recovery only after complete separated continuation replay, and a
  separate exact Nielsen-vertex binding only after a literal computed-complete class match;
- a typed braid-continuation operation with identity-word passthrough, one exact normalized
  quadratic (B_2) generator/inverse coefficient homotopy, and typed non-conclusions beyond that
  bounded slice;
- bounded algebraic recognition followed by independently verified exactification;
- projection results that distinguish a regular-fiber count from a certified generic degree;
- exact weighted braid planning over a supplied finite action and cost map;
- typed `NumericUnknown` and `UnsupportedNumeric` non-conclusions; and
- independently versioned numeric receipts nested in central certificates and claim graphs.

These additions do not change `arbogast.hurwitz.weighted_braid_path` or any 0.1, 0.2, or 0.3
function signature, schema identifier, certificate contract, or published compatibility fixture.

## Proof boundary

The canonical numerical boundary contains exact dyadic data, not floats or printed decimal
approximations. A closed ball, condition bound, or continuation tube can carry a portable
certificate that its stated inequalities replay. That certifies numerical evidence; it does not
identify an exact algebraic value or exact braid target.

Serialization bounds and operational support are separate. Automatic cover certification is
restricted to one monic quadratic equation in a sheet variable and parameter, degree 2, with the
complete exact discriminant divisor (including the parity-determined infinity branch). Automatic
recognition accepts real-centered balls only, degree at most 2, and height at most 16. Larger
serializable recognition bounds return `UnsupportedNumeric`.

Every runtime snapshot and receipt also fits a global portable envelope: at most 100,000
canonical nodes, nesting depth 128, 16,384 characters per text value or key, 256 dependencies,
and 256 assumptions. These global bounds can narrow advertised per-object serialization maxima
for composite tubes and graphs.

Recognition and exactification are deliberately separate. `recognize` returns only a candidate
compatible with a ball and explicit degree and height bounds. `exactify` must independently bind
that candidate to an exact polynomial system and replay the exact substitutions. Ambiguity,
insufficient precision, and unsupported scope remain typed non-conclusions.

`projection_degree` also preserves two different theorems. A supplied regular-fiber witness can
certify the number of solutions in that fiber. Only a stronger exact generic witness can certify
generic degree. Neither higher precision nor a regular sample silently strengthens the claim.

Numerically real branch points do not imply a real normalized model. Local sheet-loop evidence is
not a cover-coefficient homotopy. The one nontrivial `braid_continue` success in 0.4 is the exact
`QuadraticB2Homotopy` for the normalized (x^2-t(t-1)) cover and one (\sigma_0) generator or
inverse. Absent, local-sheet-only, unwitnessed unsupported-cover, and general-word cases remain
typed non-conclusions; a witness bound to a different cover, word, endpoint, or action is rejected
as invalid input. Weighted optimality is relative to the supplied finite action and costs, not to
an undeclared geometric metric.

## Runnable journeys

The portable examples require no external algebra backend:

- `examples/numeric/two_sheet_cover/` validates a two-sheet cover, recovers its numerical branch
  cycles, binds an exact Nielsen vertex, proves the supported normalized quadratic \(B_2\)
  generator homotopy, retains missing-witness and general-word continuations as typed unknowns,
  and rejects reordered branch evidence.
- `examples/numeric/sqrt2_exactification/` recognizes a bounded candidate for sqrt(2), exactifies
  it against an exact polynomial, retains an insufficient-precision unknown branch, and rejects a
  tampered receipt.
- `examples/numeric/weighted_braid_plan/` finds a lower-cost path with more edges in a supplied
  finite action, exactly replays its word, and shows that the word alone cannot authorize a
  numerical endpoint or exact target claim.

## Release integrity

The source-tree checker and wheel, sdist, and Git-source qualifier require the complete numeric
package, this documentation, all three runnable journeys, and their strict acceptance tests for
0.4 and later releases. Requirements for older releases remain additive and version gated. The
compatibility index names only published immutable snapshots. The 0.3 fixture is generated from
the published `v0.3.0` tag and its exact release-asset hashes; no unreleased 0.4 fixture is invented.
