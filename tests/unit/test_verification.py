from __future__ import annotations

import pytest

from web2doc.domain.models import FillAction, ObservationDraft, Target
from web2doc.verification.models import (
    ControlPredicate,
    PredicateStatus,
    TitlePredicate,
    UrlPredicate,
    VisibleTextPredicate,
)
from web2doc.verification.predicates import PredicateEvaluator
from web2doc.verification.workflows import materialize_action


@pytest.mark.asyncio
async def test_browser_predicates_are_explicit() -> None:
    observation = ObservationDraft(
        url="https://example.test/items/1",
        title="Created item",
        aria_snapshot='- heading "Created"\n- button "Delete"',
        screenshot=b"png",
        controls=[],
    )
    evaluator = PredicateEvaluator(None, None)
    assert (
        await evaluator.evaluate(VisibleTextPredicate(text="created"), observation)
    ).status is PredicateStatus.PASSED
    assert (
        await evaluator.evaluate(UrlPredicate(expected="/items/1", match="path"), observation)
    ).status is PredicateStatus.PASSED
    assert (
        await evaluator.evaluate(TitlePredicate(expected="item", match="contains"), observation)
    ).status is PredicateStatus.PASSED
    assert (
        await evaluator.evaluate(
            ControlPredicate(target=Target(role="button", name="Delete"), present=False), observation
        )
    ).status is PredicateStatus.PASSED


def test_materializes_only_exact_input_placeholders() -> None:
    action = FillAction(
        description="Enter name",
        target=Target(label="Item name"),
        value="{{item_name}}",
    )
    assert materialize_action(action, {"item_name": "Example"}).value == "Example"
    with pytest.raises(ValueError, match="item_name"):
        materialize_action(action, {})
