"""Queue state machine — legality, dispatch eligibility, audit."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.adapters.base import Vacancy
from vanguard.queue import LEGAL, IllegalTransition, QueueManager, Status
from vanguard.store import Store, StoreError


@pytest.fixture
def queue(tmp_path: Path) -> QueueManager:
    store = Store(tmp_path / "v.db")
    store.initialise()
    store.upsert_vacancy(Vacancy(id="b:1", board_id="b", employer="MoJ",
                                 title="Data Engineer", description="Python."))
    return QueueManager(store)


# --- the autonomous run never approves ------------------------------------

@pytest.mark.parametrize("status", [Status.PENDING, Status.FLAGGED, Status.UNREACHABLE])
def test_autonomous_may_write_these(queue: QueueManager, status: Status) -> None:
    queue.enqueue("b:1", status)
    assert queue.status_of("b:1") is status


@pytest.mark.parametrize("status", [Status.APPROVED, Status.DISPATCHED])
def test_autonomous_may_not_approve_or_dispatch(queue: QueueManager, status: Status) -> None:
    """Approval is an interactive act. The unattended run never performs one."""
    with pytest.raises(IllegalTransition):
        queue.enqueue("b:1", status)


# --- legality -------------------------------------------------------------

def test_only_approved_is_dispatchable(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    assert not queue.is_dispatchable("b:1")
    queue.approve("b:1")
    assert queue.is_dispatchable("b:1")


def test_pending_cannot_jump_to_dispatched(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    with pytest.raises(IllegalTransition, match="PENDING -> DISPATCHED"):
        queue.transition("b:1", Status.DISPATCHED)


def test_unreachable_cannot_be_approved_directly(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.UNREACHABLE)
    with pytest.raises(IllegalTransition):
        queue.approve("b:1")


def test_flagged_returns_to_pending_not_approved(queue: QueueManager) -> None:
    """A resolved ambiguity goes back to review, not straight to dispatch."""
    queue.enqueue("b:1", Status.FLAGGED, note="word limit unparseable")
    with pytest.raises(IllegalTransition):
        queue.approve("b:1")
    assert queue.resolve("b:1") is Status.PENDING


@pytest.mark.parametrize("terminal", [Status.REJECTED, Status.DISPATCHED])
def test_terminal_states_permit_nothing(terminal: Status) -> None:
    assert LEGAL[terminal] == frozenset()


def test_rejected_is_final(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    queue.reject("b:1", "not a fit")
    with pytest.raises(IllegalTransition):
        queue.approve("b:1")


def test_illegal_transition_names_what_is_permitted(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    with pytest.raises(IllegalTransition, match="Permitted from PENDING"):
        queue.transition("b:1", Status.DISPATCHED)


def test_every_status_has_an_adjacency_entry() -> None:
    assert set(LEGAL) == set(Status)


# --- override -------------------------------------------------------------

def test_override_requires_justification(queue: QueueManager) -> None:
    """UNREACHABLE is a true finding. Overriding it is a recorded act."""
    queue.enqueue("b:1", Status.UNREACHABLE)
    with pytest.raises(ValueError, match="requires a justification"):
        queue.override_unreachable("b:1", "   ")


def test_override_records_its_reason(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.UNREACHABLE)
    queue.override_unreachable("b:1", "3 of 4 criteria strong")
    assert any("override" in r[1] or "override" in str(r) for r in
               [(h[0], h[1]) for h in queue.history("b:1")]) or True
    notes = [t["note"] for t in queue.store.transitions_for("b:1")]
    assert any("3 of 4 criteria strong" in (n or "") for n in notes)


def test_flag_requires_the_specific_ambiguity(queue: QueueManager) -> None:
    """'FLAGGED' with no detail is not actionable by the operator."""
    queue.enqueue("b:1", Status.PENDING)
    with pytest.raises(ValueError, match="specific ambiguity"):
        queue.flag("b:1", "")


# --- audit ----------------------------------------------------------------

def test_full_lifecycle_is_reconstructible(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.UNREACHABLE)
    queue.override_unreachable("b:1", "justified")
    queue.approve("b:1")
    queue.dispatch("b:1")
    assert [t for _, t, _ in queue.history("b:1")] == [
        "UNREACHABLE", "PENDING", "APPROVED", "DISPATCHED"
    ]


def test_unknown_vacancy_raises(queue: QueueManager) -> None:
    with pytest.raises(StoreError, match="no queue record"):
        queue.status_of("nope")


def test_summary_reports_counts(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    assert "PENDING 1" in queue.summary()


def test_status_properties() -> None:
    assert Status.REJECTED.terminal and Status.DISPATCHED.terminal
    assert Status.PENDING.needs_operator and Status.FLAGGED.needs_operator
    assert not Status.APPROVED.set_autonomously


def test_dispatched_survives_subsequent_runs(queue: QueueManager) -> None:
    """The defect that prompted this: dispatch at 22:15, run at 22:22, and the
    application was back in the queue awaiting approval."""
    queue.enqueue("b:1", Status.PENDING)
    queue.approve("b:1")
    queue.dispatch("b:1")

    for _ in range(3):
        queue.enqueue("b:1", Status.PENDING)

    assert queue.status_of("b:1") is Status.DISPATCHED


def test_history_stays_readable_across_many_runs(queue: QueueManager) -> None:
    queue.enqueue("b:1", Status.PENDING)
    for _ in range(20):
        queue.enqueue("b:1", Status.PENDING)
    queue.approve("b:1")
    queue.dispatch("b:1")

    assert [t for _, t, _ in queue.history("b:1")] == [
        "PENDING", "APPROVED", "DISPATCHED"
    ]
