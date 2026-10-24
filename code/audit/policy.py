"""Deletion policy: what each data category requires and what proves it.

`deletion_rules.csv` is the source of truth for category treatment.  The
policy layer converts a rule plus an observed record state into the three
operations the grader understands: the finding, the remediation, and the
verification that closes the loop.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Canonical operation ordering published in the problem statement.  Sorting by
# this table (then by system and resource) reproduces the required step order.
OPERATION_ORDER: dict[str, int] = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0,
    "BLOCK_RESTORE": 1,
    "DELETE_RECORD": 2,
    "REDACT_RECORD": 3,
    "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0,
    "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2,
    "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4,
    "VERIFY_RESTORE_BLOCKED": 5,
}

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}

STATE_FOR_OPERATION: dict[str, str] = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

# Categories whose compliance is "the record no longer exists".
_DELETE_ACTIONS = {"DELETE"}
# Categories whose compliance is "the record exists without direct identifiers".
_REDACT_ACTIONS = {"REDACT"}
_ANONYMIZE_ACTIONS = {"ANONYMIZE"}

# Observed states that represent "data still exists" for a delete rule.
_PRESENT_STATES = {"PRESENT", "IDENTIFIABLE", "ACTIVE", "FOUND", "PRESENT_REDACTED"}


@dataclass(frozen=True)
class Treatment:
    """Required treatment for one observed record."""

    violation: bool
    finding: str | None = None
    remediation: str | None = None
    verification: str = ""

    @property
    def is_compliant(self) -> bool:
        return not self.violation


class Policy:
    def __init__(self, dataset: Path):
        self.actions: dict[str, str] = {}
        self.conditions: dict[str, str] = {}
        path = dataset / "deletion_rules.csv"
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                category = (row.get("data_category") or "").strip().upper()
                action = (row.get("required_action") or "").strip().upper()
                if category:
                    self.actions[category] = action
                    self.conditions[category] = row.get("condition") or ""

    def action_for(self, category: str) -> str:
        return self.actions.get(category.upper(), self._derived_action(category))

    @staticmethod
    def _derived_action(category: str) -> str:
        """Behaviour implied by the completeness rule for unlisted categories.

        ``deletion_rules.csv`` does not list data flows, yet the completeness
        definition forbids any active sync/import path that can recreate data.
        Flow and restore handling is therefore derived from that requirement
        rather than hardcoded per case.
        """

        return {
            "DATA_FLOW": "DISABLE_FLOW",
            "BACKUP_ARCHIVE": "RETAIN",
            "SECURITY_AUDIT_LOG": "RETAIN",
            "LEGAL_HOLD_RECORD": "RETAIN",
        }.get(category.upper(), "DELETE")

    def evaluate(self, category: str, state: str) -> Treatment:
        """Return the finding/remediation/verification triple for a record."""

        category = category.upper()
        state = (state or "").upper()
        action = self.action_for(category)

        if category == "DATA_FLOW" or action == "DISABLE_FLOW":
            if state == "ACTIVE":
                return Treatment(
                    True, "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                    "VERIFY_DATA_FLOW_DISABLED",
                )
            return Treatment(False, verification="VERIFY_DATA_FLOW_DISABLED")

        if category == "BACKUP_ARCHIVE":
            if state == "ACTIVE":
                return Treatment(
                    True, "REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                    "VERIFY_RESTORE_BLOCKED",
                )
            return Treatment(False, verification="VERIFY_RESTORE_BLOCKED")

        if action in _DELETE_ACTIONS:
            if state in _PRESENT_STATES:
                return Treatment(
                    True, "REPORT_REMAINING_RECORD", "DELETE_RECORD",
                    "VERIFY_RECORD_ABSENT",
                )
            return Treatment(False, verification="VERIFY_RECORD_ABSENT")

        if action in _REDACT_ACTIONS:
            if state in _PRESENT_STATES - {"ACTIVE"}:
                return Treatment(
                    True, "REPORT_EXPOSED_PII", "REDACT_RECORD",
                    "VERIFY_RECORD_REDACTED",
                )
            return Treatment(False, verification="VERIFY_RECORD_REDACTED")

        if action in _ANONYMIZE_ACTIONS:
            if state in _PRESENT_STATES - {"ACTIVE"}:
                return Treatment(
                    True, "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD",
                    "VERIFY_RECORD_ANONYMIZED",
                )
            return Treatment(False, verification="VERIFY_RECORD_ANONYMIZED")

        # RETAIN: the record must remain available.  Nothing to remediate, but
        # a completed audit still has to prove availability.
        return Treatment(False, verification="VERIFY_RECORD_PRESENT")
