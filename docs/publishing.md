# Publishing Arbogast to Python package indexes

PyPI publication promotes the same qualified Python distributions that were approved and
published on the corresponding GitHub release. It never rebuilds a package under an existing
version and never uploads the Git source archive or qualification report.

## Trust and approval boundary

The manual `.github/workflows/publish-pypi.yml` workflow accepts an exact final tag, version,
source commit, wheel SHA-256, source-distribution SHA-256, and registry target. Its validation job
has no OIDC publishing authority. It downloads only the named wheel and Python source
distribution from the public GitHub release, checks those inputs against the canonical
`release/pypi/vVERSION.json` manifest committed on `main`, checks the tag and release target,
rejects extra or foreign files, checks both hashes and both package metadata payloads, renders the
description, smoke-installs each distribution independently, and performs a two-file `uv publish
--dry-run`. The extra-file rejection applies to the isolated two-file transfer directory; the
GitHub release may retain its separately approved source archive and qualification report.

Only after validation succeeds is the exact pair transferred to a separate registry-specific
job. That job has `id-token: write` but does not check out or execute repository code. It rechecks
the file count and hashes, waits for environment approval, then revalidates the live public
release and tag and byte-compares fresh public downloads with the transferred pair. It generates
PEP 740 attestations, rechecks both distribution hashes once more after attestation generation,
requires the two exact `.publish.attestation` sidecars, and invokes `uv publish
--trusted-publishing always` with only the two distributions and their two sidecars.

The `testpypi` and `pypi` GitHub environments are distinct OIDC subjects. Protect the production
`pypi` environment with required reviewers and restrict deployment branches to `main`. The
workflow itself also refuses validation unless dispatched from `main`.

The repository currently has one eligible release reviewer. Configure that account as the
required `pypi` reviewer with self-review prevention disabled; enabling it with no second reviewer
deadlocks an owner-dispatched release. If a second trusted reviewer is added, enable self-review
prevention as a further separation-of-duties control.

## One-time registry setup

The PyPI and TestPyPI accounts and Trusted Publisher configurations are separate. Before the
first upload, register pending publishers with these exact values:

| Field | TestPyPI | PyPI |
| --- | --- | --- |
| Project | `arbogast` | `arbogast` |
| Owner | `azide0x37` | `azide0x37` |
| Repository | `arbogast` | `arbogast` |
| Workflow | `publish-pypi.yml` | `publish-pypi.yml` |
| Environment | `testpypi` | `pypi` |

A pending publisher does not reserve the project name. Only a successful production upload
creates the PyPI project and claims its normalized name.

## Dispatch inputs for v0.6.0

The exact approved inputs are:

```text
target: testpypi (first), then pypi only after separate approval
tag: v0.6.0
version: 0.6.0
source_commit: 893af39a7b826728793ba3f3b7b5a5f5bc5a8e7c
wheel_sha256: 65e9891d93de84e3a8937a9c507babf0aa471cc4d48d182170094d0acfde6b18
sdist_sha256: 5e9c7cba2f9b4df7b8c15ba3db45ea133313ec9d4bfbaba5cf345f059371558a
```

They are independently bound by `release/pypi/v0.6.0.json`; dispatcher-supplied hashes cannot
authorize different bytes without a reviewed change to the manifest on `main`.

The custom `arbogast-0.6.0-source.tar.gz` archive and qualification JSON are deliberately outside
the workflow's accepted file set.

## Independent verification

After either upload, query the registry JSON API, require exactly one wheel and one source
distribution for the version, compare their SHA-256 digests and sizes with custody, download both
files into a new directory, compare their bytes with the approved GitHub assets, verify the PEP
740 provenance, and perform a cache-bypassing registry install. TestPyPI verification is evidence
for the publication path; it does not authorize or imply the production upload.

The byte-custody verifier performs the JSON, host, redirect, file-set, metadata, bounded-download,
and byte-comparison checks. For v0.6.0 on TestPyPI, run it against the separately retained approved
pair. Set `approved_dir` to that pair's directory and `verified_dir` to a fresh destination; the
destination must not already exist:

```bash
uv run --no-project python scripts/verify_pypi_registry.py \
  --target testpypi \
  --project arbogast \
  --version 0.6.0 \
  --wheel-filename arbogast-0.6.0-py3-none-any.whl \
  --wheel-sha256 65e9891d93de84e3a8937a9c507babf0aa471cc4d48d182170094d0acfde6b18 \
  --wheel-size 918629 \
  --approved-wheel "${approved_dir}/arbogast-0.6.0-py3-none-any.whl" \
  --sdist-filename arbogast-0.6.0.tar.gz \
  --sdist-sha256 5e9c7cba2f9b4df7b8c15ba3db45ea133313ec9d4bfbaba5cf345f059371558a \
  --sdist-size 2276578 \
  --approved-sdist "${approved_dir}/arbogast-0.6.0.tar.gz" \
  --output-dir "${verified_dir}"
```

Legacy version JSON does not expose PEP 740 provenance, so verify it separately through the
Integrity API and the pinned official verifier. TestPyPI uses the production Sigstore trust root;
do not pass `--staging`:

```bash
for filename in \
  arbogast-0.6.0-py3-none-any.whl \
  arbogast-0.6.0.tar.gz
do
  curl --fail --location --silent --show-error \
    -H 'Accept: application/vnd.pypi.integrity.v1+json' \
    --output "${verified_dir}/${filename}.provenance" \
    "https://test.pypi.org/integrity/arbogast/0.6.0/${filename}/provenance"
  jq --exit-status '
    .version == 1 and (.attestation_bundles | length) == 1 and
    all(.attestation_bundles[];
      .publisher.kind == "GitHub" and
      .publisher.repository == "azide0x37/arbogast" and
      .publisher.workflow == "publish-pypi.yml" and
      .publisher.environment == "testpypi")
  ' "${verified_dir}/${filename}.provenance"
  uvx --from pypi-attestations==0.0.30 \
    pypi-attestations verify pypi \
    --repository https://github.com/azide0x37/arbogast \
    --provenance-file "${verified_dir}/${filename}.provenance" \
    "${verified_dir}/${filename}"
done
```

For production, change the verifier target and hosts to `pypi`, and require publisher environment
`pypi` instead of `testpypi`.

PyPI filenames are immutable. A changed file requires a new package version. Yanking or deleting
a release does not authorize reusing its version or filename.
