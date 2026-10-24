#!/usr/bin/env python3
"""Validate predictions and score public-sample accuracy.

Legality checks and accuracy metrics are intentionally reported separately.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HEADER = ["case_id", "deletion_status", "steps_json"]
STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
STEP_FIELDS = [
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
]
PHASES = {"FINDING", "REMEDIATION", "VERIFICATION"}
OP_STATE = {
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


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def parse_steps(raw: str, case_id: str, errors: list[str]) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append(f"{case_id}: steps_json is invalid JSON: {exc}")
        return []
    if not isinstance(value, list):
        errors.append(f"{case_id}: steps_json must be an array")
        return []
    return value


def validate(predictions: Path, request_file: Path | None = None) -> dict[str, Any]:
    header, rows = read_rows(predictions)
    errors: list[str] = []
    if header != EXPECTED_HEADER:
        errors.append(f"header must be {EXPECTED_HEADER}, got {header}")
    case_ids = [row.get("case_id", "") for row in rows]
    if len(case_ids) != len(set(case_ids)):
        errors.append("duplicate case_id values")
    if case_ids != sorted(case_ids):
        errors.append("rows are not sorted by case_id")
    if request_file:
        _, requests = read_rows(request_file)
        expected = sorted(row["case_id"] for row in requests)
        if case_ids != expected:
            missing = sorted(set(expected) - set(case_ids))
            extra = sorted(set(case_ids) - set(expected))
            errors.append(f"case coverage mismatch: missing={missing[:5]} extra={extra[:5]}")
    for row in rows:
        case_id = row.get("case_id", "<missing>")
        status = row.get("deletion_status", "")
        if status not in STATUSES:
            errors.append(f"{case_id}: invalid status {status!r}")
        steps = parse_steps(row.get("steps_json", ""), case_id, errors)
        if status == "NOT_APPLICABLE" and steps:
            errors.append(f"{case_id}: NOT_APPLICABLE must use []")
        if status == "COMPLETE" and any(step.get("phase") != "VERIFICATION" for step in steps):
            errors.append(f"{case_id}: COMPLETE may contain verification steps only")
        expected_numbers = list(range(1, len(steps) + 1))
        if [step.get("step_no") for step in steps] != expected_numbers:
            errors.append(f"{case_id}: step numbers are not consecutive from 1")
        for step in steps:
            if not isinstance(step, dict) or list(step.keys()) != STEP_FIELDS:
                errors.append(f"{case_id}: step must contain exactly {STEP_FIELDS} in canonical order")
                continue
            if step["phase"] not in PHASES:
                errors.append(f"{case_id}: invalid phase {step['phase']!r}")
            if OP_STATE.get(step["operation"]) != step["state"]:
                errors.append(
                    f"{case_id}: invalid operation/state {step['operation']}/{step['state']}"
                )
            if status == "INCOMPLETE" and step["phase"] != "FINDING" and step["evidence_id"]:
                errors.append(f"{case_id}: future steps must use an empty evidence_id")
            if (status == "COMPLETE" or step["phase"] == "FINDING") and not step["evidence_id"]:
                errors.append(f"{case_id}: evidence-backed step is missing evidence_id")
    return {"rows": len(rows), "errors": errors}


def score(predictions: Path, gold: Path) -> dict[str, Any]:
    _, predicted_rows = read_rows(predictions)
    _, gold_rows = read_rows(gold)
    predicted = {row["case_id"]: row for row in predicted_rows}
    expected = {row["case_id"]: row for row in gold_rows}
    common = sorted(set(predicted) & set(expected))
    status_hits = exact_case_hits = sequence_hits = field_hits = field_total = 0
    step_tp = step_pred = step_gold = 0
    causes: Counter[str] = Counter()
    for case_id in common:
        pred = predicted[case_id]
        truth = expected[case_id]
        if pred["deletion_status"] == truth["deletion_status"]:
            status_hits += 1
        else:
            causes["status"] += 1
        pred_steps = json.loads(pred["steps_json"])
        gold_steps = json.loads(truth["steps_json"])
        if pred_steps == gold_steps and pred["deletion_status"] == truth["deletion_status"]:
            exact_case_hits += 1
        if [s.get("operation") for s in pred_steps] == [s.get("operation") for s in gold_steps]:
            sequence_hits += 1
        else:
            causes["sequence_or_step_count"] += 1
        pred_counter = Counter(json.dumps(s, sort_keys=True) for s in pred_steps)
        gold_counter = Counter(json.dumps(s, sort_keys=True) for s in gold_steps)
        step_tp += sum((pred_counter & gold_counter).values())
        step_pred += len(pred_steps)
        step_gold += len(gold_steps)
        for index, gold_step in enumerate(gold_steps):
            for field in STEP_FIELDS:
                field_total += 1
                if index < len(pred_steps) and pred_steps[index].get(field) == gold_step.get(field):
                    field_hits += 1
                elif field not in {"step_no", "phase", "operation", "state"}:
                    causes[f"field:{field}"] += 1
    count = len(expected)
    precision = step_tp / step_pred if step_pred else (1.0 if not step_gold else 0.0)
    recall = step_tp / step_gold if step_gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cases": count,
        "status_accuracy": status_hits / count if count else 0.0,
        "exact_case_accuracy": exact_case_hits / count if count else 0.0,
        "sequence_accuracy": sequence_hits / count if count else 0.0,
        "step_precision": precision,
        "step_recall": recall,
        "step_f1": f1,
        "field_accuracy": field_hits / field_total if field_total else 1.0,
        "cause_histogram": dict(causes.most_common()),
    }


def print_report(legality: dict[str, Any], metrics: dict[str, Any] | None) -> None:
    print("Legality checks")
    print(f"  rows: {legality['rows']}")
    print(f"  errors: {len(legality['errors'])}")
    for error in legality["errors"][:20]:
        print(f"  - {error}")
    if metrics is None:
        return
    print("Accuracy metrics")
    for key in (
        "status_accuracy",
        "exact_case_accuracy",
        "sequence_accuracy",
        "step_precision",
        "step_recall",
        "step_f1",
        "field_accuracy",
    ):
        print(f"  {key}: {metrics[key]:.4f}")
    print("Cause histogram")
    for key, value in metrics["cause_histogram"].items():
        print(f"  {key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--requests", type=Path)
    parser.add_argument("--gold", type=Path)
    args = parser.parse_args()
    legality = validate(args.predictions, args.requests)
    metrics = score(args.predictions, args.gold) if args.gold else None
    print_report(legality, metrics)
    if legality["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
