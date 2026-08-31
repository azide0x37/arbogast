# Arbogast agent instructions

Arbogast is certificate-first computational mathematics and a provenance-preserving research
campaign framework.

A stale Python interpreter or missing optional backend is a blocked capability, not permission
to reimplement Arbogast and not a mathematical result.

## 1. Classify the task before touching code

Choose exactly one operating mode and record it in the diagnostic report.

### `USE_RELEASE`

Use a pinned Arbogast release from a separate campaign project. This is the default unless the
user explicitly asks to modify Arbogast itself.

### `CONTRIBUTE_CORE`

Modify this repository, its public API, schemas, verifiers, documentation, or release artifacts.

### `REPLAY`

Verify an existing certificate, claim graph, campaign, or preserved evidence bundle without
changing its mathematical scope.

## 2. Mandatory environment gate

Before editing implementation code or spawning subagents:

1. Read `pyproject.toml`, `docs/agent-bootstrap.md`, and the contracts for relevant operations.
2. Use `uv` as the authoritative Python and environment manager. Do not rely on ambient
   `python`, `python3`, or `pip`.
3. Run the diagnostic preflight for the selected mode:

   ```bash
   uv run arbogast doctor --mode MODE --json
   ```

   Use lower-case `campaign`, `core`, or `replay` for `MODE`, matching the selected operating
   mode above.

4. Preserve the complete diagnostic report. It is input evidence, not the readiness theorem.
5. Verify the expected Arbogast version, source identity, lock identity, and every capability
   required by the intended plan.
6. For campaign or replay work, construct the exact readiness profile, certify it, replay its
   certificate, record the environmental claim, and activate it in the current runtime.
7. Do not dispatch work until the active readiness claim covers the exact plan, task, registries,
   executor, and artifact store.

Use `arbogast describe OPERATION --json` and
`arbogast route --from INPUT_TYPE --to OUTPUT_TYPE --json` for small semantic views. Use
`arbogast.agent.compact_context()` when a bounded complete operation packet is needed.

## 3. Hard guardrails

- Do not copy or reimplement Arbogast internals in a campaign project.
- Do not modify Arbogast core to make one campaign run unless the user requested a core change.
- Do not substitute a homemade campaign ledger, claim graph, certificate, or outcome model.
- Do not treat a missing backend as `FAILED`, `SEARCH_EXHAUSTED`, or `PROVED_IMPOSSIBLE`.
- Do not treat process exit, solver status, or a generated file as mathematical verification.
- Do not launch multiple agents before shared schemas and file ownership are frozen.
- Do not let discovery code certify itself.
- Do not infer resource usage from requested resources or elapsed timestamps.
- Do not silently upgrade `TASK_LOCAL` evidence to `TARGET_GLOBAL`.
- Do not make a portable mathematical claim logically depend on its discovery environment.

## 4. Campaign runtime boundary

Serialized campaign files contain data, not executable Python callables. Campaign-specific
operations and verifiers must be registered in the current trusted runtime before campaign state
is loaded or dispatched. An unavailable operation is capability-blocked; it is not a
mathematical observation.

Prefer a separate campaign package with an explicit runtime entry point:

```text
src/<campaign_name>/runtime.py
src/<campaign_name>/operations.py
src/<campaign_name>/verifiers.py
src/<campaign_name>/specification.py
tests/
campaign.json
environment-snapshot.json
readiness-profile.json
readiness-certificate.json
readiness-claim.json
bootstrap-report.json
```

Preserve the earlier diagnostic as `doctor-report.json`; it is separate from the five readiness
artifacts above, and `bootstrap-report.json` is reserved for the readiness-result projection.

The readiness claim and certificate are durable evidence. Runtime activation is not: reloads,
registry changes, executor or store changes, new plans, new tasks, and new leases require
revalidation or recertification.

## 5. Core contributor commands

For `CONTRIBUTE_CORE` work:

```bash
uv sync --frozen --extra dev
uv run arbogast doctor --mode core --json
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Run focused tests during development, then the required full release and example gates before
finishing. Preserve published compatibility inputs and existing dirty-worktree state that does
not belong to the task.

## 6. Campaign commands

For `USE_RELEASE` campaign work:

```bash
uv run arbogast doctor --mode campaign --json
uv run arbogast backends --json
uv run arbogast describe OPERATION --json
uv run arbogast route --from INPUT_TYPE --to OUTPUT_TYPE --json
```

The generic diagnostic command cannot certify arbitrary callables named by campaign JSON. Use
the campaign's explicit runtime entry point to inject its operation and verifier registries and
to certify readiness.

Read `docs/agent-bootstrap.md` for the full protocol, use
`prompts/campaign-bootstrap.md` as a paste-ready gate, and copy
`examples/campaigns/_template/` for a minimal external campaign.

Generated Arbogast agent manifests and operation contexts remain the authoritative semantic API
descriptions. This file is an operational bootstrap contract, not a duplicate operation catalog.
