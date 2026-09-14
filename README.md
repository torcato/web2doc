# web2doc

`web2doc` maps website states, constructs versioned workflows, and verifies browser procedures with evidence as the foundation for generating user documentation. It supports deterministic supplied workflows and bounded feature discovery using either local heuristic ranking or a structured Pydantic AI planner.

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

Run bounded unguided discovery without a model provider:

```bash
uv run web2doc discover demo --role default --max-actions 20 --max-states 15
```

Use a Pydantic AI model after configuring its provider credentials:

```bash
uv run web2doc discover demo --role default --model openai:MODEL_NAME
```

Map a known procedure into the same state graph without calling a model:

```bash
uv run web2doc discover demo \
  --role default \
  --mode supplied \
  --procedure examples/procedure.json
```

Inspect or recover runs:

```bash
uv run web2doc status demo RUN_ID
uv run web2doc recover demo
uv run web2doc cancel demo RUN_ID
uv run web2doc discovery-report demo RUN_ID
```

Draft workflow revisions from explored transitions, or import a reviewed workflow definition:

```bash
uv run web2doc workflow-draft demo DISCOVERY_RUN_ID --role default
uv run web2doc workflow-add demo examples/workflow.json
```

Replay an exact revision. The optional trusted fixture adapter prepares/reset synthetic data and verifies backend state through fixed same-origin endpoints:

```bash
uv run web2doc verify demo REVISION_ID --trusted-fixture-api
uv run web2doc verification-report demo VERIFICATION_ID
```

The runtime data lives below `PROJECT/.web2doc/`. Authentication state and traces are private artifacts and must not be published.

Discovery is not universally read-only: a button can have effects even when its label looks observational. Use disposable test data, explicit write-operation allowlists, and infrastructure-level network isolation.

Verification reports `passed`, `failed`, or `inconclusive`. A click completing is never treated as proof of its business outcome, and uncertain writes are not repeated until trusted state reconciliation can establish whether the prior effect occurred.
