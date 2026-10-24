# Prompt Pack

The prompts that drove this build, kept in the submission because the code alone
does not explain how the work was steered. They are short on purpose: a prompt
that dictates implementation produces code nobody can defend; a prompt that
fixes the contract and the definition of done produces decisions that can be
reviewed.

The canonical specification is [`../ENGAGEMENT-BRIEF.md`](../ENGAGEMENT-BRIEF.md).
The raw competition request is preserved in `../log.txt`.

---

## P1 — Engagement prompt (project kickoff)

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

## P2 — Calibration prompt (per iteration)

> Run the sample scorer and print the cause histogram. For the largest cause,
> identify the general rule that is wrong — not the case that is wrong. Implement
> the rule, re-measure, and report before/after for status, exact case, sequence,
> step F1 and field accuracy. Do not add any lookup keyed by case id or email.

## P3 — Hostile review prompt (pre-submission audit)

> Review `code/` as a hostile reviewer who wants this rejected. For each of:
> evidence parsing, identity resolution, temporal cutoff, account attribution,
> policy application, step ordering, and citation rules — name a concrete input
> that would produce a wrong verdict, say what the user would see, and propose the
> fix. Then check the submission artefacts: does `output.csv` satisfy the contract
> on all 518 rows, does a clean unzip reproduce it, and does any claim in the
> README exceed what the evaluator prints?

## P4 — Evaluation prompt (what the harness must prove)

> Produce numbers, not adjectives. Separate legality checks from accuracy
> metrics. Add at least three cases the sample set does not cover, and make them
> executable so they fail loudly when behaviour breaks. Report the gaps you could
> not close and their measured cost.

## P5 — Interview drill prompt (post-submission)

> Ask the 15 hardest questions a technical judge could ask about this system, from
> architecture to hostile ("why does your exact-case accuracy stop at 0.6875?").
> For each, give the answer the code actually supports, with the constant or
> command that proves it, and flag anything that is a limitation rather than a
> feature.

---

## Operating rules these prompts assume

| Rule | Source |
| --- | --- |
| Append-only transcript, failures included | `AGENTS.md` §2, §5 |
| No hardcoded labels or case-specific answers | `AGENTS.md` §6.7, brief C1 |
| Legality checks are never presented as accuracy | brief AC3–AC4 |
| Ambiguities recorded with alternatives | `DECISIONS.md` (ADR-001 … ADR-012) |
| Unknowable values are reported, not invented | ADR-010 |
