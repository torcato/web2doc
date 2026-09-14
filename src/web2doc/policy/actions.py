from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from web2doc.config import origin_for
from web2doc.domain.models import Action, Effect, NavigateAction, ProjectConfig


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str


class ActionPolicy:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.allowed_origins = {origin_for(origin) for origin in config.allowed_origins}
        self.supporting_origins = {
            origin_for(origin) for origin in config.policy.supporting_origins
        }

    def evaluate(self, action: Action) -> PolicyDecision:
        if action.kind not in self.config.policy.allowed_actions:
            return PolicyDecision(
                allowed=False, reason=f"action kind is not allowed: {action.kind}"
            )
        if (
            action.effect is Effect.WRITE
            and action.operation_id not in self.config.policy.allowed_write_operations
        ):
            return PolicyDecision(
                allowed=False,
                reason=f"write operation is not explicitly allowed: {action.operation_id}",
            )
        if isinstance(action, NavigateAction):
            try:
                origin = origin_for(action.url)
            except ValueError as exc:
                return PolicyDecision(allowed=False, reason=str(exc))
            if origin not in self.allowed_origins:
                return PolicyDecision(
                    allowed=False, reason=f"navigation origin is not allowed: {origin}"
                )
        return PolicyDecision(allowed=True, reason="allowed by project policy")

    def navigation_allowed(self, url: str) -> bool:
        try:
            return origin_for(url) in self.allowed_origins
        except ValueError:
            return url.startswith(("about:", "data:", "blob:"))

    def resource_allowed(self, url: str) -> bool:
        if url.startswith(("about:", "data:", "blob:")):
            return True
        try:
            origin = origin_for(url)
        except ValueError:
            return False
        return origin in self.allowed_origins | self.supporting_origins
