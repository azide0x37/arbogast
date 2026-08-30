# Arbogast 0.3.0 release notes

Arbogast 0.3.0 is a bounded, certificate-first deformation-theory slice over the immutable 0.1
finite-exact core and the additive 0.2 arithmetic layer.

## Release scope

The public `arbogast.deform` package adds:

- pinned finite Artin rings, elements, maps, and small extensions over prime fields;
- explicit three-term deformation complexes and finite deformation presentations;
- exact gauge, tangent, and obstruction spaces;
- explicit framings and finite equivariant deformation actions;
- invariant spaces and supplied-projector equivariant decompositions;
- finite lift families, literal lift obstructions, and typed unknown outcomes;
- separate uniqueness and rigidity results;
- fixed lifts certified by explicit endomorphisms and contraction witnesses; and
- central verification certificates, semantic claims, and claim graphs for substantial results.

The operations are additive. Existing 0.1 and 0.2 APIs, schema identifiers, certificate IDs, CLI
contracts, and published artifacts remain compatibility inputs rather than objects to regenerate.

## Proof boundary

The automatic layer begins with finite exact data. A `DeformationComplex` is a pinned complex

\[
C^0 \xrightarrow{d^0} C^1 \xrightarrow{d^1} C^2
\]

over a prime field with \(d^1d^0=0\). A deformation presentation says how that complex and its
finite equations model the problem at hand. Arbogast verifies the supplied algebra and computes
the resulting quotient spaces; it does not manufacture a comparison theorem between that
presentation and an unmodeled geometric or arithmetic deformation functor.

Framings, group actions, projectors, lift maps, and fixed-lift endomorphisms are explicit inputs.
The verifier replays their identities. In particular:

- a tangent vector is not automatically an effective deformation;
- an obstruction-space element is not automatically a complete geometric obstruction;
- a vanishing obstruction does not imply a lift unless the finite lift equations are solved;
- existence and uniqueness are separate claims;
- a repeated iterate is not a certified fixed lift; and
- a fixed lift is promoted only when the endomorphism and contraction witness replay exactly.

The supported computations are small globally coupled finite linear systems. They are therefore
advertised as non-shardable in 0.3. No fleet planner is published merely to split matrix rows or
columns without an independent mathematical reduction boundary.

Portable receipts enforce explicit transport caps: prime characteristics at 2,147,483,647,
individual dimensions and finite-group orders at 256, matrix and ring-tensor payloads at
1,000,000 cells, and contraction exponents at 256. Verification and receipt formation reject
objects outside those limits; constructors may enforce the same boundary eagerly.

## Runnable journeys

The portable examples require no external backend:

- `examples/deformation/exact_spaces/` checks gauge, tangent, obstruction, framing,
  equivariance, invariant decomposition, rigidity, and semantic claim graphs.
- `examples/deformation/finite_lifts/` checks solved and obstructed lift branches, unique and
  non-unique outcomes, and a contraction-certified fixed lift.

## Explicit deferrals

This release does not claim automatic construction of deformation complexes from schemes,
curves, covers, representations, or Galois objects; Schlessinger criteria or pro-representability;
versal or universal deformation rings; arbitrary complete local rings; formal power series;
derived deformation theory; general obstruction comparison theorems; numerical recognition;
stable reduction; or general p-adic and characteristic-zero lifting.

## Release integrity

The final wheel, sdist, and source archive are qualified as exact files before publication. The
0.1.0 and 0.2.0 API, CLI, schema, certificate, release-note, and published-asset fixtures remain
immutable inputs. After publication, 0.3.0 receives the same compatibility snapshot before any
0.4 metadata is changed.
