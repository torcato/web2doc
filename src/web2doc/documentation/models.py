from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProvenanceKind(StrEnum):
    VERIFIED = "verified"
    OWNER = "owner"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    observation_id: str
    screenshot_artifact_id: str


class DocumentClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    provenance: ProvenanceKind
    evidence: list[EvidenceReference] = Field(default_factory=list)
    owner_source_id: str | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> DocumentClaim:
        if self.provenance is ProvenanceKind.VERIFIED and not self.evidence:
            raise ValueError("verified claims require evidence")
        if self.provenance is ProvenanceKind.OWNER and self.owner_source_id is None:
            raise ValueError("owner claims require an owner source")
        if self.provenance is ProvenanceKind.OWNER and self.evidence:
            raise ValueError("owner claims cannot be represented as observed evidence")
        return self


class DocumentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    instruction: DocumentClaim
    expected_result: DocumentClaim | None = None


class DocumentContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    summary: DocumentClaim
    role: str = Field(min_length=1, max_length=100)
    goal: DocumentClaim
    prerequisites: list[DocumentClaim] = Field(default_factory=list)
    steps: list[DocumentStep] = Field(min_length=1)
    outcome: DocumentClaim
    troubleshooting: list[DocumentClaim] = Field(default_factory=list)
    owner_notes: list[DocumentClaim] = Field(default_factory=list)


class NarrativeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=2_000)
    expected_result: str | None = Field(default=None, max_length=2_000)


class DocumentNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2_000)
    goal: str = Field(min_length=1, max_length=2_000)
    prerequisites: list[str] = Field(default_factory=list, max_length=30)
    steps: list[NarrativeStep] = Field(min_length=1, max_length=100)
    outcome: str = Field(min_length=1, max_length=2_000)
    troubleshooting: list[str] = Field(default_factory=list, max_length=30)


class DocumentRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workflow_revision_id: str
    verification_id: str
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    source_kind: str
    content: DocumentContent


class OwnerSourceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(pattern=r"^(terminology|business_rule)$")
    label: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10_000)


class GenerationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_revision_id: str
    verification_id: str
    workflow_title: str
    goal: str
    role: str
    prerequisite_descriptions: list[str]
    step_descriptions: list[str]
    step_expected_descriptions: list[str | None]
    outcome_description: str
    unresolved_questions: list[str]
    evidence_by_step: dict[int, EvidenceReference]
    prerequisite_evidence: EvidenceReference
    outcome_evidence: EvidenceReference
    owner_sources: dict[str, str] = Field(default_factory=dict)
