from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin

from web2doc.discovery.models import CandidateAction
from web2doc.domain.models import (
    ClickAction,
    ControlDraft,
    Effect,
    FillAction,
    NavigateAction,
    ObservationDraft,
    SelectAction,
    Target,
)

WRITE_WORDS = re.compile(r"(?i)\b(create|delete|remove|save|submit|send|publish|invite|buy|pay|confirm)\b")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "unnamed"


def _target(control: ControlDraft) -> Target:
    if control.test_id:
        return Target(test_id=control.test_id)
    if control.label:
        return Target(label=control.label)
    return Target(role=control.role, name=control.name)


def _candidate(action: NavigateAction | ClickAction | FillAction | SelectAction, label: str) -> CandidateAction:
    payload = action.model_dump(mode="json", exclude={"id", "description", "timeout_ms"})
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return CandidateAction(
        id=signature[:16],
        signature=signature,
        label=label,
        action=action,
    )


def enumerate_candidates(observation: ObservationDraft) -> list[CandidateAction]:
    candidates: dict[str, CandidateAction] = {}
    for control in observation.controls:
        if control.disabled or not control.name.strip() or control.input_type == "password":
            continue
        action: NavigateAction | ClickAction | FillAction | SelectAction | None = None
        if control.role == "link" and control.href:
            href = urljoin(observation.url, control.href)
            action = NavigateAction(description=f"Open {control.name}", url=href)
        elif control.role == "combobox" and control.options:
            action = SelectAction(
                description=f"Select an option in {control.name}",
                target=_target(control),
                value=control.options[0],
            )
        elif control.role in ("button", "menuitem", "option", "switch", "combobox", "tab"):
            write = WRITE_WORDS.search(control.name) is not None
            action = ClickAction(
                description=f"Activate {control.name}",
                target=_target(control),
                effect=Effect.WRITE if write else Effect.OBSERVE,
                operation_id=f"click-{_slug(control.name)}" if write else None,
            )
        elif control.role == "textbox":
            action = FillAction(
                description=f"Enter a test value in {control.name}",
                target=_target(control),
                value="web2doc test",
            )
        if action is not None:
            candidate = _candidate(action, control.name)
            candidates[candidate.signature] = candidate
    return list(candidates.values())
