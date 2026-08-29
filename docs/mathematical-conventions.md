# Mathematical conventions

Certificates are portable only when indices, actions, multiplication, and quotient choices are
explicit. These conventions are part of Arbogast 0.1.0's public contract.

## Indexing

Python and interchange indices are zero-based. Permutation points are
`0, ..., degree - 1`; braid generator `sigma(i)` acts on tuple slots `i` and `i + 1`.
Human-facing exports may render one-based mathematical notation, but must record the transport.

## Permutations and composition

A permutation is stored in one-line form: `images[i]` is the image of `i`. Its concrete degree is
part of its value, including trailing fixed points.

Composition is function composition:

```text
p * q means p after q
(p * q)(i) = p(q(i))
```

Arbogast never silently extends a permutation by fixed points. It also never silently identifies
conjugate concrete group embeddings. Moving between embeddings requires an explicit transport;
conjugation by `t` is `t * p * t.inverse()`.

## Finite groups

The pure-Python group type is a concretely embedded finite permutation group. Closure is
enumerated exactly for modest finite workloads. Elements and generators have deterministic
ordering, and generation witnesses are replayable words in the pinned ordered generator tuple.

An abstract isomorphism does not make elements interchangeable. Certificates bind the concrete
degree, generators, elements, and embedding fingerprint required by their operation.

## Prime fields and linear maps

The 0.1 exact linear-algebra core supports prime fields \(\mathbf F_p\), represented by canonical
integer residues in `range(p)`. `FiniteField` is an alias for `PrimeField`; it does not pretend
that extension fields are implemented.

An \(m\)-by-\(n\) matrix represents a map

\[
A : \mathbf F_p^n \longrightarrow \mathbf F_p^m
\]

acting on column vectors. Matrices are exposed in row-major form. `A @ B` means ordinary matrix
multiplication, so \(B\) acts first. Kernel vectors live in the domain; image vectors live in
the codomain.

An RREF certificate includes an invertible row-operation witness \(E\) with \(EA=R\). An
inconsistent system \(Ax=b\) can be obstructed by a row vector \(y\) with \(yA=0\) and
\(yb\ne0\). These identities are checked rather than inferred from a solver status string.

## Group cohomology

Group cohomology uses a **left** action on column vectors and the normalized inhomogeneous bar
complex. Normalized \(n\)-cochains are represented on tuples of nonidentity group elements; a
cochain is understood to vanish when any argument is the identity.

For an \(n\)-cochain \(f\), the differential is

\[
(df)(g_1,\ldots,g_{n+1}) =
g_1 f(g_2,\ldots,g_{n+1})
+ \sum_{i=1}^{n}(-1)^i
f(g_1,\ldots,g_i g_{i+1},\ldots,g_{n+1})
+ (-1)^{n+1}f(g_1,\ldots,g_n).
\]

Thus \(H^n(G,M)=\ker(d_n)/\operatorname{im}(d_{n-1})\). Certificates include the finite
multiplication table and action matrices, reconstruct the bar differentials, check \(d^2=0\),
recompute kernel and image, and verify explicit quotient projection and section maps.

Only prime-field coefficients are supported by this 0.1 implementation. Complexity limits are
checked before constructing a bar complex; increasing a limit is an explicit caller decision.

## Nielsen classes

An ordered Nielsen tuple \((g_1,\ldots,g_r)\) is valid only when:

1. each \(g_i\) lies in the explicitly supplied conjugacy class \(C_i\);
2. the product \(g_1\cdots g_r\) is the identity under the pinned group multiplication;
3. the entries generate the full pinned concrete group.

Inner equivalence is simultaneous conjugation inside that same concrete group. A canonical inner
representative is accompanied by a conjugator witness. Enumerating representatives proves
completeness only when the certificate also covers all valid raw tuples and their inner-orbit
partition.

## Hurwitz braid action

Arbogast uses the right Hurwitz action. The zero-based standard generator `sigma(i)` replaces
adjacent entries \((a,b)\) by

\[
(a,b) \longmapsto (aba^{-1},a),
\]

and its inverse sends

\[
(a,b) \longmapsto (b,b^{-1}ab).
\]

This matches equations (2.4)--(2.5) of
[Häfner, arXiv:2202.08222v3](https://arxiv.org/abs/2202.08222), translated to zero-based
Python slots. A `BraidWord` is applied from left to right in stored order; `first.then(second)`
applies `first` and then `second`.

For zero-based strands \(i<j\), the generic `pure_braid_word(i, j)` API uses the basis

\[
G_{i,j}=\sigma_{j-1}^{-1}\cdots\sigma_{i+1}^{-1}\sigma_i^2
        \sigma_{i+1}\cdots\sigma_{j-1}.
\]

In code-like notation this is

```text
sigma(j-1)^-1 ... sigma(i+1)^-1 sigma(i)^2
sigma(i+1) ... sigma(j-1)
```

The compact M23 example instead pins the basis displayed by Häfner (with his braid indices
translated to zero-based Artin generators):

\[
H_{i,j}=\sigma_i^{-1}\cdots\sigma_{j-2}^{-1}\sigma_{j-1}^2
        \sigma_{j-2}\cdots\sigma_i.
\]

Thus, for example, its `beta13` word is
\(H_{0,2}=\sigma_0^{-1}\sigma_1^2\sigma_0\), whereas the generic API returns
\(G_{0,2}=\sigma_1^{-1}\sigma_0^2\sigma_1\). These are different individual braid words,
not interchangeable edge labels.

Both bases consist of pure braids and generate the same pure braid group \(P_n\). More
precisely, the reflection automorphism
\(\phi(\sigma_k)=\sigma_{n-2-k}\) sends
\(H_{n-1-j,n-1-i}\) to \(G_{i,j}\). Consequently the two complete generating families induce
the same \(P_n\)-orbit partition, although their named generator edges differ. The generic API
certifies the \(G\)-basis it actually applies; the M23 verifier separately pins and replays every
Häfner \(H\)-word and transition. Each word induces the identity permutation on tuple slots.

## Real structures and genus

A real fixed-point claim must identify the exact finite involution or real-action permutation
being checked and the convention for any fiber conjugation parameter \(c\). A list of asserted
fixed-point counts without that action is imported summary data, not a real-point certificate.

The source genus obtained from the branch cycles by Riemann--Hurwitz is not the genus of a
Hurwitz component or reduced parameter curve. These invariants live on different covers and are
never substituted for one another.

## Canonical JSON and hashes

The exact core's canonical JSON uses UTF-8, Unicode NFC strings, lexicographically sorted string
keys, compact separators, and integers rather than floating-point values. Raw bytes require an
explicit standardized encoding. There is no `repr` fallback for mathematical identity.

Artifact identities bind the artifact kind, schema version, and canonical payload with SHA-256.
A matching digest proves content identity, not mathematical truth; the relevant finite verifier
must still check the witness.
