# Decisions

## Deterministic evidence engine

The submission will use a deterministic local evidence parser rather than a paid model call for the final run. The dataset is structured enough to reconstruct records from participant-facing artifacts, and determinism improves reproducibility, cost, and exact sequence ordering. Optional OCR/PDF extraction is treated as an evidence adapter and must warn clearly if unavailable.

Alternatives considered: a hosted LLM/VLM pipeline or a hybrid fallback. Those add cost, credentials, nondeterminism, and serialization risk. They remain possible future extensions but are not required for the supplied corpus.

## State at audit time

Only observations at or before `audit_at` can decide a case. For each logical resource, the latest grounded observation at or before the cutoff wins. Workflow status and activity results are retained as context but never override a later readback.

## Missing direct linkage

Some participant-facing readbacks prove that an account resource is absent but omit the subject identifier. The engine will first seek grounded linkage in current identities, historical identifiers, structured evidence, prior observations, and participant-visible activity. If only a candidate set remains, it will use a deterministic temporal/resource reconciliation heuristic and record this as a limitation rather than embedding a case-specific answer.

## Evidence preference

When multiple observations support the same current state, prefer the latest evidence captured at or before the cutoff. File evidence is preferred for present/absent state. Activity and audit IDs are used when they directly prove the required condition.

## Non-deletion requests

Explicit access, correction, export, login-help, and marketing-only requests are `NOT_APPLICABLE`, even if the workflow fields resemble deletion cases. Classification uses multilingual deletion and negation phrases, not case IDs. Negations are checked before deletion stems, in German, French, Spanish, Portuguese, Italian, Japanese, Korean, and Chinese as well as English; a unit test pins `Bitte löschen Sie mein Konto nicht` to `NOT_APPLICABLE` after an earlier version misclassified it.

## Event time, not shipment time

A readback bundle shipped on 2026-09-18 can describe events from 2026-09-16. The cutoff is therefore the event time. On top of that, when two observations describe the same record, the engine prefers the one whose file already existed at `audit_at`, because that is what an auditor could actually read. The preference is applied per record: if only a later capture mentions a record, it is still used (otherwise retained audit records would silently disappear).

## Account attribution

A successful deletion removes the profile row, so the account record has no readback to name it. It is recovered from `system_activity.csv`: claims are grouped by the case's `reported_at` batch, only claims whose `reported_result` matches the workflow status are preferred, a claim already bound to another person by direct evidence is never reused, and the remaining result-compatible claims are allocated in ascending event time. Alternatives considered: nearest-in-time (swapped two cases in the same batch) and case-order pairing (contradicted by the samples).

## Evidence ranking for absence

When a record is absent, which artefact proves it? A capture owned by the service that holds the record (`customer_account_failover_replica_capture`, `analytics_platform`, `customer_search_primary_capture`) and a per-user assurance bundle outrank an aggregate inventory export; among equally ranked candidates the newest before the cutoff wins. This is why an absent account is cited from the account-service replica rather than from a later system-wide inventory dump.

## System naming

Steps name the owning service, never the physical location: `support_replica` → `support_platform`, `user_export_store` → `export_service`. A marketing contact observed through `analytics_platform` keeps `analytics_platform`, because the record lives there. When an artefact only implies a category from the resource-name prefix, any artefact that names the record type explicitly overrides that guess; diagnostic lines (`deletion_marker_check`, `checkpoint_saved`) never assert a category at all.

## Unknowable identifiers are not invented

An already-anonymised analytics profile contains no identifier, and some retained audit records appear nowhere in `dataset/`. Those steps are omitted rather than filled with a guessed resource id. The measured cost of this decision is documented in `code/evaluation/evaluation_report.md` (section 6).

