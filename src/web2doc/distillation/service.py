from __future__ import annotations

import json
from hashlib import sha256
from typing import Protocol

from web2doc.distillation.models import (
    CaptureManifest,
    DistillationResult,
    DistilledFeature,
    EvidenceReference,
)
from web2doc.domain.models import ArtifactDraft, Sensitivity, new_id
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.repository import Repository


class FeatureDistiller(Protocol):
    name: str

    def configuration(self) -> dict[str, object]: ...

    async def distill(self, manifest: CaptureManifest) -> list[DistilledFeature]: ...


class DeterministicFeatureDistiller:
    """Create conservative feature drafts from already captured evidence."""

    name = "deterministic-features-v1"

    def configuration(self) -> dict[str, object]:
        return {"algorithm": self.name}

    async def distill(self, manifest: CaptureManifest) -> list[DistilledFeature]:
        observations = {observation.id: observation for observation in manifest.content.observations}
        by_title: dict[str, DistilledFeature] = {}
        for candidate in manifest.content.candidate_features:
            observation = observations.get(candidate.observation_id)
            if observation is None:
                continue
            title = candidate.title.strip()
            if not title:
                continue
            evidence = EvidenceReference(
                observation_id=observation.id,
                screenshot_artifact_id=observation.screenshot.id,
                state_id=candidate.state_id,
                source_feature_id=candidate.id,
            )
            key = title.casefold()
            existing = by_title.get(key)
            if existing is not None:
                if evidence not in existing.evidence:
                    existing.evidence.append(evidence)
                existing.unresolved = sorted(set(existing.unresolved + candidate.unresolved))
                continue
            description = candidate.description.strip() or (
                f"Feature observed on {observation.title or observation.url}."
            )
            by_title[key] = DistilledFeature(
                id=new_id(),
                feature_key=sha256(key.encode("utf-8")).hexdigest(),
                title=title,
                description=description,
                evidence=[evidence],
                unresolved=candidate.unresolved,
            )

        if by_title:
            return sorted(by_title.values(), key=lambda feature: feature.title.casefold())

        for action in manifest.content.actions:
            if action.status != "succeeded" or action.kind in {"navigate", "scroll", "wait"}:
                continue
            description_value = action.payload.get("description")
            if not isinstance(description_value, str) or not description_value.strip():
                continue
            title = description_value.strip()[:200]
            if "logout" in title.casefold() or "log out" in title.casefold():
                continue
            observation_id = action.after_observation_id or action.before_observation_id
            observation = observations.get(observation_id or "")
            if observation is None:
                continue
            key = title.casefold()
            if key in by_title:
                continue
            by_title[key] = DistilledFeature(
                id=new_id(),
                feature_key=sha256(key.encode("utf-8")).hexdigest(),
                title=title,
                description=f"Captured {action.kind} operation on {observation.title or observation.url}.",
                evidence=[
                    EvidenceReference(
                        observation_id=observation.id,
                        screenshot_artifact_id=observation.screenshot.id,
                        state_id=observation.state_id,
                        action_attempt_id=action.id,
                    )
                ],
                unresolved=["The operation outcome has not been independently verified."],
            )
        return sorted(by_title.values(), key=lambda feature: feature.title.casefold())


class DistillationService:
    def __init__(self, repository: Repository, artifacts: ArtifactStore) -> None:
        self.repository = repository
        self.artifacts = artifacts

    def freeze(self, run_id: str) -> CaptureManifest:
        content = self.repository.capture_manifest_content(run_id)
        for observation in content.observations:
            for reference in (observation.aria, observation.screenshot):
                self.artifacts.read_verified(
                    ArtifactDraft(
                        id=reference.id,
                        relative_path=reference.relative_path,
                        sha256=reference.sha256,
                        media_type=reference.media_type,
                        sensitivity=Sensitivity(reference.sensitivity),
                        size_bytes=reference.size_bytes,
                    )
                )
        return self.repository.add_capture_manifest(content)

    async def distill(
        self,
        manifest_id: str,
        distiller: FeatureDistiller | None = None,
    ) -> DistillationResult:
        selected = distiller or DeterministicFeatureDistiller()
        configuration = json.dumps(
            selected.configuration(), sort_keys=True, separators=(",", ":")
        )
        configuration_hash = sha256(configuration.encode("utf-8")).hexdigest()
        cached = self.repository.completed_distillation(
            manifest_id, selected.name, configuration_hash
        )
        if cached is not None:
            return cached

        manifest = self.repository.get_capture_manifest(manifest_id)
        attempt = self.repository.start_distillation(
            manifest_id, selected.name, configuration_hash
        )
        try:
            features = await selected.distill(manifest)
            return self.repository.complete_distillation(attempt.id, features)
        except Exception as exc:
            self.repository.fail_processing_attempt(attempt.id, str(exc))
            raise
