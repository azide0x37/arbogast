# Optional backends

Python is Arbogast's control plane. The 0.1.0 core is pure Python and requires no external
computer algebra system. Optional backend adapters can expose additional discovery capability or
performance while preserving Arbogast's mathematical types and certificates.

## Capability model

Arbogast knows about capability protocols for:

| System | Typical role | Distribution boundary |
| --- | --- | --- |
| GAP | finite groups, conjugacy classes, and discovery searches | external executable |
| FLINT | high-performance exact arithmetic and linear algebra | external installation/binding |
| PARI/GP | number-field and arithmetic experiments | external executable |
| SageMath | interoperability and broader CAS orchestration | external executable/environment |
| Magma | optional proprietary comparison or discovery workflows | user-supplied licensed installation |

These names do not imply that every planned adapter or operation exists in 0.1.0. Capability
probes report what is actually available at runtime. No backend is bundled, downloaded on demand,
or emulated when absent.

The 0.1.0 executable adapter surface is deliberately narrow:

- `FlintBackend.matrix_rank` and `FlintBackend.matrix_determinant` translate an Arbogast
  prime-field matrix to `python-flint`'s `nmod_mat` and return a typed scalar result plus a
  `DiscoveryReceipt`.
- `GapBackend.permutation_group_order` accepts only validated, zero-based permutation image
  tables, constructs a closed GAP program internally, and returns the group order plus a
  `DiscoveryReceipt`. It never accepts caller-provided GAP source.

Other listed systems have capability probes in 0.1.0 but no public computational adapter. The
two operations above are discovery surfaces: the external result is exact arithmetic, but its
receipt is not by itself a verification certificate and cannot promote a theorem claim.

Probe without importing a computer algebra system:

```python
from arbogast.backends import backend_statuses

for status in backend_statuses():
    print(status.name, status.available, status.version, status.reason)
```

To fail closed on a requirement, pass the same scheduler-neutral requirement object used by a
task:

```python
from arbogast.backends import require_backend
from arbogast.fleet import BackendRequirement

gap = require_backend(
    BackendRequirement(name="gap", capabilities=("finite-groups",)),
)
```

This returns a point-in-time `BackendStatus` or raises `BackendUnavailableError`; it never installs
or substitutes a backend.

For example, after installing `python-flint` independently:

```python
from arbogast.backends import FLINT
from arbogast.linalg import DenseMatrix, PrimeField

matrix = DenseMatrix(PrimeField(7), ((1, 2), (3, 4)))
result = FLINT.matrix_determinant(matrix)
assert result.value == 5
print(result.receipt.content_id)
```

## Discovery is not verification

A backend may discover candidate representatives, bases, or orbits. Arbogast then canonicalizes
the output and, where the certificate contract permits, verifies it using the finite exact core.
The claim graph records the backend and version as discovery provenance without automatically
adding that backend to the certificate verifier's trusted base.

Some certificates may legitimately require an external verifier. Such a requirement must be
declared in the certificate and operation contract; a missing executable yields an explicit
unavailable outcome.

## Safe operation

Arbogast does not sandbox backend executables. They inherit the invoking process's permissions.
Use trusted installations and scripts, and treat backend output as untrusted until decoded and
verified. Do not place license files, credentials, private source paths, or environment dumps in
shareable provenance.

In particular, Arbogast never generates or bypasses a proprietary license. A Magma adapter uses
only a valid user-provided installation and passfile.

## Portable certificates

Backend-neutral certificates use stable mathematical data:

- permutations as finite image tables under the documented action convention;
- matrices over standardized exact field presentations;
- canonical representative IDs rather than session object numbers;
- explicit maps and witnesses rather than printed backend transcripts.

Thus “GAP discovers; the portable verifier need not know GAP exists” is an architectural goal,
not an assumption that every discovery result already has a completeness certificate.
