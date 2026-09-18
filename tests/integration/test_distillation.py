from __future__ import annotations

from pathlib import Path

import pytest

from web2doc.discovery.models import StateIdentity
from web2doc.distillation.models import CaptureManifest, DistilledFeature
from web2doc.distillation.service import DistillationService
from web2doc.domain.models import (
    DiscoveryMode,
    ObservationDraft,
    RunStatus,
    Sensitivity,
)
from web2doc.storage.artifacts import ArtifactStore


def seed_capture(repository, tmp_path: Path, project_config) -> tuple[str, DistillationService]:
    project_id, roles = repository.register_project(tmp_path, project_config)
    run = repository.create_run(
        project_id,
        roles["admin"],
        "offline capture",
        discovery_mode=DiscoveryMode.UNGUIDED,
    )
    store = ArtifactStore(tmp_path / ".web2doc")
    aria = store.write(
        run_id=run.id,
        category="observations",
        content=b"- button: Open settings",
        suffix=".yaml",
        media_type="application/yaml",
        sensitivity=Sensitivity.PRIVATE,
    )
    screenshot = store.write(
        run_id=run.id,
        category="screenshots",
        content=b"png",
        suffix=".png",
        media_type="image/png",
        sensitivity=Sensitivity.PRIVATE,
    )
    repository.add_artifact(run.id, aria)
    repository.add_artifact(run.id, screenshot)
    observation = repository.add_observation(
        run.id,
        ObservationDraft(
            url="http://127.0.0.1:8765/settings",
            title="Settings",
            aria_snapshot="- button: Open settings",
            screenshot=b"png",
        ),
        aria.id,
        screenshot.id,
    )
    state, _created = repository.add_state(
        project_id=project_id,
        role_id=roles["admin"],
        scenario="default",
        observation_id=observation.id,
        identity=StateIdentity(
            fingerprint="a" * 64,
            algorithm_version="test-v1",
            route="http://127.0.0.1:8765/settings",
            normalized_structure="button: Open settings",
        ),
    )
    repository.add_feature(
        run_id=run.id,
        role_id=roles["admin"],
        state_id=state.id,
        observation_id=observation.id,
        title="Application settings",
        description="Configure the application settings visible on this page.",
        confidence=0.8,
    )
    repository.set_run_status(run.id, RunStatus.COMPLETED, "frontier_exhausted")
    return run.id, DistillationService(repository, store)


@pytest.mark.asyncio
async def test_manifest_is_immutable_and_distillation_is_reused(
    repository, tmp_path: Path, project_config
) -> None:
    run_id, service = seed_capture(repository, tmp_path, project_config)

    first_manifest = service.freeze(run_id)
    second_manifest = service.freeze(run_id)
    first = await service.distill(first_manifest.id)
    second = await service.distill(second_manifest.id)

    assert second_manifest.id == first_manifest.id
    assert first_manifest.content.origin == "autonomous"
    assert not first_manifest.content.partial
    assert [feature.title for feature in first.features] == ["Application settings"]
    assert first.features[0].evidence[0].observation_id == first_manifest.content.observations[0].id
    assert not first.reused
    assert second.processing_attempt_id == first.processing_attempt_id
    assert second.reused


class FailingOnceDistiller:
    name = "failing-once"

    def __init__(self) -> None:
        self.calls = 0

    def configuration(self) -> dict[str, object]:
        return {"version": 1}

    async def distill(self, manifest: CaptureManifest) -> list[DistilledFeature]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary offline failure")
        return []


@pytest.mark.asyncio
async def test_failed_offline_processing_retries_without_changing_capture(
    repository, tmp_path: Path, project_config
) -> None:
    run_id, service = seed_capture(repository, tmp_path, project_config)
    manifest = service.freeze(run_id)
    distiller = FailingOnceDistiller()

    with pytest.raises(RuntimeError, match="temporary offline failure"):
        await service.distill(manifest.id, distiller)
    result = await service.distill(manifest.id, distiller)

    assert result.status == "completed"
    assert distiller.calls == 2
    assert repository.discovery_usage(run_id)["actions"] == 0
