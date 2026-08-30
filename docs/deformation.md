# Certified finite deformation theory

The 0.3 development surface is a bounded exact layer for deformation problems that have already
been reduced to finite algebra. It is not a routine that accepts an arbitrary curve, cover,
scheme, representation, or Galois object and discovers its deformation theory.

The trusted input begins with a pinned three-term complex

\[
C^0 \xrightarrow{d^0} C^1 \xrightarrow{d^1} C^2,
\qquad d^1d^0=0,
\]

over a `PrimeField`. `DeformationPresentation` binds that complex to an explicit source identity,
and `DeformationProblem` records the effective complex after any framing. All matrices use the
same column-vector convention as `arbogast.linalg`.

## Exact infinitesimal spaces

The public operations recompute the defining kernels, images, and quotients:

| Operation | Exact result |
| --- | --- |
| `gauge(problem)` | \(H^0=\ker(d^0)\) |
| `tangent(problem)` | \(H^1=\ker(d^1)/\operatorname{im}(d^0)\) |
| `obstructions(problem)` | \(H^2=C^2/\operatorname{im}(d^1)\) |
| `rigid(problem)` | `Rigid` iff the computed tangent quotient is zero; otherwise `NonRigid` with a literal nonzero class |

These statements are scoped to the supplied complex. Calling the third quotient an obstruction
space records its role in the presentation; it does not prove that the presentation captures
every obstruction of an external geometric deformation functor. Such a comparison is a separate
imported or verified claim.

## Framing

`Framing` is an explicit linear constraint on degree-zero gauge parameters. Its kernel is the
allowed gauge subspace. `frame(problem, framing)` restricts `C0` and composes its inclusion with
`d0`; it does not choose markings heuristically or silently alter the source presentation.

Framing can remove automorphisms without removing tangent directions. Consequently `gauge`,
`tangent`, and `rigid` must be recomputed on the framed problem rather than inferred from the
unframed dimensions.

## Equivariance

`DeformationAction` supplies the finite acting group and its matrices in all three degrees.
Verification checks the group law, identity, invertibility, and commutation with both
differentials. `equivariant(problem, action)` binds that action to the exact problem;
`invariant_deformations(...)` computes the fixed subcomplex and its exact spaces.

`equivariant_decomposition(...)` uses only exact supplied projector data. A label or character
name is never enough to construct a projector. In modular characteristic, where averaging by the
group order is unavailable, the operation returns a typed unsupported result unless the required
exact projectors were supplied and replayed.

## Finite Artin rings and small extensions

`ArtinRing` is a pinned finite-dimensional algebra over a prime field. Its structure constants,
unit, residue map, basis labels, and declared maximal-ideal powers are canonical data.
`ArtinRingElement` and `ArtinRingMap` retain their parent identities. A `SmallExtension` names an
explicit surjection and a complete kernel basis, then verifies exactness and the advertised
square-zero identities.

These are finite rings, not symbolic presentations of complete local rings. No completion,
power-series arithmetic, or implicit change of basis crosses the proof boundary.

## Lifts and uniqueness

`LiftDatum` contains one complete finite affine lifting problem: the small extension, base point,
linearized lift map, and requested target. `lift(datum)` returns one of two proved outcomes:

- `LiftFamily`, with a checked representative and exact homogeneous directions;
- `LiftObstructed`, with a literal left-nullspace separator.

The convenience call `lift(problem, extension)` returns `UnsupportedDeformation` unless an
object-specific target (and, when needed, a correction chart) is supplied. `LiftUnknown` is an
explicit non-conclusion used by later operations such as `fixed_lift(...)` when an endomorphism or
contraction witness is missing; it is not a failed solver branch.

Failure to find a lift is not an obstruction. `LiftObstructed` is constructed only when the
separator annihilates the lift map and evaluates nontrivially on the target.

`unique_lift(family)` is deliberately separate from existence. It returns `UniqueLift` only when
the homogeneous solution space modulo the pinned gauge image is zero. Otherwise `NonUniqueLift`
carries a nonzero mod-gauge class and two gauge-inequivalent representatives. A singleton produced
by a search budget is never treated as uniqueness evidence.

## Fixed lifts

`LiftEndomorphism` is an exact affine self-map of a pinned lift family.
`ContractionCertificate` supplies a finite exponent witnessing that the induced linear map kills
every homogeneous direction. `fixed_lift(...)` replays that witness and the fixed-point equation
before returning `FixedLift`.

Repeated iteration, apparent stabilization, floating-point contraction, or an endomorphism name
does not establish a fixed lift. Without the exact contraction witness the operation remains
unsupported or unknown.

## Certificates and claims

Within the portable receipt limits, substantial deformation results expose the same semantic
boundary as the 0.2 arithmetic layer:

```python
from arbogast.cert import verify_certificate

assert result.verify()
assert verify_certificate(result.certificate).valid
claim = result.claim()
graph = result.claim_graph()
assert claim.verify().verified
assert graph.verify().verified
```

The proving receipt is nested inside the central `VerificationCertificate`; it does not create a
new evidence layer. Canonical identities bind the field, matrices, presentations, actions, rings,
maps, lift equations, and result witnesses. Altering any of those inputs changes the certificate
subject and fails replay.

The portable verifier deliberately caps prime characteristics at 2,147,483,647, individual vector
space dimensions and finite-group orders at 256, matrix and ring-tensor payloads at 1,000,000
cells, and contraction exponents at 256. Runtime exact objects can be constructed outside some of
those transport limits, but `.certificate` rejects them; they are not certified 0.3 results.

## Fleet boundary

All 0.3 deformation operations are non-shardable. The supported kernels, quotient spaces,
equivariant restrictions, and affine lift equations are small global computations. Splitting a
matrix into rows or columns would create scheduler work units, not independent mathematical
claims, so `arbogast.deform` publishes no fleet plan for them.

## Explicit deferrals

The 0.3 slice does not provide:

- automatic complexes for schemes, curves, covers, representations, or Galois objects;
- Schlessinger criteria, pro-representability, or versal/universal deformation rings;
- arbitrary complete local rings or formal power-series computation;
- derived deformation theory or general obstruction-comparison theorems;
- general characteristic-zero or p-adic lifting and Hensel recognition;
- stable reduction or deformation data extracted from reduction; or
- numerical recognition promoted to exact deformation evidence.

See the runnable [`exact_spaces`](../examples/deformation/exact_spaces/) and
[`finite_lifts`](../examples/deformation/finite_lifts/) journeys for the complete portable input
boundary.
