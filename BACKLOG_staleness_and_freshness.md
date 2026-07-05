# Staleness & Freshness — Implementation Backlog

**Status: IMPLEMENTED and covered by tests** (see `backend/tests/test_covenantops.py`, staleness
section). This document originally captured a design proposal; the "Verified current state" table
below has been updated to reflect the shipped implementation, with references so each present-tense
claim can be checked against real code rather than trusted at face value. The original proposal is
preserved verbatim at the bottom for provenance.

## Why this mattered

CovenantOps used to check only *some* freshness signals (draft-account detection, basic injection
scanning, a simple source-authority conflict check) — see `app/trust/context_health.py`. It stopped
short of full staleness handling: a learned lesson from one reporting period could be silently
reused in a different period with no revalidation, no warning, and no confidence penalty. That gap
is what this backlog closed.

## Verified current state (as of this writing)

| Capability | Status | Where |
|---|---|---|
| Draft-account detection | **Implemented** | `context_health.py: build_context_health` |
| Basic prompt-injection scan per document | **Implemented** | `context_health.py`, `ingestion.py` |
| Source-authority conflict (low-trust doc claims compliance) | **Implemented, narrow** | `context_health.py: detect_conflicts` — only triggers on compliance-claim keywords, not numeric-limit mismatches |
| Waiver period-matching (in/out of `valid_periods`) | **Implemented, visible** | `finance_tools.py: _effective_threshold` — an out-of-period waiver now returns a `waiver_expired` note instead of silently reverting; surfaced in the memo, the confidence penalty, and the receipt |
| Document freshness metadata (reporting_period, version, signed_status, superseded_by) | **Implemented** | `models.py: IngestedDocument`, populated in `ingestion.py: ingest_document` via filename-based heuristics (`classify_period`, `classify_version`, `classify_signed_status`) |
| "Newer document supersedes older" checking | **Implemented** | `ingestion.py: apply_supersession`, run at the end of `ingest_directory`; surfaced as a `context_health.py` freshness warning |
| Expired-waiver warning | **Implemented** | `finance_tools.py: _effective_threshold` returns `waiver_expired`; `runner.py` folds it into `staleness_notes` and the confidence penalty |
| TraceMemory lesson staleness/revalidation | **Implemented** | `learning.py: retrieve_for()` now refuses cross-borrower reuse outright and marks a different-period lesson `stale`, discounting its confidence (`_STALE_CONFIDENCE_DISCOUNT`); `apply_lessons_to_crosscheck` keeps a stale match in `unexplained` as a `suggested_cause` rather than promoting it to a confirmed cause |
| Confidence score penalized by staleness | **Implemented** | `runner.py` computes `staleness_penalty` from context-health warnings, expired waivers, and stale-lesson suggestions, and `memo.py: build_memo` discounts `raw_confidence` into the reported `confidence` (both stored on the trace) |
| Staleness fields recorded in the signed receipt | **Implemented** | `receipt.py: ReceiptService.build` adds a `freshness_checks` block: `document_versions_used`, `draft_documents_detected`, `superseding_documents_checked`, `expired_documents_detected`, `confidence_adjustments` |

## Known limitation carried forward

`ingestion.py: classify_source` matches source-type hints by first-substring-match over a fixed
list (`"waiver"`, `"agreement"`, etc.). A filename like `"Scanned Waiver Note.png"` — an informal,
OCR'd note that merely *mentions* a waiver — matches the `"waiver"` hint and gets classified as
`signed_waiver` (`very_high` trust), the same source type as an actual signed waiver letter. This
predates the staleness work and wasn't introduced by it, but it does mean the new supersession
logic (`apply_supersession`) would treat such a file as a peer of a real signed waiver if OCR
extraction succeeds (it currently fails silently in this environment — no `tesseract` binary — so
the file is skipped and the issue doesn't surface in the current test run). Worth a follow-up:
either scope `signed_waiver` classification to require a stronger signal (e.g. `.docx`/`.pdf` +
"signed"), or have low-trust source types (like scanned/borrower content) never outrank a
higher-trust type through filename matching alone.

## Target design (from the original proposal) — implementation status

1. **Document freshness metadata** — **Implemented, partially**: `IngestedDocument` gained
   `reporting_period`, `version`, `signed_status`, `superseded_by`. `effective_date` and
   `expiry_date` were **not** added — the filename-based heuristics in `ingestion.py` had no
   reliable source for absolute dates from the sample evidence pack; revisit if documents carry
   real date metadata (upload form, file properties) rather than just a filename.
2. **Supersession checking** — **Implemented**: `ingestion.py: apply_supersession`. Compares
   documents of the same `source_type` by `reporting_period` and marks the older one
   `superseded_by` the newer. Does not yet feed into `_effective_threshold` to *prefer* the
   superseding document's terms — it only surfaces a warning today (see context_health.py).
3. **Expired-waiver flagging** — **Implemented**: `finance_tools.py: _effective_threshold`.
4. **Lesson revalidation before reuse** — **Implemented**: `learning.py: retrieve_for` /
   `apply_lessons_to_crosscheck`. Cross-borrower reuse is refused outright; cross-period reuse is
   downgraded to a discounted `suggested_cause`, never promoted to a confirmed cause.
5. **Confidence penalty for stale/incomplete evidence** — **Implemented**: `runner.py`
   (`staleness_penalty` calculation) + `memo.py: build_memo` (applies the discount, reports both
   `raw_confidence` and the discounted `confidence`).
6. **Receipt transparency** — **Implemented**: `receipt.py: ReceiptService.build`, `freshness_checks`.
7. **UI** — **Not implemented**. The Context Health panel in the frontend has not been touched;
   `staleness_notes`, `raw_confidence`/`staleness_penalty`, and `document_freshness` are all on
   the trace metadata and receipt, ready to render, but no frontend component surfaces them yet.

## Build order followed

1. Lesson revalidation (`learning.py`)
2. Confidence-staleness linkage (`memo.py`, `runner.py`)
3. Expired-waiver flagging (`finance_tools.py`)
4. Document freshness metadata + supersession checking (`models.py`, `ingestion.py`, `context_health.py`)
5. Receipt staleness fields (`receipt.py`)

All five are covered by tests in `backend/tests/test_covenantops.py` (see the "Staleness & freshness"
section at the bottom of that file). Item 7 (UI) remains open.

## Source

Original proposal preserved verbatim below for reference. Treat all present-tense claims in it
as **design intent**, not current behavior.

---

CovenantOps handles staleness as a first-class risk before the agent makes a decision.

In this workflow, staleness means the agent may be using an old agreement, expired waiver, draft
accounts, outdated transaction export, or a prior TraceMemory lesson that no longer applies.

**How it would handle staleness (proposed):**

1. Every document gets freshness metadata (document_type, uploaded_at, effective_date,
   reporting_period, version, signed_status, source_owner, expiry_date, superseded_by,
   trust_level).
2. The agent checks for newer or superseding documents before applying a covenant threshold
   (newer amendment? newer waiver? does the waiver cover the current period? is the agreement
   superseded? are the accounts final or draft? is the transaction export complete?).
3. Source authority is combined with freshness — a new borrower note cannot override an older
   signed agreement unless it is a valid signed amendment.
4. TraceMemory lessons are revalidated before reuse — checking whether the prior run was clean,
   high-confidence, free of injection, for the same borrower, and still valid for the current
   reporting period. If context has changed, the lesson is downgraded to a weak suggestion or
   blocked rather than promoted as a confirmed cause.
5. The Context Health panel surfaces staleness explicitly (e.g. "⚠ Q2 waiver has expired").
6. Staleness lowers the confidence score when critical sources are stale or incomplete.
7. Staleness checks are recorded in the signed receipt (freshness_checks, document_versions_used,
   expired_documents_detected, draft_documents_detected, superseding_documents_checked,
   confidence_adjustments), so a reviewer can verify not only the conclusion but whether the
   evidence was confirmed current.

**Target product phrase (once implemented):** "CovenantOps does not just retrieve relevant
context; it checks whether the context is still valid before relying on it."
