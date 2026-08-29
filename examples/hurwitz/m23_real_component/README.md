# Exact M23 real component

This flagship example independently verifies a complete finite result for the generating inner
Nielsen class

\[
\operatorname{Ni}^{\mathrm{in}}(M_{23};2A,3A,6A,2A).
\]

The checked-in witness dataset was discovered with GAP, but verification now runs through
Arbogast's public typed `M23ExactDataset`/`M23ExactCertificate` API. Its finite replay uses only
the Python standard library; it neither invokes GAP nor repeats the search. Successful replay
produces six independently claim-bound `COMPUTED`, `CERTIFIED` nodes in the public
`ClaimGraph` workflow.

## Verified result

The fresh-process verifier checks all of the following:

| Finite statement | Verified value |
| --- | ---: |
| Product-one inner orbits in the full passport | 7,114 |
| Generating inner Nielsen classes | 1,428 |
| Intransitive nongenerating product-one orbits | 5,686 |
| Standard pure-braid generators | 6 |
| Serialized forward pure-braid transitions | 8,568 |
| Generating inner classes fixed by the straight real involution | 70 |
| Generating classes satisfying the strict \(c=1\) criterion | 20 |
| Nongenerating strict \(c=1\) representatives | 212 |

The six positive pure generators contribute \(1428\cdot6=8568\) serialized transition and
conjugator records. Each generator table is checked to be a permutation, so its inverse table is
certified without duplicating it in the fixture; counting both signs gives 17,136 directed moves.

The distinction between 70 and 20 is mathematical, not cosmetic. Seventy inner classes are fixed
after allowing the recorded inner conjugator. Exactly 20 canonical generating representatives
are fixed with the literal conjugator \(c=1\). Those 20 exhaust the **generating inner Nielsen
class** because the completeness verifier proves that every other product-one inner orbit is
intransitive and nongenerating.

The 212 nongenerating strict \(c=1\) representatives are retained as an explicit guardrail. It is
correct to say “no hidden generating \(c=1\) component”; it is false to make an unqualified
no-hidden-\(c=1\) statement over every product-one tuple.

## Run the two stages

```bash
uv run python examples/hurwitz/m23_real_component/compute.py \
  --output /tmp/m23-claims.json
uv run python examples/hurwitz/m23_real_component/verify.py \
  /tmp/m23-claims.json
```

Representative output is:

```text
fixture verified through arbogast.hurwitz: 1428 generating inner classes, 20 c=1, 70 inner-real fixed
completeness: 7114 product-one inner orbits = 1428 generating + 5686 intransitive
claim graph: 6 computed, 6 certified
fixture verification: valid through arbogast.hurwitz (1428 generating, 5686 nongenerating)
real census: 20 generating c=1; 212 nongenerating c=1 guardrail; 70 inner-real fixed
claim graph: 6 computed, 6 certified
```

`compute.py` calls `load_m23_exact_dataset`, `m23_claim_graph_for`,
`m23_certificates_for`, and `m23_verifier_registry` from `arbogast.hurwitz`. `verify.py` starts a
new process, replays the typed dataset again, reconstructs the specialized certificate, every
claim-bound certificate, the graph, and the source/provenance registry, then rejects any
projection that differs from the verified conclusions. A content-addressed summary alone cannot
verify: `M23ExactCertificate.verify(...)` requires the fully replayed typed dataset.

## What is checked

The completeness proof fixes the first entry \(a\) in the pinned 2A class, partitions the 3A
entry \(b\) into the 35 orbits of \(C_{M_{23}}(a)\), and ranges over the full 2A class for the
last entry \(d\). Product one forces

\[
c=(ab)^{-1}d.
\]

Every accepted \(c\) carries an explicit conjugator from the pinned 6A representative; matching
cycle shape alone is not accepted. Residual centralizer orbits then give all 7,114 simultaneous
inner orbits. The verifier checks that the 1,428 stored component vertices are exactly the
generating part: a seed generates the pinned M23, pure braid moves preserve generation, and all
5,686 representatives in the complement are intransitive on 23 points.

For the generating class it also checks:

- the pinned standard degree-23 M23 generators with a Schreier order certificate;
- class membership, product one, inner canonicality, and uniqueness;
- every forward pure-braid edge and canonicalizing conjugator;
- bijectivity, closure, and transitivity of the six pure-generator tables;
- the complete straight-real permutation and its involution identity;
- all 70 inner-fixed indices and all 20 strict \(c=1\) indices.

## Custody, discovery, and proof

The files have deliberately different roles:

- `generate.g` is the discovery and regeneration program. It requires GAP and is not in the
  verifier's trusted base.
- `expected/generation-receipt.json` records the discovery backend, command, conventions, and
  output identities.
- `expected/dataset.json` contains the precomputed finite witnesses. Precomputation is custody,
  not proof by itself.
- `expected/manifest.json` binds artifact hashes, counts, provenance, and scope.
- `expected/sources.json` is a typed `SourceRegistry` sidecar for the Häfner convention and ATLAS
  nomenclature. It is context and provenance, not proof of any count.
- `arbogast.hurwitz.m23_exact` is the public typed loader, finite verifier, certificate adapter,
  and six-node ClaimGraph projection.
- `fixture.py` is only a compatibility wrapper around that public API.
- `compute.py` and `verify.py` are thin public-workflow consumers.

The supplied brief's expected values remain provenance for what was sought; they are not used as
proof. Likewise, a successful artifact hash or resolved literature reference proves identity and
context, not mathematics. The computed claim status is licensed only by replaying the finite
witnesses. The emitted claims expose their hypotheses, dependency edges, source keys, derivation,
specialized certificate ID, and projection provenance record separately.

## Theorem boundary

This certificate proves the complete generating inner Nielsen class for the pinned concrete M23
embedding, its pure-braid transitivity, and the stated straight-real census. It does not:

- construct equations for a Hurwitz curve or a rational model;
- identify a field of definition;
- compute a Hurwitz-component genus;
- prove that the finite result is novel in the literature;
- turn the 212 nongenerating \(c=1\) representatives into Nielsen-class points.

The dataset records its one-based GAP permutation convention, while the verifier converts it to
zero-based internal tuples and replays the specified right action exactly. The pure-braid words
follow the convention in
[Häfner, arXiv:2202.08222v3](https://arxiv.org/abs/2202.08222), as summarized in
[Mathematical conventions](../../../docs/mathematical-conventions.md). The paper supplies the
action convention, not evidence for the verified counts. The
[ATLAS M23 entry](https://brauer.maths.qmul.ac.uk/Atlas/v3/spor/M23/) supplies the group/class
nomenclature sidecar; exact group order and class membership are still replayed from the finite
witnesses.
