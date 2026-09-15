from __future__ import annotations

from web2doc.documentation.composer import DocumentComposer
from web2doc.documentation.models import (
    DocumentClaim,
    DocumentContent,
    DocumentRevision,
    DocumentStep,
    EvidenceReference,
    GenerationContext,
    ProvenanceKind,
)
from web2doc.storage.repository import Repository
from web2doc.verification.models import (
    ControlPredicate,
    EnvironmentJsonPredicate,
    OutcomePredicate,
    TitlePredicate,
    UrlPredicate,
    VisibleTextPredicate,
)


class DocumentationService:
    def __init__(self, repository: Repository, project_id: str) -> None:
        self.repository = repository
        self.project_id = project_id

    async def generate(
        self,
        workflow_revision_id: str,
        composer: DocumentComposer,
        *,
        verification_id: str | None = None,
    ) -> DocumentRevision:
        context = self._context(workflow_revision_id, verification_id)
        narrative = await composer.compose(context)
        expected_sequences = list(range(1, len(context.step_descriptions) + 1))
        if [step.sequence for step in narrative.steps] != expected_sequences:
            raise ValueError("composer changed the verified workflow step sequence")
        if len(narrative.prerequisites) != len(context.prerequisite_descriptions):
            raise ValueError("composer changed the verified prerequisite count")
        if narrative.troubleshooting:
            raise ValueError("composer produced troubleshooting claims without supporting failure evidence")

        outcome_reference = context.outcome_evidence
        content = DocumentContent(
            title=narrative.title,
            summary=self._verified_claim(narrative.summary, outcome_reference),
            role=context.role,
            goal=self._verified_claim(narrative.goal, outcome_reference),
            prerequisites=[
                self._verified_claim(text, context.prerequisite_evidence)
                for text in narrative.prerequisites
            ],
            steps=[
                DocumentStep(
                    sequence=step.sequence,
                    instruction=self._verified_claim(
                        step.instruction, context.evidence_by_step[step.sequence]
                    ),
                    expected_result=(
                        self._verified_claim(
                            step.expected_result, context.evidence_by_step[step.sequence]
                        )
                        if step.expected_result is not None
                        else None
                    ),
                )
                for step in narrative.steps
            ],
            outcome=self._verified_claim(narrative.outcome, outcome_reference),
            troubleshooting=[],
            owner_notes=[
                DocumentClaim(
                    text=source.content,
                    provenance=ProvenanceKind.OWNER,
                    owner_source_id=source.id,
                )
                for source in self.repository.list_owner_sources(self.project_id)
            ],
        )
        self.validate_content(workflow_revision_id, context.verification_id, content)
        return self.repository.add_document_revision(
            workflow_revision_id=workflow_revision_id,
            verification_id=context.verification_id,
            content=content,
            source_kind="generated",
        )

    def revise(
        self,
        workflow_revision_id: str,
        verification_id: str,
        content: DocumentContent,
    ) -> DocumentRevision:
        self.validate_content(workflow_revision_id, verification_id, content)
        return self.repository.add_document_revision(
            workflow_revision_id=workflow_revision_id,
            verification_id=verification_id,
            content=content,
            source_kind="manual",
        )

    def validate_content(
        self,
        workflow_revision_id: str,
        verification_id: str,
        content: DocumentContent,
    ) -> None:
        context = self._context(workflow_revision_id, verification_id)
        if content.role != context.role:
            raise ValueError("document role does not match the verified workflow role")
        if [step.sequence for step in content.steps] != list(
            range(1, len(context.step_descriptions) + 1)
        ):
            raise ValueError("document steps do not match the verified workflow")
        if len(content.prerequisites) != len(context.prerequisite_descriptions):
            raise ValueError("document prerequisites do not match the verified workflow")
        owner_ids = {source.id for source in self.repository.list_owner_sources(self.project_id)}
        self._validate_claim(content.summary, context.outcome_evidence, owner_ids)
        self._validate_claim(content.goal, context.outcome_evidence, owner_ids)
        self._validate_claim(content.outcome, context.outcome_evidence, owner_ids)
        for claim in content.prerequisites:
            self._validate_claim(claim, context.prerequisite_evidence, owner_ids)
        for step in content.steps:
            expected = context.evidence_by_step[step.sequence]
            self._validate_claim(step.instruction, expected, owner_ids)
            if step.expected_result is not None:
                self._validate_claim(step.expected_result, expected, owner_ids)
        for claim in [*content.troubleshooting, *content.owner_notes]:
            if claim.provenance is ProvenanceKind.VERIFIED:
                raise ValueError("troubleshooting and owner notes require explicit owner provenance")
            self._validate_claim(claim, context.outcome_evidence, owner_ids, allow_owner=True)

    def _context(self, workflow_revision_id: str, verification_id: str | None) -> GenerationContext:
        raw = self.repository.verification_evidence_context(workflow_revision_id, verification_id)
        workflow = raw["workflow"]
        evidence_by_step = {
            int(key): EvidenceReference.model_validate(value)
            for key, value in raw["step_evidence"].items()
        }
        prerequisites = [_predicate_text(predicate) for predicate in workflow.prerequisites]
        step_expected = [
            "; ".join(_predicate_text(predicate) for predicate in step.expected) or None
            for step in workflow.steps
        ]
        return GenerationContext(
            workflow_revision_id=workflow_revision_id,
            verification_id=raw["verification_id"],
            workflow_title=workflow.title,
            goal=workflow.goal,
            role=workflow.role,
            prerequisite_descriptions=prerequisites,
            step_descriptions=[step.action.description for step in workflow.steps],
            step_expected_descriptions=step_expected,
            outcome_description="; ".join(
                _predicate_text(predicate) for predicate in workflow.final_outcomes
            ),
            unresolved_questions=workflow.unresolved_questions,
            evidence_by_step=evidence_by_step,
            prerequisite_evidence=EvidenceReference.model_validate(raw["prerequisite_evidence"]),
            outcome_evidence=EvidenceReference.model_validate(raw["outcome_evidence"]),
            owner_sources={
                source.id: source.content
                for source in self.repository.list_owner_sources(self.project_id)
            },
        )

    @staticmethod
    def _verified_claim(text: str, evidence: EvidenceReference) -> DocumentClaim:
        return DocumentClaim(
            text=text,
            provenance=ProvenanceKind.VERIFIED,
            evidence=[evidence],
        )

    @staticmethod
    def _validate_claim(
        claim: DocumentClaim,
        expected: EvidenceReference,
        owner_ids: set[str],
        *,
        allow_owner: bool = False,
    ) -> None:
        if claim.provenance is ProvenanceKind.VERIFIED:
            if claim.evidence != [expected]:
                raise ValueError("claim evidence is missing, stale, or unrelated")
        else:
            if not allow_owner:
                raise ValueError("procedural claims require verified evidence")
            if claim.owner_source_id not in owner_ids:
                raise ValueError("owner claim references a missing or unrelated source")


def _predicate_text(predicate: OutcomePredicate) -> str:
    if isinstance(predicate, VisibleTextPredicate):
        qualifier = "is visible" if predicate.present else "is not visible"
        return f"Text {predicate.text!r} {qualifier}"
    if isinstance(predicate, UrlPredicate):
        return f"The page URL has {predicate.match} match {predicate.expected!r}"
    if isinstance(predicate, TitlePredicate):
        return f"The page title has {predicate.match} match {predicate.expected!r}"
    if isinstance(predicate, ControlPredicate):
        state = "is available" if predicate.present else "is absent"
        name = predicate.target.name or predicate.target.label or predicate.target.test_id or "control"
        return f"The {name!r} control {state}"
    if isinstance(predicate, EnvironmentJsonPredicate):
        return f"Verified application state {predicate.path!r} {predicate.operator} {predicate.expected!r}"
    raise TypeError(f"unsupported predicate: {type(predicate).__name__}")
