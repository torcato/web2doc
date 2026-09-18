from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from web2doc.discovery.models import ModelObservation, StateIdentity
from web2doc.domain.models import DiscoveryConfig, ObservationDraft

FINGERPRINT_VERSION = "state-v2"
SECRET_PATTERN = re.compile(r"(?i)\b(password|secret|access[_ -]?token|api[_ -]?key|authorization)\b\s*[:=]\s*[^\s,;]+")
TRANSIENT_ARIA_MARKER = re.compile(r"\s*\[(?:ref=[^\]]+|cursor=[^\]]+|active)\]")


class StateCanonicalizer:
    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config
        self.volatile_patterns = tuple(re.compile(pattern) for pattern in config.volatile_patterns)

    def canonicalize(self, observation: ObservationDraft, *, role: str, scenario: str) -> StateIdentity:
        route = self.normalize_route(observation.url)
        structure = self.normalize_structure(observation.aria_snapshot)
        payload = {
            "version": FINGERPRINT_VERSION,
            "role": role,
            "scenario": scenario,
            "route": route,
            "title": self.sanitize_text(observation.title),
            "structure": structure,
            "active_dialogs": sorted(self.sanitize_text(value) for value in observation.active_dialogs),
            "selected_tabs": sorted(self.sanitize_text(value) for value in observation.selected_tabs),
            "alerts": sorted(self.sanitize_text(value) for value in observation.alerts),
            "invalid_controls": sorted(self.sanitize_text(value) for value in observation.invalid_controls),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return StateIdentity(
            fingerprint=hashlib.sha256(encoded).hexdigest(),
            algorithm_version=FINGERPRINT_VERSION,
            route=route,
            normalized_structure=structure,
        )

    def model_view(self, observation: ObservationDraft, *, max_characters: int = 16_000) -> ModelObservation:
        return ModelObservation(
            route=self.normalize_route(observation.url),
            title=self.sanitize_text(observation.title)[:500],
            structure=self.normalize_structure(observation.aria_snapshot)[:max_characters],
            active_dialogs=[self.sanitize_text(value) for value in observation.active_dialogs],
            selected_tabs=[self.sanitize_text(value) for value in observation.selected_tabs],
            alerts=[self.sanitize_text(value) for value in observation.alerts],
            invalid_controls=[self.sanitize_text(value) for value in observation.invalid_controls],
        )

    def normalize_route(self, url: str) -> str:
        parsed = urlsplit(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in self.config.ignored_query_parameters
        ]
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(sorted(query)), "")
        )

    def sanitize_text(self, value: str) -> str:
        sanitized = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", value)
        for pattern in self.volatile_patterns:
            sanitized = pattern.sub("<volatile>", sanitized)
        lines = (" ".join(line.split()) for line in sanitized.splitlines())
        return "\n".join(line for line in lines if line)

    def normalize_structure(self, value: str) -> str:
        """Remove browser-session metadata while preserving meaningful UI state."""

        return self.sanitize_text(TRANSIENT_ARIA_MARKER.sub("", value))
