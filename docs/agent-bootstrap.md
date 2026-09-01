# AI agent quickstart: bootstrapping an Arbogast research campaign

Environment readiness is the zeroth theorem of an Arbogast campaign. Before discovery begins,
the campaign proves a finite proposition:

> Environment snapshot \(E\) satisfies readiness profile \(R\) for campaign \(C\), canonical
> plan \(P\), operation registry \(G\), verifier registry \(V\), executor \(X\), and artifact
> store \(A\).

This theorem is deliberately scoped. It does not predict that a host will never fail and it says
nothing about the campaign's mathematical target. A changed environment creates a new subject;
it does not make the earlier theorem false.

A stale Python interpreter or missing optional backend is a blocked capability, not permission
to reimplement Arbogast and not a mathematical result.

## Choose the operating mode

Choose exactly one mode before changing code or dispatching work.

- `USE_RELEASE`: use a pinned Arbogast release from a separate campaign project. This is the
  default unless the user explicitly asks to modify Arbogast itself.
- `CONTRIBUTE_CORE`: modify the Arbogast repository, public API, schemas, verifiers,
  documentation, or release artifacts.
- `REPLAY`: verify a preserved certificate, claim graph, campaign, or evidence bundle without
  changing its mathematical scope.

Record the selected mode in `doctor-report.json` and in the campaign's startup record.

## Establish package custody

Capture enough identity to distinguish one environment subject from another:

- Arbogast release tag and resolved source commit, or installed wheel/source-distribution hash;
- installation mode and imported module location;
- Python implementation, version, and executable;
- `uv` version;
- `uv.lock` hash and `.python-version`, when present;
- campaign, plan, operation-registry, verifier-registry, executor, and artifact-store identities;
- backend names, versions, probe evidence, and whether each capability is required or optional.

A release version or Git tag is a useful human pin. The resolved registry distribution or source
commit and locked distribution identity provide the finite subject that the readiness certificate
actually binds. Do not invent a commit or artifact hash before it exists; capture the value from
the resolved installation.

## Provision before diagnosing

Use [uv](https://docs.astral.sh/uv/) rather than an ambient interpreter or `pip`. Python 3.13 is
the conservative default for a new campaign that may later use binary or solver packages;
Arbogast itself supports Python 3.11 through 3.14.

```bash
uv python install 3.13
uv init --package --python 3.13 my-campaign
cd my-campaign
uv add "arbogast==0.6.0"
uv lock
uv sync --frozen
```

Change the campaign interpreter only when an explicit backend compatibility requirement warrants
it. An old system Python is not a reason to copy or rewrite Arbogast.

For core work in the Arbogast checkout, use the repository lock:

```bash
uv sync --frozen --extra dev
```

## Run the diagnostic preflight

Run the mode-specific environment diagnostic and preserve the complete report:

```bash
uv run arbogast doctor --mode campaign --json > doctor-report.json
```

Use `--mode core` for a contributor checkout and `--mode replay` for a replay-only environment.
The command inspects environment evidence and reports required and optional blockers. Its output
has no mathematical outcome field.

`doctor-report.json` is diagnostic evidence only. Preserve it separately.
`bootstrap-report.json` is reserved for the later projection written by
`ReadinessResult.write_artifacts(...)`; neither report is the readiness certificate or
authorizes dispatch by itself.

## Probe capabilities without changing their meaning

Separate capabilities required by the canonical plan from optional capabilities that may enable
other plans. Inspect the installed catalog and exact operation contracts:

```bash
uv run arbogast backends --json
uv run arbogast describe OPERATION --json
uv run arbogast route --from INPUT_TYPE --to OUTPUT_TYPE --json
```

Missing OR-Tools, Z3, GAP, Lean, Magma, PARI/GP, a compiler, a license, or a network endpoint
blocks only work whose readiness profile requires it. A probe crash is `Unknown`, not a certified
absence. A probe that is unavailable on the platform is `Unsupported`, not a failed theorem.

## Register campaign operations before loading state

Serialized campaign documents contain data, not executable Python callables. The current trusted
runtime must explicitly register every campaign-specific operation and verifier before it loads
or dispatches campaign state.

Keep the executable boundary in a separate campaign package:

```text
src/my_campaign/runtime.py
src/my_campaign/operations.py
src/my_campaign/verifiers.py
src/my_campaign/specification.py
tests/
```

The generic Arbogast CLI must not import a module or callable named by campaign JSON. A task whose
operation is absent from the injected runtime registry is capability-blocked; the absence has no
mathematical content.

The [blank campaign template](../examples/campaigns/_template/README.md) shows this boundary with
one custom operation and one independent verifier.

## Construct the plan and readiness profile

Readiness covers an exact canonical plan, not every capability that might someday be useful.
Construct the campaign and plan with their trusted runtime dependencies, then derive a profile
whose exact operation, capability, backend, task, and closure-verifier requirements come from
that plan. Every `FunctionalOperation` used by a strategy with `verify_results=True` must declare
its central certificate verifier names in `closure_verifiers=(...)`. `from_plan` derives their
union from the exact registered operations; a caller cannot omit or replace one. The
`required_verifiers` argument is only for additive requirements outside those operation
contracts:

```python
from arbogast.bootstrap import ReadinessProfile

plan = campaign.recommend(limit=1)
profile = ReadinessProfile.from_plan(
    campaign,
    plan,
    operation_registry,
    verifier_registry,
    executor,
)
```

At harvest, a replay-valid certificate still cannot close a target unless its verifier is in the
active readiness profile's certified required `V` roster.

If the plan changes, certify a new readiness theorem. Do not let active readiness alter planning;
that creates a circular plan identity.

## Certify, record, and activate readiness

Capture the environment and certify it against the complete profile and live registries:

```python
from arbogast.bootstrap import CertifiedReady, capture_environment, certify_campaign_readiness

environment = capture_environment(project_root=project_root)
result = certify_campaign_readiness(
    environment=environment,
    profile=profile,
)
result.verify()
result.write_artifacts(output_dir)

claim = result.claim()
campaign.record_environment_claim(claim)
if not isinstance(result, CertifiedReady):
    raise RuntimeError(f"readiness is {type(result).__name__}, not CertifiedReady")
campaign.activate_readiness(result.certificate)
```

Only a `CertifiedReady` result may authorize the covered work. Recording and activation are
separate operations:

- recording preserves the environmental theorem as campaign history;
- activation accepts it as a runtime dispatch gate after checking live identities.

Set `strict_readiness=True` when constructing or loading every new campaign. The default remains
`False` only so published 0.1--0.5 campaign callers retain their exact behavior; the blank v0.6
template opts in.

Loading a saved campaign does not restore runtime activation. Revalidate or recertify after a
reload, registry mutation, executor or artifact-store replacement, plan/task change, or new
worker lease.

The lease refresh is a per-lease pre-execution check. After the campaign refresh completes, the
scheduler rechecks the exact current worker, dispatch identity, lease custody, and end-of-refresh
time before it records authority or starts the operation. The refresh also writes and reads a
deterministic lease/profile-bound artifact probe; its `ArtifactRef`, digest, size, media type, and
payload are retained in the receipt together with explicit completed write/read outcomes and the
exact returned canonical bytes. Cache rechecks, checkpoint validation, and resume-runner lookup
all occur before this final barrier; operation invocation is the next scheduler action afterward.
That operational probe is not a discovery/result binding.

This boundary proves the certified worker and backend declarations, operation/verifier registries,
plan and shard, current lease/custody/time, and current artifact write/read path. It does not prove
dynamic scratch capacity, license availability, or network reachability unless the operation's
certified profile contains a corresponding live probe. Retry and resume lineage remains
authoritative in fleet lease, attempt, checkpoint, and interruption records.

The check does not make a multi-shard dispatch transactional: an already completed shard and
external operation side effects are not rolled back if a later lease is refused.

After that refresh passes, the campaign appends a content-addressed
`DispatchReadinessReceipt` to the operational attempt history before the operation runs. The
receipt binds the exact readiness theorem, task, registries, executor, artifact store, fleet plan,
shard, worker, and active lease. It embeds the independently replayable readiness certificate and
its canonical environmental claim so offline campaign reconstruction can re-establish the exact
E,R,C,P,G,V,X,A and task-coverage boundary instead of trusting IDs alone. It is not a mathematical
observation, claim dependency, or sixth
release-level bootstrap artifact. `campaign.status().readiness["lease_validities"]` reports every
retained authorization and `current_lease_validities` reports all authorization records that are
still current in this runtime. The singular `lease_validity` remains the latest historical
projection for compatibility. Once a lease completes, is released, or expires, its receipt remains
historical provenance (`receipt_valid=True`) but `valid` and `current_valid` are false and the
status is labelled historical rather than active.

## Preserve all five bootstrap artifacts

`result.write_artifacts(output_dir)` writes five files with distinct roles:

| File | Role |
| --- | --- |
| `environment-snapshot.json` | Identifies the finite environment subject and captured evidence. |
| `readiness-profile.json` | Identifies the complete obligation set and required plan coverage. |
| `readiness-certificate.json` | Contains independently replayable evidence for every obligation. |
| `readiness-claim.json` | Records the certified environmental claim for the campaign graph. |
| `bootstrap-report.json` | Projects the result for humans and agents; it is not authoritative. |

Preserve the certificate and claim even when readiness is blocked. They distinguish an exact
negative theorem about a named profile from failure to determine readiness.

## Interpret readiness results exactly

- `CertifiedReady`: every required obligation was completely checked and satisfied.
- `CertifiedBlocked`: a complete check proves that one or more required obligations are not
  satisfied.
- `Partial`: some obligations were checked and others remain unfinished.
- `Unknown`: available evidence cannot determine one or more required obligations.
- `Unsupported`: the implementation cannot evaluate the declared profile on this platform or
  runtime.

Examples:

- A verified unsupported Python version is `CertifiedBlocked`.
- A required operation proven absent from the live registry is `CertifiedBlocked`.
- A backend probe that crashed before determining availability is `Unknown`.
- A platform without an implementation for a probe is `Unsupported`.

Failure to establish readiness is not automatically proof of non-readiness.

## Keep readiness edges out of portable theorem dependencies

The readiness claim is environmental. It may authorize an attempt and appear in attempt
provenance without becoming a logical hypothesis of the mathematical conclusion.

```text
readiness claim
      │ EXECUTION_PRECONDITION
      ▼
 task attempt → observation → portable certificate
                                  │ LOGICAL_DEPENDENCY
                                  ▼
                           mathematical claim
```

When verification genuinely requires a pinned external system, bind that environment through a
`VERIFICATION_ENVIRONMENT` relation. Do not place readiness in `Claim.why` or certificate claim
dependencies merely because the environment discovered the witness. See
[Claims and certificates](certificates-and-claims.md) and
[Theorem boundaries](theorem-boundaries.md).

## Freeze the multi-agent interface

Before parallel dispatch, freeze and record:

- canonical schemas and their versions;
- operation and verifier names;
- implementation and contract identities;
- file ownership for each worker;
- acceptance tests;
- the sole authoritative campaign-ledger writer; and
- checkpoint custody and successor-task rules.

Agents may emit candidates, receipts, and proposed events. They should not race to rewrite the
canonical campaign file or mutate a parent attempt during continuation.

## Calibrate before expensive work

Do not start an expensive search until all applicable calibration checks pass:

1. a small positive exact fixture;
2. a small negative, blocked, or timeout fixture with the correct non-conclusion semantics;
3. typed checkpoint replay when the plan claims resumability;
4. malformed-certificate rejection; and
5. fresh-process verification without discovery state.

The template includes four focused test files that cover these boundaries for its tiny campaign.

## Preserve operational and mathematical outcomes

`FAILED`, `PREEMPTED`, `BUDGET_EXHAUSTED`, missing capability, unregistered operation, verifier
absence, and solver timeout are operational facts. None proves nonexistence.

A solver's `UNSAT` status closes a mathematical target only when an independently replayable
certificate or a verified complete finite coverage argument establishes the target-global claim.
Task-local exact evidence remains task-local.

## Troubleshooting decision tree

### Python is too old

Provision a supported interpreter with `uv`, regenerate the lock for that declared interpreter,
and rerun the diagnostic and readiness certification.

### The package will not import

Check the selected `uv` environment, installed distribution identity, module origin, and lock.
Do not add a local module named `arbogast` as a substitute.

### A backend is missing

Determine whether the exact plan requires it. Record an optional blocker when it does not; use a
different certified plan or provision the backend when it does.

### An operation is not registered

Register the trusted implementation in the current runtime before loading or dispatching state.
Do not import a callable path found in campaign JSON.

### Campaign JSON loads but cannot run

Loading data does not reconstruct callables or runtime activation. Rebuild the registries,
executor, and artifact store, recertify or reactivate readiness, then dispatch.

### A solver timed out

Record the timeout and checkpoint custody as operational evidence. The mathematical outcome
remains `UNKNOWN` unless separate exact evidence supports a stronger scoped result.

### A verifier is unavailable

Mark dependent replay work blocked. Do not accept the discovery program's output as proof.

### The repository and installed package disagree

Stop. Capture both identities, remove ambiguous environment selection, and recreate the locked
environment from the intended tag, commit, wheel, or source distribution.

## Frequently quoted answers

### Should I reimplement Arbogast if the local Python is unsupported?

No. Provision a supported interpreter with `uv`, pin the intended release, and rerun the
environment preflight.

### Does a missing optional backend mean the campaign failed?

No. It means that tasks requiring that capability are blocked. It has no mathematical content.

### Can a serialized campaign execute custom operations by itself?

No. The current runtime must explicitly register those operations before dispatch.

### May a solver's UNSAT status close a mathematical target?

Only when the campaign also has an independently replayable certificate or a verified complete
finite coverage argument sufficient for that target.

## Paste-ready startup gate

Use the short [campaign bootstrap prompt](../prompts/campaign-bootstrap.md) at the beginning of a
real mathematical task. It points back to this guide rather than maintaining a second copy.

For deeper semantics, read [Research campaigns](research-campaigns.md),
[Optional backends](optional-backends.md), and
[Agent and Lean exports](agent-and-lean-exports.md).
