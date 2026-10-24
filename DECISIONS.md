# Architecture Decision Record

Format: context → decision → alternatives rejected → consequences.
Each record is written to be defensible in review, not to advertise the solution.

Legend: **Status** is *Accepted* unless stated otherwise. **Evidence** points at
the artefact that shows the decision's measured effect.

---

## ADR-001 — Deterministic local evidence engine instead of hosted inference

**Context.** The corpus is structured (JSON bundles, SQLite exports, four log
dialects, PDFs, screenshots). The scored artefact must be reproducible, costed
honestly, and explainable line by line.

**Decision.** Reconstruct state with deterministic parsers. Optional local
extraction (pypdf, tesseract) is limited to *reading* artefacts. No model call
sits in the scored path.

**Alternatives rejected.**
*Hosted LLM/VLM pipeline* — nondeterministic, requires credentials in the
submission, makes the reported accuracy unreproducible, and sends customer-like
records to a third party for no accuracy gain on structured evidence.
*Hybrid with LLM fallback* — the worst of both: nondeterminism plus a hidden
dependency, and a silent degradation path that would mask parser gaps.

**Consequences.** Zero tokens, $0 cost, 5.6 s for 518 cases, byte-identical
output on re-run. Accepted cost: no semantic reading of free text beyond the
intent grammar, so unusual wording relies on the phrase model in ADR-011.

---

## ADR-002 — Event time defines state; capture time only ranks evidence

**Context.** A readback bundle shipped on 2026-09-18 can describe events from
2026-09-16. Filtering on capture time discarded legitimate readbacks; filtering
only on event time let later bundles outrank the evidence an auditor actually had.

**Decision.** The cutoff is `observed_at ≤ audit_at`. When two observations
describe the same record, prefer the one whose `available_at ≤ audit_at`.
The preference is applied **per record**, not per case.

**Alternatives rejected.**
*Capture-time cutoff* — loses retained-audit verifications that were recorded in
time but shipped later.
*Global contemporaneous filter* — over-corrects: a record mentioned only by a
later bundle disappears entirely.

**Consequences.** Sample step F1 0.7692 → 0.8602 → 0.9178 across the two
corrections. **Evidence:** `code/evaluation/evaluation_report.md` §3, rounds 2–4.

---

## ADR-003 — Workflow status is a claim, never proof

**Context.** The inciting incident is exactly this: dashboards said Complete.

**Decision.** `reported_status` and `reported_result` may *locate* the deletion
that belongs to a case (ADR-005) but never decide compliance. State comes from a
readback: a lookup returning 404, a snapshot with no matching row, a tombstone
with populated identifiers, an enabled connector, an unrestorable backup.

**Alternatives rejected.** Trusting the status for COMPLETE cases — would have
scored 0 on the sample set's deliberately broken cases.

**Consequences.** Findings are evidence-backed and gradeable. Cost: attribution
complexity for deleted accounts (ADR-005).

---

## ADR-004 — Identity is a closure over the audit trail, not the snapshot

**Context.** Requests arrive from retired addresses (the incident's own ghost
customer re-registered months later). The snapshot holds one current email per
person.

**Decision.** Build an index over current values plus every historical
email/phone/hash in `user_audit_log.csv`; normalise case-insensitively (NFKC,
invisible-character stripping); compare phones on digits only; treat shared keys
as ambiguous but deterministic.

**Alternatives rejected.** Snapshot-only matching — misses every record keyed by
an older value, which is a silent false "COMPLETE".

**Consequences.** 4,553 keys over 850 identities. `custom_02` pins the behaviour.

---

## ADR-005 — Attribute deleted accounts per workflow batch, by result compatibility

**Context.** A successful deletion leaves no profile row, so the account resource
has no readback to name it. The only trace is the deletion worker's claim.

**Decision.** Group cases by `reported_at`; restrict claims to the batch window,
to unclaimed resources, and to resources not bound to another person by direct
evidence; prefer claims whose result matches the case's reported status; allocate
the remaining compatible claims in ascending event time; fall back to the
published `account_{numeric}` convention only when the batch has no claim.

**Alternatives rejected.**
*Nearest claim in time* — swapped two cases in one batch (sample 28/29) and stole
an account already linked to a different customer by the handover register.
*Case-order pairing* — contradicted by the samples (claim order is not case order).
*Do not attribute* — loses the account record entirely for every deleted profile.

**Consequences.** 4 of 5 broken sample attributions fixed. Residual ambiguity is
documented (report §6) rather than papered over.

---

## ADR-006 — Absence is proven by the owning service, not by an inventory dump

**Context.** For an absent record any complete snapshot arguably proves absence.
The gold answers consistently cite the service's own capture or a per-user bundle.

**Decision.** Rank absence evidence by `(tier, captured_at)`; `tier=1` for
`AUTHORITATIVE_ORIGINS` and per-user assurance bundles, `tier=0` otherwise.

**Alternatives rejected.** Newest-file-wins — cited a system-wide inventory
export where a dedicated account-service capture existed; cost measurable field
accuracy on COMPLETE cases.

**Consequences.** `field_accuracy` 0.9223 → 0.9230 and one exact case recovered,
with no case regressed.

---

## ADR-007 — Steps name the owning service; explicit category beats prefix guess

**Context.** Artefacts say `support_replica`, `user_export_store`,
`customer_profiles_failover_replica`. The graded `system_id` is the logical
owner. Separately, a diagnostic line (`deletion_marker_check`) about a support
attachment was reclassifying the record as a support message, turning a required
delete into a redact.

**Decision.** Normalise replica/store names to owning services
(`SYSTEM_ALIASES` + suffix stripping). Diagnostics never assert a category. If any
artefact names a resource's category explicitly, it overrides a prefix-only guess
for that resource.

**Alternatives rejected.** Using the physical store name (wrong taxonomy);
letting the latest line win regardless of strength (the bug above).

**Consequences.** System-id field misses 37 → 19 on the samples; one whole case
corrected. **Evidence:** report §3 round 3, §6 item 3.

---

## ADR-008 — Policy is data, not code

**Context.** `deletion_rules.csv` is the client's policy and may be revised.

**Decision.** Load category → action from the CSV at startup; keep the
state → operation mapping in one table. No rule text is hardcoded per category
except when the completeness definition requires it (active flows and restore
paths, which the CSV does not enumerate).

**Alternatives rejected.** Encoding policy as `if category == ...` branches —
would make a policy change a code change and invite case-specific hacks.

**Consequences.** A new policy version is a file swap. Derived rules are labelled
as derived in `Policy._derived_action`.

---

## ADR-009 — One record per data category per case

**Context.** A person can have several support messages, exports or backups.

**Decision.** `facts_for` returns the latest grounded record per category.

**Alternatives rejected.** Emitting every record — the gold answers describe one
record per category, and extra steps lower step precision without adding truth.

**Consequences.** Deterministic, matches sample shape. Accepted risk: a case whose
gold answer lists two records in one category would score one step short.

---

## ADR-010 — Never invent an identifier to fill a gap

**Context.** Two classes of step are not derivable from participant-facing data:
an already-anonymised analytics record (all identifiers null) and some retained
audit records that appear nowhere in `dataset/`.

**Decision.** Omit the step and report the gap. No placeholder resource ids.

**Alternatives rejected.** Emitting a guessed `analytics_NNNN` to align step
counts — would inflate apparent sequence accuracy with fabricated evidence,
which is the failure mode this programme exists to punish.

**Consequences.** Documented, quantified in report §6: 5/12 anonymised steps,
22/24 retained audit records reproduced.

---

## ADR-011 — Authorisation is classified with negation-first multilingual phrases

**Context.** `request_text` arrives in many languages and some messages are
access, correction, export, login-help or marketing-only requests that must be
`NOT_APPLICABLE` even when the workflow fields look like deletion.

**Decision.** Check withdrawal/negation patterns before deletion stems; stems are
language-aware (Latin, Japanese, Korean, Chinese, Arabic). Empty text is not a
deletion request.

**Alternatives rejected.** Keyword list on "delete" — misclassifies
"Do not delete my account" and the German "Bitte löschen Sie mein Konto nicht"
(which a unit test caught after the first version shipped it as deletion).

**Consequences.** 10/10 non-deletion requests in the evaluation set classified
correctly; `custom_01` pins the German case.

---

## ADR-012 — Canonical ordering and deterministic serialisation

**Context.** Array order is graded; key order and whitespace are not.

**Decision.** Sort by phase → published operation order → `system_id` →
`resource_id`; number from 1 per case; serialise compactly with `ensure_ascii`
disabled and `\n` line endings.

**Alternatives rejected.** Emitting in discovery order — non-deterministic across
parser changes and wrong by contract.

**Consequences.** Byte-identical re-runs; sequence accuracy is a meaningful metric
rather than noise.
