from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from web2doc.documentation.models import DocumentRevision, EvidenceReference
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
        document = self.repository.get_document_revision(document_revision_id)
        _require_safe(document.id)
        output = self.project_root / ".web2doc" / "review" / document.id
        if output.exists():
            raise FileExistsError(f"review bundle already exists: {output}")
        output.mkdir(parents=True)
        self._write_document_files(output, document, evidence_prefix="")
        (output / "document.json").write_text(document.content.model_dump_json(indent=2), encoding="utf-8")
        (output / "REVIEW.md").write_text(
            "\n".join(
                [
                    "# Review record",
                    "",
                    f"- Document revision: `{document.id}`",
                    f"- Workflow revision: `{document.workflow_revision_id}`",
                    f"- Verification: `{document.verification_id}`",
                    "",
                    "Review factual support as well as readability. Evidence existence alone does not prove the claim.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return output

    def export_approved(self, output_dir: Path) -> Path:
        target = output_dir.resolve()
        if target.exists():
            raise FileExistsError(f"export path already exists: {target}")
        documents = self.repository.approved_document_revisions(self.project_id)
        if not documents:
            raise ValueError("no latest document revisions have an approving review decision")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".web2doc-export-", dir=target.parent))
        try:
            docs_root = temporary / "docs"
            guides = docs_root / "guides"
            guides.mkdir(parents=True)
            navigation: list[dict[str, str]] = []
            for document in documents:
                workflow = self.repository.get_workflow_revision(document.workflow_revision_id)
                key = workflow.definition.workflow_key
                _require_safe(key)
                guide = guides / f"{key}.md"
                guide.write_text(
                    self.renderer.render(document.content, evidence_prefix="../"), encoding="utf-8"
                )
                self._write_evidence(docs_root, document)
                navigation.append({document.content.title: f"guides/{key}.md"})
            index_lines = ["# User documentation", ""]
            index_lines.extend(
                f"- [{markdown_escape(title)}]({path})"
                for item in navigation
                for title, path in item.items()
            )
            (docs_root / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
            config = {
                "site_name": "User documentation",
                "docs_dir": "docs",
                "site_dir": "site",
                "strict": True,
                "nav": [{"Home": "index.md"}, {"Guides": navigation}],
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
            [document.id for document in documents],
        )
        return target

    def _write_document_files(
        self, root: Path, document: DocumentRevision, *, evidence_prefix: str
    ) -> None:
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
