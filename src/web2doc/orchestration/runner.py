from __future__ import annotations

from web2doc.browser.base import BrowserAdapter
from web2doc.domain.models import (
    AttemptStatus,
    Effect,
    ObservationDraft,
    Procedure,
    RunStatus,
    Sensitivity,
)
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.database import ObservationRow
from web2doc.storage.repository import Repository


class ProcedureRunner[SessionT]:
    def __init__(
        self,
        *,
        repository: Repository,
        artifacts: ArtifactStore,
        browser: BrowserAdapter[SessionT],
        policy: ActionPolicy,
        project_id: str,
        role_id: str,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.browser = browser
        self.policy = policy
        self.project_id = project_id
        self.role_id = role_id

    async def run(self, procedure: Procedure, *, headed: bool = False) -> str:
        run = self.repository.create_run(self.project_id, self.role_id, procedure.name)
        session: SessionT | None = None
        locked = False
        try:
            self.repository.acquire_project_lock(self.project_id, run.id)
            locked = True
            self.repository.set_run_status(run.id, RunStatus.RUNNING)
            session = await self.browser.start(run_id=run.id, headed=headed)
            observation = await self._record_observation(run.id, await self.browser.observe(session))

            for sequence, action in enumerate(procedure.actions, start=1):
                current = self.repository.get_run(run.id)
                if current is None:
                    raise RuntimeError(f"run disappeared: {run.id}")
                if current.status == RunStatus.CANCELLED:
                    return run.id

                attempt = self.repository.create_attempt(run.id, sequence, action, observation.id)
                decision = self.policy.evaluate(action)
                if not decision.allowed:
                    self.repository.set_attempt_status(
                        attempt.id,
                        AttemptStatus.DENIED,
                        policy_reason=decision.reason,
                    )
                    self.repository.set_run_status(run.id, RunStatus.PAUSED, decision.reason)
                    return run.id

                self.repository.set_attempt_status(attempt.id, AttemptStatus.ALLOWED, policy_reason=decision.reason)
                self.repository.set_attempt_status(attempt.id, AttemptStatus.EXECUTING)
                try:
                    result = await self.browser.execute(session, action)
                    observation = await self._record_observation(run.id, await self.browser.observe(session))
                except BaseException as exc:
                    status = AttemptStatus.UNCERTAIN if action.effect is Effect.WRITE else AttemptStatus.FAILED
                    self.repository.set_attempt_status(attempt.id, status, error=str(exc))
                    run_status = RunStatus.PAUSED if status is AttemptStatus.UNCERTAIN else RunStatus.FAILED
                    self.repository.set_run_status(run.id, run_status, str(exc))
                    return run.id
                self.repository.set_attempt_status(
                    attempt.id,
                    AttemptStatus.SUCCEEDED,
                    result=result,
                    after_observation_id=observation.id,
                )

            current = self.repository.get_run(run.id)
            if current is not None and current.status == RunStatus.CANCELLED:
                return run.id
            self.repository.set_run_status(run.id, RunStatus.AWAITING_REVIEW)
            return run.id
        except BaseException as exc:
            current = self.repository.get_run(run.id)
            if current is not None and current.status not in {
                RunStatus.PAUSED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
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
