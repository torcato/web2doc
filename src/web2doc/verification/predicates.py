from __future__ import annotations

from urllib.parse import urlsplit

from web2doc.domain.models import ObservationDraft
from web2doc.verification.environment import EnvironmentAdapter
from web2doc.verification.models import (
    ControlPredicate,
    EnvironmentJsonPredicate,
    FixtureReceiptDraft,
    OutcomePredicate,
    PredicateResultDraft,
    PredicateStatus,
    TitlePredicate,
    UrlPredicate,
    VisibleTextPredicate,
)


class PredicateEvaluator:
    def __init__(
        self,
        environment: EnvironmentAdapter | None,
        receipt: FixtureReceiptDraft | None,
    ) -> None:
        self.environment = environment
        self.receipt = receipt

    async def evaluate(
        self,
        predicate: OutcomePredicate,
        observation: ObservationDraft,
    ) -> PredicateResultDraft:
        if isinstance(predicate, EnvironmentJsonPredicate):
            if self.environment is None or self.receipt is None:
                return PredicateResultDraft(
                    status=PredicateStatus.INCONCLUSIVE,
                    message="trusted environment adapter is required for this predicate",
                )
            return await self.environment.check(predicate, self.receipt)
        if isinstance(predicate, VisibleTextPredicate):
            haystack = observation.aria_snapshot
            needle = predicate.text
            if not predicate.case_sensitive:
                haystack, needle = haystack.casefold(), needle.casefold()
            found = needle in haystack
            passed = found is predicate.present
            return PredicateResultDraft(
                status=PredicateStatus.PASSED if passed else PredicateStatus.FAILED,
                message=f"visible text presence expected {predicate.present}, observed {found}",
                observed=found,
            )
        if isinstance(predicate, UrlPredicate):
            if predicate.match == "exact":
                passed = observation.url == predicate.expected
            elif predicate.match == "prefix":
                passed = observation.url.startswith(predicate.expected)
            else:
                expected_path = urlsplit(predicate.expected).path if "://" in predicate.expected else predicate.expected
                passed = urlsplit(observation.url).path == expected_path
            return PredicateResultDraft(
                status=PredicateStatus.PASSED if passed else PredicateStatus.FAILED,
                message=f"URL {predicate.match} match: {passed}",
                observed=observation.url,
            )
        if isinstance(predicate, TitlePredicate):
            passed = (
                observation.title == predicate.expected
                if predicate.match == "exact"
                else predicate.expected.casefold() in observation.title.casefold()
            )
            return PredicateResultDraft(
                status=PredicateStatus.PASSED if passed else PredicateStatus.FAILED,
                message=f"title {predicate.match} match: {passed}",
                observed=observation.title,
            )
        if isinstance(predicate, ControlPredicate):
            matches = [control for control in observation.controls if _control_matches(control, predicate)]
            found = bool(matches)
            passed = found is predicate.present
            if passed and found and predicate.enabled is not None:
                passed = (not matches[0].disabled) is predicate.enabled
            return PredicateResultDraft(
                status=PredicateStatus.PASSED if passed else PredicateStatus.FAILED,
                message=f"control state matched expectation: {passed}",
                observed={"present": found, "enabled": not matches[0].disabled if matches else None},
            )
        raise TypeError(f"unsupported predicate: {type(predicate).__name__}")


def _control_matches(control: object, predicate: ControlPredicate) -> bool:
    target = predicate.target
    if target.test_id:
        return getattr(control, "test_id", None) == target.test_id
    if target.label:
        return getattr(control, "label", None) == target.label
    return getattr(control, "role", None) == target.role and getattr(control, "name", None) == target.name
