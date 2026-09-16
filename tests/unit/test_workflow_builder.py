from __future__ import annotations

from typing import Any

from web2doc.domain.models import ClickAction, Effect, Target
from web2doc.verification.builder import draft_workflows


class CandidateRepository:
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self.candidates = candidates

    def explored_workflow_candidates(self, run_id: str) -> list[dict[str, Any]]:
        assert run_id == "run"
        return self.candidates


def action(label: str, *, role: str = "button", write: bool = False) -> dict[str, Any]:
    return ClickAction(
        description=f"Activate {label}",
        effect=Effect.WRITE if write else Effect.OBSERVE,
        operation_id="click-confirm" if write else None,
        target=Target(role=role, name=label),
    ).model_dump(mode="json")


def candidate(label: str, *, path: list[dict[str, Any]] | None = None, role: str = "button") -> dict[str, Any]:
    return {
        "label": label,
        "path": path or [],
        "action": action(label, role=role, write=label == "Confirm"),
        "source_structure": "",
        "target_route": "https://example.test/",
        "target_structure": f"- text: {label}",
        "target_title": "Assistant",
        "feature_ids": [f"feature-{label}"],
    }


def test_builder_synthesizes_complete_task_and_removes_dialog_detours() -> None:
    new_chat = action("New chat")
    candidates = [
        candidate("New chat"),
        candidate("Close", path=[new_chat]),
        candidate("Confirm", path=[new_chat, action("Close"), new_chat]),
        candidate("Cancel", path=[new_chat]),
    ]

    workflows = draft_workflows(CandidateRepository(candidates), discovery_run_id="run", role="default")  # type: ignore[arg-type]

    assert [workflow.workflow_key for workflow in workflows] == ["start-new-chat"]
    assert workflows[0].title == "Start a new chat"
    assert [step.action.description for step in workflows[0].steps] == [
        "Activate New chat",
        "Activate Confirm",
    ]


def test_builder_uses_parent_control_to_name_setting_and_theme_tasks() -> None:
    candidates = [
        candidate(
            "qwen3-coder",
            path=[action("Chat settings"), action("Model")],
            role="option",
        ),
        candidate("Dark Theme", path=[action("Toggle theme")], role="menuitem"),
        candidate("Model", path=[action("Chat settings")]),
        candidate("Unnamed size-6 0"),
    ]

    workflows = draft_workflows(CandidateRepository(candidates), discovery_run_id="run", role="default")  # type: ignore[arg-type]

    assert [(workflow.workflow_key, workflow.title) for workflow in workflows] == [
        ("change-theme-dark-theme", "Change to Dark Theme"),
        ("select-model", "Select a model"),
    ]
    assert [step.action.description for step in workflows[1].steps] == [
        "Activate Chat settings",
        "Activate Model",
        "Choose qwen3-coder",
    ]
    assert all("Confirm the user-facing goal" not in workflow.unresolved_questions for workflow in workflows)


def test_builder_normalizes_chainlit_loading_upload_control() -> None:
    workflows = draft_workflows(
        CandidateRepository([candidate("Upload Button Loading")]),
        discovery_run_id="run",
        role="default",
    )  # type: ignore[arg-type]

    assert [(workflow.workflow_key, workflow.title) for workflow in workflows] == [
        ("attach-file", "Attach a file to a message")
    ]


def test_builder_uses_expanded_source_control_when_saved_path_contains_other_settings() -> None:
    value = candidate(
        "coding",
        path=[action("Chat settings"), action("Model"), action("Prompt profile")],
    )
    value["source_structure"] = (
        '- generic: Model\n- combobox "Model"\n'
        '- generic: Prompt profile\n- combobox "Prompt profile" [expanded]\n'
        '- generic: MCP server\n- combobox "MCP server"'
    )

    workflows = draft_workflows(CandidateRepository([value]), discovery_run_id="run", role="default")  # type: ignore[arg-type]

    assert workflows[0].workflow_key == "select-prompt-profile"
