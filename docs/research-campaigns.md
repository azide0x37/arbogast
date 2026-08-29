# Research campaigns

Arbogast treats a research campaign as a provenance-preserving derivation, not a collection of
processes. The durable architecture is:

```text
Claim  ←  Task  ←  Campaign
```

Claims are the mathematical product. Tasks identify finite units of intended work. Campaigns
hold the objective, dependency structure, policy, resource envelope, capability requirements,
authoritative ledger, and canonical `ClaimGraph` that relate the tasks to the eventual claims.

## Antieau/Klüners--Malle case study

The supplied Antieau interview describes a Klüners--Malle workflow for constructing and
organizing explicit polynomials. This case study applies that described workflow to a precisely
scoped target over \(\mathbf Q\); it does not attribute a new target request to Antieau. The
[Klüners--Malle database](https://galoisdb.math.uni-paderborn.de/) is an important source of prior
examples and coverage information. A campaign begins by importing the exact database assertion
or absence statement it uses. “Not returned by this query” is not silently recast as “does not
exist.”

A possible task DAG is:

```text
import exact prior-work claim
          │
          ▼
pin group action, signature, and coefficient/search bounds
          │
          ├── construction-family task ─┐
          ├── specialization task ──────┼── candidate normalization
          └── bounded search task ──────┘             │
                                                       ▼
                                       exact irreducibility/signature/group checks
                                                       │
                                                       ▼
                                verification certificate → campaign-owned ClaimGraph
```

The construction and search operations may change as evidence accumulates. The mathematical
target does not. Failed attempts, excluded families, exact obstructions, and frontier metrics are
retained so the next planner can choose a genuinely different task.

## Mathematical outcome and operational state

Execution state is part of the research record, but **mathematical outcome** and **operational
state** are separate fields. The following negative and interrupted classifications have
deliberately different meanings:

### `PROVED_IMPOSSIBLE`

A verifier accepted a certificate proving nonexistence under precisely stated hypotheses. The
scope and dependencies of that impossibility result must be claim-ready. This is the only listed
negative state that directly denotes a proved negative proposition.

### `SEARCH_EXHAUSTED`

Every point in a declared finite search domain was checked, with a completeness witness. The
result excludes that domain only. It becomes a global impossibility theorem only if a separate
derivation proves that the search domain covers every admissible object.

### `BUDGET_EXHAUSTED`

The attempt consumed its recorded wall-time, operation, token, memory, or monetary budget before
completion. Partial artifacts and the unsearched frontier remain available. This state has no
negative theorem content.

### `PREEMPTED`

Execution was interrupted by an operator or scheduler. The ledger records the last accepted
checkpoint and artifact custody. Preemption says nothing mathematical. It is resumable only when
the operation cooperatively emitted a typed checkpoint and the configured executor can replay
that custody.

### `FAILED`

The implementation, input, backend, or environment failed. The ledger records the failure class
and diagnostics. A failed backend invocation cannot support “no solution.”

### `UNKNOWN`

The available record is insufficient for a stronger classification. Unknown is preferable to an
invented conclusion and may be refined by a later task.

Success is also layered: a task can produce a candidate, a verified finite result, or evidence
supporting a claim. None silently substitutes for another.

### `FOUND`

The target's stated success criterion has a witness whose embedded `VerificationCertificate`
replays through its registered verifier. This closes the campaign target. As part of acceptance,
the `Campaign` adds a `COMPUTED`, `CERTIFIED` claim envelope to its canonical
`ClaimGraph` and records the observation-to-claim binding. The envelope replays the underlying
closure certificate; it is not a second discovery claim assembled by the caller.

## Derivation rules

Campaign policy can schedule work; it cannot change mathematics. Claim promotion follows the
same fail-closed rules everywhere:

1. A task attempt can create a discovery receipt and observation-bound candidate artifacts.
2. A named verifier can accept a sufficient finite certificate.
3. Campaign closure creates a `COMPUTED` claim envelope binding the exact operation, canonical
   task and observation, and nonempty replayable evidence.
4. A `DERIVED` claim names every dependency and the inference rule.
5. Campaign target closure requires an embedded `VerificationCertificate` whose registered,
   independent verifier replays successfully; a bare theorem-certificate reference is not a
   replayable closure bundle.
6. Imported claims remain imported; integrity checks do not promote them.
7. `SEARCH_EXHAUSTED` supports only its finite-domain negative unless a coverage theorem is a
   dependency.
8. `BUDGET_EXHAUSTED`, `PREEMPTED`, `FAILED`, and `UNKNOWN` do not support negative promotion.

A rejected closure remains non-closing and its verification diagnostics remain available; a
policy cannot override these derivation rules.

## Provenance is an input to the next algorithm

Provenance is not a footer added after success. A next-generation task may consume:

- canonical input and parameter identities from earlier attempts;
- proven obstructions and exhaustively excluded cells;
- incomplete frontier partitions and checkpoints;
- runtime, memory, and verifier-cost measurements;
- backend capability and version observations;
- candidate quality under an explicitly named metric, canonicalizer, and equivalence scope;
- attempt progress, resource use, and the canonical plan that selected the work;
- failure classes that distinguish a bad strategy from a bad workstation.

Because these values are structured, a planner can avoid replaying the same failed system, change
quotient or construction family, allocate a sharper finite test, or prioritize evidence that
closes a proof gap.

## Capability matching

A task declares semantic capabilities rather than a host name: for example exact prime-field
linear algebra, a GAP finite-group operation, a minimum memory envelope, or access to a
user-supplied licensed backend. The task records its requirements and the campaign records its
declared local capability set.

Arbogast 0.1.0 provides deterministic local executors, a worker pool with declared backend and
resource matching, and optional-backend probes. A `WorkerPoolExecutor` records worker leases,
attempts, receipts, typed cooperative checkpoints, and integer resource/spend counters supplied
by the operation. It exposes extension protocols for other executors and sinks; it does not
implement SSH deployment, Slurm job control, cloud provisioning, remote license transfer, or
proprietary passfile generation. The 0.1 planner filters an unmatched task from its
recommendations; it does not synthesize an unavailable or failed observation for work that never
started. `campaign.status().blocked_tasks` and `campaign.explain(target).blockers` expose the
mismatch for inspection.

## Candidates and best-known records

A candidate is an observation-bound mathematical object, not a filename and not a claim. Every
`CandidateRecord` declares a `canonical_key`, a named `canonicalizer`, and whether that
equivalence is valid only within one `TARGET` or `GLOBAL` across targets. The ledger therefore
deduplicates only under semantics supplied by the operation; it never guesses equivalence from
stdout or a backend representation.

Candidate preference is likewise scoped. Evidence level is compared first, then an integer
quality whose `quality_metric` has been named explicitly; deterministic record identity breaks
ties. `best_known_by_metric()` returns one candidate per metric. Candidates using different
metrics are not ordered against one another, and `best_known()` requires the metric when more
than one is present.

## Value-based policy

When several tasks are runnable, policy may rank them by recorded quantities such as:

- expected mathematical information gain;
- probability of closing a named claim or proof obligation;
- coverage of a high-value target cell;
- expected discovery and verification cost;
- novelty and reuse of the resulting certificate;
- diversity from already exhausted strategies.

Those scores are planning metadata, not truth values. Each recommendation is persisted as a
canonical `CampaignPlan` event, the planned task retains its value inputs, and the campaign
snapshot retains the selected policy. Deterministic tie-breaking prevents accidental workstation
order from becoming research policy.

## The authoritative ledger

The ledger is the accepted-state boundary for a campaign. In 0.1 it records:

- target specifications and planned campaign tasks, including declared requirements and value
  metadata;
- canonical plan records and `TASK_PLANNED`, `TASK_STARTED`, observation, candidate, attempt, and
  claim-binding events;
- first-class attempt histories, including running/terminal state, worker, progress, checkpoint,
  and operation-reported integer resource use;
- mathematical outcomes and operational states;
- canonical candidates and per-metric best-known records with explicit canonicalizers and
  equivalence scopes;
- result, typed checkpoint, input, and source references;
- embedded verification-certificate payloads for closing observations.

The surrounding campaign snapshot adds the objective, strategies, declared capabilities, and
policy, and owns the canonical `ClaimGraph`. Closing observations are automatically associated
with their computed claims; imported claims can be present in that same graph before work begins.

Dispatch is not completion. Process exit is not verification. A file appearing in a worker
directory is not ledger acceptance. Consumers derive campaign state from accepted ledger records,
not from process tables or scratch paths.

The CLI can initialize, inspect, and project that portable state:

```bash
arbogast campaign init demo campaign.json --objective "Check a finite target"
arbogast plan campaign.json --json
arbogast run campaign.json --fleet auto --limit 1 --json
arbogast status campaign.json --json
arbogast target campaign.json TARGET_ID --explain --json
arbogast export claims campaign.json claims.json
```

`export claims` emits the campaign's directly replayable canonical `arbogast.claim-graph/v1`.
Lower-level `export_claim_candidates()` receipts remain available from Python for auditing the
closure boundary, but they do not replace `CandidateRecord` values or the theorem graph.

Serialized campaign data never contains executable Python callables. A CLI `run` therefore
refuses a task when its operation implementation is not registered in the current runtime; it
does not execute code recovered from JSON. `--fleet auto` supplies a conservative automatic
local worker pool and an audited built-in registry, but 0.1.0 includes only `fleet.echo.v1`. That
operation records canonical input and returns `UNKNOWN`; it is not a generic function loader or
a mathematical closure operation. Similarly, `harvest` accepts a strict serialized
`Observation`, not an arbitrary process result.

## Cooperative checkpoints and the recovery boundary

Checkpointing is an operation protocol, not a promise to snapshot any process. A resumable fleet
operation yields typed `CheckpointRef` values or a multi-shard `CheckpointManifest` bound to the
task, plan, shard, worker lease, and persisted artifact. `WorkerPoolExecutor` can replay all
checkpointed shards from that manifest; the remaining shards must come from verified cache or be
run again.

The basic `LocalExecutor` validates cooperative checkpoint content but does not persist scheduler
custody. A checkpoint successor under that executor is therefore a `SUSPEND` advisory, and direct
dispatch fails closed instead of claiming resume. Loading a snapshot with an orphaned `RUNNING`
attempt records an operational `UNKNOWN` terminal state without creating an observation or
mathematical conclusion. Arbogast 0.1.0 does not reconstruct arbitrary processes, workers, or
hosts after a crash, and it does not supply SSH, Slurm, cloud, or license infrastructure.

## Reproduce claims, not workstations

Reproducibility means a second consumer can retrieve canonical inputs, evidence, schema versions,
and verification rules; recompute content identities; and recover the same claim status. It does
not require an identical hostname, queue order, local path, proprietary session, or expensive
search schedule.

Discovery can legitimately be nonportable or costly. The durable artifact should be small,
backend-neutral evidence whenever the mathematical operation permits it. Backend versions and
receipts remain provenance for debugging without becoming the verifier's trusted base by default.

The runnable local example is in
[`examples/campaigns/antieau_klueners_malle/`](../examples/campaigns/antieau_klueners_malle/).
