from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from web2doc.browser.playwright import PlaywrightBrowser
from web2doc.config import (
    RUNTIME_DIR,
    initialize_project,
    load_document_content,
    load_procedure,
    load_project,
    load_workflow,
)
from web2doc.discovery.planner import HeuristicPlanner, PydanticAIPlanner
from web2doc.discovery.runner import ExplorationRunner
from web2doc.documentation.composer import DeterministicComposer, PydanticAIDocumentComposer
from web2doc.documentation.models import OwnerSourceDraft, OwnerSourceKind, ReviewDecision
from web2doc.documentation.publish import DocumentationPublisher
from web2doc.documentation.service import DocumentationService
from web2doc.domain.models import DiscoveryMode, ProjectConfig
from web2doc.orchestration.runner import ProcedureRunner
from web2doc.policy.actions import ActionPolicy
from web2doc.settings import load_runtime_settings
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.database import upgrade_database
from web2doc.storage.repository import ProjectBusyError, Repository
from web2doc.verification.builder import draft_workflows
from web2doc.verification.environment import HttpJsonEnvironmentAdapter
from web2doc.verification.runner import VerificationRunner

app = typer.Typer(no_args_is_help=True, help="Capture evidence-backed website procedures.")


def _open_project(
    project_dir: Path,
) -> tuple[ProjectConfig, Repository, str, dict[str, str]]:
    root = project_dir.resolve()
    config = load_project(root)
    database = root / RUNTIME_DIR / "state.sqlite3"
    upgrade_database(database)
    repository = Repository(database)
    project_id, roles = repository.register_project(root, config)
    return config, repository, project_id, roles


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Project name")],
    base_url: Annotated[str, typer.Option("--base-url", help="Initial website URL")],
    path: Annotated[Path, typer.Option("--path", help="Directory to create")] = Path("."),
) -> None:
    project_file = initialize_project(path, name, base_url)
    config, repository, _project_id, _roles = _open_project(path)
    repository.close()
    typer.echo(f"Created {config.name}: {project_file}")


@app.command("run")
def run_procedure(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    procedure_path: Annotated[Path, typer.Argument(help="JSON procedure")],
    role: Annotated[str, typer.Option("--role")] = "default",
    headed: Annotated[bool, typer.Option("--headed")] = False,
) -> None:
    config, repository, project_id, roles = _open_project(project_dir)
    try:
        role_config = config.role(role)
        role_id = roles[role]
        procedure = load_procedure(procedure_path)
        browser = PlaywrightBrowser(
            project_root=project_dir,
            config=config,
            role=role_config,
            settings=load_runtime_settings(project_dir),
        )
        runner = ProcedureRunner(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            browser=browser,
            policy=ActionPolicy(config),
            project_id=project_id,
            role_id=role_id,
        )
        run_id = asyncio.run(runner.run(procedure, headed=headed))
        typer.echo(json.dumps(repository.run_summary(run_id), indent=2))
    finally:
        repository.close()


@app.command()
def discover(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    role: Annotated[str, typer.Option("--role")] = "default",
    mode: Annotated[DiscoveryMode, typer.Option("--mode")] = DiscoveryMode.UNGUIDED,
    procedure_path: Annotated[
        Path | None,
        typer.Option("--procedure", help="Required for supplied-workflow discovery"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Pydantic AI model name; omit for deterministic heuristic ranking"),
    ] = None,
    max_actions: Annotated[int | None, typer.Option("--max-actions", min=1)] = None,
    max_states: Annotated[int | None, typer.Option("--max-states", min=1)] = None,
    max_seconds: Annotated[int | None, typer.Option("--max-seconds", min=1)] = None,
    headed: Annotated[bool, typer.Option("--headed")] = False,
    strict: Annotated[
        bool | None,
        typer.Option("--strict/--no-strict", help="Fail fast on execution errors. Defaults to true for supplied, false for unguided")
    ] = None,
) -> None:
    config, repository, project_id, roles = _open_project(project_dir)
    try:
        if mode is DiscoveryMode.SUPPLIED and procedure_path is None:
            raise typer.BadParameter("--procedure is required when --mode supplied is used")
        if mode is DiscoveryMode.UNGUIDED and procedure_path is not None:
            raise typer.BadParameter("--procedure can only be used with --mode supplied")
        procedure = load_procedure(procedure_path) if procedure_path is not None else None
        settings = load_runtime_settings(project_dir)
        selected_model = settings.model_for_discovery(model)
        planner = PydanticAIPlanner(selected_model) if selected_model else HeuristicPlanner()
        overrides = {
            key: value
            for key, value in {
                "max_actions": max_actions,
                "max_states": max_states,
                "max_duration_seconds": max_seconds,
            }.items()
            if value is not None
        }
        limits = config.discovery.limits.model_copy(update=overrides)
        
        effective_strict = strict if strict is not None else (mode is DiscoveryMode.SUPPLIED)
        config.discovery.strict = effective_strict
        
        browser = PlaywrightBrowser(
            project_root=project_dir,
            config=config,
            role=config.role(role),
            settings=settings,
        )
        runner = ExplorationRunner(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            browser=browser,
            policy=ActionPolicy(config),
            planner=planner,
            config=config,
            project_id=project_id,
            role_id=roles[role],
            role_name=role,
        )
        run_id = asyncio.run(
            runner.run(
                mode=mode,
                supplied_procedure=procedure,
                headed=headed,
                limits=limits,
            )
        )
        typer.echo(json.dumps(repository.discovery_report(run_id), indent=2))
    finally:
        repository.close()


@app.command("discovery-report")
def discovery_report(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    run_id: Annotated[str, typer.Argument(help="Discovery run identifier")],
) -> None:
    _config, repository, _project_id, _roles = _open_project(project_dir)
    try:
        typer.echo(json.dumps(repository.discovery_report(run_id), indent=2))
    finally:
        repository.close()


@app.command("workflow-add")
def workflow_add(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    workflow_path: Annotated[Path, typer.Argument(help="JSON workflow definition")],
) -> None:
    config, repository, project_id, roles = _open_project(project_dir)
    try:
        definition = load_workflow(workflow_path)
        config.role(definition.role)
        revision = repository.add_workflow_revision(
            project_id=project_id,
            role_id=roles[definition.role],
            definition=definition,
        )
        typer.echo(revision.model_dump_json(indent=2))
    finally:
        repository.close()


@app.command("workflow-draft")
def workflow_draft(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    discovery_run_id: Annotated[str, typer.Argument(help="Completed discovery run identifier")],
    role: Annotated[str, typer.Option("--role")] = "default",
) -> None:
    config, repository, project_id, roles = _open_project(project_dir)
    try:
        config.role(role)
        revisions = [
            repository.add_workflow_revision(
                project_id=project_id,
                role_id=roles[role],
                definition=definition,
            )
            for definition in draft_workflows(repository, discovery_run_id=discovery_run_id, role=role)
        ]
        typer.echo(json.dumps([revision.model_dump(mode="json") for revision in revisions], indent=2))
    finally:
        repository.close()


@app.command()
def verify(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    revision_id: Annotated[str, typer.Argument(help="Immutable workflow revision identifier")],
    trusted_fixture_api: Annotated[
        bool,
        typer.Option("--trusted-fixture-api", help="Use same-origin /__prepare, /__state and /__reset endpoints"),
    ] = False,
    headed: Annotated[bool, typer.Option("--headed")] = False,
) -> None:
    config, repository, project_id, roles = _open_project(project_dir)
    try:
        revision = repository.get_workflow_revision(revision_id)
        role = revision.definition.role
        environment = (
            HttpJsonEnvironmentAdapter(base_url=str(config.base_url), allowed_origins=config.allowed_origins)
            if trusted_fixture_api
            else None
        )
        runner = VerificationRunner(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            browser=PlaywrightBrowser(
                project_root=project_dir,
                config=config,
                role=config.role(role),
                settings=load_runtime_settings(project_dir),
            ),
            policy=ActionPolicy(config),
            environment=environment,
            project_id=project_id,
            role_id=roles[role],
            role_name=role,
            base_url=str(config.base_url),
        )
        verification_id = asyncio.run(runner.run(revision, headed=headed))
        typer.echo(json.dumps(repository.verification_report(verification_id), indent=2))
    finally:
        repository.close()


@app.command("verification-report")
def verification_report(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    verification_id: Annotated[str, typer.Argument(help="Verification identifier")],
) -> None:
    _config, repository, _project_id, _roles = _open_project(project_dir)
    try:
        typer.echo(json.dumps(repository.verification_report(verification_id), indent=2))
    finally:
        repository.close()


@app.command("owner-source-add")
def owner_source_add(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    source_path: Annotated[Path, typer.Argument(help="UTF-8 owner source text file")],
    source_kind: Annotated[OwnerSourceKind, typer.Option("--kind")],
    label: Annotated[str, typer.Option("--label", help="Human-readable source label")],
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        source = repository.add_owner_source(
            project_id,
            OwnerSourceDraft(
                source_kind=source_kind,
                label=label,
                content=source_path.read_text(encoding="utf-8"),
            ),
        )
        typer.echo(json.dumps({"id": source.id, "kind": source.source_kind, "label": source.label}, indent=2))
    finally:
        repository.close()


@app.command("document-generate")
def document_generate(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    workflow_revision_id: Annotated[str, typer.Argument(help="Verified workflow revision identifier")],
    verification_id: Annotated[
        str | None, typer.Option("--verification", help="Exact passed verification; defaults to latest passed")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Pydantic AI model; omit for deterministic composition")
    ] = None,
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        selected_model = load_runtime_settings(project_dir).model_for_documentation(model)
        composer = PydanticAIDocumentComposer(selected_model) if selected_model else DeterministicComposer()
        revision = asyncio.run(
            DocumentationService(repository, project_id).generate(
                workflow_revision_id,
                composer,
                verification_id=verification_id,
            )
        )
        typer.echo(revision.model_dump_json(indent=2))
    finally:
        repository.close()


@app.command("document-revise")
def document_revise(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    workflow_revision_id: Annotated[str, typer.Argument(help="Workflow revision identifier")],
    verification_id: Annotated[str, typer.Argument(help="Exact passed verification identifier")],
    content_path: Annotated[Path, typer.Argument(help="Edited structured document JSON")],
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        revision = DocumentationService(repository, project_id).revise(
            workflow_revision_id,
            verification_id,
            load_document_content(content_path),
        )
        typer.echo(revision.model_dump_json(indent=2))
    finally:
        repository.close()


@app.command("document-review")
def document_review(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    document_revision_id: Annotated[str, typer.Argument(help="Exact document revision identifier")],
    decision: Annotated[ReviewDecision, typer.Option("--decision")],
    reviewer: Annotated[str, typer.Option("--reviewer")],
    notes: Annotated[str, typer.Option("--notes")] = "",
) -> None:
    _config, repository, _project_id, _roles = _open_project(project_dir)
    try:
        row = repository.add_review_decision(document_revision_id, decision, reviewer, notes)
        typer.echo(json.dumps({"id": row.id, "decision": row.decision}, indent=2))
    finally:
        repository.close()


@app.command("document-bundle")
def document_bundle(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    document_revision_id: Annotated[str, typer.Argument(help="Document revision identifier")],
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        publisher = DocumentationPublisher(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            project_id=project_id,
            project_root=project_dir,
        )
        typer.echo(str(publisher.create_review_bundle(document_revision_id)))
    finally:
        repository.close()


@app.command("documentation-coverage")
def documentation_coverage(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        publisher = DocumentationPublisher(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            project_id=project_id,
            project_root=project_dir,
        )
        json_path, markdown_path = publisher.write_coverage_report()
        typer.echo(
            json.dumps(
                {
                    "report": repository.documentation_coverage(project_id),
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                },
                indent=2,
            )
        )
    finally:
        repository.close()


@app.command("docs-export")
def docs_export(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    output_dir: Annotated[Path, typer.Argument(help="New output directory")],
) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        publisher = DocumentationPublisher(
            repository=repository,
            artifacts=ArtifactStore(project_dir / RUNTIME_DIR),
            project_id=project_id,
            project_root=project_dir,
        )
        typer.echo(str(publisher.export_approved(output_dir)))
    finally:
        repository.close()


@app.command()
def status(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    run_id: Annotated[str, typer.Argument(help="Run identifier")],
) -> None:
    _config, repository, _project_id, _roles = _open_project(project_dir)
    try:
        typer.echo(json.dumps(repository.run_summary(run_id), indent=2))
    finally:
        repository.close()


@app.command()
def cancel(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    run_id: Annotated[str, typer.Argument(help="Run identifier")],
) -> None:
    _config, repository, _project_id, _roles = _open_project(project_dir)
    try:
        repository.request_cancel(run_id)
        typer.echo(f"Cancellation recorded for {run_id}")
    finally:
        repository.close()


@app.command()
def recover(project_dir: Annotated[Path, typer.Argument(help="Project directory")]) -> None:
    _config, repository, project_id, _roles = _open_project(project_dir)
    try:
        try:
            result = repository.recover_interrupted(project_id)
        except ProjectBusyError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(json.dumps(result, indent=2))
    finally:
        repository.close()


@app.command("auth-login")
def auth_login(
    project_dir: Annotated[Path, typer.Argument(help="Project directory")],
    role: Annotated[str, typer.Option("--role")] = "default",
) -> None:
    async def capture() -> Path:
        config = load_project(project_dir)
        browser = PlaywrightBrowser(
            project_root=project_dir,
            config=config,
            role=config.role(role),
            settings=load_runtime_settings(project_dir),
        )
        session = await browser.start(run_id=f"auth-{role}", headed=True)
        try:
            await session.page.goto(str(config.base_url), wait_until="domcontentloaded")
            await asyncio.to_thread(
                typer.prompt,
                "Complete login in the browser, then press Enter",
                default="",
                show_default=False,
            )
            return await browser.save_authentication(session)
        finally:
            await browser.close(session)

    path = asyncio.run(capture())
    typer.echo(f"Saved authentication state to {path}")


if __name__ == "__main__":
    app()
