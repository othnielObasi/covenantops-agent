"""Self-improvement for CovenantOps Agent: learn to attribute causes across runs.

Loop: after a run, reflect on unexplained transactions and curate a lesson; on
later runs, retrieve relevant lessons to attribute previously-unexplained causes,
raising confidence over time.

Poisoning gate (the security-relevant part): a lesson is only promoted if the run
it came from was clean (no guard block) and not low-confidence. A blocked or
low-confidence run CANNOT teach — this breaks the injection -> poisoning chain.

Staleness scope (revalidated at RETRIEVAL time, not just recorded at write time):
each lesson records the borrower and period it was learned for. A lesson fetched
for a different borrower is refused outright (cross-borrower reuse is a
correctness bug, not a confidence question). A lesson fetched for a different
period is stale: it is never silently applied as a confirmed cause — it comes
back as a discounted suggestion that still requires human revalidation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models import ExecutionTrace, GuardPath, Lesson, new_id

# A lesson is trusted enough to promote only above this confidence.
_MIN_PROMOTE_CONFIDENCE = 0.5

# A stale lesson (wrong period) is downgraded to this fraction of its original
# confidence and surfaced as a suggestion rather than a confirmed cause.
_STALE_CONFIDENCE_DISCOUNT = 0.4


@dataclass
class LessonMatch:
    lesson: Lesson
    stale: bool
    effective_confidence: float


class LessonStore:
    """In-memory lesson playbook (persisted via trust.store in production)."""
    def __init__(self):
        self._lessons: List[Lesson] = []

    def add(self, lesson: Lesson) -> None:
        self._lessons.append(lesson)

    def all(self) -> List[Lesson]:
        return list(self._lessons)

    def for_transaction(self, txn_type: str, borrower: Optional[str] = None) -> Optional[Lesson]:
        # A lesson learned for a different borrower is never a candidate match —
        # this isn't staleness, it's a correctness boundary.
        matches = [
            l for l in self._lessons
            if l.transaction_type == txn_type and (borrower is None or l.borrower is None or l.borrower == borrower)
        ]
        # most recent matching lesson wins
        return matches[-1] if matches else None

    def clear(self) -> None:
        self._lessons.clear()


class SelfImprovement:
    def __init__(self, store: Optional[LessonStore] = None):
        self.store = store or LessonStore()

    def reflect_and_curate(self, trace: ExecutionTrace) -> List[Lesson]:
        """Derive lessons from unexplained transactions in a run, applying the
        poisoning gate. Returns the lessons that were actually promoted."""
        # POISONING GATE 1: a run that was guard-blocked cannot teach.
        blocked = any(tc.guard.decision.value == "block" for tc in trace.tool_calls)
        if blocked:
            return []

        confidence = float(trace.metadata.get("confidence", 1.0))
        # POISONING GATE 2: a low-confidence run cannot promote lessons.
        if confidence < _MIN_PROMOTE_CONFIDENCE:
            return []

        promoted: List[Lesson] = []
        findings = trace.metadata.get("findings", [])
        borrower = trace.metadata.get("borrower")
        for f in findings:
            cc = f.get("cross_check")
            if not cc:
                continue
            for u in cc.get("unexplained", []):
                # Reflect: the agent proposes an attribution for the unexplained txn type.
                # (Deterministic here; a live model can supply this reasoning.)
                txn_type = u.get("type", "unclassified")
                lesson = Lesson(
                    id=new_id("lesson"),
                    source_trace_id=trace.id,
                    borrower=borrower,
                    covenant_type=f["covenant"],
                    transaction_type=txn_type,
                    cause="intercompany transfer previously reviewed and classified as debt-neutral treasury movement",
                    confidence=confidence,
                    valid_for_period=self._period_of(trace),
                    provenance=f"reflection:{trace.id}",
                )
                self.store.add(lesson)
                promoted.append(lesson)
        return promoted

    def retrieve_for(self, txn_type: str, current_period: Optional[str] = None,
                     borrower: Optional[str] = None) -> Optional[LessonMatch]:
        """Retrieve a relevant lesson for a transaction type, revalidated against
        the current period. A lesson for a different borrower is not returned at
        all. A lesson for a different period comes back marked stale, with its
        confidence discounted, so the caller cannot silently treat it as confirmed."""
        lesson = self.store.for_transaction(txn_type, borrower=borrower)
        if lesson is None:
            return None
        stale = (
            current_period is not None
            and lesson.valid_for_period is not None
            and lesson.valid_for_period != current_period
        )
        effective_confidence = lesson.confidence * (_STALE_CONFIDENCE_DISCOUNT if stale else 1.0)
        return LessonMatch(lesson=lesson, stale=stale, effective_confidence=round(effective_confidence, 2))

    @staticmethod
    def _period_of(trace: ExecutionTrace) -> Optional[str]:
        findings = trace.metadata.get("findings", [])
        for f in findings:
            p = f.get("ratio", {}).get("period")
            if p:
                return p
        return None


def apply_lessons_to_crosscheck(cc: Dict, improver: "SelfImprovement", current_period: Optional[str] = None,
                                borrower: Optional[str] = None) -> Dict:
    """Given a cross-check result, use learned lessons to attribute previously
    unexplained transactions, raising confidence. A fresh (same-period) lesson is
    promoted to a confirmed cause. A stale (different-period) lesson is NOT — it
    stays in `unexplained` with a `suggested_cause` and `suggestion_stale=True`,
    so a human reviewer sees it without the agent silently trusting it."""
    if not cc.get("unexplained"):
        return cc
    still_unexplained = []
    newly_explained = list(cc.get("matched", []))
    stale_suggestions = 0
    for u in cc["unexplained"]:
        match = improver.retrieve_for(u.get("type", "unclassified"), current_period, borrower)
        if match is None:
            still_unexplained.append(u)
        elif not match.stale:
            newly_explained.append({**u, "cause": match.lesson.cause + " [learned]",
                                     "learned_confidence": match.effective_confidence})
        else:
            stale_suggestions += 1
            still_unexplained.append({
                **u,
                "suggested_cause": match.lesson.cause,
                "suggestion_stale": True,
                "suggestion_confidence": match.effective_confidence,
                "suggestion_learned_for_period": match.lesson.valid_for_period,
            })
    total = len(newly_explained) + len(still_unexplained)
    confidence = round(len(newly_explained) / total, 2) if total else 1.0
    return {
        **cc,
        "matched": newly_explained,
        "unexplained": still_unexplained,
        "confidence": confidence,
        "explanation_count": len(newly_explained),
        "unexplained_count": len(still_unexplained),
        "stale_suggestions": stale_suggestions,
    }
