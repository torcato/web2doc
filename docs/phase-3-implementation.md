# Phase 3 implementation record

Date: September 14, 2026  
Status: core implementation complete; live discovery-to-verification quality gate pending

## Outcome

Phase 3 turns discoveries into immutable, replayable workflow revisions and judges their outcomes using explicit predicates. A completed browser action is not proof of success. Each verification is recorded as `passed`, `failed`, or `inconclusive` against an exact workflow revision, fixture receipt, predicate result set, and captured browser evidence.

The implementation adds:

- deterministic workflow drafts from explored Phase 2 transitions;
- a JSON workflow schema for role, scenario, prerequisites, named test inputs, semantic actions, step outcomes, final outcomes, source features, and unresolved questions;
- immutable, content-addressed workflow revisions with normalized step records;
- trusted same-origin fixture preparation, state inspection, and reset operations;
- replay through the Phase 1 policy and action journal;
- UI, URL, title, semantic-control, and trusted environment JSON predicates;
- explicit verification and per-predicate reports linked to observations;
- uncertain-write reconciliation that checks authoritative state before allowing a retry;
- a frozen local inventory of ten positive and negative fixture workflows.

## Commands

Create reviewed workflow candidates from an existing discovery run:

```bash
uv run web2doc workflow-draft PROJECT DISCOVERY_RUN_ID --role default
```

Import or revise a JSON definition. Importing identical semantic content returns the existing revision; changing it creates the next immutable version.

```bash
uv run web2doc workflow-add PROJECT examples/workflow.json
```

Replay an exact revision and print its verification report:

```bash
uv run web2doc verify PROJECT REVISION_ID --trusted-fixture-api
uv run web2doc verification-report PROJECT VERIFICATION_ID
```

`--trusted-fixture-api` enables fixed same-origin `POST /__reset`, `POST /__prepare`, and `GET /__state` endpoints. It is intended for a controlled test environment, not an arbitrary production website. Without it, environment predicates are reported as inconclusive.

## Verification semantics

The runner opens the configured project URL from a known browser context, evaluates prerequisites, materializes exact `{{input_name}}` placeholders in fill/select values, and executes each semantic action through the existing allowlist policy. It captures ARIA and screenshot evidence after every action.

Predicates are application-owned typed data rather than model prose:

| Predicate | Evidence checked |
| --- | --- |
| `visible_text` | Captured semantic accessibility snapshot |
| `url` | Exact URL, prefix, or parsed path |
| `title` | Exact or contained page title |
| `control` | Semantic role/name, label, or test-id plus enabled state |
| `environment_json` | A named path returned by the trusted state endpoint |

Any failed predicate makes the verification fail. Missing trusted evidence or an unreconciled write makes it inconclusive. Passed and failed runs remain `awaiting_review`; inconclusive runs pause.

## Crash and retry behavior

A browser failure after a write begins is recorded as `uncertain`, and the prepared fixture is deliberately retained. A later replay of the same workflow revision reuses that receipt and evaluates the step's trusted environment predicate before acting:

- if the effect is present, the action is recorded as `reconciled` and is not repeated;
- if one authoritative predicate conclusively shows absence, replay may execute it;
- if evidence is unavailable, absent, or conflicting, replay pauses as inconclusive.

This protects the tested fixture workflow from duplicate writes. It does not make arbitrary web operations idempotent.

## Storage

Migration `0003_phase3` adds workflow catalogs and revisions, normalized steps, fixture receipts, verifications, and predicate results. Workflow content hashes ignore generated action IDs so importing the same semantic JSON does not create spurious revisions. Evidence remains in the existing immutable artifact and observation stores.

## Local acceptance results

The deterministic fixture inventory contains ten workflows: view, create, required-field validation, edit, delete, search, dialog, tab selection, denied access, and failed save. The failed-save page intentionally renders a success-looking status while authoritative state remains unchanged.

The local checks completed with:

```text
ten-workflow Chromium benchmark: 30/30 passed (each workflow replayed three times)
pytest on Python 3.12: 57 passed
pytest on Python 3.13: 57 passed
real-Chromium tests: 10 passed (including the 30-replay benchmark)
ruff: all checks passed
mypy --strict: no issues
```

## Remaining quality gate and blind spots

Core Phase 3 is complete, but the roadmap's live-model gate is not claimed. At least 8/10 fixture workflows must still be discovered and converted into passing verifications in controlled live-model trials. Phase 2's five-run feature-recall gate also remains pending.

Additional limits remain:

- The trusted adapter assumes the target team supplies safe, authenticated, same-origin fixture endpoints. Many real products will need database snapshots, API adapters, or tenant cloning instead.
- Reconciliation is only safe when a predicate uniquely proves the intended effect. Multi-record writes, generated identifiers, queues, and third-party side effects need operation-specific checks.
- Test input values are persisted in workflow JSON and receipts. Store only synthetic data; secret references and a secret resolver are not implemented.
- Accessibility snapshots cannot cover canvas-only, inaccessible, gesture-only, hover-only, or visually encoded state.
- Authentication capture exists, but automatic login renewal, MFA, CAPTCHA, anti-bot defenses, and session-expiry recovery remain site-specific.
- Delayed controls and ambiguous selectors are exercised by the browser suite, but highly dynamic optimistic UI and eventual consistency require target-specific time and state predicates.
- Draft grouping is deterministic and conservative. Human review is still required to name business goals, confirm prerequisites, and resolve questions before documentation generation.
