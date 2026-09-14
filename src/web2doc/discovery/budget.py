from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from web2doc.discovery.models import DiscoveryStop, PlannerUsage
from web2doc.domain.models import DiscoveryLimits


@dataclass
class BudgetTracker:
    limits: DiscoveryLimits
    started_at: float = field(default_factory=monotonic)
    actions: int = 0
    states: int = 0
    model_calls: int = 0
    output_tokens: int = 0

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.max_duration_seconds - (monotonic() - self.started_at))

    def stop_reason(self, *, next_depth: int | None = None) -> DiscoveryStop | None:
        if self.remaining_seconds() <= 0:
            return DiscoveryStop.TIME_BUDGET
        if self.actions >= self.limits.max_actions:
            return DiscoveryStop.ACTION_BUDGET
        if self.states >= self.limits.max_states:
            return DiscoveryStop.STATE_BUDGET
        if next_depth is not None and next_depth > self.limits.max_depth:
            return DiscoveryStop.DEPTH_BUDGET
        return None

    def reserve_model_call(self) -> DiscoveryStop | None:
        reason = self.stop_reason()
        if reason is not None:
            return reason
        if self.model_calls >= self.limits.max_model_calls:
            return DiscoveryStop.MODEL_CALL_BUDGET
        if self.output_tokens + self.limits.max_tokens_per_call > self.limits.max_output_tokens:
            return DiscoveryStop.TOKEN_BUDGET
        self.model_calls += 1
        return None

    def record_model_usage(self, usage: PlannerUsage) -> None:
        consumed = usage.output_tokens if usage.usage_reported else self.limits.max_tokens_per_call
        self.output_tokens += consumed

    def record_action(self) -> None:
        self.actions += 1

    def record_state(self, *, created: bool) -> None:
        if created:
            self.states += 1
