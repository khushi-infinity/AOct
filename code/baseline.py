#!/usr/bin/env python3
"""Deliberately simple public-sample baseline used as a measured floor."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("requests", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.requests.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "deletion_status", "steps_json"])
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["case_id"]):
            writer.writerow(
                {"case_id": row["case_id"], "deletion_status": "INCOMPLETE", "steps_json": "[]"}
            )


if __name__ == "__main__":
    main()
