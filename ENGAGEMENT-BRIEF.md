# Engagement Brief — Deletion Assurance Agent

**Client:** Northstar Shop (fictional) · **Programme:** Privacy Assurance
**Deliverable owner:** khushi-infinity/AOct · **Status:** delivered (see `code/`)

> This is the request restated as an engineering brief. It supersedes the
> free-text competition prompt for design and acceptance purposes; the raw
> request remains in `log.txt` as the historical record.

---

## 1. Context

A customer deletion was recorded as "Complete" on every internal dashboard. Six
weeks later the same person was refused registration because their email still
existed. The post-incident review found copies of their data in a secondary
database, a support attachment, a search index, an analytics export, an
application log, an object-store archive and a backup — and an active
synchronisation job that had already recreated the primary record once.

Stated loss: **$2.4M**. Root cause: the deletion workflow was treated as the
system of record for *truth*, when it is only the system of record for *intent*.

## 2. Objective

Build an audit agent that, for any submitted deletion request, establishes the
true state of a customer's personal data **at a specified audit time**, decides
whether deletion is genuinely complete, and produces the ordered operational
plan that closes the gap — or the evidence plan that proves there is no gap.

The agent must be defensible in front of a regulator: every claim traceable to a
participant-visible artefact, every retained record justified by policy, and no
decision that depends on a workflow status message.

## 3. Functional requirements

| ID | Requirement |
| --- | --- |
| R1 | Decide authorisation from `request_text` alone. Access, correction, export, login-help and marketing-only requests are **not** deletion requests, in any supported language. |
| R2 | Resolve the subject from the supplied email **and** from every historical email, phone and email hash in the identity audit trail. |
| R3 | Reconstruct the subject's record state at `audit_at` across every data category present in the corpus: profile, secondary identifiers, search index, cache, support messages and attachments, analytics and telemetry, exports, marketing, email delivery, security audit, legal hold, backups, tombstones, and active data flows. |
| R4 | Treat `reported_status`, `reported_result` and system messages as **claims**. Only readback evidence establishes state. |
| R5 | Apply `deletion_rules.csv` per record: delete, redact, anonymise, retain, or preserve a tombstone with only the stable internal reference. |
| R6 | Report every remaining copy and every active recreation path — sync, import, restore, replication drift. |
| R7 | Emit the ordered plan: findings, then remediation, then verification; disable flows and block restores before mutating records; cite evidence for present-state claims and leave future steps uncited. |
| R8 | Never destroy records policy requires to be retained, and prove their availability instead. |
| R9 | Preserve account tombstones: the stable `user_id` may remain, direct identifiers must not. |

## 4. Output contract

`output.csv` — header `case_id,deletion_status,steps_json`; exactly one row per
request; rows sorted by `case_id`; 518 data rows for the evaluation set.

`steps_json` — JSON array of objects with exactly `step_no`, `phase`,
`system_id`, `resource_id`, `operation`, `state`, `evidence_id`. Phases are
`FINDING` → `REMEDIATION` → `VERIFICATION`; `step_no` starts at 1 and is
consecutive; operations and states are limited to the published table; ordering
is by operation order, then `system_id`, then `resource_id`.

`COMPLETE` carries verification only, all cited. `INCOMPLETE` carries findings
(cited) plus the full remediation plan and its post-checks (uncited).
`NOT_APPLICABLE` carries `[]`.

## 5. Acceptance criteria

| ID | Criterion | How it is verified |
| --- | --- | --- |
| AC1 | All three outcome categories are produced, and `NOT_APPLICABLE` matches the genuinely non-deletion requests | sample scorer + `custom_01` + distribution audit |
| AC2 | Deletion status is correct on every public sample | `evaluation/main.py` → `status_accuracy` |
| AC3 | Step arrays are structurally identical, not merely plausible | `exact_case_accuracy`, `sequence_accuracy` |
| AC4 | Field-level fidelity is measured, not asserted | `field_accuracy` per field with a cause histogram |
| AC5 | Every cited evidence id exists in `evidence_files.csv` and is not captured after `audit_at` | legality checker |
| AC6 | Remediation ordering never allows recreation of what was just deleted | unit test + `custom_04` |
| AC7 | A clean checkout reproduces the submission file byte-for-byte | clean-room unzip run |
| AC8 | The final run is costed honestly | `evaluation/usage_report.md` |

## 6. Constraints

| ID | Constraint | Consequence for the design |
| --- | --- | --- |
| C1 | Only `dataset/` is admissible; no organiser truth, no case-id shortcuts | evidence-driven engine, no lookup tables |
| C2 | Deterministic where possible | no sampling, no model calls in the scored path |
| C3 | No secrets, credentials or real personal data in the submission | stdlib-only runtime; optional local OCR/PDF |
| C4 | Must run from the terminal on a laptop | single entry point, ~6 s for 518 cases |
| C5 | Evidence arrives in heterogeneous formats (JSON, SQL, four log dialects, text registers, PDF, PNG) | one normalised observation model upstream of policy |
| C6 | Verdict must be explainable line by line in a 30-minute review | decision log, ADRs, measured metrics, stated limitations |

## 7. Non-goals

* Building the deletion *execution* system (the brief is an auditor, not a worker).
* Re-identifying anonymised analytics records from private truth we do not hold.
* Maximising step count: a finding is emitted only when evidence supports it.
* Hosted-LLM inference in the scored path — it would break C2 and C3 and make
  the reported accuracy unreproducible.

## 8. Risks the design must answer

| Risk | Mitigation |
| --- | --- |
| A dashboard status is mistaken for proof | claims are quarantined; state comes from readbacks |
| Evidence captured after the audit time leaks the answer | event-time cutoff + contemporaneous-evidence preference per record |
| Replica drift looks like survival | later capture wins; a positive readback beats an absent one on a tie |
| A sync recreates deleted data | flow/restore findings precede record mutation; disabling is step one |
| Retained records are over-deleted | policy decides retention; verification proves presence |
| Ambiguous ownership of deleted accounts | claims are matched per workflow batch against status-compatible results |
| Unknown identifiers are guessed | gaps are reported as limitations, never fabricated |

## 9. Definition of done

1. `output.csv` regenerated from a clean environment, 518 rows, zero legality errors.
2. Sample accuracy measured and published with a cause histogram.
3. At least three additional evaluation cases for behaviour the samples do not cover.
4. Unit tests for intent, policy, planning, identity and the audit-time cutoff.
5. Written architecture, decision record, limitations and cost report.
6. Submission package reproducible from a fresh unzip.
