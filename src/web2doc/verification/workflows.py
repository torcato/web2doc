from __future__ import annotations

import re

from web2doc.domain.models import Action, FillAction, SelectAction

_INPUT = re.compile(r"^\{\{([A-Za-z0-9_.-]+)\}\}$")


def materialize_action(action: Action, inputs: dict[str, str]) -> Action:
    if not isinstance(action, (FillAction, SelectAction)):
        return action
    match = _INPUT.fullmatch(action.value)
    if match is None:
        return action
    key = match.group(1)
    if key not in inputs:
        raise ValueError(f"workflow input is missing: {key}")
    return action.model_copy(update={"value": inputs[key]})
