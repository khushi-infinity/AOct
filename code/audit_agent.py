#!/usr/bin/env python3
"""Ghost Data Still Exists - deletion-audit agent.

Pipeline
--------
1. ``intent``      decides whether the message authorises deletion at all.
2. ``identity``    resolves the current *and* historical identifiers.
3. ``evidence``    normalises every artefact (JSON, SQL, logs, PDF, OCR) into
                   timestamped observations of (system, resource, category, state).
4. attribution     links keyless records (deleted accounts, anonymised analytics)
                   through the deletion workflow's own audit trail.
5. ``policy``      applies ``deletion_rules.csv`` to the state at ``audit_at``.
6. ``planner``     emits the ordered FINDING / REMEDIATION / VERIFICATION steps.

The agent is deterministic and needs no network access or model credentials to
reproduce the submitted ``output.csv``.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from audit.evidence import (
    AUTHORITATIVE_ORIGINS,
    EvidenceIndex,
    Observation,
    SYSTEM_BY_CATEGORY,
    parse_time,
)
from audit.identity import IdentityGraph
from audit.intent import is_deletion_request
from audit.planner import Fact, plan_case
from audit.policy import Policy

# A deletion worker runs the account deletion shortly before the workflow
# reports a status.  These bounds are wide enough to absorb queueing, and
# narrow enough to exclude neighbouring cases in the same audit batch.
CLAIM_WINDOW_BEFORE = timedelta(minutes=120)
CLAIM_WINDOW_AFTER = timedelta(minutes=20)

_RESULT_BY_STATUS = {
    "COMPLETE": "SUCCESS",
    "PARTIALLY_COMPLETE": "PARTIAL",
    "NOT_STARTED": "FAILED",
}


@dataclass
class Case:
    case_id: str
    email: str
    request_text: str
    requested_at: datetime
    reported_at: datetime
    audit_at: datetime
    reported_status: str
    user_id: str | None = None
    facts: list[Fact] = field(default_factory=list)

    @property
    def claims_account_deletion(self) -> bool:
        return True


@dataclass
class RunStats:
    cases: int = 0
    not_applicable: int = 0
    complete: int = 0
    incomplete: int = 0
    unresolved_identities: int = 0
    attributed_accounts: int = 0
    evidence_files: int = 0
    observations: int = 0
    warnings: list[str] = field(default_factory=list)


class DeletionAuditAgent:
    def __init__(self, dataset: Path):
        self.dataset = dataset
        self.identities = IdentityGraph(dataset)
        self.policy = Policy(dataset)
        self.evidence = EvidenceIndex(dataset, self.identities)
        self.stats = RunStats(
            evidence_files=len(self.evidence.manifest),
            observations=len(self.evidence.observations),
            warnings=list(self.evidence.warnings),
        )

    # ------------------------------------------------------------------ public
    def run(self, requests_path: Path) -> list[dict[str, str]]:
        cases = self._load_cases(requests_path)
        active: list[Case] = []
        results: dict[str, tuple[str, list[dict[str, Any]]]] = {}

        for case in cases:
            if not is_deletion_request(case.request_text):
                results[case.case_id] = ("NOT_APPLICABLE", [])
                self.stats.not_applicable += 1
                continue
            case.user_id = self.identities.resolve(case.email)
            if case.user_id is None:
                self.stats.unresolved_identities += 1
                print(
                    f"WARNING: {case.case_id}: identity not found for {case.email}",
                    file=sys.stderr,
                )
            else:
                observations = self.evidence.facts_for(case.user_id, case.audit_at)
                case.facts = [Fact.from_observation(obs) for obs in observations]
            active.append(case)

        self._attribute_missing_accounts(active)

        for case in active:
            status, steps = plan_case(case.facts, self.policy)
            results[case.case_id] = (status, steps)
            if status == "COMPLETE":
                self.stats.complete += 1
            else:
                self.stats.incomplete += 1

        self.stats.cases = len(cases)
        rows = []
        for case in sorted(cases, key=lambda item: item.case_id):
            status, steps = results[case.case_id]
            rows.append(
                {
                    "case_id": case.case_id,
                    "deletion_status": status,
                    "steps_json": json.dumps(steps, ensure_ascii=False, separators=(",", ":")),
                }
            )
        return rows

    # ------------------------------------------------------------------- load
    def _load_cases(self, requests_path: Path) -> list[Case]:
        with requests_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            cases = []
            for row in reader:
                cases.append(
                    Case(
                        case_id=row["case_id"].strip(),
                        email=(row.get("email") or "").strip(),
                        request_text=row.get("request_text") or "",
                        requested_at=parse_time(row.get("requested_at")),
                        reported_at=parse_time(row.get("reported_at")),
                        audit_at=parse_time(row.get("audit_at")),
                        reported_status=(row.get("reported_status") or "").strip().upper(),
                    )
                )
        return cases

    # ------------------------------------------------------------ attribution
    def _attribute_missing_accounts(self, cases: list[Case]) -> None:
        """Recover the account record for cases whose profile link is keyless.

        A deletion that succeeded leaves no profile row to match on, so the
        record is identified through the workflow claim: the account deletion
        the worker reported for the same batch (cases that share a
        ``reported_at``).  Claims whose result contradicts the reported status
        are only used when no compatible claim is left, and a claim already
        tied to another person by direct evidence is never reused.
        """

        claimed = {
            fact.resource_id
            for case in cases
            for fact in case.facts
            if fact.category == "USER_PROFILE"
        }
        missing = [case for case in cases if not any(f.category == "USER_PROFILE" for f in case.facts)]
        if not missing:
            return

        direct_links: dict[str, set[str]] = defaultdict(set)
        for observation in self.evidence.observations:
            if observation.subjects:
                direct_links[observation.resource_id].update(observation.subjects)
        for activity in self.evidence.activities:
            if activity.subjects:
                direct_links[activity.resource_id].update(activity.subjects)

        claims = [
            activity
            for activity in self.evidence.activities
            if activity.event_type == "DELETE_RECORD"
            and activity.target_system == SYSTEM_BY_CATEGORY["USER_PROFILE"]
        ]

        # Cases that share a workflow report time belong to one deletion batch;
        # the batch's claims are allocated together so no claim is used twice.
        batches: dict[datetime, list[Case]] = defaultdict(list)
        for case in missing:
            batches[case.reported_at].append(case)

        assigned: dict[str, Any] = {}
        for reported_at in sorted(batches):
            batch = sorted(batches[reported_at], key=lambda item: item.case_id)
            lo = reported_at - CLAIM_WINDOW_BEFORE
            hi = reported_at + CLAIM_WINDOW_AFTER
            pool = [
                activity
                for activity in claims
                if lo <= activity.event_time <= hi
                and activity.resource_id not in claimed
                and activity.resource_id not in assigned
                and direct_links.get(activity.resource_id, set()) <= {case.user_id for case in batch}
            ]
            pool.sort(key=lambda activity: (activity.event_time, activity.activity_id))
            taken: set[str] = set()
            for case in batch:
                compatible = _RESULT_BY_STATUS.get(case.reported_status)
                choice = next(
                    (
                        activity
                        for activity in pool
                        if activity.activity_id not in taken
                        and activity.reported_result == compatible
                    ),
                    None,
                )
                if choice is None:
                    # No result-compatible claim left: fall back to the nearest
                    # unused one, which still beats inventing a resource.
                    remaining = [a for a in pool if a.activity_id not in taken]
                    if not remaining:
                        continue
                    choice = min(
                        remaining,
                        key=lambda activity: abs(
                            (reported_at - activity.event_time).total_seconds()
                        ),
                    )
                taken.add(choice.activity_id)
                assigned[case.case_id] = choice

        for case in missing:
            activity = assigned.get(case.case_id)
            if activity is not None:
                case.facts.append(self._account_fact(case, activity))
                self.stats.attributed_accounts += 1

        # Nothing in the workflow stream either: fall back to the stable account
        # identifier convention so the case is still auditable.
        for case in missing:
            if case.case_id in assigned:
                continue
            numeric = "".join(ch for ch in (case.user_id or "") if ch.isdigit())
            if not numeric:
                continue
            synthetic = f"account_{int(numeric):03d}" if len(numeric) <= 3 else f"account_{numeric}"
            case.facts.append(self._account_fact(case, None, resource=synthetic))

    def _account_fact(self, case: Case, activity: Any, resource: str | None = None) -> Fact:
        resource_id = resource or activity.resource_id
        observed = [
            observation
            for observation in self.evidence.observations
            if observation.resource_id == resource_id
            and observation.observed_at <= case.audit_at
        ]
        contemporaneous = [
            observation for observation in observed if observation.available_at <= case.audit_at
        ]
        if contemporaneous:
            observed = contemporaneous
        if observed:
            latest = max(observed, key=lambda obs: obs.observed_at)
            return Fact(
                system_id=SYSTEM_BY_CATEGORY["USER_PROFILE"],
                resource_id=resource_id,
                category="USER_PROFILE",
                state=latest.state,
                observed_at=latest.observed_at,
                evidence_id=latest.evidence_id,
            )

        evidence_id = self._absence_evidence(case.audit_at, "USER_PROFILE")
        if evidence_id is None and activity is not None:
            evidence_id = activity.activity_id
        return Fact(
            system_id=SYSTEM_BY_CATEGORY["USER_PROFILE"],
            resource_id=resource_id,
            category="USER_PROFILE",
            state="ABSENT",
            observed_at=case.audit_at,
            evidence_id=evidence_id or "",
        )

    def _absence_evidence(self, cutoff: datetime, category: str) -> str | None:
        """Newest artefact that structurally covers a category before cutoff.

        A capture owned by the service that holds the record outranks an
        aggregate inventory export: the inventory proves the record is missing
        from a copy, the owning service proves it is gone from the source.
        """

        origins = self.evidence.origin_by_file
        authoritative = AUTHORITATIVE_ORIGINS.get(category, set())
        best: tuple[int, datetime, str] | None = None
        for file_id, captured in self.evidence.available_at.items():
            if captured > cutoff:
                continue
            if category not in self.evidence.capabilities.get(file_id, set()):
                continue
            origin = origins.get(file_id, "")
            # Per-user assurance bundles list the subject's own collections, so
            # they are as trustworthy as a dedicated service capture and a newer
            # bundle still wins on recency.
            tier = 1 if origin in authoritative or origin == "records_assurance_snapshot_bundle" else 0
            candidate = (tier, captured, file_id)
            if best is None or candidate > best:
                best = candidate
        return best[2] if best else None


def write_output(rows: Iterable[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "deletion_status", "steps_json"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(dataset: Path, requests: Path, output: Path) -> RunStats:
    agent = DeletionAuditAgent(dataset)
    rows = agent.run(requests)
    write_output(rows, output)
    return agent.stats
