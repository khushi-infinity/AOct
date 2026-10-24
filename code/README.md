# Deletion Audit Agent — Ghost Data Still Exists

A deterministic, evidence-grounded agent that audits whether a customer's personal
data is really gone. For each request it answers one of `COMPLETE`,
`INCOMPLETE` or `NOT_APPLICABLE` and emits the ordered findings, remediation and
verification steps that prove or finish the deletion.

No model API, no credentials, no network: the same inputs always produce the same
`output.csv`, which is what makes the reported accuracy re-printable.

---

## Quick start

```bash
python3 -m pip install -r code/requirements.txt   # only pypdf; tesseract is optional
python3 code/main.py                              # writes ./output.csv for all 518 cases
```

Expected: `Wrote <repo>/output.csv` in about six seconds.

Other entry points:

```bash
# Score the agent against the 32 public sample answers
python3 code/main.py --requests dataset/sample_deletion_requests.csv --output /tmp/sample_pred.csv
python3 code/evaluation/main.py /tmp/sample_pred.csv \
    --requests dataset/sample_deletion_requests.csv --gold dataset/sample_output.csv

# Legality checks only (schema, ordering, allowed operations, evidence rules)
python3 code/evaluation/main.py output.csv --requests dataset/deletion_requests.csv

# Hand-built cases the public samples do not cover (5/5 must pass)
python3 code/evaluation/custom_cases.py

# Unit tests
python3 -m unittest discover -s code/tests -v
```

All paths are resolved from the location of the code file, so the commands work
from any working directory. Python 3.9+.

---

## Pipeline

```text
deletion_requests.csv
        │
        ├─ 1. intent ............ does request_text authorise deletion at all?
        │                          (multilingual phrase grammar; negation first)
        ├─ 2. identity .......... request email → current user + every historical
        │                          email / phone / email hash
        ├─ 3. evidence index .... every artefact → timestamped observations of
        │                          (system, resource, category, state)
        │                          JSON bundles, service exports, SQLite .sql
        │                          snapshots, four log dialects, shift registers,
        │                          PDFs (pypdf), screenshots (tesseract)
        ├─ 4. attribution ....... deleted accounts leave no profile row, so the
        │                          workflow stream is matched per reported_at
        │                          batch, restricted to result-compatible claims
        ├─ 5. state at audit_at . latest grounded observation per record, with a
        │                          preference for evidence that already existed
        ├─ 6. policy ............ deletion_rules.csv → treatment per record
        └─ 7. planner ........... FINDING → REMEDIATION → VERIFICATION, ordered by
                                   operation table, then system_id, resource_id
```

### Modules

| File | Responsibility |
| --- | --- |
| `main.py` | CLI entry point, path resolution, writes `output.csv` |
| `audit_agent.py` | Orchestration, case loading, account attribution, CSV writing |
| `audit/intent.py` | Deletion vs. non-deletion classification (12 languages worth of stems) |
| `audit/identity.py` | Identity graph: current snapshot + audit-trail aliases |
| `audit/evidence.py` | Artefact parsers and the normalised observation model |
| `audit/policy.py` | `deletion_rules.csv` → finding/remediation/verification triple |
| `audit/planner.py` | Canonical step ordering, dedupe, consecutive numbering |
| `evaluation/main.py` | Legality checks + per-field/step/sequence accuracy vs. gold |
| `evaluation/custom_cases.py` | Synthetic dataset for uncovered behaviours |
| `evaluation/baseline.py` (`code/baseline.py`) | Measured floor: everything `INCOMPLETE`, `[]` |
| `tests/test_audit.py` | 23 unit tests over intent, policy, planner, identity, evidence |

---

## Design decisions

**Reported status is a claim, never proof.** `reported_status` and
`reported_result` only help *locate* the account deletion that belongs to a case.
Every decision uses a readback: a profile lookup returning `404`, a snapshot with
no matching row, a tombstone whose identifiers are still populated, an enabled
connector, an unrestorable backup.

**State is reconstructed at `audit_at`.** Observations are timestamped by the
event they describe, not by the file that carries them, because readback bundles
are shipped days after the events inside them. When two observations of one
record both exist, the engine prefers the one whose file already existed at the
audit time — an auditor could not have read a bundle from the future, even if it
describes an older event. A record that only a later capture mentions is still
used; the preference is per record, not per case.

**Identity is historical.** `user_audit_log.csv` supplies retired emails, phones
and hashes. Requests routinely arrive from an address the current snapshot no
longer holds; matching only the snapshot would miss every record keyed by the
older value.

**The plan names owning services, not replicas.** `support_replica` and
`user_export_store` are physical locations; the graded `system_id` is
`support_platform` and `export_service`. Replica/primary/store suffixes are mapped
to the owning service, and when an artefact only implies a category from the
resource-name prefix that weaker guess is overridden by any artefact that names
the record type explicitly.

**One canonical category per resource.** A diagnostic line
(`deletion_marker_check`, `checkpoint_lag`) must not reclassify a support
attachment as a support message; diagnostics never assert a category.

**Compliance is per rule, not per opinion.** `deletion_rules.csv` decides whether
a record must be deleted, redacted, anonymised or retained. A tombstone is
redacted (the stable reference survives, name/email/phone/hash must not), an
attributable analytics profile is anonymised, an active connector is disabled, an
unblocked backup is a restore risk, and retained security/legal records are
verified *present* rather than deleted.

**Ordering is canonical and deterministic.** Phase, then the operation order
published in the problem statement, then `system_id`, then `resource_id`; step
numbers restart at 1 per case. Disabling a flow and blocking a restore happen
before record mutation, so a sync cannot recreate what was just deleted.

**Future work is not cited.** For `INCOMPLETE`, findings cite the evidence that
proves the violation and every proposed remediation/verification uses an empty
`evidence_id`, exactly as the contract requires. For `COMPLETE` every step is
cited.

---

## Known limitations

1. **Anonymised analytics records are unlinkable.** Once anonymised, the artefact
   carries no identifier at all; which record belonged to which person is only in
   the organiser's private truth. The engine reports the anonymised records it
   can link and does not fabricate resource ids.
2. **Some retained audit records have no visible id.** When the readback log, the
   shift-handover register or a SQL replica mentions the record the engine uses
   it; when nothing in `dataset/` does, the step cannot be produced.
3. **Same-status claims in one batch are allocated in time order.** If several
   cases report the same status and none of their accounts is named by a readback,
   the claims are indistinguishable; the engine assigns result-compatible claims
   in ascending event time.
4. **Screenshot OCR needs `tesseract`.** Without it, PNG evidence warns on stderr
   and is skipped — never silently treated as empty.

Measured consequences of 1–3 are quantified in `evaluation/evaluation_report.md`.

---

## Reproducibility contract

* Standard library only at runtime (plus optional `pypdf`).
* No network, no credentials, no environment-specific paths.
* `output.csv`: exactly 518 sorted data rows, header
  `case_id,deletion_status,steps_json`, every array a valid JSON array with
  consecutive `step_no` starting at 1.
* `evaluation/usage_report.md`: 0 model calls, 0 tokens, $0 — measured, not
  estimated.
