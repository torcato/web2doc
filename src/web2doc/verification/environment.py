from __future__ import annotations

from typing import Protocol
from urllib.parse import urljoin

import httpx
from pydantic import JsonValue, TypeAdapter

from web2doc.config import origin_for
from web2doc.verification.models import (
    EnvironmentJsonPredicate,
    FixtureReceiptDraft,
    PredicateResultDraft,
    PredicateStatus,
)


class EnvironmentAdapter(Protocol):
    name: str

    async def prepare(self, scenario: str, inputs: dict[str, str]) -> FixtureReceiptDraft: ...

    async def check(
        self,
        predicate: EnvironmentJsonPredicate,
        receipt: FixtureReceiptDraft,
    ) -> PredicateResultDraft: ...

    async def reset(self, receipt: FixtureReceiptDraft) -> None: ...


class HttpJsonEnvironmentAdapter:
    name = "trusted-http-json"

    def __init__(
        self,
        *,
        base_url: str,
        allowed_origins: set[str],
        reset_path: str = "/__reset",
        prepare_path: str = "/__prepare",
        state_path: str = "/__state",
        timeout_seconds: float = 10,
    ) -> None:
        origin = origin_for(base_url)
        if origin not in {origin_for(value) for value in allowed_origins}:
            raise ValueError("fixture API origin must be in the project navigation allowlist")
        for path in (reset_path, prepare_path, state_path):
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError("fixture API paths must be origin-relative")
        self.base_url = base_url.rstrip("/") + "/"
        self.reset_url = urljoin(self.base_url, reset_path.lstrip("/"))
        self.prepare_url = urljoin(self.base_url, prepare_path.lstrip("/"))
        self.state_url = urljoin(self.base_url, state_path.lstrip("/"))
        self.timeout_seconds = timeout_seconds

    async def prepare(self, scenario: str, inputs: dict[str, str]) -> FixtureReceiptDraft:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            reset_response = await client.post(self.reset_url)
            reset_response.raise_for_status()
            response = await client.post(self.prepare_url, json={"scenario": scenario, "inputs": inputs})
            response.raise_for_status()
            payload = response.json()
        return FixtureReceiptDraft(
            adapter_name=self.name,
            scenario=scenario,
            application_version=str(payload.get("application_version", "unknown")),
            payload=payload,
        )

    async def check(
        self,
        predicate: EnvironmentJsonPredicate,
        receipt: FixtureReceiptDraft,
    ) -> PredicateResultDraft:
        del receipt
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.state_url)
                response.raise_for_status()
                state = response.json()
            observed: JsonValue = TypeAdapter(JsonValue).validate_python(_resolve_path(state, predicate.path))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return PredicateResultDraft(
                status=PredicateStatus.INCONCLUSIVE,
                message=f"trusted environment check unavailable: {exc}",
            )
        matches = _compare(observed, predicate.expected, predicate.operator)
        return PredicateResultDraft(
            status=PredicateStatus.PASSED if matches else PredicateStatus.FAILED,
            message=f"environment value at {predicate.path!r} {predicate.operator} expected value: {matches}",
            observed=observed,
        )

    async def reset(self, receipt: FixtureReceiptDraft) -> None:
        del receipt
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.reset_url)
            response.raise_for_status()


def _resolve_path(value: object, path: str) -> object:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _compare(observed: object, expected: object, operator: str) -> bool:
    if operator == "equals":
        return observed == expected
    contains = (
        (isinstance(observed, list) and expected in observed)
        or (isinstance(observed, str) and isinstance(expected, str) and expected in observed)
        or (isinstance(observed, dict) and isinstance(expected, str) and expected in observed)
    )
    if operator == "contains":
        return contains
    if operator == "not_contains":
        return not contains
    raise ValueError(f"unknown environment predicate operator: {operator}")
