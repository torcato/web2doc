# Phase 2 implementation record

Date: September 14, 2026  
Status: core implementation complete; live-model quality gate pending

## Outcome

Architecture evolution: this is a historical implementation record. The [new architecture](../architecture.md) retains autonomous discovery but makes deterministic scheduling the default and bounded model assistance optional. See the [migration plan](../development-plan.md) for proposed changes; they are not implemented by this record.

Phase 2 adds bounded website-state discovery without weakening the Phase 1 execution boundary. Application code extracts visible controls and constructs a closed set of typed candidate actions. A planner may rank those candidate IDs and describe candidate features, but it cannot invent URLs, selectors, tools, JavaScript, or shell code.

Two discovery modes use the same evidence and graph storage:

- `unguided` enumerates visible controls, ranks candidates, explores them within configured limits, and reports blocked or unexplored work.
- `supplied` executes a known JSON procedure while mapping each observed state and transition; it makes no model calls.

## Components

| Component | Responsibility |
| --- | --- |
| State canonicalizer | Normalizes routes and structural observations, removes configured volatility, sanitizes model text, and creates versioned SHA-256 fingerprints |
| Candidate enumerator | Converts visible links, buttons, text fields, and selects into typed Phase 1 actions; ignores disabled and password controls |
| Heuristic planner | Deterministic provider-free ranking for development, CI, and baseline comparisons |
| Pydantic AI planner | Structured candidate ranking and feature interpretation with validated output and usage reporting |
| Budget tracker | Enforces time, action, state, path-depth, model-call, and output-token limits independently of the model |
| Exploration runner | Persists intent, applies policy, executes actions, records transitions, restores branches, detects loops, and records every stop reason |
| Discovery report | Exposes states, transitions, candidate features, frontier status, blocked/skipped reasons, and model usage |

Pydantic AI Slim 2.43 is locked with the OpenAI provider extra. The runtime also provides a narrow planner protocol, so another provider or a deterministic test planner can be substituted without changing the explorer.

## State identity

Observations remain immutable evidence. Multiple observations may point to one canonical state. The `state-v1` fingerprint includes:

- normalized route and relevant sorted query parameters;
- role and configured scenario;
- normalized ARIA structure and title;
- active dialogs and selected tabs;
- visible alerts and user-invalid controls.

Configured cache/timestamp query parameters, ISO-like timestamps, and UUID-like identifiers are ignored by default. Errors, dialog changes, role changes, and scenario changes remain meaningful. Changing normalization rules requires a new algorithm version rather than silently reusing existing identities.

The model receives a bounded text view, not screenshots, cookies, form values, or authentication files. Common secret assignments are redacted. Page text remains present as untrusted data so that possible prompt injection is observable; the planner instruction explicitly forbids following page instructions.

## Graph and frontier persistence

Migration `0002_phase2` adds:

- run stage, scenario, discovery mode, and serialized limits;
- canonical states linked to representative observations;
- action-attempt-linked transitions, including self-transitions;
- frontier items with typed action JSON, priority, depth, saved path, status, and reason;
- candidate features linked to a state and supporting observation;
- per-call model usage events.

Frontier uniqueness is scoped to a run, state, and action signature. Returning to the same state does not schedule the same candidate repeatedly.

To explore a sibling branch, the runner navigates to the configured start URL and replays the saved semantic-action prefix. Every restoration action is journaled and consumes the normal action budget. The expected state fingerprint must match before the candidate is executed; otherwise the item is marked blocked. This restores browser state, not backend data.

## Safety model

- The model selects only application-generated candidate IDs.
- Unknown model candidate IDs are discarded; a wholly invented plan fails.
- Candidate actions still pass through the Phase 1 origin and operation policy.
- Buttons with write-like labels are conservatively classified as writes and require an allowlisted generated operation ID.
- Password fields are never candidates and their values are never collected.
- Provider failures use bounded retries. Missing usage is charged at the configured per-call maximum.
- Expired/login states pause discovery with `authentication_required`.
- Self-transitions and repeated-state visits stop explicitly as `loop_detected`.
- Budget exhaustion yields an evidence-backed partial result with a precise stop reason.

These controls reduce risk but cannot prove a click is read-only. Execute discovery against test accounts and resettable, non-production data with worker-level egress restrictions.

## Usage

The generated `project.toml` contains `[discovery]` normalization settings and `[discovery.limits]` budgets. Run a deterministic baseline:

```bash
uv run web2doc discover PROJECT \
  --role default \
  --max-actions 20 \
  --max-states 15 \
  --max-seconds 300
```

Run with a configured Pydantic AI provider:

```bash
uv run web2doc discover PROJECT --role default --model PROVIDER:MODEL
```

`WEB2DOC_LLM_MODEL` may supply the model name instead. Provider credentials use the provider SDK's environment configuration and are not written to project files or the run database.

Map a known workflow and retrieve a report:

```bash
uv run web2doc discover PROJECT --mode supplied --procedure procedure.json
uv run web2doc discovery-report PROJECT RUN_ID
```

## Verification coverage

The automated suite covers:

- Phase 1 to Phase 2 migration with existing run preservation and repeatable upgrades;
- timestamp/query churn, fingerprints, dialogs, roles, scenarios, errors, and secret redaction;
- property-tested query-order stability;
- password exclusion and conservative write classification;
- Pydantic AI structured test-model output and invented candidate rejection;
- model retry, call, and conservative token bounds;
- state, transition, feature, frontier, and usage persistence;
- sibling-branch restoration and restoration-state checks;
- action-budget exhaustion, frontier exhaustion, self-loop detection, and authentication expiry;
- supplied-mode execution with zero planner calls;
- real-Chromium control extraction and bounded discovery against the local fixture.

Routine tests make no provider calls. A live provider run is intentionally separate because it requires explicit credentials and a fixed cost budget.

The final local verification result is:

```text
pytest on Python 3.12: 48 passed
pytest on Python 3.13: 48 passed
real-Chromium tests: 8 passed
ruff: all checks passed
mypy --strict: no issues in 29 source files
git diff --check: clean
```

A fresh CLI smoke run initialized a project, upgraded its database, mapped the fixture's home and detail states plus their transition, emitted five candidate features, and recorded all remaining candidates with `action_budget_exhausted` when the configured two-action limit was reached. The synthetic initial `about:blank` page is neither persisted nor counted as a website state.

## Remaining quality gate and blind spots

The core Phase 2 implementation is complete, but the roadmap's quality exit criterion has not been claimed:

- The local fixture still lacks the frozen ten-workflow owner inventory needed to measure recall.
- Five independent live-model discovery trials have not been run because no provider/model budget was supplied.
- No real target website has been baselined for authentication expiry, complex iframes, downloads, virtualized controls, canvas interfaces, or anti-automation behavior.
- Path replay cannot restore mutated backend data. A trusted reset/checkpoint adapter is planned for Phase 3.
- Candidate extraction uses accessible HTML controls. Gesture-driven, canvas-only, hover-only, and custom controls without useful accessibility semantics may be missed.
- Feature records are candidates, not verified user workflows. Their unresolved status is explicit until Phase 3 outcome checks succeed.
- Text redaction is pattern-based and not proof against arbitrary sensitive content. Screenshots and traces remain private and are not sent to the model.

Before declaring the Phase 2 milestone fully accepted, complete the ten-workflow fixture inventory, freeze its data and role matrix, choose one provider/model and budget, run five trials, and report per-run recall and blockers rather than only the best result.
