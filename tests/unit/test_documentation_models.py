from __future__ import annotations

import json

import pytest
from pydantic_ai.models.test import TestModel

from web2doc.documentation.composer import NarrativeModelOutput, PydanticAIDocumentComposer
from web2doc.documentation.models import (
    DocumentClaim,
    DocumentNarrative,
    EvidenceReference,
    GenerationContext,
    ProvenanceKind,
)
from web2doc.documentation.render import MarkdownRenderer, markdown_escape


def test_document_provider_schema_avoids_expensive_serving_constraints() -> None:
    schema = json.dumps(NarrativeModelOutput.model_json_schema())

    assert "maxItems" not in schema
    assert "maxLength" not in schema
    assert "minimum" not in schema
    assert "maximum" not in schema


def generation_context() -> GenerationContext:
    evidence = EvidenceReference(
        verification_id="verification",
        observation_id="observation",
        screenshot_artifact_id="screenshot",
    )
    return GenerationContext(
        workflow_revision_id="workflow",
        verification_id="verification",
        workflow_title="Create item",
        goal="Create an item",
        role="admin",
        prerequisite_descriptions=[],
        step_descriptions=["Enter a name"],
        step_expected_descriptions=["The name is visible"],
        outcome_description="The item is persisted",
        unresolved_questions=[],
        evidence_by_step={1: evidence},
        prerequisite_evidence=evidence,
        outcome_evidence=evidence,
    )


@pytest.mark.asyncio
async def test_pydantic_ai_composer_returns_structured_narrative() -> None:
    model = TestModel(
        custom_output_args={
            "title": "Create an item",
            "summary": "Create a record safely.",
            "goal": "Create an item",
            "prerequisites": [],
            "steps": [{"sequence": 1, "instruction": "Enter a name", "expected_result": "The name is visible"}],
            "outcome": "The item is persisted",
            "troubleshooting": [],
        }
    )

    result = await PydanticAIDocumentComposer(model).compose(generation_context())

    assert isinstance(result, DocumentNarrative)
    assert result.steps[0].sequence == 1


def test_markdown_escape_neutralizes_html_and_links() -> None:
    escaped = markdown_escape("<script>[click](javascript:alert(1))</script>")
    assert "<script>" not in escaped
    assert "\\[click\\]\\(javascript:alert\\(1\\)\\)" in escaped

    with pytest.raises(ValueError, match="prefix"):
        MarkdownRenderer().render(object(), evidence_prefix="../../")  # type: ignore[arg-type]


def test_claim_provenance_requires_the_correct_source_kind() -> None:
    with pytest.raises(ValueError, match="verified claims require evidence"):
        DocumentClaim(text="Unsupported", provenance=ProvenanceKind.VERIFIED)
    with pytest.raises(ValueError, match="owner source"):
        DocumentClaim(text="Unattributed", provenance=ProvenanceKind.OWNER)
