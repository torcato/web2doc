from __future__ import annotations

import re
from hashlib import sha256

from pydantic import TypeAdapter

from web2doc.domain.models import Action
from web2doc.storage.repository import Repository
from web2doc.verification.models import UrlPredicate, WorkflowDefinition, WorkflowStep


def draft_workflows(
    repository: Repository,
    *,
    discovery_run_id: str,
    role: str,
) -> list[WorkflowDefinition]:
    action_adapter: TypeAdapter[Action] = TypeAdapter(Action)
    definitions: list[WorkflowDefinition] = []
    for candidate in repository.explored_workflow_candidates(discovery_run_id):
        label = str(candidate["label"])
        raw_actions = [*candidate["path"], candidate["action"]]
        actions = [action_adapter.validate_python(value) for value in raw_actions]
        route = candidate["target_route"]
        if not isinstance(route, str):
            continue
        key_base = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "workflow"
        suffix = sha256(label.encode()).hexdigest()[:8]
        definitions.append(
            WorkflowDefinition(
                workflow_key=f"{key_base[:100]}-{suffix}",
                title=label,
                goal=f"Reach the verified state for {label}",
                role=role,
                steps=[WorkflowStep(action=action) for action in actions],
                final_outcomes=[UrlPredicate(expected=route, match="path")],
                unresolved_questions=[
                    "Confirm the user-facing goal, prerequisites, and business outcome before publication."
                ],
                source_feature_ids=[str(value) for value in candidate["feature_ids"]],
            )
        )
    return definitions
