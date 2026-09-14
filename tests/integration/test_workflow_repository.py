from __future__ import annotations

from pathlib import Path

from web2doc.domain.models import NavigateAction, ProjectConfig
from web2doc.storage.repository import Repository
from web2doc.verification.models import TitlePredicate, WorkflowDefinition, WorkflowStep


def test_workflow_revisions_are_immutable_and_deduplicated(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    project_id, roles = repository.register_project(tmp_path, project_config)
    definition = WorkflowDefinition(
        workflow_key="view-items",
        title="View items",
        goal="See the item list",
        role="admin",
        steps=[WorkflowStep(action=NavigateAction(description="Open items", url="https://example.test"))],
        final_outcomes=[TitlePredicate(expected="Items")],
    )
    first = repository.add_workflow_revision(
        project_id=project_id,
        role_id=roles["admin"],
        definition=definition,
    )
    duplicate = repository.add_workflow_revision(
        project_id=project_id,
        role_id=roles["admin"],
        definition=definition,
    )
    changed = repository.add_workflow_revision(
        project_id=project_id,
        role_id=roles["admin"],
        definition=definition.model_copy(update={"goal": "See every item"}),
    )
    assert duplicate.id == first.id
    assert changed.id != first.id
    assert changed.version == 2
    assert repository.get_workflow_revision(first.id) == first
