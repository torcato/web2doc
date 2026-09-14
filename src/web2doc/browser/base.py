from __future__ import annotations

from typing import Protocol, TypeVar

from web2doc.domain.models import Action, ExecutionResult, ObservationDraft

SessionT = TypeVar("SessionT")


class BrowserAdapter(Protocol[SessionT]):
    async def start(self, *, run_id: str, headed: bool = False) -> SessionT: ...

    async def observe(self, session: SessionT) -> ObservationDraft: ...

    async def execute(self, session: SessionT, action: Action) -> ExecutionResult: ...

    async def close(self, session: SessionT) -> None: ...
