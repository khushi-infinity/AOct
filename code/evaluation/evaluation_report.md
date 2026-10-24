# Evaluation Report — Ghost Data Still Exists

All numbers in this file are printed by the shipped evaluator. Reproduce them with:

```bash
# 1. Public-sample accuracy (32 labelled cases)
python3 code/main.py --requests dataset/sample_deletion_requests.csv --output /tmp/sample_pred.csv
python3 code/evaluation/main.py /tmp/sample_pred.csv \
    --requests dataset/sample_deletion_requests.csv \
    --gold dataset/sample_output.csv

# 2. Full-dataset legality + submission file
python3 code/main.py
python3 code/evaluation/main.py output.csv --requests dataset/deletion_requests.csv

# 3. Hand-built custom cases
python3 code/evaluation/custom_cases.py

# 4. Unit tests
python3 -m unittest discover -s code/tests -v
```

Legality checks (rows, schema, ordering, allowed operations) and accuracy
metrics are printed as separate blocks on purpose: a run with zero legality
errors says nothing about accuracy.

---

## 1. What is measured

| Metric | Definition |
| --- | --- |
| `status_accuracy` | `deletion_status` matches the gold row (case level) |
| `exact_case_accuracy` | whole `steps_json` array is identical to gold |
| `sequence_accuracy` | the ordered `operation` sequence is identical to gold |
| `step_precision` / `step_recall` / `step_f1` | multiset overlap of complete step objects |
| `field_accuracy` | per-step, per-field equality over the seven required fields |
| `cause_histogram` | root cause of every missed field / sequence, so fixes target the top cause |

Legality additionally resolves every cited `evidence_id` against the manifest
(`evidence_files.csv`), the activity stream (`system_activity.csv`) and the
identity audit trail (`user_audit_log.csv`). An id that is not one of those is an
error, which is what stops a fabricated or mistyped citation from passing.

Ground truth available to participants is `dataset/sample_output.csv` (32 cases).
The 518 evaluation cases have no public labels, so they are covered by the
legality checks and by the custom cases below.

## 2. Headline result

| Implementation | status | exact case | sequence | step P | step R | step F1 | field |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `code/baseline.py` (everything `INCOMPLETE`, `[]`) | 0.6875 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| First working engine (session start) | 1.0000 | 0.4688 | 0.5312 | 0.8380 | 0.7772 | 0.8065 | 0.8631 |
| Final engine (`code/audit_agent.py`) | **1.0000** | **0.6875** | **0.7188** | **0.9402** | **0.8964** | **0.9178** | **0.9230** |

Final cause histogram (remaining misses, 32 cases):

```text
field:resource_id          20
field:system_id            19
sequence_or_step_count      9
field:evidence_id           9
```

22 of the 32 sample cases now match the gold array byte-for-byte after JSON
normalisation. Every remaining miss is one of three known, documented gaps
(section 6), not a wrong decision: all 32 statuses are correct and no sample case
contains a finding the engine should not have produced.

## 3. Where the accuracy came from (fix → measured delta)

Each round was re-measured with the same command; the log records the same
sequence of runs.

| # | Change (general rule, not a case hack) | F1 | field |
| --- | --- | --- | --- |
| 1 | Engine as inherited: identifier-only evidence index, nearest-claim account attribution | 0.8065 | 0.8631 |
| 2 | Attribution by workflow batch + result compatibility; event-time cutoff; zero-padded account convention | 0.7692 | 0.8964 |
| 3 | Canonical owning-service names; one category per resource; prefer artefacts that already existed at `audit_at` | 0.8602 | 0.8756 |
| 4 | Apply the "contemporaneous evidence" preference per record instead of per case | 0.9125 | 0.9223 |
| 5 | Rank dedicated service captures and per-user bundles above aggregate inventory exports when proving absence | **0.9178** | **0.9230** |

Two regressions happened on the way and are kept in the log:

* Round 2 raised field accuracy but dropped step F1 (0.8065 → 0.7692). Relaxing the
  cutoff to event time added observations from files captured later, without any
  preference for the artefacts a real auditor had at `audit_at`. Round 3 fixed
  that by preferring contemporaneous files *per case*, which then over-corrected
  (it dropped a retained audit record that only a later capture mentions);
  round 4 made the preference per record.
* Round 3 also introduced a temporary sequence regression (0.6875 → 0.5625) for
  the same over-correction; round 4 restored and improved it.

## 4. Custom evaluation cases (behaviour the public samples do not exercise)

`code/evaluation/custom_cases.py` builds a synthetic dataset in a temporary
directory (no repository writes), runs the real agent, and asserts status,
required steps, consecutive numbering, and phase order. Result: **5/5 pass**.

| Case | Situation | Expected | Result |
| --- | --- | --- | --- |
| `custom_01` | German refusal: "Bitte löschen Sie mein Konto nicht …" | `NOT_APPLICABLE`, `[]` | pass |
| `custom_02` | Request sent from a **historical** email; the surviving support message is still identifiable | `INCOMPLETE` + `REPORT_EXPOSED_PII`/`REDACT_RECORD`/`VERIFY_RECORD_REDACTED` on `support_9001` | pass |
| `custom_03` | Account **tombstone** kept the customer's name, email and phone | `INCOMPLETE` + redact the tombstone (not delete it) | pass |
| `custom_04` | Account gone but an **enabled connector** can recreate the data | `INCOMPLETE` + `REPORT_ACTIVE_DATA_FLOW` → `DISABLE_DATA_FLOW` → `VERIFY_DATA_FLOW_DISABLED` | pass |
| `custom_05` | Fully remediated: profile absent, retained audit record present, support message and tombstone redacted | `COMPLETE` with verification steps only | pass |

The public samples contain **no** `NOT_APPLICABLE` case, so `custom_01` plus the
ten assessment requests in the evaluation set are the only coverage of that
outcome category. `custom_03` is the only coverage of "tombstone that must be
redacted rather than deleted" outside the sample set.

## 5. Full-dataset run

| Item | Value |
| --- | --- |
| Cases processed | 518 |
| Rows written | 518, sorted by `case_id`, header `case_id,deletion_status,steps_json` |
| Legality errors | 0 |
| Wall-clock time | ~5.6 s on a laptop CPU (deterministic, no network) |
| Distribution | `INCOMPLETE` 368, `COMPLETE` 140, `NOT_APPLICABLE` 10 |
| Median steps per case | 5 (range 0–17) |
| Non-`NOT_APPLICABLE` cases with `[]` | 0 |

The ten `NOT_APPLICABLE` rows are exactly the ten non-deletion requests in the
evaluation set (phone-number correction, marketing opt-out, data export, login
help, surname correction, marketing-list removal, subject-access request,
invoice copy, email change, information copy). The classifier is phrase-based and
multilingual, so this is a consequence of `request_text`, not of case ids.

## 6. Failures found and improvements made

1. **Temporal leakage (fixed).** Filtering on file capture time discarded
   readbacks that were *recorded* before `audit_at` but shipped in a bundle
   captured afterwards; nine cases lost their retained-audit verification. Now
   the cutoff is the event time, with a per-record preference for evidence that
   already existed at the audit time.
2. **System naming (fixed).** Steps used the physical location name
   (`support_replica`, `user_export_store`), which cost 37 field misses on the
   samples. The plan now names the owning service (`support_platform`,
   `export_service`); replica/store names are normalised.
3. **Category override (fixed).** A diagnostic line such as
   `deletion_marker_check` could reclassify a support *attachment* as a support
   *message*, turning `DELETE_RECORD` into `REDACT_RECORD`. Diagnostics no longer
   assert a category, and a resource's explicitly-named category now wins over a
   prefix-only guess (cost before: one whole case).
4. **Account attribution (fixed for 4 of 5 affected samples).** A deleted
   account leaves no profile row, so the record has to be recovered from the
   workflow stream. Greedy nearest-time assignment swapped two cases in the same
   batch and stole an account already linked to another customer. Assignment is
   now solved per `reported_at` batch, restricted to claims whose reported result
   matches the workflow status, and skips resources bound to another person.
5. **Evidence preference (fixed).** For an absent account the engine used the
   newest aggregate inventory export; the gold cites the account service's own
   capture or a per-user assurance bundle. Dedicated captures and per-user bundles
   now outrank aggregate inventories.
6. **German negation (fixed, found by a unit test).** `Bitte löschen Sie mein
   Konto nicht` was classified as a deletion request. Negations were added for
   German, French, Spanish, Portuguese and Italian, and the test suite now pins
   them.
7. **Unverified citations (fixed).** The legality checker proved that findings
   *had* an evidence id, not that the id existed. It now resolves every citation
   against the three id namespaces and fails on an unknown one; two unit tests
   cover the reject and accept paths.

### Remaining, known gaps (not fixed — reported as limitations)

* **Anonymised analytics records cannot be linked.** When an analytics profile
  has already been anonymised, the artefact contains no identifier at all
  (`email`, `phone`, `email_hash`, `customer_reference` are all `null`). The gold
  answer still knows which record belonged to which person. 12 of the 32 sample
  cases carry such a step and the engine reproduces 5 of them. This is the
  largest single class of remaining misses (7 sample cases). The engine reports
  anonymised records it can link and does not invent resource ids for the rest.
* **Some retained audit records have no participant-visible id.** For example
  `audit_record_6645` (sample `case_18`) appears nowhere in `dataset/`, yet the
  gold answer includes it. Dedicated readbacks, the shift-handover register and
  the SQL replicas are used whenever the id is visible: 22 of the 24 sample cases
  that carry a retained audit record are reproduced.
* **Batch-internal account ordering.** When several cases in one batch report the
  same status and their accounts are not named by any readback, the result-compatible
  claims are allocated in time order. One sample case (`case_23`) is ordered
  differently in the gold answer; the engine cannot distinguish those claims.

## 7. Reproducibility

The engine is deterministic: no sampling, no network, no model calls. The same
inputs produce byte-identical `output.csv` and the same metrics table, which is
what makes the numbers above re-printable by one command.
