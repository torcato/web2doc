from __future__ import annotations

import hashlib
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path

from web2doc.domain.models import ArtifactDraft, Sensitivity, new_id

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class ArtifactIntegrityError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root.resolve()

    def write(
        self,
        *,
        run_id: str,
        category: str,
        content: bytes,
        suffix: str,
        media_type: str,
        sensitivity: Sensitivity,
    ) -> ArtifactDraft:
        for value in (run_id, category):
            if not SAFE_SEGMENT.fullmatch(value):
                raise ValueError(f"unsafe artifact path segment: {value!r}")
        if not re.fullmatch(r"\.[A-Za-z0-9]+", suffix):
            raise ValueError(f"unsafe artifact suffix: {suffix!r}")

        artifact_id = new_id()
        relative_dir = Path("artifacts") / run_id / category
        directory = self.runtime_root / relative_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{artifact_id}{suffix}"
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise

        return ArtifactDraft(
            id=artifact_id,
            relative_path=target.relative_to(self.runtime_root).as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type,
            sensitivity=sensitivity,
            size_bytes=len(content),
        )

    def read_verified(self, artifact: ArtifactDraft) -> bytes:
        path = (self.runtime_root / artifact.relative_path).resolve()
        if not path.is_relative_to(self.runtime_root):
            raise ArtifactIntegrityError("artifact path escapes runtime root")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ArtifactIntegrityError(f"artifact hash mismatch: {artifact.id}")
        return content
