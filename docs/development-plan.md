# Development plan: capture and offline distillation

Date: September 18, 2026

Status: implementation started; immutable manifests and deterministic offline feature distillation delivered

Design reference: [Autonomous capture and offline distillation](architecture.md)

## Outcome and scope

Keep autonomous exploration available without supplied workflows. Make browser evidence reusable across feature interpretation, documentation generation, and retries. Produce useful descriptions of observed features even when a complete operation cannot be replayed. Continue requiring applicable outcome evidence for procedural claims.

Reuse the existing Playwright adapter, policy, SQLite repository, artifacts, discovery frontier, verification engine, composers, and MkDocs export. Retain completed phase 1–4 work and its outstanding evaluation gates in the [original roadmap](history/original-development-plan.md). This migration does not require a new orchestration framework, hosted worker service, or browser stack.

## Sequence and effort

Estimates are incremental engineering effort for one engineer familiar with this repository, including focused validation and operator documentation. They are planning ranges, not measured delivery guarantees. Reestimate after the evidence compatibility audit.

| Phase | Deliverable | Effort | Dependency |
| --- | --- | --- | --- |
| A | Baseline audit and versioned evidence manifests | 3–4 days | Existing code and retained sample runs |
| B | Deterministic capture with bounded AI assistance and recovery | 4–6 days | A |
| C | Independently retryable offline distillation | 4–6 days | A; integrate with B |
| D | Feature references and evidence-aware document export | 4–6 days | C |
| E | Parameterized replay and prerequisite contracts | 3–5 days | A; integrate with D |
| F | Optional operator recording | 3–5 days | A and C |
| G | End-to-end CLI integration, migration checks, and evaluation | 3–4 days | B–E; recorder checks after F |

Core migration A–E plus G: **21–31 working days**. Optional recorder F adds **3–5 days**, giving **24–36 working days** overall. Access delays and external user studies are additional calendar time. Human recording is not a prerequisite for releasing autonomous capture and offline writing.

## Phase A — Establish the evidence boundary

- [ ] Audit retained runs and source contracts: observations, sanitized ARIA, control metadata, screenshots, actions, transitions, verification references, and artifact hashes.
- [ ] Record a baseline from existing captures: known menu/feature inventory, explored and pending branches, model failures, elapsed capture time, and generated documentation coverage. Do not infer coverage from raw state counts.
- [x] Define a versioned capture manifest with origin, scope, role, immutable evidence references, completeness, stop reason, and input references.
- [x] Add processing-stage records and input/configuration hashes through additive migrations.
- [x] Finalize partial capture manifests; freeze their inputs even when discovery later resumes.
- [x] Read existing runs directly into the versioned manifest and report missing artifact records or hash failures.

Likely areas: `storage/`, discovery models, artifact loading, and orchestration services.

Acceptance: a representative old run and a new partial run can be opened as manifests without browser access. Missing assets and mismatched hashes have actionable errors. Existing evidence, review decisions, and exports survive migration. Authentication and private traces are excluded from model/export bundles.

## Phase B — Make capture resilient to planner failure

- [ ] Make deterministic frontier ranking the default while preserving explicitly configured model-assisted behavior through documented compatibility handling.
- [ ] Prioritize navigation, expandable menus, tabs, and representative forms; bound pagination and repeated data variants.
- [ ] Build bounded semantic model views using ARIA and selected DOM fields. Keep complete sanitized evidence; report omissions and truncation.
- [ ] Batch optional model assistance, cap response size and latency, and fall back to code on timeout, invalid schema, output exhaustion, or provider outage.
- [ ] Separate assistance-failure diagnostics from terminal capture stop reasons. Unresolved branches remain visible and pending or explicitly blocked.
- [ ] Extend resume to eligible legacy planner-failed runs after checking frontier integrity and interrupted actions.
- [ ] Persist configuration changes on resume; clarify elapsed-time and additional-budget semantics.

Likely areas: `browser/playwright.py`, `discovery/candidates.py`, `discovery/planner.py`, `discovery/runner.py`, repository recovery, and CLI error handling.

Acceptance: an invalid planner response on a page with many controls cannot discard the frontier or stop otherwise possible deterministic exploration. A nested-menu fixture discovers all designated permitted menu entries within a fixed test budget. Authentication still pauses clearly; an uncertain write is not automatically repeated. Measure real-target coverage separately without promising completeness.

## Phase C — Distill features and procedures from saved evidence

- [ ] Extract offline services for feature grouping, representative path selection, procedure proposals, and unresolved-question reporting.
- [ ] Process bounded evidence groups by area and role, with provenance-preserving merging.
- [ ] Persist per-group model results, prompt/model versions, and usage. The first slice persists deterministic processor configuration, results, errors, and retries.
- [x] Reuse completed outputs only when manifest and processor configuration identity match; create a new manifest revision when captured inputs change.
- [ ] Validate procedure proposals against recorded action continuity. Missing steps become capture requests, never demonstrated instructions.
- [x] Provide deterministic baseline feature summaries when no model is configured; processing failures leave saved capture evidence retryable.

Likely areas: a small distillation service module, existing feature/workflow builders, repository stage records, and model contracts. Add a directory only if the responsibility warrants it.

Acceptance: close the browser and make the target unreachable, then distill a saved bundle successfully using a scripted model. Fail one group, retry it, and confirm completed groups and capture action counts are unchanged. Live-provider evaluation is separate and budgeted.

## Phase D — Publish the documentation evidence supports

- [ ] Add feature-reference and procedure document kinds with observed, demonstrated, and replay-verified evidence support distinct from editorial approval.
- [ ] Define schemas and templates for purpose, navigation, visible controls/fields, prerequisites, steps, and supported outcomes.
- [ ] Compose from persisted distillation and evidence; resolve illustrations only to retained artifacts.
- [ ] Validate claim support, role, evidence currency, and document revision independently of model prose.
- [ ] Preserve existing verification gates for existing procedure exports. Add the observed feature-reference path with exact-revision approval.
- [ ] Define and document explicit auto-approval eligibility for feature references; do not automatically approve demonstrated-only procedures in this migration.
- [ ] Extend coverage reports to separate observed features, demonstrated procedures, replay verdicts, document availability, approval, and unexplored branches.
- [ ] Retry composition per document and preserve previous reviews and manual edits as revisions.

Likely areas: document models, `documentation/service.py`, `composer.py`, templates, `publish.py`, repository coverage, and review commands.

Acceptance: a captured settings form produces a useful feature reference without submitting it. It cannot produce a claim that saving works without outcome evidence. Observed references and existing verified guides can export together under their respective approval rules. Stale, missing, unrelated, or wrong-role evidence prevents affected claims from publishing. MkDocs builds with valid links and assets.

## Phase E — Parameterize inputs without assuming reset

- [ ] Define typed input bindings and validation, with execution-scoped generators and cross-step reuse.
- [ ] Bind generated values before action execution and store sensitive bindings privately.
- [ ] Keep bindings stable on resume; use fresh values only for a new authorized execution.
- [ ] Track created-record references and dependencies between steps.
- [ ] Add prerequisite strategies for existing data, operator-prepared state, and configured environment adapters.
- [ ] Validate parameter suggestions from distillation; require preparation when uniqueness alone cannot make replay possible.
- [ ] Record optional cleanup outcomes and reconcile uncertain writes before retry.

Likely areas: workflow input models, replay preparation, environment adapters, and action recovery.

Acceptance: two new executions use distinct constrained values, all steps within each execution reuse the same bindings, and crash recovery does not generate a second record. A missing prerequisite produces an explicit blocked procedure while feature documentation remains available. A non-resettable fixture exercises the same contract.

## Phase F — Add optional operator recordings

- [ ] Define an explicit recording session with role/scope metadata, pause/stop, capture boundaries, and redaction rules.
- [ ] Capture supported user actions and resulting observations through the same manifest format; never store entered passwords as reusable procedure inputs.
- [ ] Mark recording origin and unsupported/manual steps. Capturing a human action does not authorize automated repetition.
- [ ] Validate continuity and outcomes before treating a recording as demonstrated evidence.
- [ ] Feed recordings and supplied workflows through the same offline distillation pipeline as autonomous capture.

Acceptance: a recorded supported multi-step operation generates a traceable draft after browser closure. An unsupported custom interaction becomes a visible gap. Autonomous exploration still works with no recording or supplied workflow.

## Phase G — Integrate the operator experience and evaluate

Proposed interfaces below are design targets, not commands available today:

| Operation | Proposed interface | Browser needed? |
| --- | --- | --- |
| Capture | Existing `discover` / `discover-resume`, producing manifests | Yes |
| Record | New `record` command | Yes |
| Interpret saved evidence | New `distill PROJECT --run RUN_ID` | No |
| Compose/review/export saved results | New `docs-build PROJECT OUTPUT --run RUN_ID` | No |
| Capture through export | Existing `docs-generate PROJECT OUTPUT` orchestrates stages | Capture and any requested replay only |

For new offline commands, default to the latest compatible result for the selected project and role, print the resolved run, and accept an explicit run override. Never silently select evidence from another role or fall back to recapturing when saved evidence is insufficient. Resolve exact naming and option compatibility during implementation and update `--help`, README, and scripts together.

- [ ] Preserve current command names and existing project configuration; document new defaults and stage-specific budget precedence.
- [ ] Allow one-command generation to continue from persisted stages with clear stage summaries and supported retry commands.
- [ ] Keep existing `--resume-run` discovery behavior compatible; distinguish capture resume from retrying offline processing.
- [ ] Emit actionable failure messages and nonzero failure exits for required stages; distinguish intentional partial coverage from successful full completion.
- [ ] Document output paths, artifact layout, automatic approval rules, migration/backup procedures, and retry examples.
- [ ] Run deterministic end-to-end and migration acceptance against old and new records.
- [ ] Compare matched-budget autonomous captures on representative Chainlit and Lodur scopes when access is available; retain failures and unvisited areas in reports.
- [ ] Have a user follow a representative generated guide and inspect feature references for unsupported behavioral claims.

Acceptance: generate documentation from retained evidence while the target is offline, retry a failed composition without login, and run the one-command path on a fresh fixture. Existing verified guides still export. An intentional interrupted run exposes usable partial evidence and remaining work. Publish measured results and unresolved limitations rather than marking external evaluations passed by assumption.

## Validation and release gates

Use scripted models for routine tests. Exercise the real local browser for observation, navigation, recovery, and screenshots. Focus regression tests on boundaries where behavior changes: migrations, stage checkpoints, fallback, claim eligibility, input identity, and retries after uncertain writes.

Release requires no evidence loss in migration fixtures, no duplicated uncertain writes in recovery tests, no unsupported procedural outcome claims in reviewed examples, and successful independent capture/distillation/composition retries. Compare recall and cost against the frozen baseline; do not trade away menu coverage merely to reduce tokens. Record live-model and user-study results separately from deterministic acceptance.

A schema migration must be backed up and reversible by restoring the project database and matching artifacts; do not promise automatic downgrade compatibility. Retain old exports unchanged. Roll out observed-reference publication only after its evidence and approval checks pass; the existing verified-guide path remains usable throughout migration.

## First implementation slice

Implement phase A and the smallest useful portion of C: freeze an existing discovery run into a manifest, process one captured area into a persisted feature draft, and retry that processing with the browser closed. Then implement phase B's planner-failure fallback and recovery. This validates the new boundary early while addressing the failure that currently interrupts long explorations.

Document new CLI examples only when their corresponding behavior is implemented. Keep all checkboxes here pending until validated; this documentation change does not claim the migration is complete.
