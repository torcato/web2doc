# Phase 4 implementation record

Date: September 15, 2026  
Status: core implementation complete; human usability and real-target review gates pending

## Outcome

Phase 4 produces illustrated Markdown guides from current, passed workflow verifications. Each procedural claim is structured, has declared provenance, and is linked to an applicable captured observation and screenshot. Generated drafts cannot be exported until a reviewer approves the exact document revision.

The implementation provides:

- deterministic and Pydantic AI structured composers;
- immutable document revisions and parent relationships;
- verified and owner-provided claim provenance;
- application-owned Jinja2 Markdown rendering;
- local review bundles containing structured content, rendered prose, evidence pages, and verified screenshots;
- workflow and feature coverage reports in JSON and Markdown;
- exact revision approval and rejection records;
- strict MkDocs source and static-site export;
- manual revision import without inherited approval.

## Libraries

| Library | Responsibility |
| --- | --- |
| Pydantic | Closed document, narrative, claim, evidence, provenance, and review schemas |
| Pydantic AI Slim | Optional structured prose composition with bounded output |
| Jinja2 | Fixed application-owned Markdown templates and strict undefined values |
| MkDocs | Strict internal-link validation and static documentation generation |
| SQLAlchemy and Alembic | Immutable revision, evidence, review, owner-source, and export records |

Jinja2 and MkDocs are runtime dependencies because guide rendering and export are product capabilities. Routine tests use a deterministic composer and Pydantic AI's test model; they make no paid provider calls.

## Data and trust model

Migration `0004_phase4` adds:

- `owner_sources` for attributed terminology and business rules;
- `document_revisions` for immutable generated or manual content;
- `document_evidence` for normalized claim-to-verification, observation, and screenshot links;
- `review_decisions` for decisions against exact document revisions;
- `exports` for output manifests.

Documentation generation requires the latest verification for the exact workflow revision to be `passed`. Evidence is selected by application code, not by the model. Step claims may only use the corresponding step observation; goal, summary, and outcome claims use final-outcome evidence. A missing, stale, unrelated, wrong-project, wrong-role, or wrong-step reference is rejected.

Owner notes are stored separately and marked `owner`. They cannot masquerade as observed facts. Procedural claims must remain `verified`. Human edits may change wording while retaining applicable evidence, but create a new document revision and require a new review.

## Composition and rendering

The model receives a bounded workflow narrative context without artifact paths or evidence identifiers. It cannot choose templates, links, files, or output destinations. The service rejects changed step sequences, changed prerequisite counts, and troubleshooting claims for which no failure evidence was supplied.

Markdown is rendered through `guide.md.j2`. Text is escaped for Markdown and HTML, while evidence links and image paths are generated exclusively from validated internal identifiers. Review bundles and exports are assembled in temporary directories and atomically moved into place. Existing destinations are never overwritten.

## Commands

Add owner-provided terminology or business rules:

```bash
uv run web2doc owner-source-add PROJECT source.txt \
  --kind terminology \
  --label "Product vocabulary"
```

Generate and inspect a revision:

```bash
uv run web2doc document-generate PROJECT WORKFLOW_REVISION_ID
uv run web2doc document-bundle PROJECT DOCUMENT_REVISION_ID
```

Use an LLM composer when provider credentials and a model are explicitly configured:

```bash
uv run web2doc document-generate PROJECT WORKFLOW_REVISION_ID --model PROVIDER:MODEL
```

Import edited structured content and review the new exact revision:

```bash
uv run web2doc document-revise PROJECT WORKFLOW_REVISION_ID VERIFICATION_ID document.json
uv run web2doc document-review PROJECT DOCUMENT_REVISION_ID \
  --decision approved \
  --reviewer "Documentation owner" \
  --notes "Factual support reviewed"
```

Create coverage reports and a strict static export:

```bash
uv run web2doc documentation-coverage PROJECT
uv run web2doc docs-export PROJECT NEW_OUTPUT_DIRECTORY
```

The export contains MkDocs sources, referenced screenshot assets, evidence pages, configuration, and the generated `site/` directory.

## Export eligibility

A guide is exportable only when all of these refer to the current chain:

1. the latest workflow revision;
2. its latest passed verification;
3. the latest document revision generated from that verification;
4. the latest review decision approving that document revision;
5. every referenced artifact exists and passes its SHA-256 integrity check.

A new failed or inconclusive verification makes earlier documentation stale. A new manual revision makes its approved parent stale. Rejection after approval takes effect immediately.

## Automated acceptance coverage

The Phase 4 suite covers:

- Phase 3 to Phase 4 migration with workflow preservation;
- exact passed-verification generation and stale-verification rejection;
- wrong project, role, step, owner source, and unrelated evidence;
- deterministic and Pydantic AI structured composition;
- invented sequence and unsupported troubleshooting rejection;
- Markdown, HTML, and malicious-link escaping;
- review bundle structure and evidence links;
- screenshot artifact tampering;
- approval, later rejection, and approval invalidation after manual edits;
- unverified features, unresolved questions, and export eligibility reporting;
- strict MkDocs build and non-overwriting export;
- real Chromium rendering at desktop and narrow viewport widths;
- CLI initialization, owner-source, coverage, and command discovery.

The final local verification result is:

```text
pytest on Python 3.12: 69 passed
pytest on Python 3.13: 69 passed
real-Chromium tests: 11 passed
ten-workflow verification benchmark: 30/30 passed
ruff: all checks passed
mypy --strict: no issues in 44 source files
strict MkDocs build: passed
desktop and 390 px rendering checks: passed
git diff --check: clean
```

## Remaining gates and blind spots

The local implementation is complete, but the following external acceptance work remains:

- A person unfamiliar with the fixture must attempt all ten guides and complete at least 8/10 without author assistance.
- A reviewer must assess a real-target output set for unsupported critical behavioral claims; the target is zero.
- Live-model quality gates remaining from Phases 2 and 3 are still pending.

Technical limits remain:

- Evidence applicability is structural and cannot itself prove that prose faithfully describes the screenshot. Review of factual support is mandatory.
- Owner sources are plain text records. Source signatures, external document synchronization, and granular quotation lineage are not implemented.
- Troubleshooting is deliberately omitted unless an owner supplies it; verified failure-example documentation needs a future failure-evidence schema.
- Screenshots can contain private information. Only explicitly reviewed guides should be exported, and production deployments need retention and redaction policy.
- Markdown rendering supports the fixed bundled template. Themes, localization, PDF export, and richer media are outside this phase.
- Generated prose quality depends on the chosen model and prompt. The deterministic composer is safe and reproducible but intentionally plain.
