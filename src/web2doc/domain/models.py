from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"


class AttemptStatus(StrEnum):
    PLANNED = "planned"
    ALLOWED = "allowed"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    DENIED = "denied"


class Effect(StrEnum):
    OBSERVE = "observe"
    WRITE = "write"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    storage_state: str | None = None


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_actions: set[str] = Field(
        default_factory=lambda: {"navigate", "click", "fill", "select", "press", "scroll", "wait"}
    )
    allowed_write_operations: set[str] = Field(default_factory=set)
    supporting_origins: set[str] = Field(default_factory=set)


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    base_url: HttpUrl
    allowed_origins: set[str]
    roles: list[RoleConfig]
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    @field_validator("allowed_origins")
    @classmethod
    def validate_nonempty_origins(cls, value: object) -> object:
        if isinstance(value, set) and not value:
            raise ValueError("at least one allowed origin is required")
        return value

    def role(self, name: str) -> RoleConfig:
        for role in self.roles:
            if role.name == name:
                return role
        raise ValueError(f"unknown role: {name}")


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    name: str | None = None
    label: str | None = None
    test_id: str | None = None
    css: str | None = None
    frame_url: str | None = None
    exact: bool = True

    @field_validator("css")
    @classmethod
    def reject_blank_css(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("css cannot be blank")
        return value

    def model_post_init(self, __context: object) -> None:
        if not any((self.role and self.name, self.label, self.test_id, self.css)):
            raise ValueError("target needs role+name, label, test_id, or css")


class ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    description: str = Field(min_length=1)
    effect: Effect = Effect.OBSERVE
    operation_id: str | None = None
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)

    def model_post_init(self, __context: object) -> None:
        if self.effect is Effect.WRITE and not self.operation_id:
            raise ValueError("write actions require operation_id")


class NavigateAction(ActionBase):
    kind: Literal["navigate"] = "navigate"
    url: str


class ClickAction(ActionBase):
    kind: Literal["click"] = "click"
    target: Target


class FillAction(ActionBase):
    kind: Literal["fill"] = "fill"
    target: Target
    value: str


class SelectAction(ActionBase):
    kind: Literal["select"] = "select"
    target: Target
    value: str


class PressAction(ActionBase):
    kind: Literal["press"] = "press"
    key: str = Field(pattern=r"^[A-Za-z0-9+_-]+$")
    target: Target | None = None


class ScrollAction(ActionBase):
    kind: Literal["scroll"] = "scroll"
    delta_y: int = Field(default=600, ge=-5000, le=5000)


class WaitAction(ActionBase):
    kind: Literal["wait"] = "wait"
    text: str = Field(min_length=1)


Action = Annotated[
    NavigateAction
    | ClickAction
    | FillAction
    | SelectAction
    | PressAction
    | ScrollAction
    | WaitAction,
    Field(discriminator="kind"),
]


class Procedure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    actions: list[Action] = Field(min_length=1)


class ObservationDraft(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    url: str
    title: str
    aria_snapshot: str
    screenshot: bytes
    observed_at: datetime = Field(default_factory=utc_now)


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_url: str
    message: str
    occurred_at: datetime = Field(default_factory=utc_now)


class ArtifactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    relative_path: str
    sha256: str
    media_type: str
    sensitivity: Sensitivity
    size_bytes: int = Field(ge=0)
