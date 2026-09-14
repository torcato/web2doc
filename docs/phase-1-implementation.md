# Phase 1 implementation record

Date: September 14, 2026  
Status: implemented and verified against the local fixture application

## Outcome

Phase 1 provides a deterministic, LLM-free execution foundation. An operator can initialize a project, capture a role-specific browser session, execute an explicit JSON procedure, inspect its status, request cancellation, and recover interrupted work. Every browser action travels through the same policy, journal, and evidence path that a later LLM planner will use.

The implementation is deliberately a workflow recorder, not yet a website explorer or documentation generator. Automated feature discovery begins in phase 2.

## Implemented architecture

```text
Typer CLI
   |
   v
Pydantic project + procedure models
   |
   v
Procedure runner ----> action policy
   |                         |
   |                         +-- origin and write-operation allowlists
   v
Playwright adapter ----> Chromium context per role
   |
   +-- semantic locators, screenshots, ARIA snapshots, traces
   |
   v
Repository + artifact store
   |
   +-- SQLite / SQLAlchemy / Alembic action journal
   +-- atomic files with SHA-256 checksums
```

The main component boundaries are:

- `domain`: strict Pydantic models for projects, actions, observations, results, and statuses.
- `policy`: pre-execution action checks plus browser request/navigation scope checks.
- `browser`: an async Playwright adapter hidden behind a browser protocol.
- `orchestration`: the procedure state machine, cancellation checks, evidence capture, and cleanup.
- `storage`: SQLAlchemy repositories, Alembic migrations, locking, recovery, and atomic artifacts.
- `cli`: the operator interface; it does not contain browser or persistence business logic.

## Library baseline

The committed `uv.lock` is the authoritative dependency resolution. The Phase 1 runtime uses:

| Library | Responsibility |
| --- | --- |
| Playwright | Chromium automation, semantic locators, authentication state, screenshots, and traces |
| Pydantic | Validated project, policy, procedure, action, and result records |
| Pydantic Settings | Environment-controlled browser runtime settings |
| SQLAlchemy | SQLite persistence and repository transactions |
| Alembic | Repeatable database schema creation and future upgrades |
| Typer | Project, authentication, execution, status, cancellation, and recovery commands |

FastAPI, Uvicorn, and HTTPX are test dependencies for the local resettable website. Pytest, pytest-asyncio, Hypothesis, Ruff, and mypy provide testing and static verification. No LLM, MCP server, Stagehand, task queue, or vector database is required in this phase.

The package declares Python 3.12 or newer. The full suite was verified with CPython 3.12.10 and the primary uv-managed CPython 3.13 environment.

## Commands

Install the environment and Chromium:

```bash
uv sync --group test --group lint
uv run playwright install chromium
```

Create a project and edit its generated policy:

```bash
uv run web2doc init demo \
  --base-url http://127.0.0.1:8000 \
  --path ./demo
```

Capture a login session, run a supplied procedure, and inspect the result:

```bash
uv run web2doc auth-login demo --role default
uv run web2doc run demo examples/procedure.json --role default
uv run web2doc status demo RUN_ID
```

Operational controls are:

```bash
uv run web2doc cancel demo RUN_ID
uv run web2doc recover demo
```

`cancel` is cooperative and takes effect at safe runner checkpoints. `recover` refuses to disturb a live worker; after a dead worker is detected it pauses incomplete runs and marks in-flight attempts uncertain.

## Persistent data and evidence

Each initialized project owns its runtime directory:

```text
PROJECT/.web2doc/
├── state.sqlite3
├── artifacts/RUN_ID/
│   ├── observations/*.yaml
│   └── screenshots/*.png
└── private/
    ├── auth/ROLE.json
    └── traces/RUN_ID.zip
```

The database records projects, roles, runs, observations, artifacts, action attempts, and the single-worker project lock. Artifact writes use a temporary file followed by an atomic replace; the database stores the relative path, media type, sensitivity, byte size, and SHA-256 digest. Authentication state and traces are private and must not be copied into generated documentation.

## Safety and interruption semantics

- Action intent is persisted before browser interaction.
- Navigation is limited to configured origins. Cross-origin resource requests, redirects, and new pages are intercepted and reported.
- Writes require both `effect: "write"` and an `operation_id` present in the project's `allowed_write_operations`.
- Missing and ambiguous semantic targets fail closed. Delayed targets are awaited only up to the action timeout.
- A failed observation after a write begins is recorded as `uncertain`, and the runner pauses instead of automatically repeating it.
- One active worker may hold a project lock. Recovery checks the recorded process before clearing a stale lock.
- Browser tracing and context cleanup run even when an action fails or is cancelled.

The action policy is an application-level safety boundary, not a replacement for infrastructure isolation. Production execution should still use a restricted test account, non-production data, network controls, and an isolated browser/container.

## Verification result

The final Phase 1 verification completed successfully:

```text
pytest on Python 3.12: 30 passed
pytest on Python 3.13: 30 passed
ruff: all checks passed
mypy --strict: no issues in 21 source files
git diff --check: clean
```

Coverage includes configuration and URL-policy validation, atomic/checksummed artifacts, foreign keys, repeatable migrations, project locks, live-worker recovery refusal, stale-worker recovery, cancellation, denied actions with zero browser effects, uncertain writes, real browser evidence, delayed/missing/ambiguous targets, new tabs, redirects, and authentication isolation between roles. A fresh CLI project was initialized and recovered twice to prove migration replay is idempotent.

## Known gaps before phase 2

- No autonomous state mapping, feature inventory, workflow inference, or documentation generation exists yet.
- The fixture application exercises the Phase 1 foundation but does not yet implement the ten-workflow benchmark planned in phase 0.
- No target customer website has been validated; authentication systems, CAPTCHAs, unusual iframes, downloads, browser extensions, and anti-bot controls remain integration risks.
- Recovery does not automatically determine whether an uncertain write succeeded. Phase 3 adds trusted outcome predicates and safe reconciliation.
- The current process lock is intended for one local worker, not distributed execution.
- Network allowlisting operates at URL/origin level inside Playwright. Deployment-level egress controls are still required for defense in depth.
- Browser traces can contain sensitive data and currently depend on filesystem access controls and publishing discipline.

## Phase 2 entry criteria

Phase 2 should extend this executor rather than bypass it. The next implementation should add canonical state records, discovered transitions, a bounded exploration queue, stop budgets, loop detection, and a structured model-service interface with deterministic test responses. LLM-proposed actions must remain proposals until the Phase 1 policy and journal accept them.
