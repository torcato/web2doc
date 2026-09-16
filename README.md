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

New projects are configured for bounded unguided exploration and allow the inferred `click-confirm` operation.
This lets discovery progress through confirmation dialogs, including dialogs that may change or delete data. Use a
disposable target environment and remove `click-confirm` from `allowed_write_operations` when confirmation must
remain operator-controlled.

Edit `demo/project.toml`, then capture authentication if needed:

```bash
uv run web2doc auth-login demo --role default
```

For sites protected by HTTP Basic Auth, provide the Basic Auth values through the process environment rather than
`project.toml` or committed files:

```bash
export WEB2DOC_BROWSER_HTTP_USERNAME="your-basic-auth-user"
read -r -s WEB2DOC_BROWSER_HTTP_PASSWORD
export WEB2DOC_BROWSER_HTTP_PASSWORD
uv run web2doc auth-login demo --role default
```

The browser applies Basic Auth automatically. For sites with a standard login form, application credentials can also
be supplied in the project `.env` (keep this file private):

```dotenv
WEB2DOC_BROWSER_LOGIN_USERNAME=your-application-user
WEB2DOC_BROWSER_LOGIN_PASSWORD=your-application-password
```

When both login settings are present, `auth-login` fills and submits the first username/password form automatically in
headless mode, matching the default mode used by discovery and verification. Pass `--headed` to both authentication
and later commands when a site requires a visible browser identity. Without login settings, complete login in the
visible browser and press Enter in the terminal to save the private Playwright authentication state.

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

Web2doc automatically loads recognized settings from `.env` in the current working directory and in the project
directory. Real environment variables take precedence, followed by the project file. Use separate models for frequent
exploration decisions and final prose composition:

```dotenv
WEB2DOC_DISCOVERY_MODEL=google-cloud:VERTEX_MODEL_ID
WEB2DOC_DOCUMENTATION_MODEL=google-cloud:VERTEX_MODEL_ID
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=europe-west4
```

The Google Cloud provider uses Application Default Credentials. Prefer user ADC, service-account impersonation, or
workload identity over a long-lived JSON key where possible. Credential files and `.env` are ignored from Git and must
never be copied into run artifacts.

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

Generate a structured documentation revision only after its exact workflow revision has a current passing verification:

```bash
uv run web2doc document-generate demo WORKFLOW_REVISION_ID
uv run web2doc document-bundle demo DOCUMENT_REVISION_ID
```

Add owner terminology or business rules as explicitly attributed sources:

```bash
uv run web2doc owner-source-add demo terminology.txt \
  --kind terminology \
  --label "Product vocabulary"
```

The deterministic composer is the default for reproducible builds. Select a configured Pydantic AI model when prose composition is desired:

```bash
uv run web2doc document-generate demo WORKFLOW_REVISION_ID --model openai:MODEL_NAME
```

Review applies to one exact document revision. Editing `document.json` from the review bundle and importing it creates a new revision whose parent approval does not carry forward:

```bash
uv run web2doc document-revise demo WORKFLOW_REVISION_ID VERIFICATION_ID edited-document.json
uv run web2doc document-review demo DOCUMENT_REVISION_ID \
  --decision approved \
  --reviewer "Documentation owner" \
  --notes "Claims checked against evidence"
```

Generate coverage reports and export the currently verified, latest, approved guides through a strict MkDocs build:

```bash
uv run web2doc documentation-coverage demo
uv run web2doc docs-export demo ./published-documentation
```

Exports never overwrite an existing destination. A newer failed or inconclusive verification, a newer unreviewed edit, missing evidence, or an artifact hash mismatch makes the affected guide ineligible for export.

## End-to-end documentation generation

For the normal user-documentation path, use the bundled helper. It runs unguided discovery, turns the results into
concise user tasks, verifies every drafted task, generates documentation for passing tasks, creates review bundles,
and writes a coverage report:

```bash
# Install jq with your platform's package manager first.
chmod +x scripts/generate-docs.sh
./scripts/generate-docs.sh demo --max-actions 100 --max-states 50
```

The target application must already be running and `demo/project.toml` must contain the correct origins and policy.
Use `--headed` to watch the browser, `--role ROLE` for another authenticated role, and
`--trusted-fixture-api` only when the target intentionally exposes the documented fixture endpoints.
Add `--model PROVIDER:MODEL` to use a Pydantic AI planner; omit it for deterministic discovery.

The helper does not approve documents automatically. After inspecting each printed review bundle, copy the ready-to-run
review command printed by the helper and export the approved set:

```bash
uv run web2doc document-review demo DOCUMENT_REVISION_ID \
  --decision approved \
  --reviewer "Documentation owner" \
  --notes "Claims checked against evidence"
uv run web2doc docs-export demo ./published-documentation
```

The helper requires `jq` and leaves runtime evidence, workflow revisions, and generated bundles under
`demo/.web2doc/`. A failed or inconclusive task is reported and skipped so passing tasks can still produce drafts.

For a fully automated build, including bulk approval of every passing generated document, use the Python CLI command:

```bash
uv run web2doc docs-generate demo ./published-documentation \
  --reviewer "Documentation owner" \
  --notes "Automated bulk approval after verification"
```

This command keeps all run, workflow, verification, and document revision IDs internal. It bulk-approves every current
document whose latest verification passed, including documents generated by an earlier run, and refuses to overwrite an
existing output directory. Use a new output path for each regeneration, or remove/archive the previous export after
confirming it is no longer needed.
