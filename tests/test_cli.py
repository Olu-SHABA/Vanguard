"""CLI — command surface, autonomous non-blocking guarantee, error reporting."""
from __future__ import annotations

from pathlib import Path

import pytest

click = pytest.importorskip("click")
from click.testing import CliRunner  # noqa: E402

from vanguard.cli import main  # noqa: E402

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def base(tmp_path: Path) -> list[str]:
    return [
        "--cv", str(ROOT / "data" / "canonical_cv.md"),
        "--aliases", str(ROOT / "config" / "alias_table.yaml"),
        "--db", str(tmp_path / "v.db"),
        "--no-model",
    ]


# --- surface --------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    ["run", "review", "approve", "reject", "resolve", "override",
     "dispatch", "score", "stats", "boards", "paste"],
)
def test_command_exists(runner: CliRunner, command: str) -> None:
    assert runner.invoke(main, [command, "--help"]).exit_code == 0


def test_help_lists_commands(runner: CliRunner) -> None:
    out = runner.invoke(main, ["--help"]).output
    assert "run" in out and "review" in out and "approve" in out


# --- standalone scoring ---------------------------------------------------

def test_score_reports_coverage_and_ceiling(runner: CliRunner) -> None:
    result = runner.invoke(main, [
        "score", "--advert", str(ADVERT),
        "--cv", str(ROOT / "data" / "canonical_cv.md"),
        "--aliases", str(ROOT / "config" / "alias_table.yaml"), "--no-model",
    ])
    assert result.exit_code == 0
    assert "ceiling" in result.output and "UNREACHABLE" in result.output


def test_score_lists_tier_c_exclusions(runner: CliRunner) -> None:
    """The operator must see WHY a term is unmet, not merely that it is."""
    result = runner.invoke(main, [
        "score", "--advert", str(ADVERT),
        "--cv", str(ROOT / "data" / "canonical_cv.md"),
        "--aliases", str(ROOT / "config" / "alias_table.yaml"), "--no-model",
    ])
    assert "no CV edit permitted" in result.output
    assert "pytest" in result.output


def test_score_needs_no_database(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(main, [
        "score", "--advert", str(ADVERT),
        "--cv", str(ROOT / "data" / "canonical_cv.md"),
        "--aliases", str(ROOT / "config" / "alias_table.yaml"), "--no-model",
    ])
    assert not (tmp_path / "v.db").exists()


# --- autonomous run -------------------------------------------------------

def test_run_completes_and_exits(runner: CliRunner, tmp_path: Path) -> None:
    """Never blocks, never prompts. No credentials configured is not an error."""
    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    assert result.exit_code == 0


def test_run_never_transmits(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    assert "no transmission" in result.output or "no vacancies" in result.output


def test_run_skips_tier_3_boards(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    assert "operator paste only" in result.output


# --- manual ingestion -----------------------------------------------------

def test_paste_ingests_scores_and_queues(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, [
        "paste", "--file", str(ADVERT), "--employer", "Ministry of Justice",
        "--boards", str(ROOT / "config" / "boards.yaml"), *base(tmp_path),
    ])
    assert result.exit_code == 0
    assert "Senior Data Engineer" in result.output
    assert "UNREACHABLE" in result.output


def test_paste_rejects_empty_input(runner: CliRunner, tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    result = runner.invoke(main, [
        "paste", "--file", str(empty),
        "--boards", str(ROOT / "config" / "boards.yaml"), *base(tmp_path),
    ])
    assert result.exit_code != 0


def test_paste_rejects_unknown_board(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, [
        "paste", "--file", str(ADVERT), "--board", "nosuchboard",
        "--boards", str(ROOT / "config" / "boards.yaml"), *base(tmp_path),
    ])
    assert result.exit_code != 0 and "unknown board" in result.output


# --- operator cycle -------------------------------------------------------

def _seed(runner: CliRunner, tmp_path: Path) -> str:
    runner.invoke(main, [
        "paste", "--file", str(ADVERT), "--employer", "MoJ",
        "--boards", str(ROOT / "config" / "boards.yaml"), *base(tmp_path),
    ])
    from vanguard.store import Store
    return Store(tmp_path / "v.db").list_queue()[0]["vacancy_id"]


def test_illegal_transition_reported_not_crashed(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    result = runner.invoke(main, ["approve", vid, "--db", str(tmp_path / "v.db")])
    assert result.exit_code != 0
    assert "illegal transition" in result.output


def test_override_requires_justification(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    result = runner.invoke(main, ["override", vid, "--why", " ",
                                  "--db", str(tmp_path / "v.db")])
    assert result.exit_code != 0


def test_full_cycle_to_dispatched(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    db = str(tmp_path / "v.db")
    assert runner.invoke(main, ["override", vid, "--why", "3 of 4 strong", "--db", db]).exit_code == 0
    assert runner.invoke(main, ["approve", vid, "--db", db]).exit_code == 0
    assert runner.invoke(main, ["dispatch", vid, "--db", db]).exit_code == 0

    out = runner.invoke(main, ["review", vid, "--db", db]).output
    assert "DISPATCHED" in out


def test_review_shows_gap_reasons(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    out = runner.invoke(main, ["review", vid, "--db", str(tmp_path / "v.db")]).output
    assert "unmet" in out and "Type 3" in out


def test_review_unknown_id_errors_cleanly(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["review", "nope", "--db", str(tmp_path / "v.db")])
    assert result.exit_code != 0 and "no queue record" in result.output


# --- stats ----------------------------------------------------------------

def test_stats_reports_recalibration_shortfall(runner: CliRunner, tmp_path: Path) -> None:
    _seed(runner, tmp_path)
    out = runner.invoke(main, ["stats", "--db", str(tmp_path / "v.db")]).output
    assert "more logged applications" in out and "P-01" in out


def test_boards_reports_health(runner: CliRunner) -> None:
    out = runner.invoke(main, ["boards", "--boards",
                               str(ROOT / "config" / "boards.yaml")]).output
    assert "registered" in out and "adzuna" in out


# ---------------------------------------------------------------------------
# M6 — response loop commands
# ---------------------------------------------------------------------------

DECLINE_BODY = """Thank you for your interest in the Senior Data Engineer role,
vacancy 19568. We were very impressed and would like to keep your details on
file. Unfortunately, on this occasion you have not been successful.
"""


@pytest.mark.parametrize("command", ["mail", "dormant", "feedback", "interview"])
def test_m6_command_exists(runner: CliRunner, command: str) -> None:
    assert runner.invoke(main, [command, "--help"]).exit_code == 0


def test_mail_correlates_on_vacancy_reference(runner: CliRunner, tmp_path: Path) -> None:
    """B-10: the reference is extracted from the advert and stored, so stage 1
    correlation can fire. Before the fix it never could."""
    _seed(runner, tmp_path)
    body = tmp_path / "decline.txt"
    body.write_text(DECLINE_BODY)

    result = runner.invoke(main, [
        "mail", "--file", str(body), "--sender", "recruit@justice.gov.uk",
        "--subject", "Senior Data Engineer 19568", "--db", str(tmp_path / "v.db"),
    ])
    assert "via reference" in result.output
    assert "DECLINE" in result.output


def test_mail_never_sends(runner: CliRunner, tmp_path: Path) -> None:
    _seed(runner, tmp_path)
    body = tmp_path / "d.txt"
    body.write_text(DECLINE_BODY)
    out = runner.invoke(main, ["mail", "--file", str(body),
                               "--db", str(tmp_path / "v.db")]).output
    assert "no outbound action taken" in out


def test_mail_uncorrelated_is_not_classified(runner: CliRunner, tmp_path: Path) -> None:
    _seed(runner, tmp_path)
    body = tmp_path / "spam.txt"
    body.write_text("Our newsletter this week features great deals.")
    out = runner.invoke(main, ["mail", "--file", str(body),
                               "--sender", "marketing@random.com",
                               "--db", str(tmp_path / "v.db")]).output
    assert "UNCORRELATED" in out and "not classified" in out


def test_mail_suggests_template_without_invoking_it(runner: CliRunner, tmp_path: Path) -> None:
    """No classification state triggers an outbound action."""
    _seed(runner, tmp_path)
    body = tmp_path / "d.txt"
    body.write_text(DECLINE_BODY)
    out = runner.invoke(main, ["mail", "--file", str(body),
                               "--subject", "vacancy 19568",
                               "--db", str(tmp_path / "v.db")]).output
    assert "operator may invoke Template D" in out


def test_feedback_drafts_only(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    out = runner.invoke(main, ["feedback", vid, "--name", "A", "--contact", "a@b.c",
                               "--db", str(tmp_path / "v.db")]).output
    assert "draft only" in out and "Review and send yourself" in out


def test_interview_generates_from_the_cv(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    out = runner.invoke(main, ["interview", vid, "--phase", "1", "--limit", "3",
                               "--cv", str(ROOT / "data" / "canonical_cv.md"),
                               "--db", str(tmp_path / "v.db")]).output
    assert "PHASE 1" in out and "You state:" in out
    assert "D1 = 0 is terminal" in out


def test_interview_phase_3_includes_d5(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    out = runner.invoke(main, ["interview", vid, "--phase", "3",
                               "--cv", str(ROOT / "data" / "canonical_cv.md"),
                               "--db", str(tmp_path / "v.db")]).output
    assert "D5" in out and "max 15" in out


def test_dormant_reports_none_when_recent(runner: CliRunner, tmp_path: Path) -> None:
    _seed(runner, tmp_path)
    out = runner.invoke(main, ["dormant", "--db", str(tmp_path / "v.db"),
                               "--boards", str(ROOT / "config" / "boards.yaml")]).output
    assert "no dormant applications" in out
