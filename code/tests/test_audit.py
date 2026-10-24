"""Unit tests for the deletion-audit primitives.

Run from the repository root:

    python3 -m unittest discover -s code/tests -v

The tests pin the behaviour the planner depends on: multilingual intent
classification, policy treatment per category, canonical step ordering, identity
resolution across historical aliases, and the audit-time cutoff.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
DATASET = CODE_DIR.parent / "dataset"
sys.path.insert(0, str(CODE_DIR))

from audit.evidence import (  # noqa: E402
    EvidenceIndex,
    Observation,
    _order_key,
    canonical_system,
    parse_time,
)
from audit.identity import IdentityGraph, digits, normalize  # noqa: E402
from audit.intent import is_deletion_request  # noqa: E402
from audit.planner import Fact, plan_case  # noqa: E402
from audit.policy import OPERATION_ORDER, PHASE_ORDER, Policy  # noqa: E402


class IntentTests(unittest.TestCase):
    def test_deletion_requests_in_several_languages(self) -> None:
        requests = [
            "Please delete my account and everything linked to it.",
            "Je demande la suppression définitive du compte associé à cette adresse.",
            "Solicito la eliminación permanente de la cuenta asociada a este correo.",
            "Bitte löschen Sie mein Konto vollständig.",
            "アカウントの削除をお願いします。",
            "请删除我的账户和个人数据。",
            "제 계정을 삭제해 주세요.",
            "Solicito a exclusão definitiva da minha conta.",
        ]
        for text in requests:
            with self.subTest(text=text):
                self.assertTrue(is_deletion_request(text))

    def test_non_deletion_requests_are_rejected(self) -> None:
        requests = [
            "I want to download a copy of my data, please keep my account.",
            "Please correct the surname on my profile.",
            "Do not delete my account, I still need the order history.",
            "Please stop the promotional emails but keep my account.",
            "I cannot access my account and need a password reset.",
            "Bitte löschen Sie mein Konto nicht, ich brauche es weiter.",
        ]
        for text in requests:
            with self.subTest(text=text):
                self.assertFalse(is_deletion_request(text))

    def test_empty_request_is_not_deletion(self) -> None:
        self.assertFalse(is_deletion_request(""))
        self.assertFalse(is_deletion_request("   "))


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = Policy(DATASET)

    def test_rules_file_is_authoritative(self) -> None:
        self.assertEqual(self.policy.action_for("USER_PROFILE"), "DELETE")
        self.assertEqual(self.policy.action_for("ANALYTICS_PROFILE"), "ANONYMIZE")
        self.assertEqual(self.policy.action_for("SECURITY_AUDIT_LOG"), "RETAIN")
        self.assertEqual(self.policy.action_for("LEGAL_HOLD_RECORD"), "RETAIN")

    def test_present_profile_requires_delete(self) -> None:
        treatment = self.policy.evaluate("USER_PROFILE", "PRESENT")
        self.assertTrue(treatment.violation)
        self.assertEqual(treatment.finding, "REPORT_REMAINING_RECORD")
        self.assertEqual(treatment.remediation, "DELETE_RECORD")
        self.assertEqual(treatment.verification, "VERIFY_RECORD_ABSENT")

    def test_absent_profile_is_compliant(self) -> None:
        treatment = self.policy.evaluate("USER_PROFILE", "ABSENT")
        self.assertFalse(treatment.violation)
        self.assertEqual(treatment.verification, "VERIFY_RECORD_ABSENT")

    def test_tombstone_must_be_redacted_not_deleted(self) -> None:
        exposed = self.policy.evaluate("ACCOUNT_TOMBSTONE", "IDENTIFIABLE")
        self.assertEqual(exposed.finding, "REPORT_EXPOSED_PII")
        self.assertEqual(exposed.remediation, "REDACT_RECORD")
        cleaned = self.policy.evaluate("ACCOUNT_TOMBSTONE", "REDACTED")
        self.assertFalse(cleaned.violation)
        self.assertEqual(cleaned.verification, "VERIFY_RECORD_REDACTED")

    def test_anonymised_analytics_is_compliant(self) -> None:
        treatment = self.policy.evaluate("ANALYTICS_PROFILE", "ANONYMIZED")
        self.assertFalse(treatment.violation)
        self.assertEqual(treatment.verification, "VERIFY_RECORD_ANONYMIZED")

    def test_active_flow_and_restore_risk(self) -> None:
        flow = self.policy.evaluate("DATA_FLOW", "ACTIVE")
        self.assertEqual(flow.finding, "REPORT_ACTIVE_DATA_FLOW")
        self.assertEqual(flow.remediation, "DISABLE_DATA_FLOW")
        restore = self.policy.evaluate("BACKUP_ARCHIVE", "ACTIVE")
        self.assertEqual(restore.finding, "REPORT_RESTORE_RISK")
        self.assertEqual(restore.remediation, "BLOCK_RESTORE")
        self.assertFalse(self.policy.evaluate("BACKUP_ARCHIVE", "BLOCKED").violation)

    def test_retained_records_verify_present(self) -> None:
        treatment = self.policy.evaluate("SECURITY_AUDIT_LOG", "PRESENT")
        self.assertFalse(treatment.violation)
        self.assertEqual(treatment.verification, "VERIFY_RECORD_PRESENT")


def _fact(resource: str, category: str, system: str, state: str, evidence: str = "evidence_01") -> Fact:
    return Fact(
        system_id=system,
        resource_id=resource,
        category=category,
        state=state,
        observed_at=parse_time("2026-09-10T00:00:00Z"),
        evidence_id=evidence,
    )


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = Policy(DATASET)

    def test_complete_case_has_only_verification_steps(self) -> None:
        status, steps = plan_case(
            [
                _fact("account_001", "USER_PROFILE", "account_service", "ABSENT"),
                _fact("audit_record_001", "SECURITY_AUDIT_LOG", "security_service", "PRESENT"),
            ],
            self.policy,
        )
        self.assertEqual(status, "COMPLETE")
        self.assertEqual({step["phase"] for step in steps}, {"VERIFICATION"})
        self.assertTrue(all(step["evidence_id"] for step in steps))
        self.assertEqual([step["step_no"] for step in steps], [1, 2])

    def test_incomplete_case_leaves_future_steps_uncited(self) -> None:
        status, steps = plan_case(
            [_fact("search_001", "SEARCH_INDEX_ENTRY", "search_service", "PRESENT")],
            self.policy,
        )
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(
            [step["phase"] for step in steps],
            ["FINDING", "REMEDIATION", "VERIFICATION"],
        )
        self.assertEqual(steps[0]["evidence_id"], "evidence_01")
        self.assertEqual(steps[1]["evidence_id"], "")
        self.assertEqual(steps[2]["evidence_id"], "")

    def test_ordering_follows_phase_operation_system_resource(self) -> None:
        facts = [
            _fact("search_002", "SEARCH_INDEX_ENTRY", "search_service", "PRESENT"),
            _fact("account_002", "USER_PROFILE", "account_service", "PRESENT"),
            _fact("support_002", "SUPPORT_MESSAGE", "support_platform", "IDENTIFIABLE"),
            _fact("data_flow_002", "DATA_FLOW", "integration_service", "ACTIVE"),
        ]
        _, steps = plan_case(facts, self.policy)
        findings = [step for step in steps if step["phase"] == "FINDING"]
        keys = [
            (OPERATION_ORDER[step["operation"]], step["system_id"], step["resource_id"])
            for step in findings
        ]
        self.assertEqual(keys, sorted(keys))
        phases = [PHASE_ORDER[step["phase"]] for step in steps]
        self.assertEqual(phases, sorted(phases))

    def test_disabling_a_flow_precedes_downstream_deletion(self) -> None:
        facts = [
            _fact("search_003", "SEARCH_INDEX_ENTRY", "search_service", "PRESENT"),
            _fact("data_flow_003", "DATA_FLOW", "integration_service", "ACTIVE"),
        ]
        _, steps = plan_case(facts, self.policy)
        remediation = [step["operation"] for step in steps if step["phase"] == "REMEDIATION"]
        self.assertEqual(remediation, ["DISABLE_DATA_FLOW", "DELETE_RECORD"])

    def test_duplicate_records_are_collapsed(self) -> None:
        status, steps = plan_case(
            [
                _fact("account_004", "USER_PROFILE", "account_service", "ABSENT"),
                _fact("account_004", "USER_PROFILE", "account_service", "ABSENT"),
            ],
            self.policy,
        )
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(len(steps), 1)


class IdentityTests(unittest.TestCase):
    def test_normalisation_is_case_and_space_insensitive(self) -> None:
        self.assertEqual(normalize("  Ren   MORI "), "ren mori")
        self.assertEqual(digits("+81 90 6947 3342"), "819069473342")

    def test_historical_email_resolves_to_current_user(self) -> None:
        graph = IdentityGraph(DATASET)
        with (DATASET / "user_audit_log.csv").open(encoding="utf-8-sig") as handle:
            import csv

            for row in csv.DictReader(handle):
                if "mail" in (row["field_name"] or "").casefold() and "@" in (row["old_value"] or ""):
                    self.assertEqual(graph.resolve(row["old_value"]), row["user_id"])
                    break

    def test_unknown_identifier_returns_none(self) -> None:
        graph = IdentityGraph(DATASET)
        self.assertIsNone(graph.resolve("nobody@example.invalid"))


class EvidenceTests(unittest.TestCase):
    def test_canonical_system_maps_replicas_and_stores(self) -> None:
        self.assertEqual(canonical_system("support_replica", "SUPPORT_MESSAGE"), "support_platform")
        self.assertEqual(canonical_system("user_export_store", "USER_EXPORT"), "export_service")
        self.assertEqual(canonical_system("analytics_platform", "ANALYTICS_PROFILE"), "analytics_platform")
        self.assertEqual(canonical_system("", "BACKUP_ARCHIVE"), "backup_service")

    def test_audit_time_cutoff_excludes_later_events(self) -> None:
        graph = IdentityGraph(DATASET)
        index = EvidenceIndex(DATASET, graph)
        user = graph.all_users()[0]
        cutoff = parse_time("2026-03-01T00:00:00Z")
        for observation in index.facts_for(user, cutoff):
            self.assertLessEqual(observation.observed_at, cutoff)

    def test_facts_are_one_record_per_category(self) -> None:
        graph = IdentityGraph(DATASET)
        index = EvidenceIndex(DATASET, graph)
        cutoff = parse_time("2026-10-02T00:00:00Z")
        for user in graph.all_users()[:50]:
            facts = index.facts_for(user, cutoff)
            categories = [fact.category for fact in facts]
            self.assertEqual(len(categories), len(set(categories)))


class OrderingKeyTests(unittest.TestCase):
    def test_positive_observation_wins_a_timestamp_tie(self) -> None:
        base = dict(
            system_id="account_service",
            resource_id="account_999",
            category="USER_PROFILE",
            observed_at=parse_time("2026-09-01T00:00:00Z"),
            evidence_id="evidence_01",
            available_at=parse_time("2026-09-01T00:00:00Z"),
        )
        present = Observation(state="PRESENT", **base)
        absent = Observation(state="ABSENT", **base)
        self.assertGreater(_order_key(present), _order_key(absent))


class OutputContractTests(unittest.TestCase):
    def test_generated_output_matches_contract(self) -> None:
        path = CODE_DIR.parent / "output.csv"
        if not path.exists():
            self.skipTest("output.csv has not been generated yet")
        import csv

        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, ["case_id", "deletion_status", "steps_json"])
            rows = list(reader)
        self.assertEqual(len(rows), 518)
        self.assertEqual([row["case_id"] for row in rows], sorted(row["case_id"] for row in rows))
        allowed = {
            "REPORT_REMAINING_RECORD",
            "REPORT_EXPOSED_PII",
            "REPORT_ACTIVE_DATA_FLOW",
            "REPORT_RESTORE_RISK",
            "DISABLE_DATA_FLOW",
            "BLOCK_RESTORE",
            "DELETE_RECORD",
            "REDACT_RECORD",
            "ANONYMIZE_RECORD",
            "VERIFY_RECORD_ABSENT",
            "VERIFY_RECORD_PRESENT",
            "VERIFY_RECORD_REDACTED",
            "VERIFY_RECORD_ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED",
            "VERIFY_RESTORE_BLOCKED",
        }
        for row in rows:
            steps = json.loads(row["steps_json"])
            self.assertIsInstance(steps, list)
            self.assertEqual([step["step_no"] for step in steps], list(range(1, len(steps) + 1)))
            for step in steps:
                self.assertIn(step["operation"], allowed)
                self.assertEqual(step["evidence_id"] == "", step["phase"] != "FINDING" and row["deletion_status"] == "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
