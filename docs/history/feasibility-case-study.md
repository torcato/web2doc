# Case study: generating website user documentation with Python and an LLM

Date: September 14, 2026  
Status: architectural assessment and proposed proof of concept

September 18, 2026 update: the current direction is [autonomous capture with offline distillation](../architecture.md), with a separate [development plan](../development-plan.md). This case study retains the original research and estimates. Its model-driven exploration loop is no longer the default target architecture: deterministic exploration collects evidence, bounded AI assistance handles ambiguous screens, and independent processing turns saved evidence into user documentation. Human recordings and supplied workflows are optional inputs. Observed feature descriptions and demonstrated procedures have distinct evidence requirements.

Implementation follow-up: [Architecture and development plan](original-architecture.md), including library decisions, development phases, and testing criteria.

## Executive summary

A Python application can explore a website and generate useful user documentation, provided it records evidence, verifies workflows, and makes coverage gaps visible. The difficult part is discovering and understanding enough of the application's behavior to produce accurate instructions. Generating prose is a comparatively straightforward final step.

The recommended foundation is **Playwright for Python, an LLM exploration loop, and a persistent graph of interface states and workflows**. Stagehand is a strong alternative browser layer worth evaluating against the same sample workflows. Playwright MCP is useful for interoperability with agent clients. Crawljax directly addresses state exploration, but introduces a Java subsystem and still needs a layer that interprets observations as user-facing features.

The proposed product promise is:

> Generate and maintain evidence-backed user guides, while making coverage gaps visible.

Complete, unattended documentation of arbitrary websites is not a dependable initial promise.

## Scope and evidence

This study considers an application that:

1. Receives a starting URL, access credentials or an authenticated session, and exploration constraints.
2. Maps visible features and relevant workflows through browser interaction.
3. Records supporting evidence and verifies discovered procedures.
4. Generates documentation that a product owner can review.
5. Eventually reruns workflows to maintain documentation as the website changes.

The tool assessment is based on official documentation and repositories consulted on September 14, 2026. No target website was supplied, and no comparative runtime benchmark was performed. Feasibility judgments, architecture choices, and effort estimates below are engineering assessments rather than measured results.

The most favorable initial setting is an application with a resettable staging environment, representative test data, and accounts for the roles being documented. Production-only access or an unfamiliar third-party website significantly reduces what can be safely explored and verified.

## Tool comparison

These tools occupy different layers. Browser control, autonomous task execution, systematic crawling, and documentation generation are separate responsibilities.

| Tool | Primary capability | Python integration | Fit for this application |
| --- | --- | --- | --- |
| Playwright | Browser control, locators, screenshots, authentication state, and traces | Official Python API | Recommended default foundation; exploration strategy and feature interpretation remain application responsibilities. |
| Playwright MCP | Browser tools exposed through MCP, primarily using accessibility snapshots | Python MCP client connected to a Node.js server | Convenient agent integration; does not supply planning, persistent feature memory, or coverage measurement. |
| Stagehand | Natural-language actions, action discovery, structured extraction, and deterministic browser APIs | Current Python SDK; local or hosted browsers | Strong candidate for reducing browser-agent implementation work. |
| Browser Use | An LLM browser agent that executes tasks | Python library; local or hosted execution | Useful for quickly prototyping workflow exploration; systematic discovery needs additional control. |
| Crawljax | Event-driven exploration and a graph of DOM states and transitions | Java process or service called from Python | Closest to the mapping requirement; adds integration work and needs semantic interpretation. |
| Crawlee | Crawling infrastructure, including a Playwright-based crawler | Python library | Useful for URL discovery and crawl management; application workflow exploration remains custom work. |
| Crawl4AI | Content extraction, Markdown conversion, recursive crawling, and scripted interactions | Python library | Useful for collecting existing content; insufficient by itself for feature discovery. |

Capability sources: [Playwright Python](https://playwright.dev/python/docs/intro), [Playwright MCP](https://github.com/microsoft/playwright-mcp), [Stagehand](https://docs.stagehand.dev/v4/first-steps/introduction), [Browser Use](https://github.com/browser-use/browser-use), [Crawljax](https://github.com/crawljax/crawljax), [Crawlee](https://crawlee.dev/python/docs/quick-start), and [Crawl4AI](https://docs.crawl4ai.com/core/page-interaction/).

### Playwright versus Playwright MCP

Playwright is the browser automation library. MCP is a protocol through which an agent can call tools. A Python application can connect to Playwright MCP using the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), or expose selected Playwright functions directly to its LLM.

Direct integration is the recommended default when action restrictions, evidence capture, and replay are central requirements. It allows the application to define a small, controlled tool interface. MCP becomes attractive when interoperability with other agent clients is a product requirement.

Neither approach supplies a complete exploration strategy. The application must decide what to visit, when to revisit a state, which actions are permitted, and when exploration should stop. Playwright MCP uses accessibility snapshots for structural interaction and also provides screenshots and other browser operations. [Playwright MCP documentation](https://github.com/microsoft/playwright-mcp).

### Stagehand

Stagehand's current v4 supports Python and combines `observe`, `act`, and `extract` with deterministic browser APIs. It drives Chromium through the Chrome DevTools Protocol without a Playwright dependency, despite offering familiar Playwright-style methods. [Stagehand v4 introduction](https://docs.stagehand.dev/v4/first-steps/introduction).

Local browser execution is supported. The former standalone Python repository is archived, and current development is in the main monorepo. Older tutorials should therefore be checked carefully for API compatibility. [Current Python example](https://pypi.org/project/stagehand/), [archived Python repository](https://github.com/browserbase/stagehand-python), [current monorepo](https://github.com/browserbase/stagehand).

Stagehand deserves a prototype because its primitives align with discovering actionable controls and extracting structured observations. Pin versions and keep the integration behind a narrow interface. Automatic recovery after a selector changes should still trigger outcome verification: a recovered action does not establish that its meaning is unchanged.

### Browser Use

Browser Use offers a Python agent library with local or hosted browser options, custom tools, and structured output. It can reduce the work needed to demonstrate an agent completing a user task. [Browser Use repository](https://github.com/browser-use/browser-use).

For this product, task completion and systematic discovery must be evaluated separately. An agent that successfully creates one project may still miss permissions, bulk operations, validation states, and alternative workflows. Use bounded tasks and persist observations outside the agent's conversation history.

### Crawljax

Crawljax explicitly produces a state-flow graph of dynamic DOM states and event transitions. That structure is directly relevant to feature mapping. Its plugin architecture provides extension points. [Crawljax repository](https://github.com/crawljax/crawljax).

However, a DOM state is not automatically a meaningful product feature. A separate layer must identify user goals, choose representative paths, explain prerequisites, and validate outcomes. The recommended approach is to benchmark Crawljax as an optional discovery engine before committing to the operational cost of a Java subsystem.

### Crawlee and Crawl4AI

Crawlee is useful when URL discovery, crawl queues, and browser-based page processing become substantial parts of the workload. [Crawlee Python quick start](https://crawlee.dev/python/docs/quick-start).

Crawl4AI is useful for gathering existing help content and converting pages into model-friendly text. It supports recursive crawling and scripted interactions, but those capabilities do not automatically provide semantic workflow discovery. [Deep crawling](https://docs.crawl4ai.com/core/deep-crawling/), [page interaction](https://docs.crawl4ai.com/core/page-interaction/).

Neither is necessary for a narrowly scoped first prototype.

## Recommended architecture

### Map states and workflows, not just URLs

One URL can represent many meaningful interface states. For example, `/projects` may display a project list, a creation dialog, validation errors, and a permissions menu without changing its URL. Conversely, thousands of project URLs may represent essentially the same capability.

The application should maintain a graph in which nodes describe relevant interface states and edges describe actions and their observed outcomes. User workflows are meaningful paths through that graph.

```text
Scope, roles, and test data
          |
          v
Initial inventory -> State exploration <-> Persistent evidence and state graph
                              |
                              v
                       Candidate workflows
                              |
                              v
                       Replay and verification
                              |
                              v
                       Documentation drafts
                              |
                              v
                         Human review
```

Missing evidence found during workflow planning or review should return to the exploration queue.

### 1. Configure the exploration environment

Inputs should include:

- Starting URLs and allowed domains.
- Target roles, accounts, and relevant application configurations.
- Permitted operations and operations that require a human decision.
- Representative data and a way to reset the environment.
- Exploration budgets, including time, action count, and model usage.
- Documentation audience, language, and desired output structure.

Treat authentication artifacts as secrets. Playwright can reuse saved authentication state, but such state can contain credentials sufficient to impersonate an account. [Playwright authentication guidance](https://playwright.dev/python/docs/auth).

### 2. Build an initial inventory

Discover navigation, links, tabs, forms, menus, dialogs, and visible instructions. Use DOM and accessibility information for structure, supplemented by screenshots when visual interpretation matters.

Existing help pages, route inventories, and owner-provided workflow lists can seed exploration. Record their provenance separately from behavior directly observed in the browser.

### 3. Explore and persist the state graph

State identity should account for the route, relevant interface structure, user role, and meaningful data conditions. Normalize volatile values such as timestamps and record IDs so they do not create endless duplicate states. Preserve differences that affect documentation, such as empty lists, disabled actions, and validation errors.

For each transition, record the starting state, attempted action, inputs, resulting state, evidence references, and execution status. Maintain an explicit queue of unexplored actions and reasons for skipping or blocking them.

The LLM can prioritize unfamiliar controls and interpret page structure. The application should enforce action constraints and exploration budgets independently of the model.

### 4. Identify candidate workflows

Group observations into user goals, such as creating a project, inviting a teammate, or exporting a report. Each workflow should include prerequisites, inputs, steps, expected or observed outcomes, relevant roles, and unresolved questions.

Keep observed facts, proposed interpretations, and owner-supplied business rules distinct. A model's confidence is not evidence that an operation works.

### 5. Replay and verify

Replay candidate workflows from a known starting condition and verify explicit outcomes. A successful click or a temporary success notification may not establish that the intended operation completed.

Store replayable instructions separately from temporary browser element references. Capture screenshots and action evidence during verified runs. Playwright traces can support failure investigation. [Playwright trace viewer](https://playwright.dev/python/docs/trace-viewer-intro).

Resetting browser storage does not reset backend data. Workflows that create or modify records require fixture restoration or a defined cleanup process to remain repeatable.

### 6. Generate and review documentation

Generate task-oriented guides from verified workflow records. Each guide should contain prerequisites, steps, expected results, relevant screenshots, and troubleshooting cases that were actually observed or supplied by an authoritative source.

Internally connect documentation claims to evidence so reviewers can inspect their basis. Preserve unresolved questions instead of filling them with plausible explanations. Human review should assess both factual accuracy and whether the instructions make sense to the intended audience.

### Example workflow record

```yaml
goal: Create a project
role: Workspace administrator
prerequisites:
  - Existing workspace
steps:
  - Open Projects
  - Select New project
  - Enter a project name
  - Select Create
observed_outcome: New project appears in the list
evidence:
  - Action log
  - Before and after screenshots
status: Replayed successfully
unknowns:
  - Whether other roles can create projects
```

## Blind spots and mitigations

| Blind spot | Consequence | Practical response |
| --- | --- | --- |
| Hidden features and permissions | One account cannot reveal every role, subscription tier, feature flag, or tenant configuration. | Supply a role/configuration matrix and report coverage separately for each. |
| Business meaning | Labels do not reveal retention rules, billing effects, or downstream consequences. | Supplement browser evidence with product knowledge, existing documentation, or owner answers. |
| Data-dependent behavior | Empty accounts hide bulk operations, pagination, reports, and lifecycle states. | Seed representative data and explore meaningful scenarios. |
| Side effects | Exploration can send invitations, publish content, delete records, or trigger integrations. | Use disposable environments and enforce restrictions in code; prompts alone are insufficient. |
| Authentication | SSO, MFA, expired sessions, and bot challenges interrupt unattended runs. | Support human-assisted login and renewal; isolate authentication by role. |
| Complex interfaces | Canvas editors, drag-and-drop, virtualized lists, frames, and poorly labelled controls complicate observation. | Combine structural inspection and vision; add site-specific adapters where necessary. |
| Exploration growth | Filters, records, and input combinations can produce an impractically large search space. | Bound depth, actions, and time; prioritize new capabilities over repeated content. |
| Misleading outcomes | An action can appear successful while the intended operation fails or remains pending. | Verify explicit outcomes and distinguish observed behavior from intended behavior. |
| Sensitive or adversarial content | Page text and screenshots may expose private data or contain instructions aimed at the agent. | Use synthetic data, redact before model transmission, and treat page content as untrusted input. |
| Documentation drift | Labels, screenshots, workflows, and permissions change after generation. | Associate documents with verified workflows and rerun affected checks after releases. |

The fundamental limitation is **unknown completeness**. Browser access alone generally cannot prove that every feature has been discovered. Report visited states, verified workflows, skipped actions, blocked areas, and unresolved questions.

“Verified 17 of 20 owner-specified workflows” is meaningful. “Discovered 95% of the website” is not meaningful without a known feature inventory and a defined denominator.

## Feasibility assessment

| Intended result | Assessment |
| --- | --- |
| Document navigation and visible controls | High feasibility for conventional websites. |
| Produce illustrated guides for specified workflows | High feasibility with suitable accounts and test data. |
| Discover common workflows with limited guidance | Moderate feasibility; strongly dependent on the application. |
| Explain permissions, business rules, and exceptional cases from browsing alone | Low feasibility. |
| Completely document arbitrary websites without review | Not a dependable product promise. |
| Maintain documentation for previously verified workflows | Promising and easier to evaluate than open-ended discovery. |

These ratings are architectural judgments. They should be replaced or refined with measurements from representative target applications.

## Suggested initial stack

| Component | Initial choice | Rationale |
| --- | --- | --- |
| Browser automation | Playwright Python | Direct control over actions, evidence capture, and verification. |
| Alternative browser layer to evaluate | Stagehand | Natural-language primitives may reduce implementation effort. |
| LLM integration | Pydantic AI or a small custom loop | Typed tool inputs and structured workflow records. |
| Persistence | SQLite plus artifact files | Simple storage for states, transitions, workflows, screenshots, and traces. |
| Documentation output | Markdown and MkDocs | Reviewable text with a straightforward documentation-site output. |
| Optional later orchestration | LangGraph | Consider when checkpointing and resumable execution become cumbersome. |
| Optional later crawling | Crawlee | Consider when broad URL discovery becomes substantial. |

Relevant documentation: [Pydantic AI](https://pydantic.dev/docs/ai/overview/), [MkDocs](https://www.mkdocs.org/), and [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview).

Avoid integrating every browser framework at once. Keep the application's observation and workflow schema independent of the browser layer, so alternatives can be evaluated without redesigning documentation generation.

Choose the LLM through task-specific evaluation of action selection, structured extraction, visual interpretation, latency, and cost. Do not assume one model must perform every stage. Browser hosting is also a separate choice: a local browser does not imply that model inference or page data processing stays local.

## Proposed proof of concept

### Scope

Use one application, two roles, and approximately ten representative workflows. Include a modal dialog, a validation error, a data-dependent feature, and an operation that changes state. Obtain an owner-provided inventory for evaluation while keeping it separate from any deliberately unguided discovery run.

Compare direct Playwright integration and Stagehand using the same model where supported, equivalent initial data, and comparable exploration budgets. Browser Use or Crawljax can be added as a bounded comparison if the initial results identify a specific gap they might address.

### Deliverables

- An inventory of discovered states and candidate features.
- A graph of actions and observed transitions.
- Workflow records with role, prerequisites, evidence, and verification status.
- Markdown guides with screenshots.
- A coverage and uncertainty report.
- A record of model usage, runtime, failures, and reviewer corrections.

### Evaluation criteria

| Metric | What to measure |
| --- | --- |
| Discovery coverage | Owner-listed features or workflows discovered, broken down by role. |
| Workflow replay | Procedures that complete from a known starting condition and satisfy outcome checks. |
| Evidence quality | Whether documented steps and behavioral claims have relevant supporting evidence. |
| Unsupported claims | Statements that go beyond observations or authoritative supplemental sources. |
| Editorial usefulness | Reviewer corrections and whether a new user can follow the instructions. |
| Operational cost | Model usage, browser runtime, retries, and cost per verified workflow. |
| Update behavior | Whether a deliberate interface change identifies affected workflows and documents. |

Set acceptance thresholds before comparing implementations. Report blocked workflows separately from successful and failed ones; do not silently remove difficult cases from the denominator.

## Effort and cost considerations

For an experienced engineer, a narrow prototype is estimated at **2–4 weeks**. A useful pilot with resumable exploration, evidence review, multiple roles, and incremental updates is more plausibly **2–3 months**, depending on the target application. Broad support for unrelated websites would require ongoing engineering. These are planning estimates, not benchmark results or delivery commitments.

Runtime cost depends primarily on the number of meaningful states explored, model calls and context size, screenshot processing, retries, and browser hosting. Human review is a separate and potentially substantial cost. Measure cost per verified workflow rather than cost per visited page.

Control costs by deduplicating equivalent states, reusing verified procedures, limiting retries, keeping evidence outside conversational context, and sending only relevant observations to the model. Avoid quoting a per-site price before measuring a representative run.

## Recommendation

Proceed with a bounded proof of concept built around Playwright Python and persistent evidence-backed workflow records. Evaluate Stagehand against the same cases before settling the browser abstraction. Use MCP when client interoperability is required, and consider Crawljax if measured discovery gaps justify a dedicated state-crawling engine.

The most valuable custom capability is the connection between observations, verified workflows, and documentation claims. Establish that connection early, make unknowns explicit, and prioritize repeatable documentation maintenance alongside initial discovery.
