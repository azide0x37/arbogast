# Contributing to Arbogast

Thank you for helping make computational mathematics easier to audit. Arbogast welcomes code,
examples, documentation, certificate formats, mathematical counterexamples, and corrections to
theorem boundaries.

## Before opening a change

For a substantial new operation or schema change, open an issue first. State:

- the mathematical object or operation;
- its exact preconditions and guarantees;
- what is discovered and what is independently verified;
- the certificate needed for cheap verification;
- canonicalization and backend-independence requirements;
- known failure modes and theorem-boundary hazards.

Every public operation belongs to a mathematical layer. Please do not introduce catch-all
`utils`, `helpers`, or `misc` modules.

## Development setup

Arbogast uses uv and supports Python 3.11 through 3.14.

```bash
git clone https://github.com/azide0x37/arbogast.git
cd arbogast
uv sync --locked --extra dev
uv run pytest
```

Before submitting a pull request, run the same checks as CI:

```bash
uv lock --check
uv sync --locked --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build --no-sources
uv run python examples/group_cohomology/cyclic_action_h1.py
uv run python examples/campaigns/antieau_klueners_malle/run.py \
  --output /tmp/arbogast-campaign
```

The integration tests execute all bundled examples, including the local campaign, the two-stage
certificate example, and the exact M23 verifier.

## Mathematical contracts

A public operation must document:

1. accepted mathematical objects and conventions;
2. preconditions and validation behavior;
3. exactness or uncertainty level;
4. postconditions and exhaustiveness guarantees;
5. failure modes, including unsupported cases;
6. certificate type and trusted verification base;
7. deterministic sharding behavior, when applicable.

Do not use a stronger result type than the evidence supports. In particular, numerical,
heuristic, conditional, imported, computed, derived, and conjectural claims must remain
distinguishable.

## Certificates and canonicalization

Certificate changes require versioned schemas, deterministic serialization, negative tests,
and an explanation of the verifier's trusted inputs. Verifiers should reject:

- unknown or incompatible schema versions;
- hashes computed over a noncanonical representation;
- missing dependencies or ambiguous object identifiers;
- duplicate or noncanonical representatives where uniqueness is claimed;
- evidence that proves a weaker claim than the graph records.

If discovery uses an optional backend, add a test showing that verification does not require
that backend unless the certificate contract explicitly says otherwise.

## Tests

Prefer small exact fixtures. Every bug fix should include a regression test that fails for the
old behavior. Property tests are welcome, but they do not replace a concrete certificate or
counterexample at a theorem boundary.

Keep expensive searches out of the ordinary test suite. Store a compact, versioned certificate
and test its independent verifier. Any precomputed fixture must record its provenance and make
the imported-versus-computed boundary visible in its documentation.

## Documentation and examples

Examples are executable documentation and run in CI on every supported Python version. They
must be deterministic, avoid network access, keep generated files in caller-selected output
paths, and state whether their data is computed in the example or imported from a fixture.

Use the spelling **Arbogast**. Describe mathematical claims precisely and avoid implying that
an external backend, literature result, or Lean proof is bundled when it is not.

## Pull requests

Keep changes focused. Explain the theorem boundary, tests, and certificate compatibility in the
pull-request description. Do not include generated caches, local backend output, credentials,
or proprietary datasets.

## Package publication

Package-index publication is a separate approval boundary after GitHub release qualification.
Follow [the publishing runbook](docs/publishing.md). Promote only the exact approved wheel and
Python source distribution; never upload a wildcard directory, Git source archive, qualification
report, or locally rebuilt file under an existing version.
