from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from web2doc.domain.models import Action, ClickAction, FillAction
from web2doc.storage.repository import Repository
from web2doc.verification.models import (
    OutcomePredicate,
    TitlePredicate,
    UrlPredicate,
    VisibleTextPredicate,
    WorkflowDefinition,
    WorkflowStep,
)

ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)

_DISMISS_ACTIONS = {"cancel", "close"}
_NON_TASK_ACTIONS = {"reset"}
_CONTEXT_CONTROLS = {"model", "prompt profile", "mcp server", "toggle theme"}
_UNNAMED = re.compile(r"^unnamed\b", re.IGNORECASE)


@dataclass(frozen=True)
class _TaskDraft:
    key: str
    title: str
    goal: str
    actions: list[Action]
    outcomes: list[OutcomePredicate]
    unresolved: list[str]
    feature_ids: list[str]
    completeness: int


def draft_workflows(
    repository: Repository,
    *,
    discovery_run_id: str,
    role: str,
) -> list[WorkflowDefinition]:
    """Turn explored transitions into concise user tasks rather than edge-by-edge test cases."""

    tasks: dict[str, _TaskDraft] = {}
    for candidate in repository.explored_workflow_candidates(discovery_run_id):
        task = _task_from_candidate(candidate)
        if task is None:
            continue
        current = tasks.get(task.key)
        if current is None or _task_quality(task) > _task_quality(current):
            tasks[task.key] = task

    return [
        WorkflowDefinition(
            workflow_key=task.key,
            title=task.title,
            goal=task.goal,
            role=role,
            steps=[WorkflowStep(action=action) for action in task.actions],
            final_outcomes=task.outcomes,
            unresolved_questions=task.unresolved,
            source_feature_ids=task.feature_ids,
        )
        for task in sorted(tasks.values(), key=lambda value: value.title.casefold())
    ]


def _task_from_candidate(candidate: dict[str, Any]) -> _TaskDraft | None:
    label = str(candidate["label"]).strip()
    normalized = label.casefold()
    if not label or _UNNAMED.match(label) or normalized in _DISMISS_ACTIONS | _NON_TASK_ACTIONS:
        return None

    raw_actions = [*candidate["path"], candidate["action"]]
    actions = _clean_actions([ACTION_ADAPTER.validate_python(value) for value in raw_actions])
    if not actions:
        return None
    context = [_action_label(action).casefold() for action in actions[:-1]]
    choice_parent = _expanded_context(str(candidate.get("source_structure", ""))) or next(
        (value for value in reversed(context) if value in _CONTEXT_CONTROLS),
        None,
    )
    terminal = actions[-1]
    expected_text: str | None = label
    completeness = 1
    unresolved: list[str] = []

    if normalized == "confirm":
        if "new chat" in context:
            key = "start-new-chat"
            title = "Start a new chat"
            goal = "Clear the current conversation and start a new chat"
            expected_text = None
            completeness = 3
            actions = _focused_confirmation_actions(actions, "new chat")
        elif "chat settings" in context:
            key = "apply-chat-settings"
            title = "Apply chat settings"
            goal = "Review and apply the selected chat settings"
            expected_text = None
            completeness = 2
            actions = _focused_confirmation_actions(actions, "chat settings")
        else:
            return None
    elif normalized == "new chat":
        key = "start-new-chat"
        title = "Start a new chat"
        goal = "Open the confirmation needed to start a new conversation"
        expected_text = "Create New Chat"
        actions = [terminal]
        unresolved.append("Confirm the final new-chat action and its effect before publication.")
    elif normalized in {"attach file", "upload"} or normalized.startswith(("upload-button", "upload button")):
        key = "attach-file"
        title = "Attach a file to a message"
        goal = "Open the file picker and attach one or more files to the next message"
        expected_text = None
        actions = [terminal]
        unresolved.append("Native file selection and the completed attachment require human confirmation.")
    elif normalized == "chat settings":
        key = "open-chat-settings"
        title = "Open chat settings"
        goal = "Open the settings used to configure the current chat"
        expected_text = "Settings panel"
        actions = [terminal]
    elif normalized == "readme":
        key = "open-readme"
        title = "Open the application guide"
        goal = "Open the built-in Readme information"
        actions = [terminal]
    elif normalized == "send message":
        key = "send-message"
        title = "Send a message"
        goal = "Enter and send a message to the assistant"
        expected_text = None
        completeness = 2
        message_input = next((action for action in reversed(actions[:-1]) if isinstance(action, FillAction)), None)
        actions = [message_input, terminal] if message_input is not None else [terminal]
        unresolved.append("Confirm the assistant response and expected completion state before publication.")
    elif isinstance(terminal, FillAction) or normalized in _CONTEXT_CONTROLS:
        return None
    elif isinstance(terminal, ClickAction) and (
        terminal.target.role in {"option", "menuitem"} or choice_parent is not None
    ):
        if choice_parent == "model":
            key = "select-model"
            title = "Select a model"
            goal = "Choose which model the chat uses"
            actions = _focused_choice_actions(actions, "model")
        elif choice_parent == "prompt profile":
            key = "select-prompt-profile"
            title = "Select a prompt profile"
            goal = "Choose which prompt profile the chat uses"
            actions = _focused_choice_actions(actions, "prompt profile")
        elif choice_parent == "mcp server":
            if normalized == "none":
                key = "disable-mcp-server"
                title = "Disable MCP servers"
                goal = "Configure the chat without an MCP server"
            else:
                key = "enable-mcp-server"
                title = "Enable an MCP server"
                goal = f"Configure the chat to use the {label} MCP server"
            actions = _focused_choice_actions(actions, "mcp server")
        elif choice_parent == "toggle theme" or normalized.endswith(" theme"):
            key = f"change-theme-{_slug(label)}"
            title = f"Change to {label}"
            goal = f"Change the interface appearance to {label}"
            actions = _focused_choice_actions(actions, "toggle theme")
        else:
            key = f"select-{_slug(label)}"
            title = f"Select {label}"
            goal = f"Select {label} from the available choices"
    else:
        key = _slug(label)
        title = label
        goal = f"Use {label}"

    structure = str(candidate.get("target_structure", ""))
    outcomes = _outcomes(
        expected_text,
        structure,
        str(candidate["target_route"]),
        str(candidate.get("target_title", "")),
    )
    if expected_text is None:
        unresolved.append("Confirm the user-visible result before publication.")
    return _TaskDraft(
        key=key,
        title=title,
        goal=goal,
        actions=actions,
        outcomes=outcomes,
        unresolved=list(dict.fromkeys(unresolved)),
        feature_ids=[str(value) for value in candidate.get("feature_ids", [])],
        completeness=completeness,
    )


def _clean_actions(actions: list[Action]) -> list[Action]:
    clean: list[Action] = []
    signatures: list[str] = []
    for action in actions:
        label = _action_label(action).casefold()
        if label in _DISMISS_ACTIONS:
            clean.clear()
            signatures.clear()
            continue
        signature = json.dumps(
            action.model_dump(mode="json", exclude={"id", "description", "timeout_ms"}),
            sort_keys=True,
        )
        if signature in signatures:
            existing = signatures.index(signature)
            clean = clean[:existing]
            signatures = signatures[:existing]
        clean.append(action)
        signatures.append(signature)
    return clean


def _action_label(action: Action) -> str:
    description = action.description
    for prefix in ("Activate ", "Open ", "Select ", "Enter a test value in "):
        if description.casefold().startswith(prefix.casefold()):
            return description[len(prefix) :].strip()
    return description.strip()


def _focused_choice_actions(actions: list[Action], parent: str) -> list[Action]:
    """Keep only the route into a chooser, its parent control, and the selected value."""

    terminal = actions[-1].model_copy(update={"description": f"Choose {_action_label(actions[-1])}"})
    parent_index = next(
        (index for index in range(len(actions) - 2, -1, -1) if _action_label(actions[index]).casefold() == parent),
        None,
    )
    if parent_index is None:
        return actions
    chat_settings_index = next(
        (
            index
            for index in range(parent_index - 1, -1, -1)
            if _action_label(actions[index]).casefold() == "chat settings"
        ),
        None,
    )
    focused = actions[chat_settings_index : chat_settings_index + 1] if chat_settings_index is not None else []
    return [*focused, actions[parent_index], terminal]


def _focused_confirmation_actions(actions: list[Action], trigger: str) -> list[Action]:
    terminal = actions[-1]
    trigger_action = next(
        (action for action in reversed(actions[:-1]) if _action_label(action).casefold() == trigger),
        None,
    )
    return [trigger_action, terminal] if trigger_action is not None else actions


def _expanded_context(structure: str) -> str | None:
    """Identify the chooser whose expanded popup produced an option candidate."""

    lowered = structure.casefold()
    labels = ("model", "prompt profile", "mcp server")
    positions = [(label, lowered.find(label)) for label in labels]
    positions = sorted(
        ((label, position) for label, position in positions if position >= 0),
        key=lambda value: value[1],
    )
    for index, (label, position) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(lowered)
        if "[expanded]" in lowered[position:end]:
            return label
    return None


def _outcomes(expected_text: str | None, structure: str, route: str, title: str) -> list[OutcomePredicate]:
    if expected_text and expected_text.casefold() in structure.casefold():
        return [VisibleTextPredicate(text=expected_text)]
    path = urllib.parse.urlsplit(route).path or "/"
    if path != "/":
        return [UrlPredicate(expected=path, match="path")]
    if title:
        return [TitlePredicate(expected=title)]
    return [UrlPredicate(expected=path, match="path")]


def _task_quality(task: _TaskDraft) -> tuple[int, int, int]:
    return task.completeness, -len(task.unresolved), -len(task.actions)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:100]
    return slug or "task"
