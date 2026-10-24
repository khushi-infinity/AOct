# Prompt Pack

The prompts that steered this build. They are kept in the submission because the
code alone does not explain how the work was directed, and because a reviewer
auditing an agent should be able to audit the instructions as well as the output.

Two properties matter more than length:

1. **A prompt fixes the contract, not the implementation.** A prompt that dictates
   code produces code nobody can defend in an interview; a prompt that fixes the
   definition of done and the evidence standard produces decisions that can be
   reviewed.
2. **Every prompt ends in something executable** — a metric, a test, a byte-identical
   reproduction, an exit status. Prompts that end in prose produce prose.

The canonical specification is [`../ENGAGEMENT-BRIEF.md`](../ENGAGEMENT-BRIEF.md);
the raw competition request is preserved in `../log.txt`.

---

## Index

| # | Phase | Prompt | Produces |
| --- | --- | --- | --- |
| P1 | 0 — Scope | Engagement | the working agreement and non-negotiables |
| P2 | 0 — Scope | Output contract extraction | a checkable contract, not a paragraph |
| P3 | 1 — Understand | Corpus reconnaissance | the adapter inventory before any adapter code |
| P4 | 1 — Understand | Identity model | alias-closure rules and their normalisation |
| P5 | 2 — Build | Evidence adapters | one observation model, no operations from parsers |
| P6 | 2 — Build | Policy and planner | treatment triples, canonical ordering |
| P7 | 3 — Measure | Calibration loop | cause histogram → general rule → delta |
| P8 | 3 — Measure | Regression triage | a revert or a written defence, never silence |
| P9 | 3 — Measure | Legality vs accuracy | two separate scoreboards that cannot be conflated |
| P10 | 4 — Harden | Hostile review | named inputs that break the verdict |
| P11 | 4 — Harden | Gap cases | executable synthetic cases the sample set lacks |
| P12 | 4 — Harden | Determinism and cost | byte-identical re-runs, measured runtime |
| P13 | 5 — Ship | Packaging and clean room | a zip that passes on a machine that has never seen it |
| P14 | 5 — Ship | Claim audit | every documented number reproducible from a command |
| P15 | 6 — Defend | Interview drill | code-grounded answers to the hardest questions |

---

## Phase 0 — Scope

### P1 — Engagement prompt (project kickoff)

> You are auditing a deletion-assurance programme for Northstar Shop. Read
> `ENGAGEMENT-BRIEF.md`, `AGENTS.md` and `problem_statement.md` in full before
> writing code.
>
> Build the auditor described in the brief against the corpus in `dataset/`.
> Non-negotiables: reported workflow statuses are claims, not proof; state is
> reconstructed at each case's `audit_at`; every finding cites participant-visible
> evidence; retained records stay retained; the output contract is exact.
>
> Work from measurements, not impressions. Establish a baseline, then for every
> change re-run the scorer and report the delta. When a change makes a metric
> worse, say so and either revert it or explain why it is still right.
>
> Log every turn to `log.txt` in the `AGENTS.md` format, append-only, failures
> included.

### P2 — Output contract extraction

> Before implementing anything, restate `output.csv` as a machine-checkable
> contract: column names and order, the closed set of `deletion_status` values,
> the closed set of `phase` and `operation` values, the required step fields, the
> ordering key, numbering, citation rules, and line-ending/encoding expectations.
> Then write the checker that enforces that contract and prove it fails on a
> deliberately malformed row. A contract you cannot fail is a wish.

**Done when:** the checker rejects a bad row with a non-zero exit status and the
real output passes with zero errors.

---

## Phase 1 — Understand the corpus

### P3 — Corpus reconnaissance

> Inventory `dataset/` before writing a single adapter: every file, its format,
> its dialect, what identifiers it carries, and which of the 19 data categories it
> can speak for. Produce a table of *format → what it can prove → who owns the
> record*. Where two artefacts disagree about the same record, say which one wins
> and why. Do not write parsing code until the table is complete — an adapter
> written before the inventory encodes the first artefact's quirks as if they were
> the schema.

**Done when:** every file in the corpus maps to exactly one adapter and one owner.

### P4 — Identity model

> Requests arrive from addresses that no longer exist. Build identity as a
> closure over the audit trail, not as a lookup in the snapshot: current values
> plus every historical email, phone and hash, normalised (NFKC, invisible
> characters stripped, phones compared on digits only). State the normalisation
> rules as a table, then pin each rule with a test that fails if it regresses.
> Treat a key shared by two people as ambiguous-but-deterministic and say in the
> report what that ambiguity costs.

---

## Phase 2 — Build

### P5 — Evidence adapters

> Every format gets one adapter that emits the shared `Observation` record —
> system, resource, category, state, event time, capture time, subjects, evidence
> id. Parsers must never emit an operation name: state is the only vocabulary
> they know, because operation is a policy decision made later. A parser that
> cannot decide is allowed to say so (a warning on stderr, counted), never to
> guess. Where an artefact asserts a category explicitly it outranks any guess
> derived from a resource-name prefix.

**Done when:** adding a new format touches one file and no decision logic.

### P6 — Policy and planner

> Load treatment from `deletion_rules.csv` at runtime — policy is data, so a
> policy revision is a file swap, not a code change. Derive only what the rules
> genuinely do not cover, and label those derivations as derived. The planner
> takes facts and returns steps: phase, then the published operation order, then
> system, then resource; numbered from 1; findings cite evidence, future work does
> not. Keep the planner free of imports from the evidence layer so it can be
> tested on fabricated facts with no corpus present.

---

## Phase 3 — Measure

### P7 — Calibration loop (per iteration)

> Run the sample scorer and print the cause histogram. For the largest cause,
> identify the general rule that is wrong — not the case that is wrong. Implement
> the rule, re-measure, and report before/after for status, exact case, sequence,
> step F1 and field accuracy. Do not add any lookup keyed by case id or email.

### P8 — Regression triage

> A metric just dropped. Do not ship it and do not silently revert it. Bisect the
> last change, name the mechanism that broke, and choose one of three outcomes,
> written down either way: revert, or keep with a stated reason the loss is the
> correct trade, or split the change so the profitable half survives. Record the
> incident in the failure history with the number it cost — a log that shows only
> successes is not evidence of measurement.

### P9 — Legality versus accuracy

> Keep two scoreboards and never let one stand in for the other. Legality answers
> "does the file obey the contract" — schema, closed vocabularies, ordering,
> citation resolution, evidence rules. Accuracy answers "is it right" — against
> gold answers. Report both, labelled, and add a test that proves an illegal file
> is rejected even when its contents look plausible.

**Done when:** an injected bad citation exits non-zero while the real file exits 0.

---

## Phase 4 — Harden

### P10 — Hostile review (pre-submission audit)

> Review `code/` as a hostile reviewer who wants this rejected. For each of:
> evidence parsing, identity resolution, temporal cutoff, account attribution,
> policy application, step ordering, and citation rules — name a concrete input
> that would produce a wrong verdict, say what the user would see, and propose the
> fix. Then check the submission artefacts: does `output.csv` satisfy the contract
> on all 518 rows, does a clean unzip reproduce it, and does any claim in the
> README exceed what the evaluator prints?

### P11 — Gap cases

> Write the cases the sample set does not cover, as executable checks rather than
> prose: a refusal in a language the sample set lacks, a request that is access
> rather than deletion, a record already anonymised so no identifier survives, a
> system that would silently recreate deleted data, and a fully remediated case
> that must stay COMPLETE with no findings. Each case must fail loudly if
> behaviour regresses. Then state which gaps these cases still do not close.

### P12 — Determinism and cost

> Prove the run is boring: identical input produces byte-identical output across
> runs and across machines, no network access is required, no credential is read,
> and the runtime is measured and reported rather than assumed. If a step is
> optional (OCR, PDF extraction), make its absence loud and counted instead of
> silent — a degraded run that looks healthy is worse than a failed run.

**Done when:** two runs hash the same file and the measured runtime is on record.

---

## Phase 5 — Ship

### P13 — Packaging and clean room

> Build the zip from an empty directory: what the brief asks for, nothing else —
> no datasets, no caches, no virtualenvs, no nested archives, no secrets, no
> build artifacts. Then unpack it into a fresh directory on a machine that has
> never seen this project, run the full verification there, and diff the generated
> output against the submitted one. If the clean room and the author's directory
> disagree, the submission is wrong regardless of what the author's directory says.

### P14 — Claim audit

> Walk every number in the README, the reports and the architecture document. For
> each, name the command that reproduces it and run that command. Where a claim
> has no command, delete or downgrade the claim — do not soften it into something
> that happens to be true. Documentation that cannot be executed is marketing.

---

## Phase 6 — Defend

### P15 — Interview drill (post-submission)

> Ask the 15 hardest questions a technical judge could ask about this system, from
> architecture to hostile ("why does your exact-case accuracy stop at 0.6875?").
> For each, give the answer the code actually supports, with the constant or
> command that proves it, and flag anything that is a limitation rather than a
> feature. Answers that are not grounded in the file on disk are counted as wrong.

**Companion:** [`interview-prep.md`](./interview-prep.md) holds the questions and
the code-grounded answers.

---

## Operating rules these prompts assume

| Rule | Source |
| --- | --- |
| Append-only transcript, failures included | `AGENTS.md` §2, §5 |
| No hardcoded labels or case-specific answers | `AGENTS.md` §6.7, brief C1 |
| Legality checks are never presented as accuracy | brief AC3–AC4 |
| Ambiguities recorded with alternatives | `DECISIONS.md` (ADR-001 … ADR-012) |
| Unknowable values are reported, not invented | ADR-010 |
| Quality claims must be executable | brief AC8, `Makefile`, CI workflow |

## Why the prompts look like this

The failure mode this pack is written against is the common one: a long, eager
prompt that names files, functions and algorithms produces a confident solution
nobody can interrogate, and a transcript that reads like dictation. Short prompts
with a hard acceptance condition push the reasoning into the artefacts — a
histogram, an exit status, a hash — where a reviewer can check it. That is also
how the interview is answered: not "we decided", but "here is the command".
