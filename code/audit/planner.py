"""Turn per-case record facts into the graded step list.

The planner is deliberately tiny and deterministic: policy decides the
treatment, this module orders the steps exactly as the specification requires
(phase, then operation, then system, then resource) and numbers them from 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .evidence import Observation
from .policy import OPERATION_ORDER, PHASE_ORDER, STATE_FOR_OPERATION, Policy


@dataclass(frozen=True)
class Fact:
    """A record that must appear in the audit plan for one case."""

    system_id: str
    resource_id: str
    category: str
    state: str
    observed_at: datetime
    evidence_id: str

    @classmethod
    def from_observation(cls, observation: Observation) -> "Fact":
        return cls(
            system_id=observation.system_id,
            resource_id=observation.resource_id,
            category=observation.category,
            state=observation.state,
            observed_at=observation.observed_at,
            evidence_id=observation.evidence_id,
        )


def make_step(phase: str, fact: Fact, operation: str, evidence_id: str, number: int) -> dict[str, Any]:
    return {
        "step_no": number,
        "phase": phase,
        "system_id": fact.system_id,
        "resource_id": fact.resource_id,
        "operation": operation,
        "state": STATE_FOR_OPERATION[operation],
        "evidence_id": evidence_id,
    }


def plan_case(facts: Iterable[Fact], policy: Policy) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(deletion_status, steps)`` for one case."""

    facts = list(facts)
    findings: list[tuple[Fact, str]] = []
    remediations: list[tuple[Fact, str]] = []
    verifications: list[tuple[Fact, str]] = []

    for fact in facts:
        treatment = policy.evaluate(fact.category, fact.state)
        if treatment.violation:
            assert treatment.finding and treatment.remediation
            findings.append((fact, treatment.finding))
            remediations.append((fact, treatment.remediation))
            verifications.append((fact, treatment.verification))
        else:
            verifications.append((fact, treatment.verification))

    status = "INCOMPLETE" if findings else "COMPLETE"

    steps: list[dict[str, Any]] = []
    if status == "INCOMPLETE":
        # Findings cite the evidence that proves the violation; remediation and
        # post-remediation verification describe future work and cite nothing.
        for fact, operation in _dedupe(findings):
            steps.append(make_step("FINDING", fact, operation, fact.evidence_id, 0))
        for fact, operation in _dedupe(remediations):
            steps.append(make_step("REMEDIATION", fact, operation, "", 0))
        for fact, operation in _dedupe(verifications):
            steps.append(make_step("VERIFICATION", fact, operation, "", 0))
    else:
        for fact, operation in _dedupe(verifications):
            steps.append(make_step("VERIFICATION", fact, operation, fact.evidence_id, 0))

    steps.sort(
        key=lambda step: (
            PHASE_ORDER[step["phase"]],
            OPERATION_ORDER[step["operation"]],
            step["system_id"],
            step["resource_id"],
        )
    )
    for number, step in enumerate(steps, start=1):
        step["step_no"] = number
    return status, steps


def _dedupe(pairs: Iterable[tuple[Fact, str]]) -> list[tuple[Fact, str]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[tuple[Fact, str]] = []
    for fact, operation in pairs:
        key = (fact.system_id, fact.resource_id, operation)
        if key in seen:
            continue
        seen.add(key)
        unique.append((fact, operation))
    return unique
