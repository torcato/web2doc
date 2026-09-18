from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.test_verification_runner import VerificationBrowser, make_runner
from web2doc.documentation.composer import DeterministicComposer
from web2doc.documentation.models import (
    DocumentClaim,
    DocumentNarrative,
    NarrativeStep,
    OwnerSourceDraft,
    ProvenanceKind,
    ReviewDecision,
)
from web2doc.documentation.publish import DocumentationPublisher
from web2doc.documentation.service import DocumentationService
from web2doc.domain.models import NavigateAction, ProjectConfig, RoleConfig
from web2doc.storage.artifacts import ArtifactIntegrityError, ArtifactStore
from web2doc.storage.repository import Repository
from web2doc.verification.models import VisibleTextPredicate, WorkflowDefinition, WorkflowRevision, WorkflowStep


async def verified_workflow(
    repository: Repository,
    tmp_path: Path,
    project_config: ProjectConfig,
    *,
    key: str = "documented-workflow",
) -> tuple[str, str, WorkflowRevision]:
    runner, project_id, role_id = make_runner(repository, tmp_path, project_config, VerificationBrowser(), None)
    definition = WorkflowDefinition(
        workflow_key=key,
        title="Use <unsafe> [feature](javascript:alert(1))",
        goal="Complete the verified workflow",
        role="admin",
        prerequisites=[VisibleTextPredicate(text="Success")],
        steps=[
            WorkflowStep(
                action=NavigateAction(
                    description="Open the [unsafe](javascript:alert(1)) page",
                    url=str(project_config.base_url),
                ),
                expected=[VisibleTextPredicate(text="Success")],
            ),
            WorkflowStep(
                action=NavigateAction(description="Confirm the result", url=str(project_config.base_url)),
                expected=[VisibleTextPredicate(text="Success")],
            ),
        ],
        final_outcomes=[VisibleTextPredicate(text="Success")],
        unresolved_questions=["Confirm customer terminology"],
    )
    revision = repository.add_workflow_revision(project_id=project_id, role_id=role_id, definition=definition)
    verification_id = await runner.run(revision)
    assert repository.verification_report(verification_id)["status"] == "passed"
    return project_id, verification_id, revision


def publisher(repository: Repository, tmp_path: Path, project_id: str) -> DocumentationPublisher:
    return DocumentationPublisher(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        project_id=project_id,
        project_root=tmp_path,
    )


@pytest.mark.asyncio
async def test_generate_review_revise_and_export_exact_revision(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, verification_id, workflow = await verified_workflow(repository, tmp_path, project_config)
    owner = repository.add_owner_source(
        project_id,
        OwnerSourceDraft(
            source_kind="terminology",
            label="Product vocabulary",
            content="Call an item a record.",
        ),
    )
    service = DocumentationService(repository, project_id)
    document = await service.generate(workflow.id, DeterministicComposer())

    assert document.verification_id == verification_id
    assert document.version == 1
    assert document.content.owner_notes[0].owner_source_id == owner.id
    bundle = publisher(repository, tmp_path, project_id).create_review_bundle(document.id)
    guide = (bundle / "guide.md").read_text(encoding="utf-8")
    assert "&lt;unsafe&gt;" in guide
    assert "\\[feature\\]\\(javascript:alert\\(1\\)\\)" in guide
    assert (bundle / "document.json").is_file()
    assert list((bundle / "assets").glob("*.png"))

    repository.add_review_decision(document.id, ReviewDecision.APPROVED, "Owner", "Supported")
    first_export = publisher(repository, tmp_path, project_id).export_approved(tmp_path / "first-export")
    assert (first_export / "site" / "index.html").is_file()
    assert (first_export / "docs" / "guides" / "documented-workflow.md").is_file()
    repository.add_review_decision(document.id, ReviewDecision.REJECTED, "Owner", "Needs an edit")
    assert repository.approved_document_revisions(project_id) == []

    edited = document.content.model_copy(deep=True)
    edited.goal.text = "Complete the verified workflow using the reviewed wording"
    revision = service.revise(workflow.id, verification_id, edited)
    assert revision.version == 2
    assert revision.source_kind == "manual"
    assert repository.approved_document_revisions(project_id) == []
    with pytest.raises(ValueError, match="no latest document revisions"):
        publisher(repository, tmp_path, project_id).export_approved(tmp_path / "unreviewed-export")

    repository.add_review_decision(revision.id, ReviewDecision.APPROVED, "Owner", "Edited wording")
    second_export = publisher(repository, tmp_path, project_id).export_approved(tmp_path / "second-export")
    assert (second_export / "site" / "index.html").is_file()


@pytest.mark.asyncio
async def test_rejects_wrong_role_step_evidence_and_other_project(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="evidence-validation"
    )
    service = DocumentationService(repository, project_id)
    document = await service.generate(workflow.id, DeterministicComposer())

    wrong_role = document.content.model_copy(deep=True)
    wrong_role.role = "member"
    with pytest.raises(ValueError, match="role"):
        service.revise(workflow.id, verification_id, wrong_role)

    wrong_step = document.content.model_copy(deep=True)
    wrong_step.steps[0].instruction.evidence = list(wrong_step.steps[1].instruction.evidence)
    with pytest.raises(ValueError, match="stale, or unrelated"):
        service.revise(workflow.id, verification_id, wrong_step)

    other_root = tmp_path / "other-project"
    other_config = project_config.model_copy(update={"name": "other", "roles": [RoleConfig(name="admin")]})
    other_project_id, _roles = repository.register_project(other_root, other_config)
    with pytest.raises(KeyError, match="not found in project"):
        DocumentationService(repository, other_project_id).revise(workflow.id, verification_id, document.content)
    unrelated_owner = repository.add_owner_source(
        other_project_id,
        OwnerSourceDraft(
            source_kind="business_rule",
            label="Other tenant rule",
            content="Unrelated rule",
        ),
    )
    wrong_owner = document.content.model_copy(deep=True)
    wrong_owner.owner_notes = [
        DocumentClaim(
            text="Unrelated rule",
            provenance=ProvenanceKind.OWNER,
            owner_source_id=unrelated_owner.id,
        )
    ]
    with pytest.raises(ValueError, match="missing or unrelated source"):
        service.revise(workflow.id, verification_id, wrong_owner)


@pytest.mark.asyncio
async def test_missing_or_stale_verification_is_not_documented_or_exported(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="stale-verification"
    )
    service = DocumentationService(repository, project_id)
    document = await service.generate(workflow.id, DeterministicComposer())
    repository.add_review_decision(document.id, ReviewDecision.APPROVED, "Owner", "Initially valid")

    _project_id, roles = repository.register_project(tmp_path, project_config)
    failed_run = repository.create_run(project_id, roles["admin"], "failed re-verification")
    failed_verification = repository.create_verification(workflow.id, failed_run.id, None)
    from web2doc.verification.models import VerificationStatus

    repository.set_verification_status(failed_verification.id, VerificationStatus.FAILED, "target changed")
    assert repository.approved_document_revisions(project_id) == []
    assert repository.documentation_coverage(project_id)["workflows"][0]["eligible_for_export"] is False
    with pytest.raises(ValueError, match="passed verification"):
        await service.generate(workflow.id, DeterministicComposer(), verification_id=verification_id)

    missing = repository.add_workflow_revision(
        project_id=project_id,
        role_id=roles["admin"],
        definition=workflow.definition.model_copy(update={"workflow_key": "never-verified", "title": "Never verified"}),
    )
    with pytest.raises(ValueError, match="passed verification"):
        await service.generate(missing.id, DeterministicComposer())
    with pytest.raises(ValueError, match="passed verification"):
        await service.generate(workflow.id, DeterministicComposer(), verification_id="missing")
    assert verification_id != failed_verification.id


@pytest.mark.asyncio
async def test_unrelated_verification_and_unsupported_composer_output_are_rejected(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, _verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="composer-validation"
    )
    _same_project, unrelated_verification, _other_workflow = await verified_workflow(
        repository, tmp_path, project_config, key="other-verification"
    )
    service = DocumentationService(repository, project_id)
    with pytest.raises(ValueError, match="passed verification"):
        await service.generate(workflow.id, DeterministicComposer(), verification_id=unrelated_verification)

    class UnsupportedComposer:
        def __init__(self, *, wrong_sequence: bool) -> None:
            self.wrong_sequence = wrong_sequence

        async def compose(self, _context) -> DocumentNarrative:
            return DocumentNarrative(
                title="Invented",
                summary="Invented",
                goal="Invented",
                prerequisites=["Success is visible"],
                steps=[
                    NarrativeStep(
                        sequence=99 if self.wrong_sequence else 1,
                        instruction="Invented instruction",
                    ),
                    NarrativeStep(sequence=2, instruction="Another invented instruction"),
                ],
                outcome="Invented",
                troubleshooting=[] if self.wrong_sequence else ["Unsupported advice"],
            )

    with pytest.raises(ValueError, match="step sequence"):
        await service.generate(workflow.id, UnsupportedComposer(wrong_sequence=True))
    with pytest.raises(ValueError, match="troubleshooting claims"):
        await service.generate(workflow.id, UnsupportedComposer(wrong_sequence=False))


@pytest.mark.asyncio
async def test_invalid_model_narrative_falls_back_without_aborting_generation(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="composer-fallback"
    )

    class InvalidModelComposer:
        async def compose(self, _context) -> DocumentNarrative:
            return DocumentNarrative(
                title="Changed structure",
                summary="Changed structure",
                goal="Changed structure",
                prerequisites=[],
                steps=[NarrativeStep(sequence=7, instruction="Invented")],
                outcome="Changed structure",
                troubleshooting=[],
            )

    document = await DocumentationService(repository, project_id).generate(
        workflow.id,
        InvalidModelComposer(),
        verification_id=verification_id,
        fallback_composer=DeterministicComposer(),
    )

    assert document.source_kind == "generated-fallback"
    assert [step.sequence for step in document.content.steps] == [1, 2]
    assert [step.instruction.text for step in document.content.steps] == [
        "Open the [unsafe](javascript:alert(1)) page",
        "Confirm the result",
    ]


@pytest.mark.asyncio
async def test_tampered_evidence_blocks_review_bundle(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, _verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="tampered-evidence"
    )
    document = await DocumentationService(repository, project_id).generate(workflow.id, DeterministicComposer())
    artifact_id = document.content.steps[0].instruction.evidence[0].screenshot_artifact_id
    artifact = repository.artifact_draft(artifact_id)
    (tmp_path / ".web2doc" / artifact.relative_path).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        publisher(repository, tmp_path, project_id).create_review_bundle(document.id)


@pytest.mark.asyncio
async def test_coverage_report_identifies_unresolved_and_exportable_workflows(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, _verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="coverage"
    )
    document = await DocumentationService(repository, project_id).generate(workflow.id, DeterministicComposer())
    repository.add_review_decision(document.id, ReviewDecision.APPROVED, "Owner", "ok")

    json_path, markdown_path = publisher(repository, tmp_path, project_id).write_coverage_report()

    assert '"eligible_for_export": true' in json_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Confirm customer terminology" in markdown
    assert "| coverage | passed |" in markdown
