from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from web2doc.documentation.models import (
    DocumentRevision,
    EvidenceReference,
    FeatureEvidenceReference,
    FeatureReferenceRevision,
)
from web2doc.documentation.render import MarkdownRenderer, markdown_escape
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.repository import Repository

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class DocumentationPublisher:
    def __init__(
        self,
        *,
        repository: Repository,
        artifacts: ArtifactStore,
        project_id: str,
        project_root: Path,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.project_id = project_id
        self.project_root = project_root.resolve()
        self.renderer = MarkdownRenderer()

    def create_review_bundle(self, document_revision_id: str) -> Path:
        try:
            document = self.repository.get_document_revision(document_revision_id)
        except KeyError:
            return self._create_feature_review_bundle(document_revision_id)
        self.repository.verification_evidence_context(
            self.project_id, document.workflow_revision_id, document.verification_id
        )
        _require_safe(document.id)
        review_root = self.project_root / ".web2doc" / "review"
        output = review_root / document.id
        if output.exists():
            raise FileExistsError(f"review bundle already exists: {output}")
        review_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".bundle-", dir=review_root))
        try:
            self._write_document_files(temporary, document, evidence_prefix="")
            (temporary / "document.json").write_text(document.content.model_dump_json(indent=2), encoding="utf-8")
            (temporary / "REVIEW.md").write_text(
                "\n".join(
                    [
                        "# Review record",
                        "",
                        f"- Document revision: `{document.id}`",
                        f"- Workflow revision: `{document.workflow_revision_id}`",
                        f"- Verification: `{document.verification_id}`",
                        "",
                        "Review factual support as well as readability. "
                        "Evidence existence alone does not prove the claim.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            os.replace(temporary, output)
        except BaseException:
            _remove_temporary_tree(temporary)
            raise
        return output

    def _create_feature_review_bundle(self, revision_id: str) -> Path:
        document = self.repository.get_feature_reference_revision(revision_id)
        if document.project_id != self.project_id:
            raise KeyError(f"feature reference revision not found in project: {revision_id}")
        _require_safe(document.id)
        review_root = self.project_root / ".web2doc" / "review"
        output = review_root / document.id
        if output.exists():
            raise FileExistsError(f"review bundle already exists: {output}")
        review_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".bundle-", dir=review_root))
        try:
            (temporary / "reference.md").write_text(
                self.renderer.render_reference(document.content), encoding="utf-8"
            )
            self._write_feature_evidence(temporary, document)
            (temporary / "document.json").write_text(
                document.content.model_dump_json(indent=2), encoding="utf-8"
            )
            (temporary / "REVIEW.md").write_text(
                "\n".join(
                    [
                        "# Feature-reference review",
                        "",
                        f"- Document revision: `{document.id}`",
                        f"- Distillation attempt: `{document.processing_attempt_id}`",
                        "",
                        "Approve only observed or demonstrated interface claims. "
                        "This reference does not assert that unverified changes were saved.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            os.replace(temporary, output)
        except BaseException:
            _remove_temporary_tree(temporary)
            raise
        return output

    def export_approved(self, output_dir: Path) -> Path:
        target = output_dir.resolve()
        if target.exists():
            raise FileExistsError(f"export path already exists: {target}")
        documents = self.repository.approved_document_revisions(self.project_id)
        references = self.repository.approved_feature_reference_revisions(self.project_id)
        if not documents and not references:
            raise ValueError("no latest document revisions have an approving review decision")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".web2doc-export-", dir=target.parent))
        try:
            docs_root = temporary / "docs"
            guides = docs_root / "guides"
            features = docs_root / "features"
            docs_root.mkdir(parents=True)
            navigation: list[dict[str, str]] = []
            if documents:
                guides.mkdir()
            for document in documents:
                workflow = self.repository.get_workflow_revision(document.workflow_revision_id)
                key = workflow.definition.workflow_key
                _require_safe(key)
                guide = guides / f"{key}.md"
                guide.write_text(self.renderer.render(document.content, evidence_prefix="../"), encoding="utf-8")
                self._write_evidence(docs_root, document)
                navigation.append({document.content.title: f"guides/{key}.md"})
            feature_navigation: list[dict[str, str]] = []
            if references:
                features.mkdir()
            for reference in references:
                _require_safe(reference.reference_key)
                path = features / f"{reference.reference_key}.md"
                path.write_text(
                    self.renderer.render_reference(reference.content, evidence_prefix="../"),
                    encoding="utf-8",
                )
                self._write_feature_evidence(docs_root, reference)
                feature_navigation.append(
                    {reference.content.title: f"features/{reference.reference_key}.md"}
                )
            index_lines = ["# User documentation", ""]
            index_lines.extend(
                f"- [{markdown_escape(title)}]({path})" for item in navigation for title, path in item.items()
            )
            index_lines.extend(
                f"- [{markdown_escape(title)}]({path})"
                for item in feature_navigation
                for title, path in item.items()
            )
            (docs_root / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
            site_navigation: list[dict[str, object]] = [{"Home": "index.md"}]
            if navigation:
                site_navigation.append({"Guides": navigation})
            if feature_navigation:
                site_navigation.append({"Feature reference": feature_navigation})
            config = {
                "site_name": "User documentation",
                "docs_dir": "docs",
                "site_dir": "site",
                "strict": True,
                "nav": site_navigation,
            }
            (temporary / "mkdocs.yml").write_text(_yaml(config), encoding="utf-8")
            subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "--strict", "--config-file", str(temporary / "mkdocs.yml")],
                cwd=temporary,
                check=True,
                capture_output=True,
                text=True,
            )
            os.replace(temporary, target)
        except BaseException:
            _remove_temporary_tree(temporary)
            raise
        self.repository.add_export(
            self.project_id,
            str(target),
            [document.id for document in documents] + [reference.id for reference in references],
        )
        return target

    def write_coverage_report(self) -> tuple[Path, Path]:
        review_root = self.project_root / ".web2doc" / "review"
        review_root.mkdir(parents=True, exist_ok=True)
        report = self.repository.documentation_coverage(self.project_id)
        json_path = review_root / "coverage.json"
        markdown_path = review_root / "coverage.md"
        json_temporary = review_root / ".coverage.json.pending"
        markdown_temporary = review_root / ".coverage.md.pending"
        entries = report["workflows"]
        lines = [
            "# Documentation coverage",
            "",
            "| Workflow | Verification | Document | Review | Exportable | Unresolved |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for entry in entries:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(entry["workflow_key"]),
                        markdown_escape(entry["verification"]),
                        markdown_escape(entry["document_revision_id"] or "missing"),
                        markdown_escape(entry["review"]),
                        "yes" if entry["eligible_for_export"] else "no",
                        markdown_escape("; ".join(entry["unresolved_questions"]) or "none"),
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Discovered features",
                "",
                "| Feature | Verified workflow |",
                "| --- | --- |",
            ]
        )
        for feature in report["features"]:
            lines.append(f"| {markdown_escape(feature['title'])} | {'yes' if feature['verified'] else 'no'} |")
        lines.extend(
            [
                "",
                "## Feature references",
                "",
                "| Reference | Evidence | Review | Exportable | Unresolved |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for reference in report["feature_references"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(reference["title"]),
                        markdown_escape(", ".join(reference["evidence_levels"])),
                        markdown_escape(reference["review"]),
                        "yes" if reference["eligible_for_export"] else "no",
                        markdown_escape("; ".join(reference["unresolved"]) or "none"),
                    ]
                )
                + " |"
            )
        json_temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        markdown_temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(json_temporary, json_path)
        os.replace(markdown_temporary, markdown_path)
        return json_path, markdown_path

    def _write_document_files(self, root: Path, document: DocumentRevision, *, evidence_prefix: str) -> None:
        (root / "guide.md").write_text(
            self.renderer.render(document.content, evidence_prefix=evidence_prefix), encoding="utf-8"
        )
        self._write_evidence(root, document)

    def _write_evidence(self, root: Path, document: DocumentRevision) -> None:
        evidence_dir = root / "evidence"
        asset_dir = root / "assets"
        evidence_dir.mkdir(exist_ok=True)
        asset_dir.mkdir(exist_ok=True)
        references = _references(document)
        for reference in references:
            _require_safe(reference.observation_id)
            _require_safe(reference.screenshot_artifact_id)
            artifact = self.repository.artifact_draft(reference.screenshot_artifact_id)
            if artifact.media_type != "image/png":
                raise ValueError("document evidence screenshot is not a PNG artifact")
            content = self.artifacts.read_verified(artifact)
            (asset_dir / f"{artifact.id}.png").write_bytes(content)
            (evidence_dir / f"{reference.observation_id}.md").write_text(
                "\n".join(
                    [
                        "# Evidence",
                        "",
                        f"- Verification: `{reference.verification_id}`",
                        f"- Observation: `{reference.observation_id}`",
                        "",
                        f"![Captured browser state](../assets/{reference.screenshot_artifact_id}.png)",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

    def _write_feature_evidence(self, root: Path, document: FeatureReferenceRevision) -> None:
        evidence_dir = root / "evidence"
        asset_dir = root / "assets"
        evidence_dir.mkdir(exist_ok=True)
        asset_dir.mkdir(exist_ok=True)
        for reference in _feature_references(document):
            _require_safe(reference.observation_id)
            _require_safe(reference.screenshot_artifact_id)
            artifact = self.repository.artifact_draft(reference.screenshot_artifact_id)
            if artifact.media_type != "image/png":
                raise ValueError("feature-reference screenshot is not a PNG artifact")
            content = self.artifacts.read_verified(artifact)
            (asset_dir / f"{artifact.id}.png").write_bytes(content)
            (evidence_dir / f"{reference.observation_id}.md").write_text(
                "\n".join(
                    [
                        "# Captured interface evidence",
                        "",
                        f"- Evidence level: `{reference.support.value}`",
                        f"- Observation: `{reference.observation_id}`",
                        "",
                        f"![Captured browser state](../assets/{reference.screenshot_artifact_id}.png)",
                        "",
                    ]
                ),
                encoding="utf-8",
            )


def _references(document: DocumentRevision) -> list[EvidenceReference]:
    claims = [document.content.summary, document.content.goal, document.content.outcome]
    claims.extend(document.content.prerequisites)
    for step in document.content.steps:
        claims.append(step.instruction)
        if step.expected_result is not None:
            claims.append(step.expected_result)
    unique: dict[tuple[str, str], EvidenceReference] = {}
    for claim in claims:
        for reference in claim.evidence:
            unique[(reference.observation_id, reference.screenshot_artifact_id)] = reference
    return list(unique.values())


def _feature_references(document: FeatureReferenceRevision) -> list[FeatureEvidenceReference]:
    unique: dict[tuple[str, str], FeatureEvidenceReference] = {}
    for section in document.content.sections:
        for reference in section.evidence:
            unique[(reference.observation_id, reference.screenshot_artifact_id)] = reference
    return list(unique.values())


def _require_safe(value: str) -> None:
    if _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"unsafe generated path identifier: {value!r}")


def _yaml(config: dict[str, object]) -> str:
    # Values are application-owned; JSON is valid YAML and avoids a second serializer dependency.
    return json.dumps(config, indent=2)


def _remove_temporary_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    root.rmdir()
