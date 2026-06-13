"""The rules engine.

Deterministic, no machine learning, no LLM. It reads the policy file and
checks a loan's numbers against each rule. The same inputs always produce the
same verdict, and every verdict traces to a line a human can read in
policy.yaml. That is deliberate: this is the part of the platform a regulator
would inspect, so the path from facts to decision stays plain arithmetic.

The engine does not know anything about specific rules. It applies whatever
the policy file declares, which is what lets compliance change policy without
touching this code.
"""
from __future__ import annotations

import functools
import pathlib
from dataclasses import dataclass, field
from typing import Any

import yaml

POLICY_FILE = pathlib.Path(__file__).parent / "policy.yaml"

# How each operator in the policy maps to an actual comparison.
_OPERATORS = {
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "eq": lambda value, threshold: value == threshold,
}


@dataclass
class Exception_:
    """One fired rule, with everything needed to explain and route it."""
    code: str
    title: str
    section: str
    severity: str
    observed: float
    threshold: float
    waiver_authority: str          # an authority level, or "unwaivable"
    routes_to: str | None = None   # e.g. "compliance" for the bright-line rules


@dataclass
class Verdict:
    loan_id: str
    exceptions: list[Exception_] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.exceptions

    @property
    def routes_to_compliance(self) -> bool:
        return any(e.routes_to == "compliance" for e in self.exceptions)

    @property
    def minimum_authority(self) -> str | None:
        """Highest authority rung any fired exception demands. None if clean.
        'unwaivable' findings don't set an authority — they route to
        compliance instead, so they're excluded here."""
        ladder = _policy()["authority_levels"]
        needed = [e.waiver_authority for e in self.exceptions
                  if e.waiver_authority in ladder]
        if not needed:
            return None
        return max(needed, key=ladder.index)

    @property
    def routing(self) -> str:
        """The single headline outcome, mirroring the stamp the desk shows."""
        if self.routes_to_compliance:
            return "compliance_review"
        if self.is_clean:
            return "clean"
        return "exception_review"


@functools.lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    with open(POLICY_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def evaluate(loan: dict[str, Any]) -> Verdict:
    """Run every policy rule against one loan's facts and collect what fires.

    `loan` is a mapping with the fields the rules reference (dscr, leverage,
    utilization, income_discrepancy_pct). A missing or null field means the
    rule simply can't fire — we don't guess.
    """
    policy = _policy()
    verdict = Verdict(loan_id=loan.get("loan_id", "<unknown>"))

    for rule in policy["rules"]:
        value = loan.get(rule["field"])
        if value is None:
            continue
        value = float(value)
        compare = _OPERATORS[rule["operator"]]
        if compare(value, rule["threshold"]):
            verdict.exceptions.append(Exception_(
                code=rule["code"],
                title=rule["title"],
                section=rule["section"],
                severity=rule["severity"],
                observed=value,
                threshold=rule["threshold"],
                waiver_authority=rule["waiver_authority"],
                routes_to=rule.get("routes_to"),
            ))

    # Stable ordering: severest first, so the most serious finding leads.
    rank = {"severe": 0, "high": 1, "medium": 2, "low": 3}
    verdict.exceptions.sort(key=lambda e: rank.get(e.severity, 9))
    return verdict


def codes(verdict: Verdict) -> list[str]:
    """Just the fired exception codes — handy for grading against ground truth."""
    return sorted(e.code for e in verdict.exceptions)
