"""
Queue state machine — Route 4.

Directive §4. The autonomous run terminates here for each vacancy. It does not
block, prompt, or wait.

    PENDING  ->  APPROVED | REJECTED | FLAGGED | UNREACHABLE
    FLAGGED  ->  PENDING  | REJECTED
    UNREACHABLE -> PENDING (manual override) | REJECTED (archive)
    APPROVED ->  DISPATCHED | REJECTED
    REJECTED ->  terminal
    DISPATCHED -> terminal

**Only APPROVED is eligible for dispatch.** Enforced by `is_dispatchable()`
and again by the transition table, which permits DISPATCHED from no other
state.

Illegal transitions raise. The alternative — logging and continuing — would
let a vacancy reach dispatch by a path nobody designed, and the audit trail
would show a state sequence that cannot be explained.

Every transition is appended to `transitions`, never overwritten. Status and
transition are written in one database transaction, so the audit trail cannot
diverge from the record it describes.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from vanguard.store import Store, StoreError

__all__ = ["Status", "IllegalTransition", "QueueManager", "LEGAL"]


class Status(str, Enum):
    PENDING = "PENDING"
    FLAGGED = "FLAGGED"
    UNREACHABLE = "UNREACHABLE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPATCHED = "DISPATCHED"

    @property
    def terminal(self) -> bool:
        return self in (Status.REJECTED, Status.DISPATCHED)

    @property
    def needs_operator(self) -> bool:
        return self in (Status.PENDING, Status.FLAGGED, Status.UNREACHABLE)

    @property
    def set_autonomously(self) -> bool:
        """States the unattended run may write. It never approves or dispatches."""
        return self in (Status.PENDING, Status.FLAGGED, Status.UNREACHABLE)


# Adjacency. Anything absent is illegal by construction rather than by check.
LEGAL: dict[Status, frozenset[Status]] = {
    Status.PENDING: frozenset(
        {Status.APPROVED, Status.REJECTED, Status.FLAGGED, Status.UNREACHABLE}
    ),
    # A resolved ambiguity returns to review, not straight to dispatch.
    Status.FLAGGED: frozenset({Status.PENDING, Status.REJECTED}),
    # Manual override is permitted: an UNREACHABLE vacancy has told the operator
    # something true, and they may still choose to apply.
    Status.UNREACHABLE: frozenset({Status.PENDING, Status.REJECTED}),
    Status.APPROVED: frozenset({Status.DISPATCHED, Status.REJECTED}),
    Status.REJECTED: frozenset(),
    Status.DISPATCHED: frozenset(),
}


class IllegalTransition(ValueError):
    """A state change the machine does not permit."""

    def __init__(self, current: Status, requested: Status) -> None:
        allowed = ", ".join(sorted(s.value for s in LEGAL[current])) or "none (terminal)"
        super().__init__(
            f"illegal transition {current.value} -> {requested.value}. "
            f"Permitted from {current.value}: {allowed}"
        )
        self.current, self.requested = current, requested


class QueueManager:
    """Operations on the review queue. All state changes pass through here."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- creation ----------------------------------------------------------

    def enqueue(
        self,
        vacancy_id: str,
        status: Status,
        *,
        submission_type: str = "",
        flags: dict | None = None,
        artefacts: Iterable[str] = (),
        note: str = "",
    ) -> None:
        """Write a new queue record. Autonomous context only.

        The unattended run may write PENDING, FLAGGED or UNREACHABLE. It may
        never write APPROVED or DISPATCHED — approval is an interactive act.
        """
        if not status.set_autonomously:
            raise IllegalTransition(Status.PENDING, status)
        self.store.create_queue_record(
            vacancy_id, status.value,
            submission_type=submission_type, flags=flags,
            artefacts=list(artefacts), note=note,
        )

    # -- reading -----------------------------------------------------------

    def status_of(self, vacancy_id: str) -> Status:
        row = self.store.queue_record(vacancy_id)
        if row is None:
            raise StoreError(f"no queue record for {vacancy_id!r}")
        return Status(row["status"])

    def is_dispatchable(self, vacancy_id: str) -> bool:
        """Only APPROVED is eligible for dispatch."""
        return self.status_of(vacancy_id) is Status.APPROVED

    def pending(self, limit: int = 50):
        return self.store.list_queue(Status.PENDING.value, limit)

    def flagged(self, limit: int = 50):
        return self.store.list_queue(Status.FLAGGED.value, limit)

    # -- transitions -------------------------------------------------------

    def transition(self, vacancy_id: str, to: Status, note: str = "") -> Status:
        """Move a vacancy. Raises IllegalTransition rather than logging."""
        current = self.status_of(vacancy_id)
        if to not in LEGAL[current]:
            raise IllegalTransition(current, to)
        self.store.set_status(vacancy_id, to.value, note)
        return to

    def approve(self, vacancy_id: str, note: str = "") -> Status:
        return self.transition(vacancy_id, Status.APPROVED, note or "operator approved")

    def reject(self, vacancy_id: str, reason: str = "") -> Status:
        return self.transition(vacancy_id, Status.REJECTED, reason or "operator rejected")

    def flag(self, vacancy_id: str, ambiguity: str) -> Status:
        """Attach the SPECIFIC ambiguity. 'FLAGGED' alone is not actionable."""
        if not ambiguity.strip():
            raise ValueError("a flag must state the specific ambiguity")
        return self.transition(vacancy_id, Status.FLAGGED, ambiguity)

    def resolve(self, vacancy_id: str, note: str = "") -> Status:
        """Operator has resolved a flagged ambiguity. Returns to review."""
        return self.transition(vacancy_id, Status.PENDING, note or "ambiguity resolved")

    def dispatch(self, vacancy_id: str, note: str = "") -> Status:
        """Record a submission. Vanguard never transmits; the operator does."""
        return self.transition(vacancy_id, Status.DISPATCHED, note or "submitted by operator")

    def override_unreachable(self, vacancy_id: str, justification: str) -> Status:
        """Apply despite a coverage ceiling below threshold.

        Requires a justification, because UNREACHABLE is a true finding about
        the gap between the CV and the role. Overriding it should be a
        deliberate, recorded act rather than a click.
        """
        if not justification.strip():
            raise ValueError(
                "overriding UNREACHABLE requires a justification — the vacancy "
                "was marked unreachable on evidence"
            )
        return self.transition(vacancy_id, Status.PENDING, f"override: {justification}")

    # -- audit -------------------------------------------------------------

    def history(self, vacancy_id: str) -> list[tuple[str, str, str]]:
        return [
            (r["from_state"] or "-", r["to_state"], r["at"])
            for r in self.store.transitions_for(vacancy_id)
        ]

    def summary(self) -> str:
        counts = self.store.counts_by_status()
        if not counts:
            return "queue empty"
        return "  ".join(f"{k} {v}" for k, v in sorted(counts.items()))
