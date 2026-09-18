from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from web2doc.distillation.models import (
    ActionReference,
    CaptureManifest,
    DistillationResult,
    DistilledFeature,
)
from web2doc.documentation.models import (
    EvidenceLevel,
    FeatureEvidenceReference,
    FeatureReferenceContent,
    FeatureReferenceRevision,
    FeatureReferenceSection,
)
from web2doc.storage.repository import Repository

_SETTINGS_MARKERS = ("settings", "configuration", "configure")
_CONTROL_MARKERS = ("model", "profile", "mcp", "server")
_OMITTED_STANDALONE = {"confirm", "none"}
_SLUG_CHARACTERS = re.compile(r"[^a-z0-9]+")


class FeatureReferenceService:
    """Compose conservative reference pages from immutable distilled evidence."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def generate(self, processing_attempt_id: str) -> list[FeatureReferenceRevision]:
        result = self.repository.get_distillation_result(processing_attempt_id)
        manifest = self.repository.get_capture_manifest(result.manifest_id)
        project_id, role_id, role_name = self.repository.manifest_scope(result.manifest_id)
        contents = _group_features(result, manifest, role_name)
        return [
            self.repository.add_feature_reference_revision(
                project_id=project_id,
                role_id=role_id,
                processing_attempt_id=processing_attempt_id,
                reference_key=_slug(content.title),
                content=content,
            )
            for content in contents
        ]


def _group_features(
    result: DistillationResult,
    manifest: CaptureManifest,
    role_name: str,
) -> list[FeatureReferenceContent]:
    if not result.features:
        return []
    settings_root = next(
        (
            feature
            for feature in result.features
            if any(marker in feature.title.casefold() for marker in _SETTINGS_MARKERS)
        ),
        None,
    )
    controls = [
        feature
        for feature in result.features
        if any(marker in feature.title.casefold() for marker in _CONTROL_MARKERS)
        and feature is not settings_root
    ]
    actions_by_label: dict[str, list[ActionReference]] = defaultdict(list)
    features_by_observation: dict[str, list[DistilledFeature]] = defaultdict(list)
    for feature in result.features:
        for evidence in feature.evidence:
            features_by_observation[evidence.observation_id].append(feature)
    for action in manifest.content.actions:
        label = _action_label(action.payload)
        if label and action.status == "succeeded":
            actions_by_label[label.casefold()].append(action)

    documents: list[FeatureReferenceContent] = []
    consumed: set[str] = set()
    if settings_root is not None or controls:
        root_title = settings_root.title if settings_root is not None else "Settings"
        if settings_root is not None:
            consumed.add(settings_root.feature_key)
        sections: list[FeatureReferenceSection] = []
        for control in sorted(controls, key=lambda item: item.title.casefold()):
            consumed.add(control.feature_key)
            options: dict[str, DistilledFeature] = {}
            for action in actions_by_label.get(control.title.casefold(), []):
                after_observation_id = getattr(action, "after_observation_id", None)
                for candidate in features_by_observation.get(after_observation_id or "", []):
                    if candidate.feature_key == control.feature_key:
                        continue
                    if candidate in controls or candidate is settings_root:
                        continue
                    if candidate.title.casefold() in _OMITTED_STANDALONE:
                        continue
                    options[candidate.title.casefold()] = candidate
            for option in options.values():
                consumed.add(option.feature_key)
            sections.append(
                FeatureReferenceSection(
                    title=control.title,
                    description=_control_description(control.title, root_title, bool(options)),
                    options=sorted((item.title for item in options.values()), key=str.casefold),
                    evidence=_evidence_for(
                        [control, *options.values()],
                        actions_by_label.get(control.title.casefold(), []),
                    ),
                )
            )
        if not sections and settings_root is not None:
            sections.append(
                FeatureReferenceSection(
                    title=settings_root.title,
                    description=f"{settings_root.title} was visible in the captured interface.",
                    evidence=_evidence_for(
                        [settings_root], actions_by_label.get(settings_root.title.casefold(), [])
                    ),
                )
            )
        documents.append(
            FeatureReferenceContent(
                title=root_title,
                summary=(
                    f"The captured interface exposes {root_title} and the controls listed below. "
                    "The page describes observed choices without claiming that unverified changes were saved."
                ),
                role=role_name,
                sections=sections,
                unresolved=_unresolved([settings_root, *controls] if settings_root is not None else controls),
            )
        )

    remaining = [
        feature
        for feature in result.features
        if feature.feature_key not in consumed and feature.title.casefold() not in _OMITTED_STANDALONE
    ]
    if remaining:
        interface_title = (
            "Chat interface"
            if any(feature.title.casefold() == "new chat" for feature in remaining)
            else "Observed features"
        )
        documents.append(
            FeatureReferenceContent(
                title=interface_title,
                summary="These controls and capabilities were visible in the captured application interface.",
                role=role_name,
                sections=[
                    FeatureReferenceSection(
                        title=feature.title,
                        description=f"{feature.title} was visible in the captured interface.",
                        evidence=_evidence_for(
                            [feature], actions_by_label.get(feature.title.casefold(), [])
                        ),
                    )
                    for feature in sorted(remaining, key=lambda item: item.title.casefold())
                ],
                unresolved=_unresolved(remaining),
            )
        )
    return documents


def _action_label(payload: dict[str, object]) -> str | None:
    target = payload.get("target")
    if isinstance(target, dict):
        for key in ("name", "label"):
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    description = payload.get("description")
    if isinstance(description, str):
        value = description.removeprefix("Restore path: ").removeprefix("Activate ").strip()
        return value or None
    return None


def _control_description(title: str, root_title: str, has_options: bool) -> str:
    suffix = " The observed choices are listed below." if has_options else ""
    return f"{title} was observed as a configurable control in {root_title}.{suffix}"


def _evidence_for(
    features: list[DistilledFeature], actions: list[ActionReference]
) -> list[FeatureEvidenceReference]:
    successful_action = actions[0] if actions else None
    support = EvidenceLevel.DEMONSTRATED if successful_action is not None else EvidenceLevel.OBSERVED
    action_id = getattr(successful_action, "id", None)
    unique: dict[tuple[str, str], FeatureEvidenceReference] = {}
    for feature in features:
        for evidence in feature.evidence:
            key = (evidence.observation_id, evidence.screenshot_artifact_id)
            unique[key] = FeatureEvidenceReference(
                observation_id=evidence.observation_id,
                screenshot_artifact_id=evidence.screenshot_artifact_id,
                state_id=evidence.state_id,
                action_attempt_id=evidence.action_attempt_id or action_id,
                support=support,
            )
    return list(unique.values())


def _unresolved(features: Sequence[DistilledFeature | None]) -> list[str]:
    return sorted(
        {
            item
            for feature in features
            if feature is not None
            for item in feature.unresolved
        }
    )


def _slug(value: str) -> str:
    slug = _SLUG_CHARACTERS.sub("-", value.casefold()).strip("-")
    return slug[:180] or "features"
