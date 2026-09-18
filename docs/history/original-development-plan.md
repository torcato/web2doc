# Phased development plan

Date: September 14, 2026  
Status: historical implementation checklist; replaced for new development on September 18, 2026

The active roadmap is the [capture and offline distillation development plan](../development-plan.md), based on the [revised architecture](../architecture.md). It builds on the existing application rather than starting again at phase 0. Keep the completed tasks and pending evaluation gates below as the baseline record; the estimates and sequence below are not the new migration schedule.

Related documents:

- [Architecture and library decisions](original-architecture.md)
- [Feasibility case study](feasibility-case-study.md)
- [Phase 1 implementation record](phase-1.md)
- [Phase 2 implementation record](phase-2.md)

## Objective

Build a Python application that explores a website, identifies user workflows, verifies them through browser interaction, and generates documentation supported by recorded evidence.

The initial release runs locally against one application with two user roles and representative test data. It produces Markdown guides, screenshots, a coverage report, and a reviewed static documentation export.

This document is the implementation roadmap. The architecture document remains the reference for component interfaces, storage models, and library choices. Keep both documents aligned when scope or milestones change.

## Delivery overview

Estimates assume one experienced engineer, a resettable test environment, and a product owner available for feedback. They describe engineering effort, not guaranteed delivery dates.

| Phase | Outcome | Estimated effort | Depends on |
| --- | --- | --- | --- |
| 0. Preparation and benchmark | Repeatable test website and confirmed browser stack | 2–3 days | None |
| 1. Browser and evidence foundation | Execute configured actions and persist their evidence | 4–6 days | Phase 0 |
| 2. Feature discovery | Explore interface states with a bounded LLM planner | 4–6 days | Phase 1 |
| 3. Workflow verification | Replay procedures and establish their outcomes | 5–7 days | Phase 2 |
| 4. Documentation generation | Produce and review illustrated user guides | 4–6 days | Phase 3 |
| 5. Pilot and review interface | Operate resumable jobs and review results through a local UI | 6–9 days | Phase 4 |
| 6. Documentation maintenance | Detect changes and update affected guides | 5–8 days | Phase 5 |

Total implementation effort is **30–45 working days**, or **6–9 engineer-weeks**. Budget **8–12 weeks** including integration, feedback, and contingency.

The milestones are:

- **Technical prototype:** phases 0–3, approximately 3–5 weeks.
- **Documentation-producing MVP:** phases 0–4, approximately 4–6 weeks.
- **Operational pilot:** phase 5 completed.
- **Maintenance-capable pilot:** phase 6 completed.

The original plan began with all phases pending. Phase 1–4 core implementation is now recorded below, with remaining live-model and human evaluation gates explicitly outstanding. A phase is accepted when its deliverables and exit criteria are demonstrated, not merely when its tasks are implemented.

## Python library adoption plan

The original architecture selected the core stack. This section records its adoption plan; it is not a current dependency audit. Consult the repository's package configuration and implementation records for installed dependencies and validation status.

### Application libraries

| Package | Purpose and integration decision | Introduction | Required validation |
| --- | --- | --- | --- |
| [`playwright`](https://playwright.dev/python/docs/intro) | Async browser control, semantic locators, screenshots, authentication state, and traces behind the browser adapter | Phase 0 benchmark; phase 1 runtime | Launch pinned Chromium, perform fixture actions, capture evidence, isolate roles, and clean up sessions |
| [`pydantic`](https://docs.pydantic.dev/latest/) | Typed configuration, actions, observations, workflows, and document records | Phase 1 | Reject invalid payloads and verify serialization of versioned records |
| [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | Runtime configuration and environment-based settings; reference credentials separately from persisted run data | Phase 1 | Test configuration precedence, missing settings, and absence of secrets in normal logs |
| [`sqlalchemy`](https://docs.sqlalchemy.org/en/20/) | Repositories and transactional persistence using SQLite initially | Phase 1 | Test transactions, constraints, action journals, and restart consistency |
| [`alembic`](https://alembic.sqlalchemy.org/en/latest/) | Database schema migrations | Phase 1 | Create a fresh database and migrate a representative prior schema without losing evidence references |
| [`typer`](https://typer.tiangolo.com/) | CLI for setup, authentication, runs, verification, review, and export | Phase 1 | Exercise argument validation, exit codes, and operator-visible failure states |
| [`pydantic-ai`](https://pydantic.dev/docs/ai/overview/) | Structured model calls for action proposals, workflow interpretation, and document composition | Phase 2 | Substitute test models, reject malformed output, enforce usage limits, and run a bounded provider smoke test |
| [`jinja2`](https://jinja.palletsprojects.com/en/stable/) | Application-owned templates for documents and later review pages | Phase 4 | Check escaping, required fields, evidence links, and malicious text handling |
| [`mkdocs`](https://www.mkdocs.org/) | Build reviewed Markdown and assets into a local static documentation site | Phase 4; `docs` extra | Build strictly, check assets and local links, and inspect representative rendered pages |
| [`fastapi`](https://fastapi.tiangolo.com/) | Local review API and lightweight review pages; browser jobs remain in the separate worker | Phase 5 runtime; `api` extra | Test job submission, project scope, stale revisions, and local request protections |
| [`uvicorn`](https://github.com/Kludex/uvicorn) | ASGI server for FastAPI | Phase 5 runtime; `api` extra | Test startup, shutdown, loopback binding, and requests against the running server |
| [`httpx`](https://www.python-httpx.org/) | Fixture/API testing and, only when required, trusted target-specific setup or outcome adapters | Phase 0 tests; optional runtime use from phase 3 | Test timeouts, error responses, fixture reset, and adapter outcome checks |

Use short synchronous SQLAlchemy transactions initially, outside browser and model awaits. SQLite access uses Python's included driver; an additional async database driver is not required for this design. Reconsider async access or PostgreSQL when measurements or deployment requirements justify it.

Choose one model provider for the first integration and record the exact model/configuration used in evaluations. Keep provider access behind the model service. Declare a provider SDK directly only if application code imports it; otherwise use Pydantic AI's supported provider installation. A provider-specific slim installation can replace the broader package after the integration is validated. [Pydantic AI installation options](https://pydantic.dev/docs/ai/overview/install/).

Use FastAPI and Uvicorn as test-only dependencies in phase 0 to serve the resettable fixture application. Adding them to the runtime `api` extra in phase 5 does not change the CLI-first milestone sequence. HTTPX remains test-only unless a real runtime adapter needs it.

### Testing and development tools

| Package / tool | Planned use | Introduction |
| --- | --- | --- |
| [`pytest`](https://docs.pytest.org/en/stable/) | Unit, integration, browser, and end-to-end test runner | Phase 0; `test` group |
| [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/en/stable/) | Async tests and browser/model fixtures | Phase 0; `test` group |
| [`hypothesis`](https://hypothesis.readthedocs.io/en/latest/) | Property tests for policy, URL normalization, fingerprints, and budgets | Phase 1; `test` group |
| Pydantic AI test models | Scripted responses and provider-free execution in routine CI | Phase 2; part of the selected Pydantic AI installation |
| [`ruff`](https://docs.astral.sh/ruff/) | Formatting and linting | Phase 0; `lint` group |
| [`mypy`](https://mypy.readthedocs.io/en/stable/) | Static checks for domain models and adapter contracts | Phase 0; `lint` group |
| [`uv`](https://docs.astral.sh/uv/) | Python environment management, dependency resolution, and locked execution | Phase 0; development/CI tool, not an application import |

Browser integration tests use the same Playwright adapter as the application. Routine CI uses scripted model responses; live model evaluations remain a separate budgeted job.

### Standard-library choices

Use `asyncio` for async execution, `tomllib` for reading project TOML, `pathlib` for managed artifact paths, `hashlib` for content hashes, `json` for serialized payloads, and `logging` for application logs. Phase 6 can use `difflib` for textual revision comparisons alongside the application's structured dependency checks.

The initial durable worker uses the database and application lifecycle code. A distributed queue, graph database, vector store, or additional orchestration framework is not required for the first pilot.

### Dependency organization and version policy

| Declaration in `pyproject.toml` | Contents as phases are implemented |
| --- | --- |
| `project.dependencies` | Core CLI/browser/persistence packages; add Pydantic AI in phase 2 and Jinja2 in phase 4 |
| `project.optional-dependencies.docs` | MkDocs for static export |
| `project.optional-dependencies.api` | FastAPI and Uvicorn for the phase 5 review service |
| `dependency-groups.test` | pytest, pytest-asyncio, HTTPX, fixture FastAPI/Uvicorn, and Hypothesis when introduced |
| `dependency-groups.lint` | Ruff and mypy |
| `dependency-groups.benchmark` | Stagehand only while the phase 0 comparison is maintained |

uv distinguishes runtime dependencies, installable extras, and local development groups. [uv dependency management](https://docs.astral.sh/uv/concepts/projects/dependencies/).

Keep optional imports inside the corresponding feature boundary: running the base CLI must not require the `api` or `docs` extras. Missing extras should produce an actionable installation message. The fixture's test dependencies must not hide missing runtime dependency declarations, so test a clean base installation separately.

Start with Python 3.12, declare supported versions explicitly, and commit both `pyproject.toml` and `uv.lock`. Select compatible stable releases during implementation and record exact tested versions in the lockfile and milestone notes. Do not infer compatibility merely because individual packages support Python 3.12.

Install Chromium and required operating-system dependencies separately through the tested Playwright setup. Keep browser binaries or container images aligned with the locked Playwright version. Dependency upgrades must rerun relevant integration tests; browser/model changes also rerun the affected live evaluations.

### Deferred alternatives

| Candidate | Adoption condition |
| --- | --- |
| Stagehand | Phase 0 comparison demonstrates a material benefit while preserving action policy, evidence, and replay contracts |
| Playwright MCP and the Python MCP SDK | External MCP-client interoperability becomes an explicit requirement; the browser server also introduces a Node.js runtime |
| Browser Use | Measured discovery gaps justify an alternative planner, subject to the same controlled executor requirements |
| Crawljax | State discovery gains justify a separately operated Java component |
| Crawlee / Crawl4AI | Broad URL crawling or existing-content extraction becomes a demonstrated need |
| LangGraph | Resumable orchestration outgrows the initial explicit state machine |

These are evaluation options, not dependencies to install together. The [architecture alternatives](original-architecture.md#alternatives-and-adoption-triggers) and [case-study tool comparison](feasibility-case-study.md#tool-comparison) contain the supporting rationale and sources.

### Library adoption checklist

Before accepting a new dependency or upgrade:

- [ ] Confirm that it serves a named component and development phase.
- [ ] Add it to the correct runtime extra or development group and update the lockfile.
- [ ] Check Python/platform compatibility and the project's distribution/license requirements.
- [ ] Run the relevant validation from the library table in a clean environment.
- [ ] Verify that base CLI and optional-feature installations work independently.
- [ ] Record tested versions, browser prerequisites, and any known limitations.

## Phase 0 — Preparation and benchmark

### Goal

Establish a reproducible development environment and a small benchmark before implementing autonomous exploration.

### Implementation tasks

- [ ] Create the Python package skeleton, `pyproject.toml`, and locked dependencies using uv.
- [ ] Establish the dependency groups and optional extras from the library adoption plan; keep later-phase packages out until needed.
- [ ] Configure Ruff, mypy, pytest, and pytest-asyncio.
- [ ] Start with Python 3.12 and validate compatibility with the selected packages.
- [ ] Build a local fixture website with a resettable backend and two roles.
- [ ] Define an inventory of ten representative workflows and their expected outcomes; implement an initial subset of fixture behavior now.
- [ ] Include navigation, lists, a modal, form validation, delayed responses, and a controlled write.
- [ ] Record independent test data and expected outcomes, separate from model inputs for unguided discovery.
- [ ] Compare Playwright and Stagehand on a few equivalent browser tasks, including evidence capture and action restrictions.
- [ ] Record the browser choice and tested versions. Use Playwright unless the comparison supplies a concrete reason to change.
- [ ] Validate a clean base installation independently of fixture and benchmark dependencies.

### Deliverables

A reproducible environment, an initial fixture website, a benchmark inventory, and a short browser-selection decision record.

### Testing and completion criteria

- Fixture setup and reset restore the same initial backend state.
- Representative browser tasks can be repeated with equivalent results and usable screenshots.
- The chosen browser adapter supports controlled actions and evidence capture.
- At least one representative path is checked on the intended target application when access is available.

If real application access is unavailable, continue fixture development and record that the browser choice has only been validated against the fixture.

## Phase 1 — Browser and evidence foundation

### Goal

Execute a supplied procedure reliably and retain enough evidence to explain what happened, including after an interruption.

### Implementation tasks

- [x] Implement project configuration and initial Typer CLI commands.
- [x] Add Pydantic schemas for runs, roles, actions, observations, and execution results.
- [x] Create SQLAlchemy repositories and Alembic migrations for SQLite.
- [x] Implement artifact storage with hashes and consistent database references.
- [x] Implement the async Playwright browser adapter and semantic target resolution.
- [x] Support operator-assisted login and separate authentication state per role.
- [x] Capture structural observations, screenshots, and private diagnostic traces.
- [x] Enforce configured target scope and allowed operations before execution.
- [x] Persist action intent before browser interaction and record the resulting outcome.
- [x] Add cancellation, browser cleanup, a single-worker project lock, and basic restart handling.
- [x] Mark interrupted actions with unknown effects as uncertain; prevent automatic repetition of uncertain writes.

### Deliverables

A CLI that executes a configured workflow and produces an evidence bundle, backed by persistent run and action records.

### Testing and completion criteria

- Validate configuration, migrations, foreign keys, and missing/failed artifact writes.
- Test stale or ambiguous targets, delayed elements, role separation, redirects, and new tabs.
- Inject failures before and after a controlled write, including after submission but before the result is recorded.
- Confirm restart retains history and does not duplicate an unresolved write.
- Demonstrate a complete configured procedure from a fresh fixture environment.
- Forbidden fixture operations produce zero observed effects in the test suite.

This phase must work without an LLM. The planner added later uses the same execution path.

## Phase 2 — Feature discovery

### Goal

Build a bounded map of meaningful interface states and candidate features.

### Implementation tasks

- [x] Normalize observations into canonical states while retaining original evidence.
- [x] Include role, scenario, route, active dialog/tab, and meaningful control state in identity.
- [x] Ignore configured volatile values while preserving errors and empty/populated states.
- [x] Persist discovered transitions and a queue of unexplored actions.
- [x] Enumerate candidate controls and rank actions by novelty and exploration value.
- [x] Integrate Pydantic AI for typed action proposals and feature interpretations.
- [x] Validate proposals through the phase 1 policy and executor.
- [x] Add loop detection, bounded retries, and limits for time, actions, states, model calls, and token usage.
- [x] Separate supplied-workflow mode from unguided discovery mode.
- [x] Report discovered features, skipped actions, blocked areas, and explicit stop reasons.

### Deliverables

A persisted state graph, a feature inventory, and a coverage/uncertainty report from a bounded exploration run.

### Testing and completion criteria

- Distinguish different dialogs, tabs, and validation states at the same URL.
- Deduplicate repeated content without losing meaningful role or data differences.
- Stop repeated cycles, excessive pagination, and budget exhaustion predictably.
- Handle malformed model output and expired authentication without false completion.
- Test page content that attempts to alter policy or request secrets.
- Keep routine CI deterministic through scripted model responses.
- Run five live discovery trials; target mean feature recall of at least 80% against the ten-item fixture inventory, reporting every run and its blockers.

The recall target applies to the fixture benchmark. It does not establish completeness on an arbitrary website.

Implementation is complete. Phase acceptance remains pending until the frozen ten-workflow fixture inventory exists and five budgeted live-model trials demonstrate and report the recall gate.

## Phase 3 — Workflow construction and verification

### Goal

Convert discoveries into repeatable user procedures and verify their actual outcomes.

### Implementation tasks

- [x] Group observations into candidate user goals and workflow revisions.
- [x] Record role, prerequisites, test inputs, ordered steps, and unresolved questions.
- [x] Serialize semantic locators instead of temporary browser element references.
- [x] Complete fixture support for all ten benchmark workflows, including negative cases.
- [x] Add trusted fixture preparation/reset adapters and track fixture receipts.
- [x] Implement replay from known starting conditions.
- [x] Define explicit step and final-outcome predicates.
- [x] Record verification as passed, failed, or inconclusive against an exact workflow revision.
- [x] Check outcomes before retrying an action with uncertain effects.
- [x] Capture evidence from verified executions for documentation generation.

### Deliverables

A workflow catalog, a replay command, verification reports, and evidence for each supported procedure.

### Testing and completion criteria

- Replay each of the ten fixture procedures three times from reset data.
- Confirm the intended positive or negative outcome, not just that clicks succeeded.
- Test failed saves, delayed completion, broken prerequisites, expired sessions, and ambiguous controls.
- Verify that a success-looking notification cannot override a failed final outcome.
- Inject a crash after submission and demonstrate that recovery does not duplicate the write.
- Require re-verification after target/label recovery.
- Target at least 8/10 workflows for live discovery-to-verification on the frozen fixture suite; retain failures and inconclusive results in reporting.

Completion of this phase is the **technical prototype milestone**.

Core implementation and deterministic local acceptance are complete. The technical prototype is usable; the separate live-model 8/10 discovery-to-verification quality gate remains pending and is not represented as passed.

## Phase 4 — Documentation generation and review

### Goal

Generate readable guides whose instructions and behavioral claims can be traced to applicable evidence.

### Implementation tasks

- [x] Define structured document schemas for goals, prerequisites, steps, outcomes, and troubleshooting.
- [x] Compose drafts from verified workflow revisions using the LLM.
- [x] Associate procedural claims and screenshots with evidence references.
- [x] Accept owner-provided terminology and business rules with explicit provenance.
- [x] Render Markdown using fixed, application-owned Jinja2 templates.
- [x] Generate a coverage report that identifies unverified features and unresolved questions.
- [x] Create a local review bundle with evidence links and versioned edits.
- [x] Record review decisions against exact document revisions.
- [x] Export reviewed guides and assets through MkDocs.
- [x] Preserve manual edits by creating new revisions during regeneration.

### Deliverables

Illustrated user guides, an evidence-backed review bundle, a coverage report, and a local static documentation export.

### Testing and completion criteria

- Test missing, stale, wrong-role, and unrelated evidence references.
- Prevent unverified workflows from being presented as verified instructions.
- Validate output paths, link schemes, escaping, and handling of malicious page/model text.
- Check document structure and evidence associations without requiring exact prose matches.
- Build the site strictly and inspect representative desktop and narrow layouts.
- Require review of factual support; reference existence alone does not establish truth.
- Export only revisions with applicable verification and a matching review decision.
- Target zero unsupported critical behavioral claims in reviewer assessment.
- Have a person unfamiliar with the fixture complete at least 8/10 documented tasks without author assistance; record difficulties and corrections.

Completion of this phase is the **documentation-producing MVP milestone**.

Core implementation and deterministic local acceptance are complete. The documentation-producing MVP is usable; the unfamiliar-user 8/10 study and real-target reviewer assessment remain external acceptance gates and are not represented as passed.

## Phase 5 — Operational pilot and review interface

### Goal

Make long-running jobs and documentation review usable outside a developer's interactive session.

### Implementation tasks

- [ ] Add a separately launched worker and a durable job table.
- [ ] Implement job status, heartbeat, progress, pause, resume, and cancellation.
- [ ] Prevent concurrent executors for the same project and reconcile interrupted work before restarting it.
- [ ] Add a FastAPI review API and lightweight local review pages.
- [ ] Display features, workflows, verification results, evidence, and document revisions.
- [ ] Support corrections and scoped decisions for blocked operations.
- [ ] Protect review decisions against stale revisions and duplicate submissions.
- [ ] Add artifact retention, resource limits, cleanup, and backup/restore instructions.
- [ ] Add structured operational logs and model/runtime usage summaries.
- [ ] Package and document the local pilot deployment.

### Deliverables

A resumable worker, local review interface, operator guide, and completed pilot run on the target application.

### Testing and completion criteria

- Test API contracts, duplicate job requests, concurrent starts, and outdated review decisions.
- Kill and restart the worker during different stages and reconcile uncertain effects.
- Test browser process cleanup, full storage, model unavailability, and exhausted budgets.
- Restore a project from backup and check its evidence references.
- Run a multi-hour fixture soak with bounded model usage.
- Verify loopback request protections; remote deployment additionally requires authentication and project authorization tests.
- Demonstrate that the target owner can complete discovery, review, and export through the pilot workflow.

Completion of this phase is the **operational pilot milestone**.

## Phase 6 — Change detection and documentation maintenance

### Goal

Identify outdated guides and update affected content without discarding reviewed work.

### Implementation tasks

- [ ] Track dependencies between observations, workflows, claims, and document revisions.
- [ ] Compare runs and identify meaningful interface or outcome changes.
- [ ] Mark affected guides and evidence as stale.
- [ ] Rerun affected workflows and regenerate candidate document revisions.
- [ ] Show revision diffs while preserving manual edits and prior exports.
- [ ] Treat failed or inconclusive reruns as unresolved changes, not successful updates.
- [ ] Add a full scoped replay command suitable for periodic scheduling.
- [ ] Record target release identities where available; otherwise use observation timestamps.
- [ ] Run repeated evaluations on the agreed real-target workflow inventory.
- [ ] Compare reviewer effort, verification success, runtime, and estimated cost with the initial baseline.

### Deliverables

A run comparison report, stale-document tracking, selective replay/update support, and a real-application evaluation report.

### Testing and completion criteria

- Seed changes to labels, permissions, validation, prerequisites, and final outcomes.
- Confirm affected guides are identified for every seeded meaningful change.
- Confirm timestamps-only changes do not rewrite unaffected guides.
- Test removed features, unavailable evidence, failed reruns, and preserved manual corrections.
- Keep verification of existing procedures separate from discovery of new features.
- Complete owner review of the real-target suite and document all remaining gaps.

Completion of this phase is the **maintenance-capable pilot milestone**.

## Testing across phases

| Test layer | Purpose | Execution policy |
| --- | --- | --- |
| Unit and property tests | Schemas, policy, fingerprints, budgets, lifecycle invariants | Every relevant change; no network |
| Repository integration | Migrations, transactions, recovery records, artifact consistency | Every change |
| Browser integration | Real actions, observation, waits, redirects, role state | Browser-affecting changes and release candidates |
| Deterministic end-to-end | Full run with a real local browser and scripted model responses | Pipeline changes and release candidates |
| Live-model evaluation | Discovery quality, grounding, recovery, usage and latency | Explicit or scheduled runs with fixed budgets |
| Human review | Business accuracy, readability, task completion | Documentation milestones and pilot releases |

Freeze fixture data, workflow inventory, browser version, viewport, locale, model configuration, prompts, and limits for comparative evaluations. Report individual failures and distribution across repeated runs; do not select only the best attempt. Keep blocked and inconclusive workflows in the overall task denominator.

Use an independent expected-outcome source for tests. The same LLM that proposes a workflow must not be the sole judge of whether that workflow succeeded.

## Definition of done

For every phase:

- Implemented behavior meets the stated scope and exit criteria.
- Relevant deterministic tests, linting, and type checks pass.
- Required live evaluations and human reviews are recorded, with limitations stated.
- Evidence and authentication artifacts follow the project's storage and sensitivity rules.
- Failure, cancellation, and recovery behavior is demonstrated where applicable.
- Operator instructions and dependency locks are updated.
- Remaining work is recorded explicitly; deferred capabilities are not reported as supported.

Record each milestone's commit, tested configuration, evaluation results, and outstanding issues in a short release note. The quantitative fixture targets are provisional engineering gates; set separate real-target acceptance thresholds after measuring its baseline.

## Dependencies and contingency

| Dependency or risk | Response |
| --- | --- |
| Target access or representative data is delayed | Continue fixture development; postpone claims about real-target readiness. |
| Browser alternative does not satisfy policy/evidence contracts | Retain Playwright and close the comparison with recorded results. |
| Discovery recall misses its gate | Inspect missed states, improve observations and bounded exploration, then repeat the same benchmark. |
| Workflow outcome cannot be established | Mark it inconclusive and add a trusted outcome check or owner clarification. |
| Authentication requires human participation | Pause and resume with role-specific session state. |
| Model costs exceed the pilot budget | Reduce repeated context and unnecessary calls, reuse verified paths, and reevaluate under fixed limits. |
| Requested scope grows to hosted multi-tenancy or arbitrary production writes | Treat it as a separate milestone with revised architecture, tests, and estimates. |

## First development slice

Start with phase 0 and the smallest useful part of phase 1: execute one configured workflow on the local fixture, persist its action history and screenshots, and confirm its final outcome. Demonstrate recovery from a crash after submission before connecting the LLM planner.
