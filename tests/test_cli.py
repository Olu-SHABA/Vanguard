"""CLI — command surface, autonomous non-blocking guarantee, error reporting."""
from __future__ import annotations

import os
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


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    """Clear board credentials for EVERY CLI test.

    `main()` calls `_load_env()`, which reads the operator's real `.env`. Once
    credentials were configured, any test invoking `run` began making live API
    calls — fetching hundreds of vacancies, hydrating each with a detail call,
    and blocking on the 60/hour rate limiter. The suite hung, and it was
    consuming the operator's API quota to do it.

    A test suite must never touch a live endpoint.
    """
    for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"):
        monkeypatch.delitem(os.environ, name, raising=False)

    # Neutralise the .env read that `main()` performs at group level, without
    # replacing the function itself — three tests below exercise `_load_env`
    # directly and stubbing it would remove the code under test.
    import vanguard.cli as cli_module

    real = cli_module._load_env
    monkeypatch.setattr(
        cli_module, "_load_env",
        lambda path=Path(".env"): 0 if path == Path(".env") else real(path),
    )


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
    # Status depends on the configured gate, which is meant to be tuned.
    # Assert the machinery reported, not which side of the line it fell.
    assert "ceiling" in result.output and "C = " in result.output


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
    """Skips are collapsed to a count; `vanguard boards` carries the detail."""
    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    assert "board(s) skipped" in result.output

    detail = runner.invoke(main, ["boards", "--boards",
                                  str(ROOT / "config" / "boards.yaml")]).output
    assert "Operator paste is the ingress" in " ".join(detail.split())


# --- manual ingestion -----------------------------------------------------

def test_paste_ingests_scores_and_queues(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, [
        "paste", "--file", str(ADVERT), "--employer", "Ministry of Justice",
        "--boards", str(ROOT / "config" / "boards.yaml"), *base(tmp_path),
    ])
    assert result.exit_code == 0
    assert "Senior Data Engineer" in result.output
    assert any(s in result.output for s in ("UNREACHABLE", "FLAGGED", "PENDING"))


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
    assert "more reliable scores" in out and "P-01" in out


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


# ---------------------------------------------------------------------------
# Output discipline — width awareness and word-boundary truncation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unicode_mode, ellipsis", [(True, "\u2026"), (False, "...")])
def test_clip_never_cuts_mid_word(unicode_mode: bool, ellipsis: str) -> None:
    """A half-word reads as data rather than as omission.

    The theme is set explicitly rather than detected: under pytest the output
    is not a terminal, so detection yields ASCII and a hardcoded `…` fails.
    A test must control its inputs, not observe the ambient environment.
    """
    from vanguard import ui
    from vanguard.cli import _clip

    ui.set_theme(ui.Theme(colour=False, unicode=unicode_mode,
                          decorated=False, width=80))
    try:
        out = _clip("adapter NHSJobsAPIAdapter is declared but not yet implemented", 40)
        assert out.endswith(ellipsis)
        assert not out[: -len(ellipsis)].endswith(("implemen", "declare"))
    finally:
        ui.set_theme(None)


def test_clip_leaves_short_text_alone() -> None:
    from vanguard.cli import _clip

    assert _clip("Python", 40) == "Python"


def test_clip_normalises_whitespace() -> None:
    from vanguard.cli import _clip

    assert _clip("a   b\n c", 40) == "a b c"


@pytest.mark.parametrize("unicode_mode, ellipsis", [(True, "\u2026"), (False, "...")])
def test_clip_handles_a_single_long_token(unicode_mode: bool, ellipsis: str) -> None:
    """No space to break on — must still terminate, not loop or raise."""
    from vanguard import ui
    from vanguard.cli import _clip

    ui.set_theme(ui.Theme(colour=False, unicode=unicode_mode,
                          decorated=False, width=80))
    try:
        out = _clip("x" * 200, 20)
        assert len(out) <= 20
        assert out.endswith(ellipsis)
    finally:
        ui.set_theme(None)


def test_wrap_preserves_every_word() -> None:
    """Exclusion reasons say WHY no edit is permitted. Nothing may be lost."""
    from vanguard.cli import _wrap

    text = ("CV lists 'cloud computing' inside a software catch-all line with "
            "no named platform and no supporting bullet.")
    joined = " ".join(_wrap(text, 40))
    assert joined == " ".join(text.split())


def test_wrap_respects_the_width() -> None:
    from vanguard.cli import _wrap

    assert all(len(line) <= 40 for line in _wrap("word " * 60, 40))


def test_terminal_width_has_a_floor() -> None:
    from vanguard.cli import MIN_WIDTH, _terminal_width

    assert _terminal_width() >= MIN_WIDTH


def test_review_detail_shows_full_exclusion_reason(runner: CliRunner, tmp_path: Path) -> None:
    """Was clipped at 56 chars, losing the operative part of the ruling."""
    vid = _seed(runner, tmp_path)
    out = runner.invoke(main, ["review", vid, "--db", str(tmp_path / "v.db")]).output
    assert "Insufficient for any named-platform requirement" in " ".join(out.split())


def test_boards_detail_is_not_cut_mid_word(runner: CliRunner) -> None:
    out = runner.invoke(main, ["boards", "--boards",
                               str(ROOT / "config" / "boards.yaml")]).output
    assert "declared but n\n" not in out
    assert "not yet implemented" in " ".join(out.split())


def test_run_collapses_skipped_boards(runner: CliRunner, tmp_path: Path) -> None:
    """Seven skip lines before any vacancy buried the signal."""
    out = runner.invoke(main, ["run", *base(tmp_path),
                               "--boards", str(ROOT / "config" / "boards.yaml")]).output
    assert "board(s) skipped" in out
    assert out.count("skipped —") <= 1


def test_review_list_columns_align(runner: CliRunner, tmp_path: Path) -> None:
    _seed(runner, tmp_path)
    from vanguard.store import Store
    status = Store(tmp_path / "v.db").list_queue()[0]["status"]
    out = runner.invoke(main, ["review", "--status", status,
                               "--db", str(tmp_path / "v.db")]).output
    lines = [ln for ln in out.split("\n") if ln.startswith("  ")]
    assert len(lines) >= 2
    header, first = lines[0], lines[1]
    assert header.index("EMPLOYER") < header.index("TITLE") < header.index("ID")
    # employer value starts at the same column as its header
    assert first[header.index("EMPLOYER")] not in " "


# ---------------------------------------------------------------------------
# Credentials and configuration
# ---------------------------------------------------------------------------

def test_env_file_populates_credentials(tmp_path: Path, monkeypatch) -> None:
    """Without this, keys must be exported in every new shell — the friction
    that ends with someone pasting a key into a tracked file.

    Uses names that cannot collide with real credentials. An earlier version
    asserted on ADZUNA_APP_ID/KEY and passed only on a machine with no Adzuna
    credentials configured — it failed the moment the feature started working.
    """
    from vanguard.cli import _load_env

    for name in ("VANGUARD_TEST_A", "VANGUARD_TEST_B"):
        monkeypatch.delitem(os.environ, name, raising=False)

    env = tmp_path / ".env"
    env.write_text("VANGUARD_TEST_A=abc\nVANGUARD_TEST_B='def'\n# comment\n\n")

    assert _load_env(env) == 2
    assert os.environ["VANGUARD_TEST_A"] == "abc"
    assert os.environ["VANGUARD_TEST_B"] == "def"      # quotes stripped


def test_exported_variable_wins_over_env_file(tmp_path: Path, monkeypatch) -> None:
    from vanguard.cli import _load_env

    monkeypatch.setitem(os.environ, "VANGUARD_TEST_C", "exported")
    env = tmp_path / ".env"
    env.write_text("VANGUARD_TEST_C=from-file\n")

    assert _load_env(env) == 0, "an already-set variable must not be counted as loaded"
    assert os.environ["VANGUARD_TEST_C"] == "exported"


def test_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    from vanguard.cli import _load_env
    assert _load_env(tmp_path / "absent.env") == 0


def test_diagnose_command_exists(runner: CliRunner) -> None:
    assert runner.invoke(main, ["diagnose", "--help"]).exit_code == 0


def test_diagnose_reports_nothing_when_empty(runner: CliRunner, tmp_path: Path) -> None:
    out = runner.invoke(main, ["diagnose", "--db", str(tmp_path / "v.db")]).output
    assert "no diagnostics recorded" in out


def test_diagnose_lists_unrecognised_headings(runner: CliRunner, tmp_path: Path) -> None:
    """The evidence for widening classify_heading()."""
    from vanguard.diagnostics import diagnose_advert
    from vanguard.store import Store

    store = Store(tmp_path / "v.db")
    store.initialise()
    store.record_diagnostic(diagnose_advert(
        "r:1", "<strong>Our Ideal Teammate Vibe</strong><ul><li>Perks</li></ul>",
        terms_extracted=0))

    out = runner.invoke(main, ["diagnose", "--db", str(tmp_path / "v.db")]).output
    assert "Our Ideal Teammate Vibe" in out
    assert "classify_heading" in out


def test_run_records_diagnostics(runner: CliRunner, tmp_path: Path) -> None:
    from vanguard.store import Store

    _seed(runner, tmp_path)
    assert Store(tmp_path / "v.db").parse_health()["total"] >= 1


# ---------------------------------------------------------------------------
# Documentation coverage — the reference must not drift from the CLI
# ---------------------------------------------------------------------------

COMMANDS_DOC = ROOT / "COMMANDS.md"


def test_command_reference_exists() -> None:
    assert COMMANDS_DOC.is_file()


def test_every_command_is_documented() -> None:
    """A command added without a reference entry is undiscoverable."""
    doc = COMMANDS_DOC.read_text(encoding="utf-8")
    undocumented = [n for n in main.commands if f"vanguard {n}" not in doc]
    assert not undocumented, f"undocumented commands: {undocumented}"


def test_every_option_is_documented() -> None:
    doc = COMMANDS_DOC.read_text(encoding="utf-8")
    gaps = [
        f"{name} {param.opts[0]}"
        for name, command in main.commands.items()
        for param in command.params
        if isinstance(param, click.Option)
        and param.opts[0] != "--help"
        and param.opts[0] not in doc
    ]
    assert not gaps, f"undocumented options: {gaps}"


def test_documented_commands_all_exist() -> None:
    """The reverse: the reference must not describe commands that were removed."""
    import re

    doc = COMMANDS_DOC.read_text(encoding="utf-8")
    referenced = set(re.findall(r"^## `vanguard (\w+)", doc, re.M))
    assert referenced <= set(main.commands), (
        f"documented but absent: {referenced - set(main.commands)}"
    )


# ---------------------------------------------------------------------------
# A coverage figure that was never measured must not be printed
# ---------------------------------------------------------------------------

def _seed_unmeasured(tmp_path: Path) -> None:
    """A vacancy scored on one requirement — the case that displayed 1.000."""
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    store = Store(tmp_path / "v.db")
    store.initialise()
    store.upsert_vacancy(Vacancy(
        id="adzuna:999", board_id="adzuna", employer="Barclays",
        title="AI Engineer", description="Short summary mentioning data.",
        description_is_partial=True,
    ))
    store.create_queue_record("adzuna:999", "FLAGGED")
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
            " terms_total, terms_matched, soft_hits, embedder, computed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("adzuna:999", 1.0, 0.549, 1.0, 1, 1, 0, "minilm",
             "2026-08-09T21:00:00+00:00"),
        )


def test_unmeasured_coverage_is_not_shown_as_a_figure(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A bare 1.000 at the top of the queue reads as the best match. It meant
    the opposite: one requirement extracted, nothing measured."""
    _seed_unmeasured(tmp_path)
    out = runner.invoke(main, ["review", "--status", "FLAGGED",
                               "--db", str(tmp_path / "v.db")]).output
    assert "1.000" not in out
    assert "not measured" in out


def test_unmeasured_records_are_counted(runner: CliRunner, tmp_path: Path) -> None:
    _seed_unmeasured(tmp_path)
    out = runner.invoke(main, ["review", "--status", "FLAGGED",
                               "--db", str(tmp_path / "v.db")]).output
    assert "1 not measured" in out
    assert "diagnose" in out


def test_measured_coverage_shows_its_denominator(
    runner: CliRunner, tmp_path: Path
) -> None:
    """0.429 alone is not interpretable; 9/21 is."""
    vid = _seed(runner, tmp_path)
    from vanguard.store import Store

    status = Store(tmp_path / "v.db").list_queue()[0]["status"]
    out = runner.invoke(main, ["review", "--status", status,
                               "--db", str(tmp_path / "v.db")]).output
    assert "/" in out and "TERMS" in out


def test_sop_exists() -> None:
    assert (ROOT / "SOP.md").is_file()


def test_sop_references_only_real_commands() -> None:
    """An SOP naming a command that does not exist sends the reader nowhere."""
    import re

    sop = (ROOT / "SOP.md").read_text(encoding="utf-8")
    referenced = set(re.findall(r"vanguard (\w+)", sop))
    # `run` and `logs` also appear as ordinary words; both are real commands.
    assert referenced <= set(main.commands) | {"run", "logs"}


# ---------------------------------------------------------------------------
# RESULT must describe THIS RUN, not the whole queue
# ---------------------------------------------------------------------------

def test_result_block_distinguishes_run_from_queue_total(
    runner: CliRunner, tmp_path: Path
) -> None:
    """`counts_by_status()` covers every vacancy ever ingested. Reporting it
    under a RESULT heading showed 543 records for a run that scored 14."""
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    store = Store(tmp_path / "v.db")
    store.initialise()
    for i in range(40):
        store.upsert_vacancy(Vacancy(id=f"old:{i}", board_id="reed", employer="E",
                                     title=f"T{i}", description="d"))
        store.create_queue_record(f"old:{i}", "FLAGGED")

    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    out = result.output

    # No board is reachable in the test environment, so nothing is scored —
    # but the historical 40 must not be presented as this run's outcome.
    assert "RESULT" not in out or "this run scored" in out
    if "queue total" in out:
        assert "all runs" in out


def test_run_reports_zero_scored_honestly(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["run", *base(tmp_path),
                                  "--boards", str(ROOT / "config" / "boards.yaml")])
    assert result.exit_code == 0
    assert "no vacancies" in result.output or "this run scored" in result.output


def test_manual_entry_guide_exists() -> None:
    assert (ROOT / "MANUAL_ENTRY.md").is_file()


def test_manual_entry_guide_names_only_real_boards() -> None:
    """A guide telling the operator to use `--board x` for a board that is not
    in the registry sends them to an error."""
    import re

    from vanguard.adapters.base import load_registry

    guide = (ROOT / "MANUAL_ENTRY.md").read_text(encoding="utf-8")
    registry = load_registry(ROOT / "config" / "boards.yaml")
    referenced = set(re.findall(r"--board (\w+)", guide))
    known = {e.id for e in registry} | {"indeed"}   # indeed is an example to add
    assert referenced <= known, f"unknown boards: {referenced - known}"


@pytest.mark.parametrize("guide", ["HOW_TO_ADD_A_JOB.md", "HOW_TO_ADD_MANY_JOBS.md",
                                  "HOW_TO_HANDLE_REPLIES.md",
                                  "HOW_TO_USE_REPOSITORY_EVIDENCE.md"])
def test_quick_guide_exists(guide: str) -> None:
    assert (ROOT / guide).is_file()


@pytest.mark.parametrize("guide", ["HOW_TO_ADD_A_JOB.md", "HOW_TO_ADD_MANY_JOBS.md",
                                  "HOW_TO_HANDLE_REPLIES.md",
                                  "HOW_TO_USE_REPOSITORY_EVIDENCE.md"])
def test_quick_guides_stay_short(guide: str) -> None:
    """They exist because the reference was too long to follow while working.

    This fired on 12 Aug when a batch section pushed the single-job guide to
    163 lines. The right answer was to split it, not to raise the limit —
    raising it would have removed the only thing keeping either guide quick.
    """
    lines = (ROOT / guide).read_text(encoding="utf-8").split("\n")
    assert len(lines) < 130, f"{guide} has stopped being quick"


def test_dispatch_archives_the_application(runner: CliRunner, tmp_path: Path) -> None:
    """Directive §5. Without it, an interview six weeks later has no record of
    what was submitted."""
    vid = _seed(runner, tmp_path)
    db = str(tmp_path / "v.db")
    root = tmp_path / "Pipeline_Archive"

    for command in (["resolve", vid], ["approve", vid]):
        runner.invoke(main, [*command, "--db", db])
    result = runner.invoke(main, ["dispatch", vid, "--db", db,
                                  "--archive-root", str(root),
                                  "--cv-source", str(ROOT / "data" / "canonical_cv.md")])

    assert result.exit_code == 0
    assert "archived" in result.output
    assert list(root.glob("*/*/manifest.json"))


def test_no_archive_flag_is_honoured(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    db = str(tmp_path / "v.db")
    root = tmp_path / "Pipeline_Archive"
    for command in (["resolve", vid], ["approve", vid]):
        runner.invoke(main, [*command, "--db", db])
    runner.invoke(main, ["dispatch", vid, "--db", db, "--no-archive",
                         "--archive-root", str(root)])
    assert not root.exists()


def test_archive_command_lists_applications(runner: CliRunner, tmp_path: Path) -> None:
    vid = _seed(runner, tmp_path)
    db = str(tmp_path / "v.db")
    root = tmp_path / "Pipeline_Archive"
    for command in (["resolve", vid], ["approve", vid]):
        runner.invoke(main, [*command, "--db", db])
    runner.invoke(main, ["dispatch", vid, "--db", db, "--archive-root", str(root),
                         "--cv-source", str(ROOT / "data" / "canonical_cv.md")])

    out = runner.invoke(main, ["archive", "--root", str(root)]).output
    assert "Senior Data Engineer" in out or "Job_Specs" in out


def test_archive_command_handles_empty(runner: CliRunner, tmp_path: Path) -> None:
    out = runner.invoke(main, ["archive", "--root", str(tmp_path / "none")]).output
    assert "nothing archived" in out


def test_poll_strategy_is_configurable() -> None:
    from vanguard.cli import _mail_strategy, _window_threshold

    assert _mail_strategy(str(ROOT / "config" / "boards.yaml")) in (
        "auto", "targeted", "window")
    assert _window_threshold(str(ROOT / "config" / "boards.yaml")) > 0


def test_poll_reports_which_strategy_it_used(runner: CliRunner, tmp_path: Path) -> None:
    """Without this a switch would be invisible.

    With no credentials the command stops at the health check, before a
    strategy is chosen — so the mailbox line is what proves it got that far.
    `choose_strategy` is tested directly in test_mailbox.
    """
    out = runner.invoke(main, ["poll", "--db", str(tmp_path / "v.db"),
                               "--cv", str(ROOT / "data" / "canonical_cv.md")]).output
    assert "MAILBOX" in out
    assert "UNREACHABLE" in out or "TARGETED" in out or "WINDOW" in out


# ---------------------------------------------------------------------------
# Batch ingestion — the bottleneck at 70 adverts a day
# ---------------------------------------------------------------------------

def _advert_folder(tmp_path: Path, count: int = 3) -> Path:
    directory = tmp_path / "adverts"
    directory.mkdir()
    source = (ROOT / "tests" / "fixtures" / "moj_senior_data_engineer.txt"
              ).read_text(encoding="utf-8")
    for i in range(count):
        (directory / f"job{i}.txt").write_text(source, encoding="utf-8")
    return directory


@pytest.mark.parametrize("command", ["add", "list", "check", "ingest", "register"])
def test_adverts_subcommand_exists(runner: CliRunner, command: str) -> None:
    assert runner.invoke(main, ["adverts", command, "--help"]).exit_code == 0


def test_unregistered_files_are_not_ingested(runner: CliRunner, tmp_path: Path) -> None:
    directory = _advert_folder(tmp_path)
    out = runner.invoke(main, ["adverts", "ingest", "--dir", str(directory),
                               "--db", str(tmp_path / "v.db"), "--no-model",
                               "--boards", str(ROOT / "config" / "boards.yaml"),
                               "--cv", str(ROOT / "data" / "canonical_cv.md"),
                               "--aliases", str(ROOT / "config" / "alias_table.yaml")]
                        ).output
    assert "3 skipped" in out or "nothing to ingest" in out


def test_registered_files_are_ingested(runner: CliRunner, tmp_path: Path) -> None:
    directory = _advert_folder(tmp_path)
    for i in range(3):
        runner.invoke(main, ["adverts", "add", f"job{i}.txt", "--dir", str(directory),
                             "--employer", f"Employer {i}",
                             "--url", f"https://example.com/{i}"])

    out = runner.invoke(main, ["adverts", "ingest", "--dir", str(directory),
                               "--db", str(tmp_path / "v.db"), "--no-model",
                               "--boards", str(ROOT / "config" / "boards.yaml"),
                               "--cv", str(ROOT / "data" / "canonical_cv.md"),
                               "--aliases", str(ROOT / "config" / "alias_table.yaml")]
                        ).output
    assert "3 valid" in out
    from vanguard.store import Store
    assert len(Store(tmp_path / "v.db").list_queue(limit=50)) == 3


def test_template_lists_unregistered_files(runner: CliRunner, tmp_path: Path) -> None:
    directory = _advert_folder(tmp_path, count=5)
    runner.invoke(main, ["adverts", "register", "--template", "--dir", str(directory)])
    csv_path = directory / "to_register.csv"
    assert csv_path.is_file()
    assert csv_path.read_text(encoding="utf-8").count("job") == 5


def test_bulk_register_reports_rejected_rows(runner: CliRunner, tmp_path: Path) -> None:
    """One bad row must not stop the rest registering."""
    directory = _advert_folder(tmp_path, count=3)
    csv_path = directory / "reg.csv"
    csv_path.write_text(
        "filename,employer,url,board\n"
        "job0.txt,Acme,https://example.com/0,linkedin\n"
        "job1.txt,,https://example.com/1,linkedin\n"
        "job2.txt,Beta,not-a-url,linkedin\n",
        encoding="utf-8")

    out = runner.invoke(main, ["adverts", "register", "--from-csv", str(csv_path),
                               "--dir", str(directory)]).output
    assert "REGISTERED 1" in out
    assert "2 rejected" in out


def test_ingest_dry_run_scores_nothing(runner: CliRunner, tmp_path: Path) -> None:
    directory = _advert_folder(tmp_path, count=2)
    for i in range(2):
        runner.invoke(main, ["adverts", "add", f"job{i}.txt", "--dir", str(directory),
                             "--employer", f"E{i}", "--url", f"https://example.com/{i}"])

    runner.invoke(main, ["adverts", "ingest", "--dir", str(directory), "--dry-run",
                         "--db", str(tmp_path / "v.db"), "--no-model",
                         "--boards", str(ROOT / "config" / "boards.yaml")])
    from vanguard.store import Store
    store = Store(tmp_path / "v.db")
    store.initialise()
    assert store.count_vacancies() == 0


def test_growth_guidance_is_in_both_documents() -> None:
    """The reference explains it per command; the SOP needs it to hand during
    monthly maintenance."""
    commands = (ROOT / "COMMANDS.md").read_text(encoding="utf-8")
    sop = (ROOT / "SOP.md").read_text(encoding="utf-8")

    for document in (commands, sop):
        assert "vanguard.db" in document
        assert "Pipeline_Archive" in document
        assert "to_register.csv" in document

    assert "what-grows" in commands, "the contents table must link to it"
    assert "stats --storage" in sop, "the monthly checklist must include it"


def test_operational_docs_cover_the_response_loop() -> None:
    """COMMANDS is the reference; the SOP is what gets followed. A command
    missing from the SOP is a command nobody runs."""
    sop = (ROOT / "SOP.md").read_text(encoding="utf-8")
    for command in ("vanguard poll", "vanguard interviews", "vanguard adverts"):
        assert command in sop, f"{command} absent from SOP.md"


#: Every step-by-step guide, and the documents that must point at it. A guide
#: nobody links to is a guide nobody reads.
GUIDES = (
    "HOW_TO_ADD_A_JOB.md",
    "HOW_TO_ADD_MANY_JOBS.md",
    "HOW_TO_HANDLE_REPLIES.md",
    "HOW_TO_USE_REPOSITORY_EVIDENCE.md",
    "HOW_TO_APPLY.md",
)


#: Documents that must name every guide. Derived rather than listed: any
#: top-level document that already references at least one guide is expected
#: to reference them all, so adding a fourth reference document brings it
#: under the guard automatically.
def _guide_indexes() -> list[str]:
    return sorted(
        path.name for path in ROOT.glob("*.md")
        if path.name not in GUIDES
        and any(guide in path.read_text(encoding="utf-8") for guide in GUIDES)
    )


@pytest.mark.parametrize("document", ["README.md", "SOP.md", "COMMANDS.md"])
def test_every_guide_is_reachable(document: str) -> None:
    """The reference, the routine and the front page must each name every
    guide. Linking from one and not the others is how a guide gets lost —
    the repository guide was reachable from the README alone."""
    text = (ROOT / document).read_text(encoding="utf-8")
    missing = [guide for guide in GUIDES if guide not in text]
    assert not missing, f"{document} does not mention {missing}"


def test_every_guide_that_exists_is_listed() -> None:
    """The reverse: a guide added without being added to GUIDES escapes the
    check above entirely."""
    on_disk = {path.name for path in ROOT.glob("HOW_TO_*.md")}
    assert on_disk == set(GUIDES), f"GUIDES is out of step with {on_disk}"


def test_any_document_indexing_guides_indexes_them_all() -> None:
    """Derived, so a fourth reference document is guarded the day it is
    written. Naming one guide and not the others is how a guide gets lost."""
    for name in _guide_indexes():
        text = (ROOT / name).read_text(encoding="utf-8")
        missing = [guide for guide in GUIDES if guide not in text]
        assert not missing, f"{name} names some guides but not {missing}"


def test_phase_document_matches_what_is_built() -> None:
    """A phase marked as upcoming after it has been built sends the reader to
    the wrong place — and it happened twice before this test existed.

    Each phase names its module. If the module is present, the phase must be
    marked complete.
    """
    phase = (ROOT / "docs" / "PHASE_2.md").read_text(encoding="utf-8")
    source = ROOT / "src" / "vanguard"

    # Derived from the document, not from a list here. A hardcoded map is a
    # list somebody has to remember to maintain — the exact failure these
    # guards exist to prevent, one level up.
    #
    # Each phase heading names its modules in backticks. If every one exists,
    # the phase is built and must say COMPLETE.
    import re

    headings = re.findall(r"^## ([A-Z] · [^\n]+)$", phase, re.M)
    assert headings, "PHASE_2.md has no phase headings to check"

    for heading in headings:
        section = phase.split(f"## {heading}", 1)[1]
        section = section.split("\n## ", 1)[0]

        modules = set(re.findall(r"`(\w+\.py)`", section))
        if not modules:
            continue
        if not all((source / module).is_file() for module in modules):
            continue

        assert "COMPLETE" in heading or "COMPLETE" in section[:200], (
            f"{heading} names modules that all exist "
            f"({', '.join(sorted(modules))}) but the section does not say "
            "COMPLETE"
        )


def test_readme_lists_every_command() -> None:
    """The front page is where someone starts. A command absent from it is a
    command they will not know exists.

    This fired when Phase 2 added eight commands and the README still stopped
    at the Phase 1 set.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [name for name in main.commands
               if f"vanguard {name}" not in readme]
    assert not missing, f"README.md does not mention {missing}"


def test_readme_records_no_test_count() -> None:
    """A figure in prose is false after the next commit and nobody notices.

    The README carried "417 tests at milestone" for weeks after the suite had
    passed a thousand.
    """
    import re

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claims = re.findall(r"\b\d{3,}\s+tests?\b", readme, re.I)
    assert not claims, f"README.md claims a test count: {claims}"


def test_readme_layout_covers_every_working_directory() -> None:
    """A directory the system creates and the README does not mention is one
    the operator will find by accident.

    Derived from `.gitignore` and from what is on disk, not from a list here.
    A new working directory is caught without anyone remembering to add it.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    # Directories the SYSTEM creates and the operator will encounter. Tool
    # caches and editor folders are neither, so they are excluded by shape:
    # anything beginning with a dot, and anything a tool is known to make.
    _TOOL_ARTEFACTS = {
        "__pycache__", "htmlcov", "ENV", "env", "venv", "build", "dist",
        "node_modules", "scratch", "models", "site-packages",
    }
    ignored = {
        name for line in (ROOT / ".gitignore").read_text(
            encoding="utf-8").splitlines()
        if (name := line.strip().rstrip("/"))
        and line.strip().endswith("/")
        and not line.startswith("#")
        and not name.startswith((".", "*"))
        and name not in _TOOL_ARTEFACTS
    }
    tracked = {
        path.name for path in ROOT.iterdir()
        if path.is_dir() and path.name in {"config", "data", "render", "docs",
                                           "src", "tests"}
    }

    missing = [name for name in sorted(ignored | tracked)
               if name not in readme and name not in {"src", "tests"}]
    assert not missing, f"README.md does not mention {missing}"


# ---------------------------------------------------------------------------
# Bulk operations
#
# Fifteen PENDING records meant thirty commands and thirty copied ids. The
# decisions cannot be batched — fifteen vacancies is fifteen judgements — but
# the invocations can.
# ---------------------------------------------------------------------------

def _queue_of(tmp_path: Path, count: int = 12) -> Path:
    """A queue with a spread of statuses and coverage values."""
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    db = tmp_path / "v.db"
    store = Store(db)
    store.initialise()
    advert = (ROOT / "tests" / "fixtures" / "moj_senior_data_engineer.txt"
              ).read_text(encoding="utf-8")

    for i in range(count):
        store.upsert_vacancy(Vacancy(
            id=f"reed:{i}", board_id="reed", employer=f"Employer {i}",
            title=f"Data Engineer {i}", description=advert))
        status = "PENDING" if i < 5 else ("FLAGGED" if i < 9 else "UNREACHABLE")
        store.create_queue_record(f"reed:{i}", status)
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (f"reed:{i}", 0.30 + i * 0.05, 0.4, 0.85, 20, 6 + i, 0, "test",
                 f"2026-08-{10 + i % 10:02d}T00:00:00+00:00"))
    return db


def test_a_filter_previews_before_acting(runner: CliRunner, tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["reject", "--status", "UNREACHABLE",
                               "--dry-run", "--db", str(db)]).output
    assert "3 record(s)" in out
    assert "dry run" in out

    from vanguard.store import Store
    assert Store(db).counts_by_status().get("REJECTED") is None


def test_bulk_reject_transitions_every_match(runner: CliRunner,
                                             tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    runner.invoke(main, ["reject", "--status", "UNREACHABLE", "--yes",
                         "--reason", "ceiling below gate", "--db", str(db)])

    from vanguard.store import Store
    counts = Store(db).counts_by_status()
    assert counts["REJECTED"] == 3
    assert "UNREACHABLE" not in counts


def test_coverage_filters_select_correctly(runner: CliRunner,
                                           tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["approve", "--status", "PENDING",
                               "--min-coverage", "0.45", "--dry-run",
                               "--db", str(db)]).output
    assert "2 record(s)" in out


def test_a_bulk_action_needs_a_filter(runner: CliRunner, tmp_path: Path) -> None:
    """Rejecting the entire queue by accident should not be one keystroke."""
    db = _queue_of(tmp_path)
    result = runner.invoke(main, ["reject", "--db", str(db)])
    assert result.exit_code != 0
    assert "filter" in result.output


def test_declining_the_prompt_changes_nothing(runner: CliRunner,
                                              tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["reject", "--status", "UNREACHABLE",
                               "--db", str(db)], input="n\n").output
    assert "nothing changed" in out

    from vanguard.store import Store
    assert Store(db).counts_by_status()["UNREACHABLE"] == 3


def test_unmeasured_records_are_excluded_from_filters(runner: CliRunner,
                                                      tmp_path: Path) -> None:
    """A coverage of 0.000 or 1.000 from one requirement should not decide a
    bulk action."""
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    db = tmp_path / "v.db"
    store = Store(db)
    store.initialise()
    store.upsert_vacancy(Vacancy(id="reed:thin", board_id="reed", employer="E",
                                 title="T", description="d"))
    store.create_queue_record("reed:thin", "FLAGGED")
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
            " terms_total, terms_matched, soft_hits, embedder, computed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("reed:thin", 1.0, 0.5, 1.0, 1, 1, 0, "test",
             "2026-08-16T00:00:00+00:00"))

    out = runner.invoke(main, ["reject", "--status", "FLAGGED", "--dry-run",
                               "--db", str(db)]).output
    assert "nothing matched" in out

    included = runner.invoke(main, ["reject", "--status", "FLAGGED",
                                    "--include-unmeasured", "--dry-run",
                                    "--db", str(db)]).output
    assert "1 record(s)" in included


def test_one_refusal_does_not_stop_the_rest(runner: CliRunner,
                                            tmp_path: Path) -> None:
    """A bulk action across fifteen records must not abort on the first
    illegal transition."""
    db = _queue_of(tmp_path)
    from vanguard.store import Store

    Store(db).set_status("reed:9", "DISPATCHED")   # terminal, cannot reject

    out = runner.invoke(main, ["reject", "--status", "UNREACHABLE", "--yes",
                               "--db", str(db)]).output
    assert "2 record(s)" in out


# --- session --------------------------------------------------------------

def test_session_walks_every_record(runner: CliRunner, tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["session", "--status", "PENDING", "--db", str(db)],
                        input="s\ns\ns\ns\ns\n").output
    assert "5 record(s)" in out
    assert "5 of 5" in out


def test_session_records_each_decision(runner: CliRunner, tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    runner.invoke(main, ["session", "--status", "PENDING", "--db", str(db)],
                  input="a\nr\nnot a fit\ns\ns\ns\n")

    from vanguard.store import Store
    counts = Store(db).counts_by_status()
    assert counts.get("APPROVED") == 1
    assert counts.get("REJECTED") == 1
    assert counts.get("PENDING") == 3


def test_quitting_leaves_the_rest_untouched(runner: CliRunner,
                                            tmp_path: Path) -> None:
    """Stopping half way must not decide anything after that point."""
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["session", "--status", "PENDING", "--db", str(db)],
                        input="a\nq\n").output
    assert "Nothing after this point" in out

    from vanguard.store import Store
    assert Store(db).counts_by_status().get("PENDING") == 4


def test_session_shows_gaps_on_request(runner: CliRunner, tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["session", "--status", "PENDING", "--db", str(db)],
                        input="o\ns\nq\n").output
    assert "Type" in out or "nothing unmet" in out


def test_session_on_an_empty_queue(runner: CliRunner, tmp_path: Path) -> None:
    db = _queue_of(tmp_path)
    out = runner.invoke(main, ["session", "--status", "APPROVED",
                               "--db", str(db)]).output
    assert "nothing in APPROVED" in out


# ---------------------------------------------------------------------------
# `todo` — everything waiting on you, in one view
# ---------------------------------------------------------------------------

def _mixed_queue(tmp_path: Path) -> Path:
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    db = tmp_path / "v.db"
    store = Store(db)
    store.initialise()
    rows = [("APPROVED", 0.70, 14, 20), ("APPROVED", 0.65, 13, 20),
            ("PENDING", 0.62, 12, 20), ("PENDING", 1.0, 2, 2),
            ("FLAGGED", 0.30, 6, 20), ("UNREACHABLE", 0.20, 4, 20)]
    for i, (status, coverage, matched, total) in enumerate(rows):
        store.upsert_vacancy(Vacancy(id=f"reed:{i}", board_id="reed",
                                     employer=f"Employer {i}",
                                     title=f"Data Engineer {i}", description="d"))
        store.create_queue_record(f"reed:{i}", "PENDING")
        if status != "PENDING":
            store.set_status(f"reed:{i}", status)
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (f"reed:{i}", coverage, 0.4, 0.85, total, matched, 0, "test",
                 f"2026-08-{10 + i:02d}T00:00:00+00:00"))
    return db


def test_todo_shows_approved_and_pending_together(runner: CliRunner,
                                                  tmp_path: Path) -> None:
    """Switching between two commands to answer "what now?" is friction."""
    db = _mixed_queue(tmp_path)
    out = runner.invoke(main, ["todo", "--db", str(db)]).output
    assert "2 approved" in out and "2 pending" in out


def test_todo_puts_approved_first(runner: CliRunner, tmp_path: Path) -> None:
    """Approved records are decided and waiting to be applied to. Pending is
    reviewing still to do."""
    db = _mixed_queue(tmp_path)
    out = runner.invoke(main, ["todo", "--db", str(db)]).output
    assert out.index("APPLY TO THESE") < out.index("STILL TO REVIEW")


def test_todo_names_the_next_command(runner: CliRunner, tmp_path: Path) -> None:
    db = _mixed_queue(tmp_path)
    out = runner.invoke(main, ["todo", "--db", str(db)]).output
    assert "vanguard apply" in out and "vanguard session" in out


def test_todo_counts_the_rest_without_listing_them(runner: CliRunner,
                                                   tmp_path: Path) -> None:
    db = _mixed_queue(tmp_path)
    out = runner.invoke(main, ["todo", "--db", str(db)]).output
    assert "FLAGGED 1" in out and "UNREACHABLE 1" in out


def test_todo_on_an_empty_queue(runner: CliRunner, tmp_path: Path) -> None:
    out = runner.invoke(main, ["todo", "--db", str(tmp_path / "v.db")]).output
    assert "nothing waiting" in out


def test_todo_marks_unmeasured_records(runner: CliRunner, tmp_path: Path) -> None:
    db = _mixed_queue(tmp_path)
    out = runner.invoke(main, ["todo", "--db", str(db)]).output
    assert "not measured" in out


# --- an empty session must explain itself ---------------------------------

def _all_unmeasured(tmp_path: Path) -> Path:
    """Three PENDING records, all unmeasured — the state after resolving
    FLAGGED records that were flagged for being unscoreable."""
    from vanguard.adapters.base import Vacancy
    from vanguard.store import Store

    db = tmp_path / "v.db"
    store = Store(db)
    store.initialise()
    for i in range(3):
        store.upsert_vacancy(Vacancy(id=f"reed:{i}", board_id="reed",
                                     employer=f"E{i}", title=f"Role {i}",
                                     description="short"))
        store.create_queue_record(f"reed:{i}", "PENDING")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (f"reed:{i}", 1.0, 0.4, 1.0, 2, 2, 0, "test",
                 f"2026-08-{10 + i:02d}T00:00:00+00:00"))
    return db


def test_empty_session_says_why(runner: CliRunner, tmp_path: Path) -> None:
    """"nothing matches" reads as "the queue is empty", which is wrong when
    records were filtered out — and misleading enough that the operator
    reported it as a defect."""
    db = _all_unmeasured(tmp_path)
    out = runner.invoke(main, ["session", "--db", str(db)]).output

    assert "3 record(s) there" in out
    assert "not measured" in out
    assert "--include-unmeasured" in out


def test_a_genuinely_empty_queue_says_so_plainly(runner: CliRunner,
                                                 tmp_path: Path) -> None:
    db = _all_unmeasured(tmp_path)
    out = runner.invoke(main, ["session", "--status", "APPROVED",
                               "--db", str(db)]).output
    assert "nothing in APPROVED" in out
    assert "not measured" not in out


def test_include_unmeasured_reaches_them(runner: CliRunner, tmp_path: Path) -> None:
    db = _all_unmeasured(tmp_path)
    out = runner.invoke(main, ["session", "--include-unmeasured", "--db", str(db)],
                        input="q\n").output
    assert "3 record(s)" in out
