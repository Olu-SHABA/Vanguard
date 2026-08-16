"""Interview processes — multi-round tracking across weeks."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.mail import State
from vanguard.process import (
    InterviewProcess,
    ProcessState,
    ProcessStore,
    suggested_phase,
)


@pytest.fixture
def processes(tmp_path: Path) -> ProcessStore:
    return ProcessStore(str(tmp_path / "v.db"))


# --- opening --------------------------------------------------------------

def test_progress_opens_a_process(processes: ProcessStore) -> None:
    process = processes.record("reed:1", State.PROGRESS, subject="Interview invite")
    assert process is not None
    assert process.state is ProcessState.ACTIVE
    assert process.current_round == 1


@pytest.mark.parametrize("state", [State.ACK, State.ADMIN, State.QUERY,
                                   State.AMBIGUOUS])
def test_other_states_do_not_open_a_process(processes: ProcessStore,
                                            state: State) -> None:
    """An acknowledgement on an application that never progressed is not an
    interview."""
    assert processes.record("reed:1", state) is None


# --- rounds ---------------------------------------------------------------

def test_each_progress_opens_a_round(processes: ProcessStore) -> None:
    for subject in ("First interview", "Technical exercise", "Final panel"):
        processes.record("reed:1", State.PROGRESS, subject=subject)
    assert processes.get("reed:1").current_round == 3


@pytest.mark.parametrize("state", [State.ADMIN, State.QUERY, State.AMBIGUOUS])
def test_logistics_attach_to_the_current_round(processes: ProcessStore,
                                               state: State) -> None:
    """Scheduling an interview is part of that interview, not a further
    stage."""
    processes.record("reed:1", State.PROGRESS, subject="First interview")
    processes.record("reed:1", state, subject="Confirming Tuesday 2pm")

    process = processes.get("reed:1")
    assert process.current_round == 1
    assert process.message_count == 2


def test_rounds_are_recorded_in_order(processes: ProcessStore) -> None:
    for subject in ("Screen", "Exercise", "Panel"):
        processes.record("reed:1", State.PROGRESS, subject=subject)
    subjects = [r.subject for r in processes.get("reed:1").rounds]
    assert subjects == ["Screen", "Exercise", "Panel"]


# --- terminal states ------------------------------------------------------

def test_offer_closes_the_process(processes: ProcessStore) -> None:
    processes.record("reed:1", State.PROGRESS, subject="Interview")
    process = processes.record("reed:1", State.OFFER, subject="We are pleased...")
    assert process.state is ProcessState.OFFER
    assert not process.active


def test_decline_closes_the_process(processes: ProcessStore) -> None:
    processes.record("reed:1", State.PROGRESS, subject="Interview")
    process = processes.record("reed:1", State.DECLINE, subject="Unsuccessful")
    assert process.state is ProcessState.DECLINE


def test_operator_withdrawal_closes_the_process(processes: ProcessStore) -> None:
    processes.record("reed:1", State.PROGRESS, subject="Interview")
    assert processes.withdraw("reed:1", "accepted another role")
    process = processes.get("reed:1")
    assert process.state is ProcessState.WITHDRAWN
    assert "another role" in process.outcome_note


@pytest.mark.parametrize("state", [State.ADMIN, State.QUERY, State.ACK,
                                   State.AMBIGUOUS])
def test_nothing_else_closes_a_process(processes: ProcessStore,
                                       state: State) -> None:
    """Silence is not an outcome, and neither is an administrative message.
    Employers go quiet between rounds and return."""
    processes.record("reed:1", State.PROGRESS, subject="Interview")
    processes.record("reed:1", state, subject="Something")
    assert processes.get("reed:1").active


def test_a_message_after_closure_changes_nothing(processes: ProcessStore) -> None:
    """A rejection must not reopen because a mailing list mentions the
    company afterwards."""
    processes.record("reed:1", State.PROGRESS, subject="Interview")
    processes.record("reed:1", State.DECLINE, subject="Unsuccessful")
    process = processes.record("reed:1", State.PROGRESS, subject="Another round?")

    assert process.state is ProcessState.DECLINE
    assert process.current_round == 1


def test_terminal_states_are_exactly_three() -> None:
    terminal = {s for s in ProcessState if s.terminal}
    assert terminal == {ProcessState.OFFER, ProcessState.DECLINE,
                        ProcessState.WITHDRAWN}


# --- listing --------------------------------------------------------------

def test_active_excludes_closed(processes: ProcessStore) -> None:
    processes.record("reed:1", State.PROGRESS, subject="A")
    processes.record("reed:2", State.PROGRESS, subject="B")
    processes.record("reed:2", State.OFFER, subject="Offer")

    assert [p.vacancy_id for p in processes.active()] == ["reed:1"]
    assert len(processes.all()) == 2


def test_absent_process_reads_as_none(processes: ProcessStore) -> None:
    assert processes.get("reed:nothere") is None
    assert not processes.withdraw("reed:nothere", "reason")


# --- rehearsal phase ------------------------------------------------------

@pytest.mark.parametrize("round_number, phase", [(1, 1), (2, 2), (3, 3),
                                                 (4, 3), (9, 3)])
def test_phase_follows_the_round(round_number: int, phase: int) -> None:
    """Template E has three phases. A fourth round rehearses phase 3 again
    rather than inventing a phase 4."""
    assert suggested_phase(round_number) == phase


def test_phase_is_never_below_one() -> None:
    assert suggested_phase(0) == 1
