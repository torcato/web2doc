from __future__ import annotations

from datetime import UTC, datetime

from web2doc.distillation.models import (
    ActionReference,
    ArtifactReference,
    CaptureManifest,
    CaptureManifestContent,
    DistillationResult,
    DistilledFeature,
    EvidenceReference,
    ObservationReference,
)
from web2doc.documentation.features import _group_features


def _artifact(identifier: str, suffix: str, media_type: str) -> ArtifactReference:
    return ArtifactReference(
        id=identifier,
        relative_path=f"artifacts/run/{identifier}.{suffix}",
        sha256="a" * 64,
        media_type=media_type,
        sensitivity="private",
        size_bytes=3,
    )


def _observation(identifier: str, state_id: str) -> ObservationReference:
    return ObservationReference(
        id=identifier,
        state_id=state_id,
        url="http://localhost:8000/",
        title="Assistant",
        aria=_artifact(f"aria-{identifier}", "yaml", "application/yaml"),
        screenshot=_artifact(f"shot-{identifier}", "png", "image/png"),
        observed_at=datetime.now(UTC),
    )


def _action(sequence: int, label: str, before: str, after: str) -> ActionReference:
    return ActionReference(
        id=f"action-{sequence}",
        sequence=sequence,
        kind="click",
        effect="observe",
        status="succeeded",
        payload={
            "description": f"Activate {label}",
            "target": {"role": "button", "name": label},
        },
        before_observation_id=before,
        after_observation_id=after,
        error=None,
    )


def _feature(title: str, observation_id: str, state_id: str) -> DistilledFeature:
    return DistilledFeature(
        id=f"feature-{title}",
        feature_key=(title.casefold().encode().hex() + ("0" * 64))[:64],
        title=title,
        description=f"Observed {title}.",
        evidence=[
            EvidenceReference(
                observation_id=observation_id,
                screenshot_artifact_id=f"shot-{observation_id}",
                state_id=state_id,
            )
        ],
    )


def test_chainlit_settings_choices_are_grouped_under_controls() -> None:
    observations = [
        _observation("home", "state-home"),
        _observation("settings", "state-settings"),
        _observation("models", "state-models"),
        _observation("profiles", "state-profiles"),
        _observation("servers", "state-servers"),
    ]
    manifest = CaptureManifest(
        id="manifest",
        version=1,
        content_hash="b" * 64,
        created_at=datetime.now(UTC),
        content=CaptureManifestContent(
            run_id="run",
            project_id="project",
            role_id="role",
            scenario="default",
            origin="autonomous",
            capture_status="awaiting_review",
            stop_reason="frontier_exhausted",
            partial=False,
            limits=None,
            frontier={},
            observations=observations,
            actions=[
                _action(1, "Model", "settings", "models"),
                _action(2, "Prompt profile", "settings", "profiles"),
                _action(3, "MCP server", "settings", "servers"),
            ],
            transitions=[],
            candidate_features=[],
        ),
    )
    distilled = DistillationResult(
        processing_attempt_id="attempt",
        manifest_id="manifest",
        processor_name="test",
        configuration_hash="c" * 64,
        features=[
            _feature("Chat settings", "home", "state-home"),
            _feature("Model", "settings", "state-settings"),
            _feature("Prompt profile", "settings", "state-settings"),
            _feature("MCP server", "settings", "state-settings"),
            _feature("gemini-pro", "models", "state-models"),
            _feature("coding", "profiles", "state-profiles"),
            _feature("local-database", "servers", "state-servers"),
            _feature("New chat", "home", "state-home"),
        ],
    )

    documents = _group_features(distilled, manifest, "default")

    assert [document.title for document in documents] == ["Chat settings", "Chat interface"]
    settings = {section.title: section for section in documents[0].sections}
    assert settings["Model"].options == ["gemini-pro"]
    assert settings["Prompt profile"].options == ["coding"]
    assert settings["MCP server"].options == ["local-database"]
    assert all(section.evidence[0].support == "demonstrated" for section in settings.values())
    assert [section.title for section in documents[1].sections] == ["New chat"]
