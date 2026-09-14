from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from web2doc.domain.models import Action, Target


class VerificationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class PredicateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class VisibleTextPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["visible_text"] = "visible_text"
    text: str = Field(min_length=1, max_length=1_000)
    present: bool = True
    case_sensitive: bool = False


class UrlPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"] = "url"
    expected: str = Field(min_length=1, max_length=2_000)
    match: Literal["exact", "prefix", "path"] = "exact"


class TitlePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["title"] = "title"
    expected: str = Field(min_length=1, max_length=500)
    match: Literal["exact", "contains"] = "exact"


class ControlPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["control"] = "control"
    target: Target
    present: bool = True
    enabled: bool | None = None


class EnvironmentJsonPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["environment_json"] = "environment_json"
    path: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    operator: Literal["equals", "contains", "not_contains"] = "equals"
    expected: JsonValue


OutcomePredicate = Annotated[
    VisibleTextPredicate | UrlPredicate | TitlePredicate | ControlPredicate | EnvironmentJsonPredicate,
    Field(discriminator="kind"),
]


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    expected: list[OutcomePredicate] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=1_000)
    role: str = Field(min_length=1, max_length=100)
    scenario: str = Field(default="default", min_length=1, max_length=100)
    prerequisites: list[OutcomePredicate] = Field(default_factory=list)
    test_inputs: dict[str, str] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(min_length=1)
    final_outcomes: list[OutcomePredicate] = Field(min_length=1)
    unresolved_questions: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)


class WorkflowRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workflow_id: str
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    definition: WorkflowDefinition


class FixtureReceiptDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_name: str
    scenario: str
    application_version: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class PredicateResultDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PredicateStatus
    message: str
    observed: JsonValue = None


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    run_id: str
    workflow_revision_id: str
    status: VerificationStatus
    reason: str | None = None
