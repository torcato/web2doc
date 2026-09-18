# Offline distillation implementation record

Date: September 18, 2026

Status: immutable capture/distillation, resilient discovery scheduling, and observed feature-reference publishing implemented

## Delivered behavior

The first migration slice separates persisted browser capture from feature processing. Existing and new runs can be frozen into immutable capture manifests. A manifest records its run, role, origin, status, limits, frontier summary, observations, artifact paths and hashes, actions, transitions, and candidate features. It references existing evidence instead of copying artifact bytes.

`capture-freeze PROJECT RUN_ID` verifies every referenced observation artifact and creates or reuses a content-addressed manifest. If discovery later adds evidence, freezing creates a new version. An unchanged run returns the existing manifest.

`distill PROJECT --run RUN_ID` freezes the current evidence and runs deterministic feature distillation without opening a browser or loading target authentication. The result contains feature drafts with observation and screenshot provenance. Existing candidate features are preferred; successful captured operations provide a conservative fallback and are marked as not independently verified.

Processing attempts store the manifest, processor identity, configuration hash, status, error, and completion time. Feature outputs are stored per attempt. A successful result with identical inputs is reused. A failed attempt can be retried while the underlying capture and its action count remain unchanged.

Discovery now fingerprints semantic UI structure instead of Playwright session references. Transient ARIA markers such as `ref`, `cursor`, and `active` are removed while meaningful state such as `checked`, selected tabs, and dialogs remains part of state identity. This prevents a visually unchanged page from consuming the state budget as hundreds of false states.

Frontier scheduling applies deterministic coverage tiers above optional model ranking. Settings and configuration entry points are handled before state-reset actions such as New chat. Per-state visit and per-action repeat limits prevent one branch from monopolizing the action budget. If the configured planner exhausts its call/token allowance or repeatedly returns an invalid result, the run records the failure and continues with the deterministic planner.

Because state identity changed from `state-v1` to `state-v2`, old discovery runs remain readable and distillable but are not safe to resume. The resume command returns an explicit instruction to start a fresh run.

Completed distillation results can now produce versioned feature-reference documents. Configuration controls are grouped into a settings page and choices observed after opening each control are rendered as options rather than standalone pages. References record observed or demonstrated evidence separately from verified workflow claims, support exact-revision review bundles, and export alongside verified guides. `docs-generate` runs capture freezing, distillation, reference generation, automatic review, workflow verification, and combined export in one operation.

New observations persist a structured control inventory in capture manifest schema 2. This preserves native select options for offline documentation, while custom dropdown choices continue to come from captured state transitions. An intermediate documentation plan owns page structure, widget types, option lists, option-completeness labels, audience, tone, and evidence. Optional model editing receives a bounded plan and may return only a summary and one explanation per existing section. Invalid output falls back to a more explanatory deterministic editor without changing facts.

AI documentation composition is isolated from verified workflow structure. Returned prose is assigned the verified step order, and structural or provider failures fall back to deterministic composition for only the affected document. The run continues and marks a newly created fallback revision with source kind `generated-fallback`.

## Storage migration

Alembic revision `0005_offline_distillation` adds:

- `capture_manifests` for immutable, versioned evidence snapshots;
- `processing_attempts` for independently retryable offline stages;
- `distilled_features` for evidence-linked feature drafts.

Revision `0006_feature_references` adds versioned feature-reference documents and exact-revision reviews. Revision
`0007_observation_controls` adds structured control inventories to observations for offline option documentation.

The migration is additive. Existing run, workflow, verification, document, review, and export tables are unchanged.

## Validation

Automated coverage verifies idempotent manifest freezing, artifact-integrity checks through the artifact store, evidence-linked deterministic output, successful-result reuse, structured select options, documentation plans, constrained model editing, model fallback, and retry after an offline processing failure without new browser actions. Discovery regressions cover volatile Chainlit-style references, settings-first scheduling, repeat suppression, planner failure, and model-budget fallback. Migration, repository, CLI help, lint, and strict type checks pass. Browser extraction no longer presents arbitrary DOM IDs as user-facing names; known controls can still receive explicit synthetic labels.

## Next slice

Improve generic area classification beyond settings/interfaces and add owner-maintained descriptions for product-specific option values. Model-assistance batching, legacy-run migration, persisted resume configuration, and parameterized replay remain separate follow-up work.
