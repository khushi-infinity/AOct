# Interview Preparation — 15 Questions and the Answers the Code Supports

Rule for the interview: quote only numbers the evaluator prints
(`code/evaluation/evaluation_report.md`). If a question goes beyond them, say what
the code does and label the rest as a limitation.

**Numbers that are safe to quote**

| Claim | Value |
| --- | --- |
| Deletion-status accuracy (32 public samples) | 1.0000 |
| Exact-array match | 0.6875 (22/32) |
| Step-sequence match | 0.7188 |
| Step precision / recall / F1 | 0.9402 / 0.8964 / 0.9178 |
| Field accuracy | 0.9230 |
| Baseline (everything `INCOMPLETE`, `[]`) | 0.6875 status, 0.0000 everything else |
| Full run | 518 rows, 0 legality errors, 5.6 s |
| Distribution | 368 INCOMPLETE / 140 COMPLETE / 10 NOT_APPLICABLE |
| Tests | 23 unit tests, 5 custom cases, all passing |
| Model calls / tokens / cost | 0 / 0 / $0.00 (measured) |

---

### Q1. Walk me through one case end to end.

Take `case_18`. The request is English and clearly authorises deletion, so intent
passes. `mori.ren@gmail.com` resolves to `user_50` through the current snapshot;
the audit trail adds any retired aliases. The evidence index has already parsed
all 94 artefacts into 2,540 observations; we keep the ones whose subject is
`user_50` and whose event time is at or before `audit_at` (2026-09-26). The latest
observation per record says: search index present, support message identifiable,
analytics profile identifiable, connector enabled, profile absent. Policy turns
that into four findings, then remediation (disable flow, delete index entry,
redact support message, anonymise analytics), then verification for each plus the
account and the retained security record. The planner sorts, numbers, and writes
one CSV row.

### Q2. Why deterministic instead of an LLM? What did you give up?

The corpus is structured enough that state can be reconstructed exactly, and the
deliverable must be reproducible and costed. An LLM in the scored path would make
the accuracy claim unreproducible and would put customer-like records in front of
a third party — for no gain here. What I gave up is graceful handling of prose I
did not anticipate: intent is a phrase grammar, so a novel phrasing of "actually
please don't delete me" in an unsupported language could slip through. That is
the honest cost, and it is why intent is the most heavily unit-tested module.

### Q3. How do I know your numbers are real?

Three commands, all in the report:

```bash
python3 code/main.py --requests dataset/sample_deletion_requests.csv --output /tmp/p.csv
python3 code/evaluation/main.py /tmp/p.csv --requests dataset/sample_deletion_requests.csv --gold dataset/sample_output.csv
python3 code/evaluation/main.py output.csv --requests dataset/deletion_requests.csv
```

Legality and accuracy print in separate blocks so "0 errors" can never be
mistaken for accuracy. The clean-room check is an unzip of `code.zip` into an
empty directory plus a copy of `dataset/`; it reproduces `output.csv`
byte-for-byte.

### Q4. Exact-case accuracy is 0.6875. Why isn't it higher?

Because two classes of step are not derivable from participant-facing data:

* an already-anonymised analytics record has all identifiers null, so nothing
  links it to a person — gold knows it from private truth (5 of 12 reproduced);
* some retained audit records (e.g. `audit_record_6645`) appear nowhere in
  `dataset/` — 22 of 24 reproduced.

Every one of the 32 statuses is correct, and no case contains a finding that
should not be there. I chose not to fabricate resource ids to inflate the score.

### Q5. Why is a tombstone redacted rather than deleted?

Because policy says so and because retained records still point at the stable
`user_id`. Rule 15 requires the reference to survive; name, email, phone and
email hash must not. Deleting the tombstone would orphan the legal and security
records that must be kept, which is why "delete everything" is the wrong answer
even when it feels thorough. `custom_03` pins this.

### Q6. How do you stop evidence captured after the audit time from leaking the answer?

Two mechanisms. First, the cutoff is on `observed_at` — the event inside the
artefact. Second, when two observations describe the same record, the one whose
file already existed at `audit_at` wins. That distinction matters because bundles
are shipped days after the events they contain; filtering on shipment time threw
away valid readbacks, and filtering on nothing let a later bundle outrank what an
auditor actually had. The preference is per record, so a record only mentioned in
a later bundle is still used instead of silently disappearing.

### Q7. A customer changed their email six months ago. What happens?

The identity graph indexes every historical email, phone and hash from
`user_audit_log.csv` — 4,553 keys over 850 identities — so the request resolves to
the same `user_id` regardless of which address they wrote from. `custom_02`
covers a request from a retired address whose surviving support message is keyed
by the current one.

### Q8. What stops a sync from recreating the data after you fix the record?

Findings include `REPORT_ACTIVE_DATA_FLOW` and `REPORT_RESTORE_RISK`, and the
planner puts `DISABLE_DATA_FLOW` and `BLOCK_RESTORE` first in remediation. A
deletion is only `COMPLETE` when no active path can recreate prohibited data,
which is why flows and backups are modelled as first-class records rather than
metadata. `custom_04` is an account that is gone but would come back through an
enabled connector.

### Q9. Why is remediation ordered the way it is?

Order is contractual: phase, then the published operation order, then
`system_id`, then `resource_id`. The semantic part is that stopping a flow or
blocking a restore precedes mutating records, so a subsequent sync cannot undo
the work. A unit test asserts `DISABLE_DATA_FLOW` comes before `DELETE_RECORD`
when both apply.

### Q10. What happens if OCR is unavailable?

`shutil.which("tesseract")` fails and every image prints
`WARNING: tesseract unavailable; skipping <file>`. The run continues and the
degradation is visible in stderr and in `RunStats.warnings` — never as a silent
empty record. Same for `pypdf` and PDFs. That was a deliberate rule: a missing
adapter must fail loudly, because a silent failure here looks exactly like
"record absent".

### Q11. How did you validate `NOT_APPLICABLE`? The samples contain none.

Three ways. The evaluation set contains ten non-deletion requests and all ten are
classified `NOT_APPLICABLE`, which is exactly the count the dataset notes predict.
`custom_01` is a German refusal ("Bitte löschen Sie mein Konto nicht"), which is
the case that caught a real bug: the first classifier treated it as deletion
because it matched the "löschen" stem. And the unit tests cover correction,
export, login-help, marketing opt-out and information-request phrasings.

### Q12. How do I know this isn't overfitted to the sample ids?

There is no request-id lookup anywhere: policy comes from `deletion_rules.csv`,
ordering from a published table, identity from the audit trail, and state from
artefacts. The one convention I use is the published `account_{numeric}` id
fallback, and it only fires when a batch has no workflow claim at all. When I
fixed cases I changed rules, not rows — the report lists each rule with the delta
it produced, including two regressions I kept.

### Q13. Token usage and cost?

Zero model calls, zero tokens, $0.00, measured not estimated — the run is
standard-library Python plus optional local PDF/OCR extraction.
`evaluation/usage_report.md` documents how a future model adapter would be
accounted (per-call JSONL ledger) and why it is not enabled for the scored run.

### Q14. What would you change for production scale?

Three things. (1) Promote the observation model into a shared contract so every
service emits `resource_id`, `category` and `observed_at` on deletion events —
most ambiguity here is missing event metadata, not missing evidence. (2) Keep a
deletion ledger per subject so the auditor does not have to infer accounts from
workflow claims. (3) Make evidence pulls incremental with an immutable per-day
snapshot; today the corpus is small enough that a full rebuild is cheaper and more
reproducible. None of that changes the policy layer, which is data.

### Q15. What is the weakest part of the system?

Attribution of deleted accounts when several cases in one batch share a status and
none of their accounts is named by a readback. Result-compatible claims are then
allocated in event-time order; gold orders one sample case differently, so one of
32 is wrong for that reason. Ranked second is the anonymised-analytics gap, which
is unfixable from participant data by construction. Third is intent coverage for
languages outside the phrase set. I would fix (1) with the event-metadata contract
above, (2) not at all without private truth, and (3) with a small classifier
trained on labelled refusal/authorisation phrases.

---

## Rapid-fire constants (be able to explain each)

| Constant | Where | Value | Why |
| --- | --- | --- | --- |
| `CLAIM_WINDOW_BEFORE` | `audit_agent.py` | 120 min | absorbs queueing before the workflow report |
| `CLAIM_WINDOW_AFTER` | `audit_agent.py` | 20 min | a claim after the report is an exception, not the rule |
| `_RESULT_BY_STATUS` | `audit_agent.py` | COMPLETE→SUCCESS, PARTIALLY_COMPLETE→PARTIAL, NOT_STARTED→FAILED | result compatibility used for attribution only |
| `AUTHORITATIVE_ORIGINS` | `evidence.py` | per-category origin sets | owning service outranks aggregate inventory |
| `PREFIX_CATEGORY` | `evidence.py` | 15 prefixes | fallback only; explicit categories override |
| `_PRESENT_STATES` | `policy.py` | 5 states | what counts as "still exists" for a delete rule |
| `OPERATION_ORDER` | `policy.py` | 0..5 per phase | reproduces the published ordering |
| `step_no` base | `planner.py` | 1 | contract |
