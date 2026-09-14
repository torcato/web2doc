# web2doc

`web2doc` records browser procedures and their evidence as the foundation for generating user documentation. Phase 1 is deterministic: the operator supplies a JSON procedure, and the same controlled execution path will later be used by an LLM planner.

## Development setup

```bash
uv sync --group test --group lint
uv run playwright install chromium
uv run pytest
uv run ruff check .
uv run mypy src
```

## Quick start

Create a project:

```bash
uv run web2doc init demo --base-url http://127.0.0.1:8000 --path ./demo
```

Edit `demo/project.toml`, then capture authentication if needed:

```bash
uv run web2doc auth-login demo --role default
```

Execute an explicit procedure:

```bash
uv run web2doc run demo examples/procedure.json --role default
```

Inspect or recover runs:

```bash
uv run web2doc status demo RUN_ID
uv run web2doc recover demo
uv run web2doc cancel demo RUN_ID
```

The runtime data lives below `PROJECT/.web2doc/`. Authentication state and traces are private artifacts and must not be published.

