#!/usr/bin/env python3
"""Hand-built evaluation cases for behaviour the public samples do not cover.

The public sample file contains no ``NOT_APPLICABLE`` case, no tombstone whose
direct identifiers survived, no historical-email lookup, and no active
synchronisation path.  This module builds a small synthetic dataset for exactly
those situations, runs the real agent against it, and asserts the expected
``deletion_status`` and step structure.

Run from the repository root:

    python3 code/evaluation/custom_cases.py

Exit status is non-zero when a case fails, so the script doubles as a regression
gate.  The dataset is generated in a temporary directory and never written into
the repository.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from audit_agent import DeletionAuditAgent  # noqa: E402

REQUESTS_HEADER = [
    "case_id",
    "email",
    "requested_at",
    "reported_status",
    "reported_at",
    "audit_at",
    "request_text",
]

# Every case is reported by the legacy workflow as COMPLETE: the point of these
# cases is that the claim is not proof.
CASES = [
    {
        "case_id": "custom_01",
        "email": "aiko.tanaka@example.com",
        "reported_status": "COMPLETE",
        "request_text": (
            "Bitte löschen Sie mein Konto nicht. Ich brauche es weiter und möchte "
            "nur meine Telefonnummer aktualisieren."
        ),
        "expected_status": "NOT_APPLICABLE",
        "expected_steps": [],
    },
    {
        # The request arrives from a retired address, so only the historical
        # identity chain links it to the surviving support message.
        "case_id": "custom_02",
        "email": "aiko.old@example.com",
        "reported_status": "COMPLETE",
        "request_text": "Please delete my account and all personal information linked to it.",
        "expected_status": "INCOMPLETE",
        "expected_steps": [
            ("FINDING", "REPORT_EXPOSED_PII", "support_9001"),
            ("REMEDIATION", "REDACT_RECORD", "support_9001"),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_9001"),
        ],
    },
    {
        # A tombstone may keep the stable reference but not the direct
        # identifiers, so this record must be redacted rather than deleted.
        "case_id": "custom_03",
        "email": "ben.ortiz@example.com",
        "reported_status": "COMPLETE",
        "request_text": "I am requesting deletion of the account registered to this address.",
        "expected_status": "INCOMPLETE",
        "expected_steps": [
            ("FINDING", "REPORT_EXPOSED_PII", "tombstone_9002"),
            ("REMEDIATION", "REDACT_RECORD", "tombstone_9002"),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "tombstone_9002"),
        ],
    },
    {
        # The account is gone, but an enabled connector would recreate the data,
        # so the flow must be stopped before the deletion can be called complete.
        "case_id": "custom_04",
        "email": "cara.silva@example.com",
        "reported_status": "PARTIALLY_COMPLETE",
        "request_text": "Solicito a exclusão definitiva da conta associada a este e-mail.",
        "expected_status": "INCOMPLETE",
        "expected_steps": [
            ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "data_flow_9003"),
            ("REMEDIATION", "DISABLE_DATA_FLOW", "data_flow_9003"),
            ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "data_flow_9003"),
        ],
    },
    {
        # Fully remediated: the evidence must prove the final state.
        "case_id": "custom_05",
        "email": "dan.wu@example.com",
        "reported_status": "COMPLETE",
        "request_text": "Please treat this message as a request for permanent account deletion.",
        "expected_status": "COMPLETE",
        "expected_steps": [
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "audit_record_9004"),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_9004"),
        ],
    },
]

IDENTITIES = [
    ("user_9001", "Aiko Tanaka", "aiko.tanaka@example.com", "+81 90 1111 2222", "a" * 64),
    ("user_9002", "Ben Ortiz", "ben.ortiz@example.com", "+1 555 0100", "b" * 64),
    ("user_9003", "Cara Silva", "cara.silva@example.com", "+55 11 99999 0000", "c" * 64),
    ("user_9004", "Dan Wu", "dan.wu@example.com", "+86 138 0000 0000", "d" * 64),
]

AUDIT_ROWS = [
    ("audit_9001", "user_9001", "2026-02-01T00:00:00Z", "email", "aiko.old@example.com", "aiko.tanaka@example.com")
]

ACTIVITY_ROWS = [
    (
        "activity_9001",
        "2026-09-12T09:00:00Z",
        "SYNC_RECORD",
        "integration_service",
        "search_service",
        "search_9003",
        "SUCCESS",
        "Customer profile synchronization processed search_9003.",
    )
]

SNAPSHOT = {
    "captured_at": "2026-09-20T00:00:00Z",
    "source": "records_assurance",
    "snapshots": [
        {
            # Empty on purpose: the absence of every profile is what proves the
            # account deletions happened.
            "captured_at": "2026-09-20T00:00:00Z",
            "data_store": "account_service",
            "collection": "customer_profiles",
            "records": [],
        },
        {
            "captured_at": "2026-09-20T00:00:00Z",
            "data_store": "support_platform",
            "collection": "support_records",
            "records": [
                {
                    "resource_id": "support_9001",
                    "customer_reference": None,
                    "requester_name": "Aiko Tanaka",
                    "requester_email": "aiko.tanaka@example.com",
                    "requester_phone": None,
                    "message_excerpt": "Shared order context for order 88121.",
                },
                {
                    "resource_id": "support_9004",
                    "customer_reference": "user_9004",
                    "requester_name": None,
                    "requester_email": None,
                    "requester_phone": None,
                    "message_excerpt": "Agent note retained without customer identifiers.",
                },
            ],
        },
        {
            "captured_at": "2026-09-20T00:00:00Z",
            "data_store": "identity_service",
            "collection": "deleted_customer_references",
            "records": [
                {
                    "resource_id": "tombstone_9002",
                    "subject_reference": "user_9002",
                    "name": "Ben Ortiz",
                    "email": "ben.ortiz@example.com",
                    "phone": "+1 555 0100",
                    "email_hash": None,
                },
                {
                    "resource_id": "tombstone_9004",
                    "subject_reference": "user_9004",
                    "name": None,
                    "email": None,
                    "phone": None,
                    "email_hash": None,
                },
            ],
        },
        {
            "captured_at": "2026-09-20T00:00:00Z",
            "data_store": "integration_service",
            "collection": "connector_subscriptions",
            "records": [
                {
                    "resource_id": "data_flow_9003",
                    "customer_reference": "user_9003",
                    "customer_email": None,
                    "connector_name": "customer_profile_sync",
                    "enabled": True,
                    "last_delivery_status": "delivered",
                }
            ],
        },
        {
            "captured_at": "2026-09-20T00:00:00Z",
            "data_store": "security_service",
            "collection": "security_audit_events",
            "records": [
                {
                    "resource_id": "audit_record_9004",
                    "subject_reference": "user_9004",
                    "event_name": "account_deletion_reviewed",
                    "actor_type": "automated_privacy_workflow",
                    "integrity_seal": "sha256:" + "0" * 64,
                }
            ],
        },
    ],
}


def build_dataset(target: Path) -> Path:
    """Materialise the synthetic dataset in ``target``."""

    (target / "evidence" / "records").mkdir(parents=True, exist_ok=True)
    with (target / "user_identities.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["user_id", "name", "email", "phone", "email_hash", "updated_at"])
        for user_id, name, email, phone, email_hash in IDENTITIES:
            writer.writerow([user_id, name, email, phone, email_hash, "2026-01-01T00:00:00Z"])
    with (target / "user_audit_log.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"])
        writer.writerows(AUDIT_ROWS)
    with (target / "system_activity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "activity_id",
                "event_time",
                "event_type",
                "source_system",
                "target_system",
                "resource_id",
                "reported_result",
                "details",
            ]
        )
        writer.writerows(ACTIVITY_ROWS)
    with (target / "evidence_files.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file_id", "file_path", "origin", "captured_at"])
        writer.writerow(
            [
                "evidence_01",
                "evidence/records/snapshot_20260920.json",
                "records_assurance_snapshot_bundle",
                "2026-09-20T00:00:00Z",
            ]
        )
    (target / "evidence" / "records" / "snapshot_20260920.json").write_text(
        json.dumps(SNAPSHOT, indent=2), encoding="utf-8"
    )
    shutil.copy(ROOT / "dataset" / "deletion_rules.csv", target / "deletion_rules.csv")
    with (target / "deletion_requests.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUESTS_HEADER)
        writer.writeheader()
        for case in CASES:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "email": case["email"],
                    "requested_at": "2026-09-10T08:00:00Z",
                    "reported_status": case["reported_status"],
                    "reported_at": "2026-09-12T09:00:00Z",
                    "audit_at": "2026-09-25T09:00:00Z",
                    "request_text": case["request_text"],
                }
            )
    return target


def run() -> int:
    with tempfile.TemporaryDirectory() as workdir:
        dataset = build_dataset(Path(workdir) / "dataset")
        agent = DeletionAuditAgent(dataset)
        rows = {row["case_id"]: row for row in agent.run(dataset / "deletion_requests.csv")}

    failures: list[str] = []
    print(f"{'case':10} {'expected':16} {'actual':16} steps")
    for case in CASES:
        case_id = case["case_id"]
        row = rows[case_id]
        status = row["deletion_status"]
        steps = json.loads(row["steps_json"])
        ok = status == case["expected_status"]
        for phase, operation, resource in case["expected_steps"]:
            if not any(
                step["phase"] == phase
                and step["operation"] == operation
                and step["resource_id"] == resource
                for step in steps
            ):
                ok = False
                failures.append(f"{case_id}: missing {phase} {operation} {resource}")
        if status != "NOT_APPLICABLE" and not any(
            step["operation"] == "VERIFY_RECORD_ABSENT"
            and step["system_id"] == "account_service"
            for step in steps
        ):
            ok = False
            failures.append(f"{case_id}: no account verification step")
        if status != case["expected_status"]:
            failures.append(f"{case_id}: status {status} != {case['expected_status']}")
        if [step["step_no"] for step in steps] != list(range(1, len(steps) + 1)):
            failures.append(f"{case_id}: step numbers are not consecutive")
        phases = [step["phase"] for step in steps]
        order = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
        if [order[phase] for phase in phases] != sorted(order[phase] for phase in phases):
            failures.append(f"{case_id}: phases are out of order")
        print(f"{case_id:10} {case['expected_status']:16} {status:16} {'PASS' if ok else 'FAIL'} ({len(steps)})")

    print()
    print(f"{len(CASES) - len(set(f.split(':')[0] for f in failures))}/{len(CASES)} custom cases passed")
    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
