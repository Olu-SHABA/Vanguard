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
