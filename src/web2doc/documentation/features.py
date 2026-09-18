from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from web2doc.distillation.models import (
    ActionReference,
    CaptureManifest,
    ControlReference,
    DistillationResult,
    DistilledFeature,
    ObservationReference,
)
from web2doc.documentation.feature_composer import (
    DeterministicFeatureReferenceComposer,
    FeatureReferenceComposer,
    deterministic_feature_narrative,
)
from web2doc.documentation.models import (
    EvidenceLevel,
    FeatureEvidenceReference,
    FeatureReferenceContent,
    FeatureReferenceNarrative,
    FeatureReferencePlan,
    FeatureReferencePlanSection,
    FeatureReferenceRevision,
    FeatureReferenceSection,
    OptionCoverage,
)
from web2doc.domain.models import DocumentationStyleConfig
from web2doc.storage.repository import Repository

_SETTINGS_MARKERS = ("settings", "configuration", "configure")
_CONTROL_MARKERS = ("model", "profile", "mcp", "server")
_OMITTED_STANDALONE = {"confirm", "none"}
_SLUG_CHARACTERS = re.compile(r"[^a-z0-9]+")


class FeatureReferenceService:
    """Plan and compose coherent reference pages from immutable distilled evidence."""

    def __init__(
        self,
        repository: Repository,
        *,
        style: DocumentationStyleConfig | None = None,
    ) -> None:
        self.repository = repository
        self.style = style or DocumentationStyleConfig()

    async def generate(
        self,
        processing_attempt_id: str,
        composer: FeatureReferenceComposer | None = None,
    ) -> list[FeatureReferenceRevision]:
        result = self.repository.get_distillation_result(processing_attempt_id)
        manifest = self.repository.get_capture_manifest(result.manifest_id)
        project_id, role_id, role_name = self.repository.manifest_scope(result.manifest_id)
        plans = _build_plans(result, manifest, role_name, self.style)
        selected = composer or DeterministicFeatureReferenceComposer()
        revisions: list[FeatureReferenceRevision] = []
        for plan in plans:
            used_fallback = False
            try:
                async with asyncio.timeout(self.style.max_editor_seconds):
                    narrative = await selected.compose(plan)
                _validate_narrative(plan, narrative)
            except Exception:
                narrative = deterministic_feature_narrative(plan)
                _validate_narrative(plan, narrative)
                used_fallback = True
            content = _content_from_plan(plan, narrative)
            revisions.append(
                self.repository.add_feature_reference_revision(
                    project_id=project_id,
                    role_id=role_id,
                    processing_attempt_id=processing_attempt_id,
                    reference_key=_slug(content.title),
                    content=content,
                    source_kind="generated-fallback" if used_fallback else "generated",
                )
            )
        return revisions


def _build_plans(
    result: DistillationResult,
    manifest: CaptureManifest,
    role_name: str,
    style: DocumentationStyleConfig,
) -> list[FeatureReferencePlan]:
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
    observations = {observation.id: observation for observation in manifest.content.observations}
    for feature in result.features:
        for evidence in feature.evidence:
            features_by_observation[evidence.observation_id].append(feature)
    for action in manifest.content.actions:
        label = _action_label(action.payload)
        if label and action.status == "succeeded":
            actions_by_label[label.casefold()].append(action)

    plans: list[FeatureReferencePlan] = []
    consumed: set[str] = set()
    if settings_root is not None or controls:
        root_title = settings_root.title if settings_root is not None else "Settings"
        if settings_root is not None:
            consumed.add(settings_root.feature_key)
        sections: list[FeatureReferencePlanSection] = []
        for control in sorted(controls, key=lambda item: item.title.casefold()):
            consumed.add(control.feature_key)
            option_features: dict[str, DistilledFeature] = {}
            for action in actions_by_label.get(control.title.casefold(), []):
                for candidate in features_by_observation.get(action.after_observation_id or "", []):
                    if candidate.feature_key == control.feature_key:
                        continue
                    if candidate in controls or candidate is settings_root:
                        continue
                    if candidate.title.casefold() in _OMITTED_STANDALONE:
                        continue
                    option_features[candidate.title.casefold()] = candidate
            for option in option_features.values():
                consumed.add(option.feature_key)
            inventory = _control_inventory(control, observations)
            native_options = inventory.options if inventory is not None else []
            observed_options = [item.title for item in option_features.values()]
            options = _ordered_unique([*native_options, *sorted(observed_options, key=str.casefold)])
            if not style.include_available_options:
                options = []
            sections.append(
                _plan_section(
                    feature=control,
                    related=[*option_features.values()],
                    actions=actions_by_label.get(control.title.casefold(), []),
                    widget_type=(
                        inventory.role if inventory is not None else _action_role(control, actions_by_label)
                    ),
                    options=options,
                    option_coverage=(
                        OptionCoverage.COMPLETE if native_options else OptionCoverage.OBSERVED
                    ),
                )
            )
        if not sections and settings_root is not None:
            inventory = _control_inventory(settings_root, observations)
            sections.append(
                _plan_section(
                    feature=settings_root,
                    related=[],
                    actions=actions_by_label.get(settings_root.title.casefold(), []),
                    widget_type=inventory.role if inventory is not None else None,
                    options=inventory.options if inventory is not None else [],
                    option_coverage=(
                        OptionCoverage.COMPLETE
                        if inventory is not None and inventory.options
                        else OptionCoverage.OBSERVED
                    ),
                )
            )
        plans.append(
            _plan(
                title=root_title,
                purpose=f"Configure the controls available in {root_title}.",
                role_name=role_name,
                sections=sections,
                unresolved=_unresolved([settings_root, *controls] if settings_root is not None else controls),
                style=style,
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
        remaining_sections: list[FeatureReferencePlanSection] = []
        for feature in sorted(remaining, key=lambda item: item.title.casefold()):
            inventory = _control_inventory(feature, observations)
            options = inventory.options if inventory is not None and style.include_available_options else []
            remaining_sections.append(
                _plan_section(
                    feature=feature,
                    related=[],
                    actions=actions_by_label.get(feature.title.casefold(), []),
                    widget_type=(
                        inventory.role if inventory is not None else _action_role(feature, actions_by_label)
                    ),
                    options=options,
                    option_coverage=(
                        OptionCoverage.COMPLETE if options else OptionCoverage.OBSERVED
                    ),
                )
            )
        plans.append(
            _plan(
                title=interface_title,
                purpose="Explain the controls available in this part of the application.",
                role_name=role_name,
                sections=remaining_sections,
                unresolved=_unresolved(remaining),
                style=style,
            )
        )
    return plans


def _plan(
    *,
    title: str,
    purpose: str,
    role_name: str,
    sections: list[FeatureReferencePlanSection],
    unresolved: list[str],
    style: DocumentationStyleConfig,
) -> FeatureReferencePlan:
    return FeatureReferencePlan(
        title=title,
        purpose=purpose,
        audience=style.audience,
        tone=style.tone,
        detail=style.detail,
        role=role_name,
        sections=sections,
        unresolved=unresolved,
        max_inline_options=style.max_inline_options,
        show_evidence_labels=style.show_evidence_labels,
    )


def _plan_section(
    *,
    feature: DistilledFeature,
    related: list[DistilledFeature],
    actions: list[ActionReference],
    widget_type: str | None,
    options: list[str],
    option_coverage: OptionCoverage,
) -> FeatureReferencePlanSection:
    return FeatureReferencePlanSection(
        section_key=feature.feature_key,
        title=feature.title,
        widget_type=widget_type,
        fact_description=feature.description,
        options=options,
        option_coverage=option_coverage,
        evidence=_evidence_for([feature, *related], actions),
    )


def _content_from_plan(
    plan: FeatureReferencePlan,
    narrative: FeatureReferenceNarrative,
) -> FeatureReferenceContent:
    return FeatureReferenceContent(
        title=plan.title,
        summary=narrative.summary,
        audience=plan.audience,
        role=plan.role,
        sections=[
            FeatureReferenceSection(
                title=section.title,
                description=narrative.section_descriptions[index],
                widget_type=section.widget_type,
                options=section.options,
                option_coverage=section.option_coverage,
                collapse_options=len(section.options) > plan.max_inline_options,
                evidence=section.evidence,
            )
            for index, section in enumerate(plan.sections)
        ],
        unresolved=plan.unresolved,
        show_evidence_labels=plan.show_evidence_labels,
    )


def _validate_narrative(
    plan: FeatureReferencePlan,
    narrative: FeatureReferenceNarrative,
) -> None:
    if len(narrative.section_descriptions) != len(plan.sections):
        raise ValueError("feature composer changed the documentation section count")


def _control_inventory(
    feature: DistilledFeature,
    observations: Mapping[str, ObservationReference],
) -> ControlReference | None:
    candidates: list[ControlReference] = []
    for evidence in feature.evidence:
        observation = observations.get(evidence.observation_id)
        controls = observation.controls if observation is not None else []
        candidates.extend(
            control
            for control in controls
            if feature.title.casefold() in {control.name.casefold(), (control.label or "").casefold()}
        )
    if not candidates:
        return None
    options = _ordered_unique([option for candidate in candidates for option in candidate.options])
    return candidates[0].model_copy(update={"options": options})


def _action_role(
    feature: DistilledFeature,
    actions_by_label: dict[str, list[ActionReference]],
) -> str | None:
    actions = actions_by_label.get(feature.title.casefold(), [])
    if not actions:
        return None
    target = actions[0].payload.get("target")
    if isinstance(target, dict):
        role = target.get("role")
        if isinstance(role, str):
            return role
    return actions[0].kind


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


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _slug(value: str) -> str:
    slug = _SLUG_CHARACTERS.sub("-", value.casefold()).strip("-")
    return slug[:180] or "features"


def _group_features(
    result: DistillationResult,
    manifest: CaptureManifest,
    role_name: str,
) -> list[FeatureReferenceContent]:
    """Compatibility helper for deterministic tests and callers."""

    plans = _build_plans(result, manifest, role_name, DocumentationStyleConfig())
    return [_content_from_plan(plan, deterministic_feature_narrative(plan)) for plan in plans]
