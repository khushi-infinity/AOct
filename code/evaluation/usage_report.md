# Token Usage and Cost Report

## Scope

This report describes the single final run that produced the submitted
`output.csv`: all 518 cases of `dataset/deletion_requests.csv` processed by
`code/main.py` on the participant's laptop.

## Summary

| Item | Value |
| --- | --- |
| Model providers | none |
| Model names | none (deterministic rule engine, no hosted or local LLM) |
| Model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Cases processed | 518 |
| Average tokens per request | 0.0 |
| Average tokens per case (incl. plan generation) | 0.0 |
| Estimated total cost | $0.00 |
| Estimated cost per request | $0.00 |

Per-model table (single row because no model is called):

| Provider | Model | Calls | Input tokens | Output tokens | Cost |
| --- | --- | --- | --- | --- | --- |
| — | — | 0 | 0 | 0 | $0.00 |

## Why there are zero tokens

The agent is a deterministic evidence engine, not a prompting pipeline:

1. `audit/intent.py` classifies the request with a curated multilingual phrase
   grammar (deletion verbs and negation patterns).
2. `audit/identity.py` resolves current and historical identifiers from
   `user_identities.csv` and `user_audit_log.csv`.
3. `audit/evidence.py` normalises every participant-facing artefact into
   timestamped observations: JSON snapshot bundles, service exports, SQLite
   snapshot exports, several log syntaxes, plain-text registers, PDFs (`pypdf`
   text extraction) and screenshots (`tesseract` OCR, when installed).
4. `audit/policy.py` applies `deletion_rules.csv` to the reconstructed state at
   `audit_at`, and `audit/planner.py` orders findings, remediation and
   verification.

None of those steps sends data to a model. A hosted LLM/VLM pipeline was
considered and rejected (see `DECISIONS.md`): the corpus is structured enough to
reconstruct the state exactly, the run must be reproducible and re-scorable, and
sending customer-like records to a third-party model would need a data-processing
justification the challenge does not require us to take on.

## Local compute used instead of tokens

| Resource | Usage |
| --- | --- |
| CPU time | ~5.6 s wall clock for 518 cases |
| Network requests | 0 |
| API keys / credentials | none required, none present in the submission |
| Optional dependencies | `pypdf` (PDF text), `tesseract` (screenshot OCR); both local, both warn loudly on stderr if missing |

## How this would be accounted if a model were enabled

The engine keeps every model-facing artefact (prompt text, options) in source
code, so an enabled LLM/VLM adapter would log provider, model name, call count,
prompt and completion tokens per call into a JSONL ledger and aggregate it here.
That adapter is intentionally not part of the submitted run; adding one would
make the reported accuracy impossible to reproduce offline.

## Honesty note

The zeros above are measured facts of the final run, not an omission: the same
`output.csv` is regenerated bit-for-bit by `python3 code/main.py` with no network
access and no credentials.
