from __future__ import annotations

from collections.abc import Sequence

from web2doc.browser.base import BrowserAdapter
from web2doc.domain.models import (
    Action,
    AttemptStatus,
    Effect,
    NavigateAction,
    ObservationDraft,
    RunStatus,
    Sensitivity,
)
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.database import ObservationRow
from web2doc.storage.repository import Repository
from web2doc.verification.environment import EnvironmentAdapter
from web2doc.verification.models import (
    EnvironmentJsonPredicate,
    OutcomePredicate,
    PredicateStatus,
    VerificationStatus,
    WorkflowRevision,
)
from web2doc.verification.predicates import PredicateEvaluator
from web2doc.verification.workflows import materialize_action


class VerificationRunner[SessionT]:
    def __init__(
        self,
        *,
        repository: Repository,
        artifacts: ArtifactStore,
        browser: BrowserAdapter[SessionT],
        policy: ActionPolicy,
        environment: EnvironmentAdapter | None,
        project_id: str,
        role_id: str,
        role_name: str,
        base_url: str,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.browser = browser
        self.policy = policy
        self.environment = environment
        self.project_id = project_id
        self.role_id = role_id
        self.role_name = role_name
        self.base_url = base_url

    async def run(self, revision: WorkflowRevision, *, headed: bool = False) -> str:
        definition = revision.definition
        if definition.role != self.role_name:
            raise ValueError(f"workflow requires role {definition.role!r}, not {self.role_name!r}")
        run = self.repository.create_run(
            self.project_id,
            self.role_id,
            f"verify:{definition.workflow_key}:v{revision.version}",
            stage="verification",
            scenario=definition.scenario,
        )
        session: SessionT | None = None
        locked = False
        verification_id: str | None = None
        receipt_id: str | None = None
        receipt = None
        leave_fixture = False
        try:
            self.repository.acquire_project_lock(self.project_id, run.id)
            locked = True
            self.repository.set_run_status(run.id, RunStatus.RUNNING)
            reconciliation = self.repository.reconciliation_receipt(revision.id)
            if reconciliation is not None:
                receipt_id, receipt = reconciliation
            elif self.environment is not None:
                receipt = await self.environment.prepare(definition.scenario, definition.test_inputs)
                receipt_row = self.repository.add_fixture_receipt(self.project_id, receipt)
                receipt_id = receipt_row.id
            verification = self.repository.create_verification(revision.id, run.id, receipt_id)
            verification_id = verification.id
            evaluator = PredicateEvaluator(self.environment, receipt)
            session = await self.browser.start(run_id=run.id, headed=headed)

            setup = NavigateAction(description="Open workflow entry page", url=self.base_url)
            observation, observation_draft = await self._execute(run.id, 0, session, setup, None)
            if self.repository.list_attempts(run.id)[-1].status != AttemptStatus.SUCCEEDED:
                return self._finish(
                    run.id,
                    verification.id,
                    VerificationStatus.INCONCLUSIVE,
                    "workflow entry page could not be opened",
                )
            outcome = await self._evaluate(
                verification.id,
                "prerequisite",
                0,
                definition.prerequisites,
                evaluator,
                observation,
                observation_draft,
            )
            if outcome is not None:
                return self._finish(run.id, verification.id, outcome, "workflow prerequisites were not satisfied")

            for sequence, step in enumerate(definition.steps, start=1):
                action = materialize_action(step.action, definition.test_inputs)
                prior_uncertain = self.repository.uncertain_attempt_for_revision(revision.id, sequence)
                if prior_uncertain is not None and action.effect is Effect.WRITE:
                    environment_predicates = [
                        item for item in step.expected if isinstance(item, EnvironmentJsonPredicate)
                    ]
                    if not environment_predicates:
                        leave_fixture = True
                        return self._finish(
                            run.id,
                            verification.id,
                            VerificationStatus.INCONCLUSIVE,
                            "an uncertain write has no trusted environment predicate; action was not repeated",
                        )
                    reconciliation_status = await self._evaluate(
                        verification.id,
                        "reconciliation",
                        sequence,
                        environment_predicates,
                        evaluator,
                        observation,
                        observation_draft,
                    )
                    if reconciliation_status is VerificationStatus.INCONCLUSIVE:
                        leave_fixture = True
                        return self._finish(
                            run.id, verification.id, reconciliation_status, "uncertain write could not be reconciled"
                        )
                    if reconciliation_status is None:
                        self.repository.set_attempt_status(
                            prior_uncertain.id,
                            AttemptStatus.RECONCILED,
                            error="trusted environment check confirmed the intended effect",
                        )
                        attempt = self.repository.create_attempt(run.id, sequence, action, observation.id)
                        self.repository.set_attempt_status(
                            attempt.id,
                            AttemptStatus.RECONCILED,
                            error=f"effect confirmed for prior attempt {prior_uncertain.id}; action not repeated",
                            after_observation_id=observation.id,
                        )
                        step_status = await self._evaluate(
                            verification.id,
                            "step",
                            sequence,
                            step.expected,
                            evaluator,
                            observation,
                            observation_draft,
                        )
                        if step_status is not None:
                            return self._finish(run.id, verification.id, step_status, "step outcome did not pass")
                        continue
                    if len(environment_predicates) != 1:
                        leave_fixture = True
                        return self._finish(
                            run.id,
                            verification.id,
                            VerificationStatus.INCONCLUSIVE,
                            "multiple reconciliation predicates disagreed; action was not repeated",
                        )
                    # One conclusive failed authoritative predicate proves the write did not take effect.
                    self.repository.set_attempt_status(
                        prior_uncertain.id,
                        AttemptStatus.FAILED,
                        error="trusted environment check confirmed that the intended effect was absent",
                    )

                observation, observation_draft = await self._execute(run.id, sequence, session, action, observation)
                attempt = self.repository.list_attempts(run.id)[-1]
                if attempt.status == AttemptStatus.UNCERTAIN:
                    leave_fixture = True
                    return self._finish(
                        run.id,
                        verification.id,
                        VerificationStatus.INCONCLUSIVE,
                        "write outcome is uncertain; fixture retained for reconciliation",
                    )
                if attempt.status in {AttemptStatus.FAILED, AttemptStatus.DENIED}:
                    status = (
                        VerificationStatus.INCONCLUSIVE
                        if attempt.status == AttemptStatus.DENIED
                        else VerificationStatus.FAILED
                    )
                    return self._finish(run.id, verification.id, status, attempt.error or attempt.policy_reason)
                step_status = await self._evaluate(
                    verification.id,
                    "step",
                    sequence,
                    step.expected,
                    evaluator,
                    observation,
                    observation_draft,
                )
                if step_status is not None:
                    return self._finish(run.id, verification.id, step_status, "step outcome did not pass")

            final_status = await self._evaluate(
                verification.id,
                "final",
                0,
                definition.final_outcomes,
                evaluator,
                observation,
                observation_draft,
            )
            if final_status is not None:
                return self._finish(run.id, verification.id, final_status, "final outcome did not pass")
            return self._finish(run.id, verification.id, VerificationStatus.PASSED, None)
        except BaseException as exc:
            if verification_id is not None:
                self.repository.set_verification_status(verification_id, VerificationStatus.INCONCLUSIVE, str(exc))
            current = self.repository.get_run(run.id)
            if current is not None and current.status not in {RunStatus.PAUSED, RunStatus.FAILED}:
                self.repository.set_run_status(run.id, RunStatus.FAILED, str(exc))
            raise
        finally:
            try:
                if session is not None:
                    await self.browser.close(session)
                if self.environment is not None and receipt is not None and not leave_fixture:
                    try:
                        await self.environment.reset(receipt)
                        if receipt_id is not None:
                            self.repository.mark_fixture_reset(receipt_id)
                    except Exception as exc:
                        if verification_id is not None:
                            reason = f"fixture reset failed: {exc}"
                            self.repository.set_verification_status(
                                verification_id, VerificationStatus.INCONCLUSIVE, reason
                            )
                            self.repository.set_run_status(run.id, RunStatus.PAUSED, reason)
            finally:
                if locked:
                    self.repository.release_project_lock(self.project_id, run.id)

    async def _execute(
        self,
        run_id: str,
        sequence: int,
        session: SessionT,
        action: Action,
        before: ObservationRow | None,
    ) -> tuple[ObservationRow, ObservationDraft]:
        attempt = self.repository.create_attempt(run_id, sequence, action, before.id if before else None)
        decision = self.policy.evaluate(action)
        if not decision.allowed:
            self.repository.set_attempt_status(attempt.id, AttemptStatus.DENIED, policy_reason=decision.reason)
            draft = await self.browser.observe(session)
            return before or await self._record_observation(run_id, draft), draft
        self.repository.set_attempt_status(attempt.id, AttemptStatus.ALLOWED, policy_reason=decision.reason)
        self.repository.set_attempt_status(attempt.id, AttemptStatus.EXECUTING)
        try:
            result = await self.browser.execute(session, action)
            draft = await self.browser.observe(session)
            observation = await self._record_observation(run_id, draft)
        except BaseException as exc:
            status = AttemptStatus.UNCERTAIN if action.effect is Effect.WRITE else AttemptStatus.FAILED
            self.repository.set_attempt_status(attempt.id, status, error=str(exc))
            draft = await self.browser.observe(session)
            return before or await self._record_observation(run_id, draft), draft
        self.repository.set_attempt_status(
            attempt.id, AttemptStatus.SUCCEEDED, result=result, after_observation_id=observation.id
        )
        return observation, draft

    async def _evaluate(
        self,
        verification_id: str,
        phase: str,
        sequence: int,
        predicates: Sequence[OutcomePredicate],
        evaluator: PredicateEvaluator,
        observation: ObservationRow,
        observation_draft: ObservationDraft,
    ) -> VerificationStatus | None:
        statuses: list[PredicateStatus] = []
        for index, predicate in enumerate(predicates, start=1):
            result = await evaluator.evaluate(predicate, observation_draft)
            statuses.append(result.status)
            self.repository.add_predicate_result(
                verification_id=verification_id,
                phase=phase,
                step_sequence=sequence,
                predicate_index=index,
                predicate=predicate,
                result=result,
                observation_id=observation.id,
            )
        if PredicateStatus.INCONCLUSIVE in statuses:
            return VerificationStatus.INCONCLUSIVE
        if PredicateStatus.FAILED in statuses:
            return VerificationStatus.FAILED
        return None

    def _finish(self, run_id: str, verification_id: str, status: VerificationStatus, reason: str | None) -> str:
        self.repository.set_verification_status(verification_id, status, reason)
        run_status = (
            RunStatus.AWAITING_REVIEW
            if status in {VerificationStatus.PASSED, VerificationStatus.FAILED}
            else RunStatus.PAUSED
        )
        self.repository.set_run_status(run_id, run_status, reason)
        return verification_id

    async def _record_observation(self, run_id: str, draft: ObservationDraft) -> ObservationRow:
        aria = self.artifacts.write(
            run_id=run_id,
            category="observations",
            content=draft.aria_snapshot.encode(),
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
