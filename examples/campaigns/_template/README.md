# Arbogast campaign template

This is a minimal external campaign package. It demonstrates one exact custom operation, one
independent verifier, one authoritative campaign snapshot and ledger, and fresh-process replay.
It does not modify or reimplement Arbogast core.

The template deliberately uses the valid placeholder `campaign_name` so every checked-in Python
file remains executable. Copy the directory, rename the project and package consistently, and
replace the tiny modular-square fixture with the actual mathematical specification only after
the bootstrap gate passes.

## Provision the pinned release

The dependency is pinned to the production PyPI distribution `arbogast==0.6.0`. The generated
`uv.lock` records the resolved registry artifacts and hashes; preserve its hash with the readiness
evidence.

```bash
uv python install 3.13
uv lock
uv sync --frozen --group dev
uv run arbogast version --json
uv run arbogast doctor --mode campaign --json > doctor-report.json
```

Arbogast supports Python 3.11 through 3.14; 3.13 is the conservative campaign default. Do not
fall back to ambient Python or replace the library when provisioning fails.
Preserve `doctor-report.json` as diagnostic evidence; the readiness command below writes the
distinct `bootstrap-report.json` projection in its output directory.

Read the pinned
[AI agent bootstrap guide](https://github.com/azide0x37/arbogast/blob/v0.6.0/docs/agent-bootstrap.md)
and the
[paste-ready campaign gate](https://raw.githubusercontent.com/azide0x37/arbogast/v0.6.0/prompts/campaign-bootstrap.md).

## Runtime boundary

The source files have separate responsibilities:

- `specification.py` defines the canonical target, plan inputs, names, and mathematical claim;
- `operations.py` performs discovery and emits a finite certificate;
- `verifiers.py` replays that certificate without importing discovery code; and
- `runtime.py` is the sole trusted entry point that registers callables, certifies readiness,
  activates it, loads state, and dispatches work.

Campaign JSON records operation names but cannot reconstruct Python callables. A new process must
register operations and verifiers before loading state. Because this strategy enables
`verify_results`, its `FunctionalOperation` declares `closure_verifiers=(VERIFIER,)`; readiness
derives that required `V` entry from the registered operation instead of trusting a caller list.

## Prove readiness before dispatch

Create the five bootstrap artifacts:

```bash
uv run python -m campaign_name.runtime certify-readiness \
  --output outputs/bootstrap
```

This writes:

```text
outputs/bootstrap/environment-snapshot.json
outputs/bootstrap/readiness-profile.json
outputs/bootstrap/readiness-certificate.json
outputs/bootstrap/readiness-claim.json
outputs/bootstrap/bootstrap-report.json
```

The report is a projection. The certificate and environmental claim are authoritative. Runtime
activation is intentionally ephemeral, so a later `run` command revalidates the live identities
and activates readiness again in the process that dispatches.

## Run the tiny campaign

```bash
uv run python -m campaign_name.runtime run --output outputs/run
uv run python -m campaign_name.runtime status outputs/run/campaign.json
uv run python -m campaign_name.runtime verify outputs/run/certificate.json
```

The output contains the readiness artifacts, canonical campaign snapshot, append-only ledger
projection, content-addressed sink records, and independently replayable mathematical
certificate. The fixture asks whether 2 has a square root modulo 7; it is a finite teaching
problem, not a research claim.

## Qualification tests

```bash
uv run pytest
```

The four tests establish only the startup and proof boundaries needed to copy the template:

- the exact Arbogast pin, runtime registries, and artifact-store round trip;
- one small positive certified campaign with authoritative state replay;
- blocked-operation and malformed-certificate semantics without false mathematical negatives;
  and
- verification in a fresh process that never imports discovery code.

Add campaign-specific checkpoint replay before expensive work whenever the real executor claims
resumable custody.
