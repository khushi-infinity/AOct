#!/usr/bin/env python3
"""Generate the HackerRank submission file from participant-facing evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from audit_agent import run


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=root / "dataset")
    parser.add_argument("--requests", type=Path)
    parser.add_argument("--output", type=Path, default=root / "output.csv")
    args = parser.parse_args()
    requests = args.requests or args.dataset / "deletion_requests.csv"
    run(args.dataset.resolve(), requests.resolve(), args.output.resolve())
    print(f"Wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
