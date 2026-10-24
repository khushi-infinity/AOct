# Architecture — Deletion Assurance Agent

Scope: how the auditor reaches a verdict, why the boundaries sit where they do,
and what fails when. Figures come from the delivered corpus: 850 identities,
4,553 identity keys, 2,540 evidence observations, 4,011 workflow claims,
94 artefacts, 1,588 resources, 19 data categories, 518 requests.

---

## 1. System context

```text
   ┌────────────────────────────┐        ┌──────────────────────────────┐
   │ Privacy operations         │        │ Deletion workflow (legacy)   │
   │ (requests, audit deadlines)│        │ claims: COMPLETE/PARTIAL/... │
   └─────────────┬──────────────┘        └──────────────┬───────────────┘
                 │ requests + audit_at                  │ claims (untrusted)
                 ▼                                      ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                 Deletion assurance agent                    │
        │   identity graph · evidence index · policy · plan builder    │
        └─────────────┬───────────────────────────────────────────────┘
                      │ findings + ordered remediation/verification
                      ▼
        ┌─────────────────────────────────────────────────────────────┐
        │ output.csv  (case_id, deletion_status, steps_json)          │
        └─────────────────────────────────────────────────────────────┘
                      ▲
                      │ normalised observations
        ┌─────────────┴───────────────────────────────────────────────┐
        │ Evidence corpus: JSON bundles, SQLite snapshots, 4 log       │
        │ dialects, text registers, PDFs, screenshots                  │
        └─────────────────────────────────────────────────────────────┘
```

The agent is an **auditor**, not a deleter: it never mutates the upstream systems.
Its only side effect is an ordered plan an operator (or the workflow) can execute.

## 2. Containers and responsibilities

| Container | File | Responsibility | Explicitly not responsible for |
| --- | --- | --- | --- |
| CLI / composition root | `code/main.py` | argument parsing, path resolution, exit status | business rules |
| Orchestrator | `code/audit_agent.py` | case loading, identity resolution, attribution, output writing, run stats | parsing, policy, ordering |
| Intent classifier | `code/audit/intent.py` | authorisation decision from free text | identity, evidence |
| Identity graph | `code/audit/identity.py` | alias closure over snapshot + audit trail | evidence linkage |
| Evidence index | `code/audit/evidence.py` | format adapters → one observation model; subject/category resolution | deciding compliance |
| Policy | `code/audit/policy.py` | `deletion_rules.csv` → required treatment triple | discovering records |
| Planner | `code/audit/planner.py` | canonical ordering, dedupe, numbering, citation rules | judging state |
| Evaluator | `code/evaluation/main.py` | legality vs accuracy, cause histogram | producing answers |
| Custom-case harness | `code/evaluation/custom_cases.py` | synthetic gap coverage | scoring the real corpus |

Dependency direction is strictly one-way:
`main → audit_agent → {intent, identity, evidence, policy, planner}`.
`policy` and `planner` never import `evidence`; the evidence layer never imports
`audit_agent`. That allows the planner to be unit-tested on fabricated facts with
no corpus at all, which is how the ordering rules are pinned.

## 3. The observation model (the load-bearing abstraction)

Everything the corpus can say is reduced to one immutable record:

```python
Observation(system_id, resource_id, category, state, observed_at,
            evidence_id, available_at, subjects, source)
```

Three separate timescales are kept apart on purpose:

| Field | Meaning | Why it is not merged |
| --- | --- | --- |
| `observed_at` | when the event inside the artefact happened | the state at `audit_at` is defined by event time |
| `available_at` | when the artefact was shipped/captured | an auditor could not read a future bundle, even if it describes older events |
| case `audit_at` | the legal cutoff | the only comparison baseline for a verdict |

`state` is a closed vocabulary (`PRESENT`, `ABSENT`, `IDENTIFIABLE`, `REDACTED`,
`ANONYMIZED`, `ACTIVE`, `DISABLED`, `BLOCKED`). Policy maps states → operations,
so no parser anywhere emits an operation name. That single rule is what keeps
format quirks from leaking into the graded output.

Subject linkage happens at parse time, not query time: each record's textual
payload is scanned for emails, phones, hashes and `user_NNN` references, resolved
through the identity graph, and frozen onto the observation. `resource_subjects`
then propagates a subject to every observation of the same resource, which is how
a readback that omits the identifier (a `404` with no email) still belongs to the
right person.

## 4. Evidence adapters

| Format | Adapter | Normalisation decisions |
| --- | --- | --- |
| JSON snapshot bundles | `_parse_json` / `_collection_record` | collection name decides category; a record's own fields decide state |
| Service exports (account, analytics, search, support, backup, security) | `_parse_service_export` | system/group pair decides category; explicit `null` identifiers mean anonymised |
| SQLite snapshot exports | `_parse_sql` | executed in memory, read-only; table name → category; replication variants handled |
| Logs (KV, JSON-line, bracket, pipe) | `_parse_text` / `_parse_line` | trace id groups a request's lines so a keyless completion inherits its subject |
| Shift-handover register | `_parse_handover` | pipe-delimited `time | system | resource | category | result | subject` |
| PDF | `_parse_media` (`pypdf`) | text is scanned for resource ids and identifiers |
| Screenshot | `_parse_media` (`tesseract`) | OCR text only; a multi-row table with many subjects is not paired positionally (ambiguity is refused, not guessed) |

Every adapter failure is loud: a missing dependency or unreadable artefact prints
`WARNING:` on stderr and is counted, never silently treated as "record absent".

## 5. Decision pipeline (per case)

```text
request_text ──► intent ──► NOT_APPLICABLE ──► []                     (stop)
                     │
                     ▼ authorised
email ──► identity graph ──► user_id + alias set
                     │
                     ▼
observations for subject, observed_at ≤ audit_at
     grouped by (system, resource) → prefer available_at ≤ audit_at → latest wins
                     │
                     ▼ one record per category
policy(deletion_rules) → compliant? ──► VERIFICATION (cited)
                     │
                     └── violating? ──► FINDING (cited) + REMEDIATION + VERIFICATION (uncited)
                     │
                     ▼
incomplete? ──► account attribution for deleted profiles (workflow claims)
                     │
                     ▼
canonical sort (phase → operation → system → resource) + numbering
```

### Account attribution

A successful deletion removes the profile row, so the account has no readback to
name it. The only trace is the workflow's own claim. Attribution therefore:

1. groups cases by `reported_at` (one deletion batch),
2. filters claims to the batch window, to unclaimed resources, and to resources
   not already bound to a different person by direct evidence,
3. prefers claims whose `reported_result` matches the case's `reported_status`,
4. allocates the remaining compatible claims in ascending event time,
5. falls back to the published `account_{user numeric}` convention when the batch
   contains no claim at all.

Steps 3–4 are the whole point: a greedy nearest-time assignment swaps two cases
that share a batch, and re-uses an account already proven to belong to someone
else. Both were observed on the public samples and are covered in the report.

### Absence evidence

When the record is absent, something must still prove it. Candidates are ranked by
`(tier, captured_at)` where `tier=1` for a capture owned by the holding service
(`customer_account_failover_replica_capture`, `analytics_platform`, …) or a
per-user assurance bundle, and `tier=0` for aggregate inventory exports. Rationale:
an inventory dump proves the record is missing from *a copy*; the owning service's
capture proves it is gone from the *source*.

## 6. Invariants (enforced, not aspirational)

| # | Invariant | Enforced by |
| --- | --- | --- |
| I1 | One row per request, sorted, exact header | `write_output` + legality checker |
| I2 | Exactly one record per data category per case | `facts_for` grouping |
| I3 | No observation from after `audit_at` influences a verdict | `facts_for` filter |
| I4 | Findings and `COMPLETE` steps always cite evidence; future steps never do | `plan_case` branches |
| I5 | `step_no` is consecutive from 1 and array order is significant | planner + checker |
| I6 | A category's owning service, not a replica name, appears in `system_id` | `canonical_system` |
| I7 | A diagnostic line cannot reclassify a record | explicit-category override in `_propagate` |
| I8 | Retained records are verified present, never deleted | policy `RETAIN` branch |
| I9 | Deterministic output | no randomness, no clock reads, no network |

## 7. Failure modes and behaviour

| Failure | Detection | Behaviour |
| --- | --- | --- |
| Missing evidence file | manifest path check | `WARNING`, artefact skipped, run continues |
| Corrupt JSON/SQL | `except` around a single artefact | `WARNING`, that artefact skipped |
| `pypdf` absent | `ImportError` | `WARNING` per PDF, no silent empty text |
| `tesseract` absent | `shutil.which` | `WARNING` per image |
| Identity unresolved | `resolve()` returns `None` | `WARNING`, case still emitted (status from whatever is provable) |
| No workflow claim for a deleted account | attribution returns nothing | published id convention fallback, counted in stats |
| Unknown data category | prefix table miss | record ignored; never guessed into a delete |

Nothing in the pipeline returns an empty list to hide an error: an empty step list
is only legal for `NOT_APPLICABLE`, and the legality checker enforces that.

## 8. Complexity and performance

Let `F` = artefacts, `R` = records across artefacts, `O` = observations,
`C` = cases, `K` = workflow claims.

| Stage | Time | Space | Measured |
| --- | --- | --- | --- |
| Parse corpus | `O(F + R)` | `O(O)` | 94 files → 2,540 observations |
| Identity index | `O(identities × aliases)` | `O(aliases)` | 850 → 4,553 keys |
| Per-case facts | `O(O)` worst case, hash-grouped | `O(O)` | 32 cases in ~0.9 s |
| Attribution | `O(K log K + C × K_batch)` | `O(K)` | 4,011 claims |
| Plan + serialise | `O(steps log steps)` | `O(steps)` | 518 cases total 5.6 s |

The full 518-case run is ~5.6 s wall clock on a laptop CPU with no network. There
is no incremental index because the corpus is small enough that a full rebuild is
cheaper than cache invalidation and strictly more reproducible.

## 9. Observability

* `RunStats`: cases, complete/incomplete/not-applicable, unresolved identities,
  attributed accounts, artefacts, observations.
* Every degradation prints a `WARNING:` line to stderr; the delivered run is
  silent by design and that silence is part of the acceptance check.
* The evaluator prints legality and accuracy in separate blocks so a clean
  legality run can never be mistaken for accuracy.

## 10. Test strategy

| Layer | Test | What it protects |
| --- | --- | --- |
| Unit | 23 tests in `code/tests/test_audit.py` | intent (incl. 6 refusal languages), policy per category, ordering, dedupe, identity aliases, cutoff, output contract |
| Scenario | 5 synthetic cases in `code/evaluation/custom_cases.py` | `NOT_APPLICABLE`, historical email, tombstone redaction, active connector, fully remediated case |
| Corpus | sample scorer, 32 labelled cases | status/exact/sequence/step/field accuracy + cause histogram |
| Contract | legality checker on 518 rows | schema, allowed operations, citation rules, ordering |
| Packaging | clean-room unzip + run | reproducibility of `output.csv` |

## 11. Extension points

* **New evidence format** — add an adapter that emits `Observation`; nothing
  downstream changes.
* **New data category** — add it to `CATEGORY_BY_COLLECTION`,
  `SYSTEM_BY_CATEGORY` and (if needed) a policy row; the prefix table is only a
  fallback.
* **New policy version** — replace `deletion_rules.csv`; no code change, because
  actions are data.
* **LLM/VLM assist** — would sit *before* the observation model (extractor), not
  in the decision path, so determinism and auditability survive. Deliberately not
  enabled: it would invalidate the reproducibility of the reported metrics.
