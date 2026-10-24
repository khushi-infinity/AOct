# Ghost Data Still Exists - Build Notes

## Contract

- Input: `dataset/deletion_requests.csv` (518 rows).
- Output: root `output.csv`, exact header `case_id,deletion_status,steps_json`, exactly 518 sorted rows.
- Status values: `COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`.
- `NOT_APPLICABLE` always uses `[]`.
- `COMPLETE` uses evidence-backed verification steps only.
- `INCOMPLETE` uses findings with evidence, followed by proposed remediation and future verification with empty evidence IDs.
- Step order: phase order, then the operation order published in the problem statement, then ascending `system_id` and `resource_id`.
- Participant-facing data only. No case-specific labels or organizer truth.

## Dataset reconnaissance

- 518 evaluation requests, 32 public sample requests, 850 current identities, 306 identity-audit rows, 4,011 activity rows, 15 deletion rules, and 94 evidence files.
- The evaluation requests consist of 50 ten-case point-in-time audit batches, eight multimodal edge cases, and ten explicit non-deletion requests.
- Evidence formats: JSON, SQLite-compatible SQL exports, multiple log syntaxes, plain text, PNG screenshots, and PDFs.
- Public sample output distribution: 10 `COMPLETE`, 22 `INCOMPLETE`, 0 `NOT_APPLICABLE`. The evaluation set contains ten explicit non-deletion requests, so all three outcome categories must be supported.

## Measured engine results (public samples, 32 cases)

| Metric | Value |
| --- | --- |
| deletion-status accuracy | 1.0000 |
| exact-case accuracy | 0.6875 |
| step-sequence accuracy | 0.7188 |
| step precision / recall / F1 | 0.9402 / 0.8964 / 0.9178 |
| field accuracy | 0.9230 |

Baseline floor (`code/baseline.py`): status 0.6875, every other metric 0.0000.
Full 518-case run: 368 INCOMPLETE, 140 COMPLETE, 10 NOT_APPLICABLE, 0 legality errors, ~5.6 s.

## Inferred canonical behavior

1. `reported_status` is ignored as proof; observed evidence controls the result.
2. Identity matching is case-insensitive and includes historical email, phone, and hash values.
3. For incomplete cases, every proposed remediation and verification step has `evidence_id=""`, including checks for already-compliant base records.
4. A retained security record is verified as present when it is relevant and within retention.
5. Support conversations with shared context are redacted; subject-only attachments are deleted.
6. Attributable analytics and telemetry are anonymized; fully de-identified versions are compliant.
7. Backups may remain only when restore access is blocked.
8. Account tombstones may retain the stable internal reference but must remove direct identifiers.
9. The audit-time state must be reconstructed from event time; a bundle captured later may still prove an earlier state, but evidence that already existed at `audit_at` is preferred per record.
10. Retention evidence (security audit records) is verified present, never deleted, and is part of the plan even when the case is otherwise incomplete.
11. Steps name the owning service, not the replica or store the record was read from.
12. A record's explicitly named category overrides a category guessed from its resource-id prefix; diagnostics do not assert categories.
13. An anonymised analytics profile carries no identifiers, so it cannot be linked to a person from participant-facing evidence. The same is true for a few retained audit records. Those steps are omitted rather than guessed (see `code/evaluation/evaluation_report.md`, section 6).

## Scoring map

| Scoring area | Artifact / mechanism | Phase |
| --- | --- | --- |
| Deletion-status accuracy | multilingual intent classifier plus policy compliance engine | engine |
| Current and historical identity resolution | identity graph from current snapshot and audit chain | engine |
| Remaining records and risks | normalized, time-bounded evidence index across every supplied format | engine |
| Evidence citations | manifest-backed `file_id`, plus participant-visible activity/audit IDs | engine |
| Policy decisions | data-category rules loaded from `deletion_rules.csv` | engine |
| Step completeness and order | deterministic step planner and canonical sort | engine |
| Case/step/field/sequence metrics | reproducible evaluator against public samples | evaluation |
| Three additional cases | deterministic custom unit/evaluation cases | evaluation |
| Token/cost report | deterministic-engine zero-call usage report | packaging |
| Submission hygiene | tests, README, exact dependencies, fresh ZIP and CSV validation | packaging |
| Interview readiness | constants, weaknesses, evaluation results, and Q&A drill | handoff |

## Silent point-loss risks

- Treating an operation result as proof instead of using readback evidence.
- Using evidence captured after `audit_at`.
- Missing historical identifiers or case-insensitive email matches.
- Deleting policy-retained security/legal records.
- Citing evidence on future steps for incomplete cases.
- Omitting compliant retained records from final verification.
- Incorrect operation order or non-consecutive `step_no`.
- Silent OCR/PDF degradation.
- Packaging the dataset, caches, or nested archives in `code.zip`.

