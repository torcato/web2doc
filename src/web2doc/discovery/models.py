from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from web2doc.domain.models import Action


class FrontierStatus(StrEnum):
    PENDING = "pending"
    EXPLORING = "exploring"
    EXPLORED = "explored"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class DiscoveryStop(StrEnum):
    FRONTIER_EXHAUSTED = "frontier_exhausted"
    ACTION_BUDGET = "action_budget_exhausted"
    STATE_BUDGET = "state_budget_exhausted"
    DEPTH_BUDGET = "depth_budget_exhausted"
    TIME_BUDGET = "time_budget_exhausted"
    MODEL_CALL_BUDGET = "model_call_budget_exhausted"
    TOKEN_BUDGET = "model_token_budget_exhausted"
    LOOP_DETECTED = "loop_detected"
    POLICY_BLOCKED = "policy_blocked"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PLANNER_FAILED = "planner_failed"
    CANCELLED = "cancelled"
    SUPPLIED_COMPLETE = "supplied_workflow_complete"


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    signature: str
    label: str
    action: Action
    source: str = "visible-control"


class ModelObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str
    title: str
    structure: str
    active_dialogs: list[str]
    selected_tabs: list[str]
    alerts: list[str]
    invalid_controls: list[str]


class RankedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    rationale: str = Field(min_length=1, max_length=1_000)
    priority: int = Field(default=50, ge=0, le=100)
    feature_title: str = Field(min_length=1, max_length=200)
    feature_description: str = Field(default="", max_length=1_000)
    input_value: str | None = Field(default=None, max_length=500)


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[RankedCandidate] = Field(default_factory=list, max_length=50)
    page_summary: str = Field(default="", max_length=2_000)


class PlannerUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    usage_reported: bool = True


class PlannerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: PlannerOutput
    usage: PlannerUsage = Field(default_factory=PlannerUsage)
    model_name: str


class StateIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    algorithm_version: str
    route: str
    normalized_structure: str
