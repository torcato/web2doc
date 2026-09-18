from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import Literal

from pydantic import TypeAdapter

from web2doc.browser.base import AmbiguousTargetError, BrowserAdapter, TargetNotFoundError
from web2doc.discovery.budget import BudgetTracker
from web2doc.discovery.candidates import enumerate_candidates
from web2doc.discovery.models import (
    CandidateAction,
    DiscoveryStop,
    FrontierStatus,
    PlannerUsage,
    RankedCandidate,
)
from web2doc.discovery.planner import ModelPlanner
from web2doc.discovery.state import StateCanonicalizer
from web2doc.domain.models import (
    Action,
    AttemptStatus,
    DiscoveryLimits,
    DiscoveryMode,
    Effect,
    FillAction,
    NavigateAction,
    ObservationDraft,
    Procedure,
    ProjectConfig,
    RunStatus,
    SelectAction,
    Sensitivity,
    new_id,
)
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.database import FrontierItemRow, ObservationRow, StateRow
from web2doc.storage.repository import Repository

ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)
ACTION_LIST_ADAPTER: TypeAdapter[list[Action]] = TypeAdapter(list[Action])
BUDGET_STOPS = {
    DiscoveryStop.ACTION_BUDGET,
    DiscoveryStop.STATE_BUDGET,
    DiscoveryStop.TIME_BUDGET,
    DiscoveryStop.MODEL_CALL_BUDGET,
    DiscoveryStop.TOKEN_BUDGET,
}
RESUMABLE_STOPS = BUDGET_STOPS | {DiscoveryStop.AUTHENTICATION_REQUIRED}


def _action_signature(action: Action) -> str:
    return json.dumps(
        action.model_dump(mode="json", exclude={"id", "description", "timeout_ms"}),
        sort_keys=True,
    )


class ExplorationRunner[SessionT]:
    def __init__(
        self,
        *,
        repository: Repository,
        artifacts: ArtifactStore,
        browser: BrowserAdapter[SessionT],
        policy: ActionPolicy,
        planner: ModelPlanner,
        config: ProjectConfig,
        project_id: str,
        role_id: str,
        role_name: str,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.browser = browser
        self.policy = policy
        self.planner = planner
        self.config = config
        self.project_id = project_id
        self.role_id = role_id
        self.role_name = role_name
        self.canonicalizer = StateCanonicalizer(config.discovery)

    async def run(
        self,
        *,
        mode: DiscoveryMode,
        supplied_procedure: Procedure | None = None,
        headed: bool = False,
        limits: DiscoveryLimits | None = None,
    ) -> str:
        effective_limits = limits or self.config.discovery.limits
        if mode is DiscoveryMode.SUPPLIED and supplied_procedure is None:
            raise ValueError("supplied discovery mode requires a procedure")
        name = supplied_procedure.name if supplied_procedure is not None else "Unguided feature discovery"
        run = self.repository.create_run(
            self.project_id,
            self.role_id,
            name,
            stage="discovery",
            scenario=self.config.discovery.scenario,
            discovery_mode=mode,
            limits=effective_limits,
        )
        budget = BudgetTracker(effective_limits)
        session: SessionT | None = None
        locked = False
        try:
            self.repository.acquire_project_lock(self.project_id, run.id)
            locked = True
            self.repository.set_run_status(run.id, RunStatus.RUNNING)
            session = await self.browser.start(run_id=run.id, headed=headed)

            if mode is DiscoveryMode.SUPPLIED:
                assert supplied_procedure is not None
                first = await self._execute(
                    run.id,
                    session,
                    supplied_procedure.actions[0],
                    None,
                    None,
                    budget,
                )
                if isinstance(first, tuple):
                    observation, state = first
                    await self._run_supplied(
                        run.id,
                        session,
                        supplied_procedure.actions[1:],
                        observation,
                        state,
                        budget,
                    )
            else:
                first = await self._execute(
                    run.id,
                    session,
                    NavigateAction(
                        description="Open configured discovery start page",
                        url=str(self.config.base_url),
                    ),
                    None,
                    None,
                    budget,
                )
                current = self.repository.get_run(run.id)
                if isinstance(first, tuple) and current is not None and current.status == RunStatus.RUNNING:
                    observation, state = first
                    await self._run_unguided(run.id, session, observation, state, budget)

            current = self.repository.get_run(run.id)
            if current is not None and current.status == RunStatus.RUNNING:
                self.repository.set_run_status(
                    run.id,
                    RunStatus.AWAITING_REVIEW,
                    DiscoveryStop.FRONTIER_EXHAUSTED,
                )
            return run.id
        except BaseException as exc:
            current = self.repository.get_run(run.id)
            if current is not None and current.status not in {
                RunStatus.PAUSED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
                RunStatus.AWAITING_REVIEW,
            }:
                self.repository.set_run_status(run.id, RunStatus.FAILED, str(exc))
            raise
        finally:
            try:
                if session is not None:
                    await self.browser.close(session)
            finally:
                if locked:
                    self.repository.release_project_lock(self.project_id, run.id)

    async def resume(
        self,
        run_id: str,
        *,
        headed: bool = False,
        additional_limits: DiscoveryLimits | None = None,
    ) -> str:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        if run.project_id != self.project_id or run.role_id != self.role_id:
            raise ValueError("discovery run does not belong to the selected project and role")
        if run.stage != "discovery" or run.discovery_mode != DiscoveryMode.UNGUIDED:
            raise ValueError("only unguided discovery runs can be resumed")
        if run.stop_reason not in RESUMABLE_STOPS:
            raise ValueError(
                f"discovery run cannot be resumed from stop reason {run.stop_reason!r}; "
                "only exhausted budget or authentication-paused runs are resumable"
            )

        added = additional_limits or self.config.discovery.limits
        usage = self.repository.discovery_usage(run_id)
        effective_limits = added.model_copy(
            update={
                "max_actions": usage["actions"] + added.max_actions,
                "max_states": usage["states"] + added.max_states,
                "max_model_calls": usage["model_calls"] + added.max_model_calls,
                "max_output_tokens": usage["output_tokens"] + added.max_output_tokens,
            }
        )
        budget = BudgetTracker(
            effective_limits,
            actions=usage["actions"],
            states=usage["states"],
            model_calls=usage["model_calls"],
            output_tokens=usage["output_tokens"],
        )
        session: SessionT | None = None
        locked = False
        try:
            self.repository.acquire_project_lock(self.project_id, run_id)
            locked = True
            self.repository.requeue_interrupted_frontier(
                run_id, {str(reason) for reason in RESUMABLE_STOPS}
            )
            self.repository.set_run_status(run_id, RunStatus.RUNNING)
            session = await self.browser.start(
                run_id=f"{run_id}-resume-{new_id()}",
                headed=headed,
            )
            first = await self._execute(
                run_id,
                session,
                NavigateAction(
                    description="Resume from configured discovery start page",
                    url=str(self.config.base_url),
                ),
                None,
                None,
                budget,
            )
            current = self.repository.get_run(run_id)
            if isinstance(first, tuple) and current is not None and current.status == RunStatus.RUNNING:
                observation, state = first
                await self._run_unguided(run_id, session, observation, state, budget)

            current = self.repository.get_run(run_id)
            if current is not None and current.status == RunStatus.RUNNING:
                self.repository.set_run_status(
                    run_id,
                    RunStatus.AWAITING_REVIEW,
                    DiscoveryStop.FRONTIER_EXHAUSTED,
                )
            return run_id
        except BaseException as exc:
            current = self.repository.get_run(run_id)
            if current is not None and current.status not in {
                RunStatus.PAUSED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
                RunStatus.AWAITING_REVIEW,
            }:
                self.repository.set_run_status(run_id, RunStatus.FAILED, str(exc))
            raise
        finally:
            try:
                if session is not None:
                    await self.browser.close(session)
            finally:
                if locked:
                    self.repository.release_project_lock(self.project_id, run_id)

    async def _run_supplied(
        self,
        run_id: str,
        session: SessionT,
        actions: list[Action],
        observation: ObservationRow,
        state: StateRow,
        budget: BudgetTracker,
    ) -> None:
        for action in actions:
            reason = budget.stop_reason()
            if reason is not None:
                self._stop(run_id, reason)
                return
            outcome = await self._execute(run_id, session, action, observation, state, budget)
            if not isinstance(outcome, tuple):
                return
            observation, state = outcome
        self.repository.set_run_status(run_id, RunStatus.AWAITING_REVIEW, DiscoveryStop.SUPPLIED_COMPLETE)

    async def _run_unguided(
        self,
        run_id: str,
        session: SessionT,
        observation: ObservationRow,
        state: StateRow,
        budget: BudgetTracker,
    ) -> None:
        blocked_any = False
        depth_blocked = False
        current_path: list[Action] = []
        current_state_path: list[str] = [state.id]
        while True:
            current = self.repository.get_run(run_id)
            if current is None:
                raise RuntimeError(f"run disappeared: {run_id}")
            if current.status == RunStatus.CANCELLED:
                self.repository.skip_pending_frontier(run_id, DiscoveryStop.CANCELLED)
                return
            reason = budget.stop_reason()
            if reason is not None:
                self._stop(run_id, reason)
                return

            draft = await self.browser.observe(session)
            if self._authentication_required(draft):
                self.repository.set_run_status(run_id, RunStatus.PAUSED, DiscoveryStop.AUTHENTICATION_REQUIRED)
                return
            if not self.repository.frontier_exists_for_state(run_id, state.id):
                path_signatures = {_action_signature(action) for action in current_path}
                candidates = [
                    candidate
                    for candidate in enumerate_candidates(draft)
                    if _action_signature(candidate.action) not in path_signatures
                ][: budget.limits.max_candidates_per_state]
                if candidates:
                    if len(current_path) + 1 > budget.limits.max_depth:
                        depth_blocked = True
                        for depth_candidate in candidates:
                            item = self.repository.enqueue_frontier(
                                run_id=run_id,
                                state_id=state.id,
                                candidate=depth_candidate,
                                path=current_path,
                                rationale="Candidate exceeds the configured path-depth budget.",
                                priority=0,
                                depth=len(current_path) + 1,
                            )
                            self.repository.set_frontier_status(
                                item.id,
                                FrontierStatus.SKIPPED,
                                reason=DiscoveryStop.DEPTH_BUDGET,
                            )
                        proposals: list[RankedCandidate] = []
                    else:
                        planned = await self._plan(run_id, draft, candidates, budget)
                        if planned is None:
                            return
                        proposals = planned
                    candidate_by_id = {candidate.id: candidate for candidate in candidates}
                    for proposal in proposals:
                        selected_candidate = candidate_by_id.get(proposal.candidate_id)
                        if selected_candidate is None:
                            continue
                        selected_candidate = selected_candidate.model_copy(
                            update={"action": self._apply_input(selected_candidate.action, proposal)}
                        )
                        self.repository.enqueue_frontier(
                            run_id=run_id,
                            state_id=state.id,
                            candidate=selected_candidate,
                            path=current_path,
                            rationale=proposal.rationale,
                            priority=proposal.priority,
                            depth=len(current_path) + 1,
                        )
                        self.repository.add_feature(
                            run_id=run_id,
                            role_id=self.role_id,
                            state_id=state.id,
                            observation_id=observation.id,
                            title=self.canonicalizer.sanitize_text(proposal.feature_title),
                            description=self.canonicalizer.sanitize_text(proposal.feature_description),
                            confidence=proposal.priority / 100,
                            unresolved=["Candidate feature has not been outcome-verified."],
                        )

            frontier = self.repository.next_frontier(run_id, state_id=state.id)
            if frontier is None:
                frontier = self.repository.next_frontier(run_id)
                if frontier is None:
                    self._stop(
                        run_id,
                        DiscoveryStop.POLICY_BLOCKED
                        if blocked_any
                        else DiscoveryStop.DEPTH_BUDGET
                        if depth_blocked
                        else DiscoveryStop.FRONTIER_EXHAUSTED,
                    )
                    return
                restored = await self._restore_frontier(run_id, session, frontier, observation, state, budget)
                if restored is None:
                    return
                observation, state, current_path, current_state_path, matched = restored
                if not matched:
                    blocked_any = True
                    continue
            action = ACTION_ADAPTER.validate_json(frontier.action_json)
            decision = self.policy.evaluate(action)
            if not decision.allowed:
                blocked_any = True
                attempt = self.repository.create_attempt(
                    run_id,
                    self.repository.next_attempt_sequence(run_id),
                    action,
                    observation.id,
                )
                self.repository.set_attempt_status(
                    attempt.id,
                    AttemptStatus.DENIED,
                    policy_reason=decision.reason,
                )
                self.repository.set_frontier_status(
                    frontier.id,
                    FrontierStatus.BLOCKED,
                    reason=decision.reason,
                    attempt_id=attempt.id,
                )
                continue

            self.repository.set_frontier_status(frontier.id, FrontierStatus.EXPLORING)
            outcome = await self._execute(run_id, session, action, observation, state, budget)
            if outcome == "RECOVERABLE":
                self.repository.set_frontier_status(
                    frontier.id,
                    FrontierStatus.BLOCKED,
                    reason="recoverable execution failure",
                )
                continue
            if outcome is None:
                current = self.repository.get_run(run_id)
                self.repository.set_frontier_status(
                    frontier.id,
                    FrontierStatus.BLOCKED,
                    reason=current.stop_reason if current is not None else "run disappeared",
                )
                return
            observation, next_state = outcome
            last_attempt = self.repository.list_attempts(run_id)[-1]
            self.repository.set_frontier_status(
                frontier.id,
                FrontierStatus.EXPLORED,
                attempt_id=last_attempt.id,
            )
            state = next_state

            # Algorithmic Minimizer: Prune loops if we return to a state in the current path
            if next_state.id in current_state_path:
                loop_start_idx = current_state_path.index(next_state.id)
                current_path = current_path[:loop_start_idx]
                current_state_path = current_state_path[:loop_start_idx]
            else:
                current_path = [*current_path, action]

            current_state_path = [*current_state_path, state.id]

            # A repeated state ends only this path. Its already-created frontier is finite,
            # so discovery can safely continue with unexplored siblings until a budget or
            # frontier exhaustion provides the terminal condition.

    async def _restore_frontier(
        self,
        run_id: str,
        session: SessionT,
        frontier: FrontierItemRow,
        observation: ObservationRow,
        state: StateRow,
        budget: BudgetTracker,
    ) -> tuple[ObservationRow, StateRow, list[Action], list[str], bool] | None:
        base_action = NavigateAction(
            description="Restore discovery start page",
            url=str(self.config.base_url),
        )
        restored = await self._execute(run_id, session, base_action, observation, state, budget)
        if not isinstance(restored, tuple):
            return None
        observation, state = restored
        path = ACTION_LIST_ADAPTER.validate_json(frontier.path_json)
        replayed_path: list[Action] = []
        replayed_state_path: list[str] = [state.id]
        for saved_action in path:
            replay_action = saved_action.model_copy(
                update={
                    "id": new_id(),
                    "description": f"Restore path: {saved_action.description}",
                }
            )
            restored = await self._execute(run_id, session, replay_action, observation, state, budget)
            if not isinstance(restored, tuple):
                return None
            observation, state = restored
            replayed_path.append(saved_action)
            replayed_state_path.append(state.id)
        if state.id != frontier.state_id:
            self.repository.set_frontier_status(
                frontier.id,
                FrontierStatus.BLOCKED,
                reason="saved path no longer restores the expected canonical state",
            )
            return observation, state, replayed_path, replayed_state_path, False
        return observation, state, replayed_path, replayed_state_path, True

    async def _plan(
        self,
        run_id: str,
        draft: ObservationDraft,
        candidates: list[CandidateAction],
        budget: BudgetTracker,
    ) -> list[RankedCandidate] | None:
        model_view = self.canonicalizer.model_view(draft)
        model_candidates = [
            candidate.model_copy(
                update={
                    "label": self.canonicalizer.sanitize_text(candidate.label),
                    "action": candidate.action.model_copy(
                        update={"description": self.canonicalizer.sanitize_text(candidate.action.description)}
                    ),
                }
            )
            for candidate in candidates
        ]
        for attempt_number in range(budget.limits.model_retries + 1):
            if self.planner.requires_model_budget:
                reason = budget.reserve_model_call()
                if reason is not None:
                    self._stop(run_id, reason)
                    return None
            started = monotonic()
            timeout_scope: asyncio.Timeout | None = None
            try:
                async with asyncio.timeout(budget.remaining_seconds()) as timeout_scope:
                    result = await self.planner.propose(
                        model_view,
                        model_candidates,
                        max_output_tokens=budget.limits.max_tokens_per_call,
                    )
            except Exception as exc:
                if self.planner.requires_model_budget:
                    unknown = PlannerUsage(
                        output_tokens=budget.limits.max_tokens_per_call,
                        usage_reported=False,
                    )
                    budget.record_model_usage(unknown)
                    self.repository.add_usage_event(
                        run_id,
                        "unavailable",
                        unknown,
                        int((monotonic() - started) * 1_000),
                    )
                if timeout_scope is not None and timeout_scope.expired():
                    self._stop(run_id, DiscoveryStop.TIME_BUDGET)
                    return None
                if attempt_number >= budget.limits.model_retries:
                    self.repository.set_run_status(
                        run_id,
                        RunStatus.PAUSED,
                        f"{DiscoveryStop.PLANNER_FAILED}: {exc}",
                    )
                    return None
                continue
            if self.planner.requires_model_budget:
                budget.record_model_usage(result.usage)
                self.repository.add_usage_event(
                    run_id,
                    result.model_name,
                    result.usage,
                    int((monotonic() - started) * 1_000),
                )
            return result.output.proposals
        return None  # pragma: no cover

    async def _execute(
        self,
        run_id: str,
        session: SessionT,
        action: Action,
        before_observation: ObservationRow | None,
        before_state: StateRow | None,
        budget: BudgetTracker,
    ) -> tuple[ObservationRow, StateRow] | Literal["RECOVERABLE"] | None:
        reason = budget.stop_reason()
        if reason is not None:
            self._stop(run_id, reason)
            return None
        attempt = self.repository.create_attempt(
            run_id,
            self.repository.next_attempt_sequence(run_id),
            action,
            before_observation.id if before_observation is not None else None,
        )
        decision = self.policy.evaluate(action)
        if not decision.allowed:
            self.repository.set_attempt_status(attempt.id, AttemptStatus.DENIED, policy_reason=decision.reason)
            self.repository.set_run_status(run_id, RunStatus.PAUSED, decision.reason)
            return None
        self.repository.set_attempt_status(attempt.id, AttemptStatus.ALLOWED, policy_reason=decision.reason)
        self.repository.set_attempt_status(attempt.id, AttemptStatus.EXECUTING)
        budget.record_action()
        timeout_scope: asyncio.Timeout | None = None
        try:
            async with asyncio.timeout(budget.remaining_seconds()) as timeout_scope:
                result = await self.browser.execute(session, action)
                observation, state, created = await self._observe_state(run_id, session)
        except BaseException as exc:
            status = AttemptStatus.UNCERTAIN if action.effect is Effect.WRITE else AttemptStatus.FAILED
            self.repository.set_attempt_status(attempt.id, status, error=str(exc))
            if timeout_scope is not None and timeout_scope.expired() and status is not AttemptStatus.UNCERTAIN:
                self.repository.set_run_status(run_id, RunStatus.AWAITING_REVIEW, DiscoveryStop.TIME_BUDGET)
                return None

            is_safe_failure = isinstance(exc, (TargetNotFoundError, AmbiguousTargetError))
            if not self.config.discovery.strict and status is AttemptStatus.FAILED and is_safe_failure:
                return "RECOVERABLE"

            run_status = RunStatus.PAUSED if status is AttemptStatus.UNCERTAIN else RunStatus.FAILED
            self.repository.set_run_status(run_id, run_status, str(exc))
            return None
        budget.record_state(created=created)
        self.repository.set_attempt_status(
            attempt.id,
            AttemptStatus.SUCCEEDED,
            result=result,
            after_observation_id=observation.id,
        )
        if before_state is not None:
            self.repository.add_transition(
                run_id=run_id,
                source_state_id=before_state.id,
                target_state_id=state.id,
                attempt_id=attempt.id,
            )
        return observation, state

    async def _observe_state(
        self,
        run_id: str,
        session: SessionT,
    ) -> tuple[ObservationRow, StateRow, bool]:
        draft = await self.browser.observe(session)
        observation = await self._record_observation(run_id, draft)
        identity = self.canonicalizer.canonicalize(
            draft,
            role=self.role_name,
            scenario=self.config.discovery.scenario,
        )
        state, created = self.repository.add_state(
            project_id=self.project_id,
            role_id=self.role_id,
            scenario=self.config.discovery.scenario,
            observation_id=observation.id,
            identity=identity,
        )
        return observation, state, created

    async def _record_observation(self, run_id: str, draft: ObservationDraft) -> ObservationRow:
        aria = self.artifacts.write(
            run_id=run_id,
            category="observations",
            content=draft.aria_snapshot.encode("utf-8"),
            suffix=".yaml",
            media_type="application/yaml",
            sensitivity=Sensitivity.PRIVATE,
        )
        screenshot = self.artifacts.write(
            run_id=run_id,
            category="screenshots",
            content=draft.screenshot,
            suffix=".png",
            media_type="image/png",
            sensitivity=Sensitivity.PRIVATE,
        )
        self.repository.add_artifact(run_id, aria)
        self.repository.add_artifact(run_id, screenshot)
        return self.repository.add_observation(run_id, draft, aria.id, screenshot.id)

    def _apply_input(self, action: Action, proposal: RankedCandidate) -> Action:
        if proposal.input_value is None:
            return action
        if isinstance(action, (FillAction, SelectAction)):
            return action.model_copy(update={"value": proposal.input_value})
        return action

    def _authentication_required(self, draft: ObservationDraft) -> bool:
        route = draft.url.lower()
        title = draft.title.casefold()
        return (
            any(control.input_type == "password" for control in draft.controls)
            or any(marker in title for marker in ("401 unauthorized", "403 forbidden"))
            or any(
            marker in route for marker in ("/login", "/signin", "/sign-in")
            )
        )

    def _stop(self, run_id: str, reason: DiscoveryStop) -> None:
        self.repository.skip_pending_frontier(run_id, reason)
        self.repository.set_run_status(run_id, RunStatus.AWAITING_REVIEW, reason)
