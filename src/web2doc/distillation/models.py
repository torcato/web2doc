from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    relative_path: str
    sha256: str
    media_type: str
    sensitivity: str
    size_bytes: int = Field(ge=0)


class ObservationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    state_id: str | None
    url: str
    title: str
    aria: ArtifactReference
    screenshot: ArtifactReference
    observed_at: datetime


class ActionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sequence: int = Field(ge=1)
    kind: str
    effect: str
    status: str
    payload: dict[str, object]
    before_observation_id: str | None
    after_observation_id: str | None
    error: str | None


class TransitionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_state_id: str
    target_state_id: str
    attempt_id: str


class CandidateFeatureReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    confidence: float = Field(ge=0, le=1)
    state_id: str
    observation_id: str
    unresolved: list[str] = Field(default_factory=list)


class CaptureManifestContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    project_id: str
    role_id: str
    scenario: str
    origin: Literal["autonomous", "supplied", "procedure", "operator"]
    capture_status: str
    stop_reason: str | None
    partial: bool
    limits: dict[str, object] | None
    frontier: dict[str, int]
    observations: list[ObservationReference]
    actions: list[ActionReference]
    transitions: list[TransitionReference]
    candidate_features: list[CandidateFeatureReference]


class CaptureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime
    content: CaptureManifestContent


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    screenshot_artifact_id: str
    state_id: str | None = None
    source_feature_id: str | None = None
    action_attempt_id: str | None = None


class DistilledFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    feature_key: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceReference] = Field(min_length=1)
    unresolved: list[str] = Field(default_factory=list)


class DistillationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processing_attempt_id: str
    manifest_id: str
    processor_name: str
    configuration_hash: str
    status: Literal["completed"] = "completed"
    reused: bool = False
    features: list[DistilledFeature]
