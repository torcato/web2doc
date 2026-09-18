# Offline distillation implementation record

Date: September 18, 2026

Status: first vertical slice implemented; feature-reference publishing and planner fallback remain pending

## Delivered behavior

The first migration slice separates persisted browser capture from feature processing. Existing and new runs can be frozen into immutable capture manifests. A manifest records its run, role, origin, status, limits, frontier summary, observations, artifact paths and hashes, actions, transitions, and candidate features. It references existing evidence instead of copying artifact bytes.

`capture-freeze PROJECT RUN_ID` verifies every referenced observation artifact and creates or reuses a content-addressed manifest. If discovery later adds evidence, freezing creates a new version. An unchanged run returns the existing manifest.

`distill PROJECT --run RUN_ID` freezes the current evidence and runs deterministic feature distillation without opening a browser or loading target authentication. The result contains feature drafts with observation and screenshot provenance. Existing candidate features are preferred; successful captured operations provide a conservative fallback and are marked as not independently verified.

Processing attempts store the manifest, processor identity, configuration hash, status, error, and completion time. Feature outputs are stored per attempt. A successful result with identical inputs is reused. A failed attempt can be retried while the underlying capture and its action count remain unchanged.

## Storage migration

Alembic revision `0005_offline_distillation` adds:

- `capture_manifests` for immutable, versioned evidence snapshots;
- `processing_attempts` for independently retryable offline stages;
- `distilled_features` for evidence-linked feature drafts.

The migration is additive. Existing run, workflow, verification, document, review, and export tables are unchanged.

## Validation

Automated coverage verifies idempotent manifest freezing, artifact-integrity checks through the artifact store, evidence-linked deterministic output, successful-result reuse, and retry after an offline processing failure without new browser actions. Migration, repository, CLI help, lint, and strict type checks pass. Browser extraction no longer presents arbitrary DOM IDs as user-facing names; known controls can still receive explicit synthetic labels.

## Next slice

Implement deterministic discovery scheduling with optional bounded model batches and fallback. A planner output failure should remain a diagnostic event, preserve the frontier, and allow other permitted branches to continue. Then add model-backed offline grouping on top of the manifest and processing-attempt contracts delivered here.
