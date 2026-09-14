from __future__ import annotations

from pathlib import Path

import pytest

from web2doc.domain.models import Sensitivity
from web2doc.storage.artifacts import ArtifactIntegrityError, ArtifactStore


def test_artifact_write_is_hash_verified(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = store.write(
        run_id="run-1",
        category="screenshots",
        content=b"image bytes",
        suffix=".png",
        media_type="image/png",
        sensitivity=Sensitivity.PRIVATE,
    )

    assert store.read_verified(artifact) == b"image bytes"
    assert not list((tmp_path / "artifacts/run-1/screenshots").glob(".pending-*"))


def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = store.write(
        run_id="run-1",
        category="observations",
        content=b"original",
        suffix=".yaml",
        media_type="application/yaml",
        sensitivity=Sensitivity.PRIVATE,
    )
    (tmp_path / artifact.relative_path).write_bytes(b"changed")

    with pytest.raises(ArtifactIntegrityError):
        store.read_verified(artifact)


def test_artifact_path_segments_are_restricted(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path).write(
            run_id="../escape",
            category="screenshots",
            content=b"x",
            suffix=".png",
            media_type="image/png",
            sensitivity=Sensitivity.PUBLIC,
        )
