"""
Operator CLI — the seam between the two execution contexts.

    vanguard run                    autonomous: fetch, score, draft, queue, exit
    vanguard review                 list PENDING by rank score
    vanguard review <id>            full record: coverage, gaps, history
    vanguard approve <id>
    vanguard reject <id> [--reason]
    vanguard resolve <id>           work through FLAGGED items
    vanguard override <id> --why    apply despite an unreachable ceiling
    vanguard dispatch <id>          record a submission made by the operator
    vanguard score --advert PATH    standalone scoring
    vanguard stats                  coverage distribution, recurring gaps
    vanguard boards                 registry health

`run` never blocks and never prompts. It writes state and exits. Everything
else is interactive, where blocking input is correct.

Vanguard never transmits. `dispatch` records that the operator submitted an
application; it does not send one.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from pathlib import Path

try:
    import click
except ImportError:  # pragma: no cover
    sys.exit("click required: pip install -e '.[dev]'")

from vanguard import ui
from vanguard.adapters.base import Query, load_registry
from vanguard.archive import ARCHIVE_ROOT, Archive, ArchiveError
from vanguard.coverage import compute_coverage, load_aliases
from vanguard.cv import load as load_cv
from vanguard.extract import extract
from vanguard.gaps import classify_all
from vanguard.ingest import health_check_all, ingest
from vanguard.logs import LogConfig, RunLog, configure
from vanguard.mailbox import FetchStrategy, choose_strategy
from vanguard.process import ProcessStore
from vanguard.mail import Message
from vanguard.queue import IllegalTransition, QueueManager, Status
from vanguard.rank import LexicalEmbedder, rank_score
from vanguard.refactor import refactor
from vanguard.store import Store, StoreError
from vanguard.submission import detect


# ---------------------------------------------------------------------------
# Output helpers
#
# Fixed-width slicing cut mid-word and lost the operative information:
# "adapter 'NHSJobsAPIAdapter' for board 'nhs_jobs' is declared but n" tells
# the operator nothing about what to do. Truncate at a word boundary, mark it,
# and size to the actual terminal rather than an assumed 100 columns.
# ---------------------------------------------------------------------------

MIN_WIDTH = 60


def _load_env(path: Path = Path(".env")) -> int:
    """Load KEY=value pairs from a .env file into the environment.

    Board credentials resolve from `${VAR}` in boards.yaml. Without this they
    must be exported in every new shell, which is the kind of friction that
    ends with someone pasting a key into a tracked file. `.env` is gitignored.

    Existing environment variables win — an explicit export overrides the file.

    `VANGUARD_NO_ENV_FILE=1` skips the file entirely. Tests need it: a test
    that reads `.env` on a configured machine will connect to the operator's
    real mailbox, which is slow, non-deterministic, and touching data no test
    should touch.
    """
    if os.environ.get("VANGUARD_NO_ENV_FILE"):
        return 0
    if not path.is_file():
        return 0
    loaded = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def _terminal_width() -> int:
    """Usable width, from the active theme."""
    return ui.current_theme().width


def _clip(text: str, width: int) -> str:
    return ui.clip(text, width)


def _wrap(text: str, width: int, indent: str = "") -> list[str]:
    return ui.wrap(text, width - len(indent))


def _row(*cells: tuple[str, int]) -> str:
    """Left-aligned columns, each clipped to its own budget."""
    return "  ".join(_clip(value, budget).ljust(budget) for value, budget in cells).rstrip()


# Set by --log/--no-log. None means "use boards.yaml".
_LOG_OVERRIDE: dict[str, bool | None] = {"enabled": None}


def _logging(boards_path: str) -> LogConfig:
    """Resolve logging config, honouring the command-line override."""
    try:
        config = load_registry(boards_path).logging_config
    except Exception:
        config = LogConfig()
    override = _LOG_OVERRIDE.get("enabled")
    if override is not None:
        config = LogConfig(**{**config.__dict__, "enabled": override})
    configure(config)
    return config


#: Gmail accepts long queries; the constraint is the IMAP literal, which is
#: generous. High enough that truncation is rare, and reported when it happens.
MAX_SEARCH_TERMS = 120


STATUS_TONE = {
    "PENDING": ui.Tone.GOOD,
    "APPROVED": ui.Tone.GOOD,
    "DISPATCHED": ui.Tone.INFO,
    "FLAGGED": ui.Tone.WARN,
    "UNREACHABLE": ui.Tone.BAD,
    "REJECTED": ui.Tone.MUTED,
}


def _status(label: str, width: int = 12) -> str:
    """Status as symbol plus word. Never colour alone."""
    return ui.badge(label, STATUS_TONE.get(label, ui.Tone.PLAIN), width=width)


ADVERTS_DIR = Path("adverts")

DEFAULTS = {
    "cv": "data/canonical_cv.md",
    "aliases": "config/alias_table.yaml",
    "boards": "config/boards.yaml",
    "db": "data/vanguard.db",
}


def _embedder(prefer_model: bool):
    """Real model if available, lexical fallback otherwise. Reports which.

    A LexicalEmbedder result is degraded and is recorded as such, so a
    recalibration pass can exclude it rather than mixing it with real scores.
    """
    if prefer_model:
        try:
            from vanguard.rank import TERM_MODEL, EmbeddingCache, SentenceTransformerEmbedder

            cache = EmbeddingCache(Path("data/.embeddings.json"))
            emb = SentenceTransformerEmbedder(TERM_MODEL, cache)
            emb.similarity("warmup", "warmup")
            return emb, "minilm"
        except Exception as exc:
            click.echo(f"  model unavailable ({exc}); using lexical fallback", err=True)
    return LexicalEmbedder(), "lexical"



def _score_and_queue(vacancy, store, queue, canonical, alias_table, embedder, name,
                     *, gate: float = 0.94, rank: float | None = None) -> str:
    """Score one vacancy, classify, and write the queue record. Returns status."""
    from vanguard.diagnostics import Decision, diagnose_advert

    spec_early = detect(vacancy.description)
    if spec_early.vacancy_reference and not vacancy.reference:
        vacancy.reference = spec_early.vacancy_reference
    store.upsert_vacancy(vacancy)
    requirements = extract(vacancy.description, job_title=vacancy.title)

    # Observe how the advert parsed. Never changes behaviour; the unrecognised
    # headings recorded here are the evidence for widening classify_heading().
    diagnostic = diagnose_advert(
        vacancy.id, vacancy.description, board_id=vacancy.board_id,
        partial=vacancy.description_is_partial, terms_extracted=len(requirements),
        job_title=vacancy.title,
    )
    diagnostic.record(
        Decision.HYDRATION_NOT_ATTEMPTED if vacancy.description_is_partial
        else Decision.HYDRATED
    )
    outcome = refactor(requirements, canonical, alias_table, embedder,
                       threshold=gate,
                       source_is_partial=vacancy.description_is_partial)
    gaps = classify_all(outcome.final, canonical)
    spec = detect(vacancy.description)

    store.record_score(
        vacancy.id, outcome.final,
        rank if rank is not None else rank_score(
            canonical.full_text(), vacancy.description, embedder),
        embedder=name, gaps=gaps,
    )

    status = Status(outcome.status)
    note = outcome.exit_reason.value
    if spec.flagged:
        status, note = Status.FLAGGED, spec.flag_reason
    elif gaps.requires_operator and status is Status.PENDING:
        status = Status.FLAGGED
        note = f"{len(gaps.unconfirmed)} gap proposal(s) awaiting confirmation"

    diagnostic.record(
        Decision.SCORE_UNRELIABLE if outcome.final.unreliable else Decision.SCORED,
        f"C={outcome.final.coverage:.3f}",
    )
    store.record_diagnostic(diagnostic)

    queue.enqueue(
        vacancy.id, status,
        submission_type=spec.submission_type.value,
        flags={"ANONYMISE": spec.anonymise, "WORD_LIMIT": spec.word_limit,
               "CRITERIA": len(spec.assessed_criteria)},
        note=note,
    )
    width = ui.current_theme().width
    detail = ("not measured".ljust(15) if outcome.final.unreliable
              else f"ceiling {outcome.final.ceiling:.2f}".ljust(15))
    click.echo(
        f"  {_status(status.value)}  {outcome.final.coverage:.3f}  {detail} "
        f"{_clip(vacancy.title, max(16, width - 48))}"
    )
    return status.value


def boards_default() -> str:
    return DEFAULTS["boards"]


def _mail_block(boards_path: str) -> dict:
    try:
        return (load_registry(boards_path).defaults.get("mail") or {})
    except Exception:
        return {}


def _mail_strategy(boards_path: str) -> str:
    return str(_mail_block(boards_path).get("strategy", "auto")).lower()


def _window_threshold(boards_path: str) -> int:
    from vanguard.mailbox import DEFAULT_WINDOW_THRESHOLD

    try:
        return int(_mail_block(boards_path).get(
            "window_threshold", DEFAULT_WINDOW_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_THRESHOLD


def _filled_rows(path: Path) -> int:
    """Rows in a template that carry an employer or a url.

    A template of blank rows is disposable; one with work in it is not.
    """
    import csv as csv_module

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(
                1 for row in csv_module.DictReader(handle)
                if (row.get("employer") or "").strip()
                or (row.get("url") or "").strip()
            )
    except (OSError, ValueError):
        return 0


def _open_applications(store) -> list:
    """Applications that could receive a reply — submitted or awaiting it.

    The employer domain is derived from the vacancy URL where the vacancy
    lives on the employer's own site, which is what makes sender-domain
    correlation work without configuring anything.
    """
    from vanguard.mail import Application, domain_of

    out = []
    for row in store.list_queue(limit=500):
        if row["status"] not in ("DISPATCHED", "APPROVED"):
            continue
        vacancy = store.vacancy(row["vacancy_id"])
        out.append(Application(
            vacancy_id=row["vacancy_id"],
            employer=row["employer"],
            title=row["title"],
            reference=(vacancy["reference"] if vacancy else "") or "",
            employer_domain=domain_of(vacancy["url"] if vacancy else ""),
        ))
    return out


def registry_gate(boards_path: str = "") -> str:
    """The gate in force, for display. Never fails a render."""
    try:
        return f"{load_registry(boards_path or DEFAULTS['boards']).coverage_gate:.2f}"
    except Exception:
        return "?"


def _ctx(db: str):
    store = Store(Path(db))
    store.initialise()
    return store, QueueManager(store)


@click.group()
@click.version_option("0.1.0", prog_name="vanguard")
@click.option("--plain", is_flag=True, help="No colour, boxes or symbols. For screen readers and logs.")
@click.option("--no-color", "no_colour", is_flag=True, help="Disable colour. Symbols and words remain.")
@click.option("--ascii", "ascii_only", is_flag=True, help="ASCII instead of Unicode box drawing.")
@click.option("--high-contrast", is_flag=True, help="Drop dim and italic styling.")
@click.option("--width", type=int, default=0, help="Override detected terminal width.")
@click.option("--log/--no-log", "logging_on", default=None,
              help="Override the logging setting in boards.yaml for this run.")
def main(plain, no_colour, ascii_only, high_contrast, width, logging_on) -> None:
    """Project Vanguard — semi-autonomous job application pipeline.

    Presentation adapts to the terminal and honours NO_COLOR. Status is always
    shown as a symbol AND a word, so nothing depends on colour alone.
    """
    _load_env()
    _LOG_OVERRIDE["enabled"] = logging_on

    detected = ui.Theme.detect()
    ui.set_theme(ui.Theme(
        colour=detected.colour and not (plain or no_colour),
        unicode=detected.unicode and not ascii_only,
        decorated=detected.decorated and not plain,
        high_contrast=high_contrast or detected.high_contrast,
        width=width or detected.width,
    ))


# ---------------------------------------------------------------------------
# Autonomous
# ---------------------------------------------------------------------------

@main.command()
@click.option("--boards", default=DEFAULTS["boards"], help="Board registry.")
@click.option("--cv", default=DEFAULTS["cv"], help="Canonical CV.")
@click.option("--aliases", default=DEFAULTS["aliases"], help="Alias table.")
@click.option("--db", default=DEFAULTS["db"], help="Vacancy store.")
@click.option("--title", multiple=True, help="Override query keywords.")
@click.option("--location", default="", help="Override query location.")
@click.option("--no-model", is_flag=True, help="Force the lexical fallback.")
def run(boards, cv, aliases, db, title, location, no_model) -> None:
    """Fetch, score, classify, queue, exit. Never blocks, never prompts."""
    store, queue = _ctx(db)

    registry = load_registry(boards)
    log_config = _logging(boards)
    run_log = RunLog("run", db_path=Path(db), config=log_config)
    run_log.__enter__()

    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    embedder, embedder_name = _embedder(not no_model)

    click.echo(f"ingesting from {len(registry.automatable)} automatable board(s)")
    result = ingest(registry, Query(keywords=tuple(title), location=location))

    # Report what CONTRIBUTED. Disabled and Tier 3 boards are expected to be
    # absent and printing a line each buries the vacancies under seven lines
    # of noise. Collapse them; `vanguard boards` gives the per-board detail.
    contributed = [o for o in result.outcomes if o.ok]
    failed = result.failures
    skipped = [o for o in result.outcomes if o.skipped]

    for outcome in contributed:
        click.echo(f"  {outcome}")
    for outcome in failed:
        click.echo(f"  {outcome}", err=True)
    if skipped:
        click.echo(f"  {len(skipped)} board(s) skipped — see: vanguard boards")

    click.echo(
        f"collected {result.collected} -> kept {result.kept} "
        f"({result.duplicates} duplicate(s) logged)"
    )
    if not result.complete:
        click.echo(f"  INCOMPLETE — {len(result.truncations)} truncation(s):")
        width = _terminal_width()
        for truncation in result.truncations:
            click.echo(f"    {_clip(str(truncation), width - 4)}")

    run_log.count(collected=result.collected, kept=result.kept,
                  duplicates=result.duplicates)
    for outcome in result.failures:
        run_log.error(outcome.error, source="ingest", board_id=outcome.board_id)
    for truncation in result.truncations:
        run_log.warn(str(truncation), source="ingest", board_id=truncation.board_id)

    if not result.vacancies:
        click.echo("no vacancies. exiting.")
        run_log.__exit__(None, None, None)
        return

    # --- rank pre-filter --------------------------------------------------
    # One embedding per vacancy, no API call. Hydration and per-term scoring
    # are far more expensive, and spending them on a Finance Business Partner
    # wastes a slot a Machine Learning Engineer could have used.
    from vanguard.ingest import hydrate_selected

    floor = registry.rank_floor
    cv_text = canonical.full_text()

    ranked = []
    for vacancy in result.vacancies:
        try:
            ranked.append((rank_score(cv_text, vacancy.description, embedder), vacancy))
        except Exception:
            ranked.append((0.0, vacancy))
    ranked.sort(key=lambda pair: pair[0], reverse=True)

    selected = [(s, v) for s, v in ranked if s >= floor]
    dropped = len(ranked) - len(selected)
    if dropped:
        click.echo(
            f"\nrank filter: {len(selected)} of {len(ranked)} above {floor:.2f} "
            f"({dropped} not hydrated or scored)"
        )

    run_log.count(above_rank_floor=len(selected), below_rank_floor=dropped)
    if not selected:
        click.echo("nothing above the rank floor. exiting.")
        run_log.__exit__(None, None, None)
        return

    hydrated, notes = hydrate_selected(registry, [v for _, v in selected])
    for note in notes:
        click.echo(f"  {_clip(str(note), _terminal_width() - 4)}")
    by_id = {v.id: v for v in hydrated}

    click.echo()
    click.echo(ui.rule(f"SCORING  {len(selected)} vacancies  ·  "
                       f"{embedder_name}  ·  gate {registry.coverage_gate:.2f}"))
    click.echo(f"  {'STATUS':<14} {'C':>5}  {'':<15} TITLE")
    this_run: dict[str, int] = {}
    for score, vacancy in selected:
        vacancy = by_id.get(vacancy.id, vacancy)
        try:
            outcome_status = _score_and_queue(
                vacancy, store, queue, canonical, alias_table,
                embedder, embedder_name,
                gate=registry.coverage_gate, rank=score)
            this_run[outcome_status] = this_run.get(outcome_status, 0) + 1
        except Exception as exc:
            # One vacancy failing must not abort the run — but the reason is
            # recorded rather than lost with the terminal.
            run_log.error(str(exc), source="scoring", vacancy_id=vacancy.id,
                          detail=vacancy.title)
            click.echo(f"  ERROR        {_clip(vacancy.title, 40)}: {exc}", err=True)

    click.echo()
    click.echo(ui.rule("RESULT"))
    # THIS RUN's outcomes. `counts_by_status()` covers the whole queue table,
    # every vacancy ever ingested — reporting that under a RESULT heading
    # showed 543 records for a run that scored 14.
    ordered = ["PENDING", "FLAGGED", "UNREACHABLE"]
    scored_now = sum(this_run.values())
    click.echo(f"  this run scored {scored_now}:")
    for label in ordered:
        if this_run.get(label):
            click.echo(f"    {_status(label)}  {this_run[label]}")

    counts = store.counts_by_status()
    total = sum(counts.values())
    if total:
        click.echo(f"\n  queue total, all runs — {total} record(s):")
        for label in ["PENDING", "FLAGGED", "UNREACHABLE",
                      "APPROVED", "DISPATCHED", "REJECTED"]:
            if counts.get(label):
                click.echo(f"    {_status(label)}  {counts[label]}")

    if counts.get("PENDING"):
        click.echo(f"\n  {counts['PENDING']} ready to review:  vanguard review")
    run_log.count(scored=len(selected))
    run_log.__exit__(None, None, None)

    click.echo("\n  no transmission occurred — Vanguard never submits")
    if log_config.enabled:
        click.echo(f"  logged to {log_config.directory}/vanguard.log and the run table")


@main.command()
@click.option("--file", "path", type=click.Path(exists=True), help="File holding the advert text.")
@click.option("--url", default="", help="Vacancy URL, for the archive.")
@click.option("--board", default="linkedin", help="Registry id to attribute it to.")
@click.option("--employer", default="", help="Overrides anything parsed.")
@click.option("--title", default="", help="Overrides anything parsed.")
@click.option("--boards", default=DEFAULTS["boards"])
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--aliases", default=DEFAULTS["aliases"])
@click.option("--db", default=DEFAULTS["db"])
@click.option("--no-model", is_flag=True)
def paste(path, url, board, employer, title, boards, cv, aliases, db, no_model) -> None:
    """Ingest a vacancy by hand, then score and queue it.

    Tier 3 boards are hand-fed by design — LinkedIn's User Agreement prohibits
    automated collection, and Civil Service Jobs serves a bot interstitial.
    Everything downstream runs identically on a pasted advert.

    Reads --file, or stdin if omitted.
    """
    from vanguard.adapters.manual import ManualEntryAdapter

    text = Path(path).read_text(encoding="utf-8") if path else click.get_text_stream("stdin").read()
    if not text.strip():
        raise click.ClickException("no advert text supplied")

    store, queue = _ctx(db)
    registry = load_registry(boards)
    try:
        entry = registry.get(board)
    except KeyError as exc:
        raise click.ClickException(f"unknown board {board!r}") from exc

    try:
        vacancy = ManualEntryAdapter(entry).submit(
            text, url=url, employer=employer, title=title
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    embedder, name = _embedder(not no_model)

    click.echo(f"ingested {vacancy.title!r} from {vacancy.employer} [{name}]")
    _score_and_queue(vacancy, store, queue, canonical, alias_table, embedder, name,
                     gate=registry.coverage_gate)
    click.echo(f"\n{vacancy.id}\nvanguard review {vacancy.id}")


# ---------------------------------------------------------------------------
# Interactive
# ---------------------------------------------------------------------------

@main.command()
@click.argument("vacancy_id", required=False)
@click.option("--status", default="PENDING", help="Filter: PENDING, FLAGGED, ...")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--boards", "boards_path", default=DEFAULTS["boards"])
def review(vacancy_id, status, db, boards_path) -> None:
    """List queued records, or show one in full."""
    store, queue = _ctx(db)

    if vacancy_id:
        record = store.queue_record(vacancy_id)
        if record is None:
            raise click.ClickException(f"no queue record for {vacancy_id!r}")
        vacancy = store.vacancy(vacancy_id)
        score = store.latest_score(vacancy_id)
        width = _terminal_width()

        # --- heading ------------------------------------------------------
        click.echo()
        click.echo(ui.rule(_clip(vacancy["title"], width - 8)))
        click.echo(ui.field_list([
            ("employer", vacancy["employer"]),
            ("location", vacancy["location"] or ""),
            ("salary", vacancy["salary_band"] or ""),
            ("closes", vacancy["closes"] or ""),
            ("reference", vacancy["reference"] or ""),
        ], indent="  "))

        click.echo()
        click.echo(f"  {_status(record['status'])}   "
                   f"{record['submission_type'] or 'STANDARD_CV'}")
        if record["note"]:
            for line in _wrap(record["note"], width - 6):
                click.echo(f"      {line}")

        # --- score --------------------------------------------------------
        if score:
            click.echo()
            click.echo(ui.rule("SCORE"))
            matched, total = score["terms_matched"], score["terms_total"]
            click.echo("  " + ui.bar(matched, total, width=18))
            click.echo(ui.field_list([
                ("coverage", f"{score['coverage']:.3f}   (gate {registry_gate(boards_path)})"),
                ("ceiling", f"{score['ceiling']:.3f}   best attainable with Type 3 gaps unmet"),
                ("rank", f"{score['rank_score'] or 0:.3f}   orders the queue; never gates"),
                ("embedder", score["embedder"]),
            ], indent="  "))

        # --- gaps ---------------------------------------------------------
        rows_gaps = store.gaps_for(vacancy_id)
        unmet = [r for r in rows_gaps if r["outcome"] == "GAP"]
        if unmet:
            by_type: dict[int | None, list] = {}
            for r in unmet:
                by_type.setdefault(r["gap_type"], []).append(r)

            click.echo()
            click.echo(ui.rule(f"UNMET  ·  {len(unmet)}"))
            labels = {
                1: ("Type 1  evidenced, unstated — may be added", ui.Tone.WARN),
                2: ("Type 2  evidenced, differently named", ui.Tone.WARN),
                3: ("Type 3  not evidenced — NO CV EDIT PERMITTED", ui.Tone.BAD),
                None: ("unclassified", ui.Tone.MUTED),
            }
            for gap_type in (1, 2, 3, None):
                group = by_type.get(gap_type)
                if not group:
                    continue
                heading, tone = labels[gap_type]
                click.echo(f"\n  {ui.badge(heading, tone)}")
                for r in group:
                    click.echo(f"      {_clip(r['term'], width - 10)}")
                    for line in _wrap(r["exclusion"], width - 14):
                        click.echo(f"          {line}")

        # --- eligibility ---------------------------------------------------
        # A gate on whether you may apply at all, distinct from fit. Shown
        # before the gaps: a perfect coverage score is irrelevant if the role
        # requires clearance you do not hold.
        diag_row = store.diagnostic_for(vacancy_id)
        if diag_row:
            import json as _json
            try:
                notes = (_json.loads(diag_row["heading_kinds"] or "{}")
                         ).get("__eligibility__") or []
            except ValueError:
                notes = []
            if notes:
                click.echo()
                click.echo(ui.rule("ELIGIBILITY  ·  check before applying"))
                for note in notes:
                    click.echo(f"  {ui.badge('GATE', ui.Tone.BAD)}")
                    for line in _wrap(note, width - 6):
                        click.echo(f"      {line}")

        # --- why not scored -----------------------------------------------
        diagnostic = store.diagnostic_for(vacancy_id)
        if diagnostic and diagnostic["refusal"]:
            from vanguard.diagnostics import RefusalReason
            try:
                explanation = RefusalReason(diagnostic["refusal"]).explanation
            except ValueError:
                explanation = ""
            click.echo()
            click.echo(ui.panel(f"NOT SCORED — {diagnostic['refusal']}",
                                explanation, tone=ui.Tone.WARN))
            import json as _json
            try:
                found = _json.loads(diagnostic["headings"] or "[]")
            except ValueError:
                found = []
            if found:
                click.echo("  headings found:")
                for heading in found[:8]:
                    click.echo(f"      {_clip(heading, width - 10)}")

        # --- history ------------------------------------------------------
        click.echo()
        click.echo(ui.rule("HISTORY"))
        for frm, to, at in queue.history(vacancy_id):
            click.echo(f"  {at[:16].replace('T', ' ')}   "
                       f"{frm:>12} -> {_status(to, 0)}")

        if vacancy["url"]:
            click.echo(f"\n  {vacancy['url']}")

        # --- what you can do ----------------------------------------------
        click.echo()
        nxt = {
            "PENDING": ["approve", "reject"],
            "FLAGGED": ["resolve", "reject"],
            "UNREACHABLE": ["override --why \"...\"", "reject"],
            "APPROVED": ["dispatch", "reject"],
        }.get(record["status"], [])
        if nxt:
            options = "   ".join(f"vanguard {verb} {vacancy_id}" for verb in nxt)
            click.echo(f"  next:  {options}")
        return

    rows = store.list_queue(status.upper())
    if not rows:
        click.echo(f"no records with status {status.upper()}")
        return
    click.echo(ui.rule(f"{status.upper()}  ·  {len(rows)} record(s), strongest first"))

    body = []
    unmeasured = 0
    for r in rows:
        coverage, terms = _coverage_cell(r)
        if coverage == "not measured":
            unmeasured += 1
        body.append([coverage, terms, f"{r['rank_score'] or 0:.3f}",
                     r["employer"], r["title"], r["vacancy_id"]])

    click.echo(ui.table(
        [
            ui.Column("COVERAGE", 0.5, 12, "right"),
            ui.Column("TERMS", 0.3, 6, "right", tone=ui.Tone.MUTED),
            ui.Column("RANK", 0.3, 5, "right"),
            ui.Column("EMPLOYER", 1.1, 12),
            ui.Column("TITLE", 2.0, 16),
            ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
        ],
        body,
    ))

    click.echo()
    if unmeasured:
        click.echo(
            f"  {ui.badge(f'{unmeasured} not measured', ui.Tone.WARN)} — advert had "
            f"fewer than {_min_terms()} requirements, or partial text. "
            "Run `vanguard diagnose`."
        )
    click.echo("  vanguard review <ID>   for the full record")


@main.command()
@click.argument("vacancy_id", required=False)
@click.option("--note", default="")
@click.option("--status", default="", help="Approve every record in this state.")
@click.option("--min-coverage", type=float, default=None,
              help="Only records at or above this coverage.")
@click.option("--employer", default="", help="Only records matching this employer.")
@click.option("--dry-run", is_flag=True, help="Show what would change.")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--db", default=DEFAULTS["db"])
def approve(vacancy_id, note, status, min_coverage, employer, dry_run, yes,
            db) -> None:
    """Approve for dispatch. Only APPROVED is dispatch-eligible.

    One id, or a filter. A filtered approve always previews first and asks
    before acting — approving is where a claim gets made on your behalf, and
    doing it to fifteen records unseen is not something to make easy.

    Unmeasured scores are excluded from filters. Pass ids individually if you
    want one anyway.
    """
    store, queue = _ctx(db)

    if vacancy_id:
        _apply(queue.approve, vacancy_id, note)
        return

    if not (status or min_coverage is not None or employer):
        raise click.ClickException(
            "pass a vacancy id, or a filter: --status, --min-coverage, --employer")

    rows = _select(store, status=status or "PENDING", min_coverage=min_coverage,
                   employer=employer)
    _preview(rows, "approve")
    if not rows:
        return

    if dry_run:
        click.echo("\n  dry run — nothing changed")
        return

    if not yes:
        click.echo()
        if not click.confirm(f"  approve {len(rows)} record(s)?", default=False):
            click.echo("  nothing changed")
            return

    _apply_bulk(queue.approve, rows, note, "approved")
    click.echo("\n  approved means eligible for dispatch, not submitted")


@main.command()
@click.argument("vacancy_id", required=False)
@click.option("--reason", default="")
@click.option("--status", default="", help="Reject every record in this state.")
@click.option("--max-coverage", type=float, default=None,
              help="Only records at or below this coverage.")
@click.option("--employer", default="", help="Only records matching this employer.")
@click.option("--include-unmeasured", is_flag=True,
              help="Include records whose coverage was never measured.")
@click.option("--dry-run", is_flag=True, help="Show what would change.")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--db", default=DEFAULTS["db"])
def reject(vacancy_id, reason, status, max_coverage, employer,
           include_unmeasured, dry_run, yes, db) -> None:
    """Reject and archive. Terminal — the record keeps its reason.

    One id, or a filter. Clearing a backlog of UNREACHABLE records is one
    judgement applied to many, and doing it one at a time is typing rather
    than thinking.
    """
    store, queue = _ctx(db)

    if vacancy_id:
        _apply(queue.reject, vacancy_id, reason)
        return

    if not (status or max_coverage is not None or employer):
        raise click.ClickException(
            "pass a vacancy id, or a filter: --status, --max-coverage, --employer")

    rows = _select(store, status=status, max_coverage=max_coverage,
                   employer=employer, include_unmeasured=include_unmeasured)
    _preview(rows, "reject")
    if not rows:
        return

    if dry_run:
        click.echo("\n  dry run — nothing changed")
        return

    if not yes:
        click.echo()
        if not click.confirm(f"  reject {len(rows)} record(s)?", default=False):
            click.echo("  nothing changed")
            return

    _apply_bulk(queue.reject, rows,
                reason or f"bulk reject: {status or 'filtered'}", "rejected")


@main.command()
@click.argument("vacancy_id")
@click.option("--note", default="")
@click.option("--db", default=DEFAULTS["db"])
def resolve(vacancy_id, note, db) -> None:
    """Mark a FLAGGED ambiguity resolved. Returns to PENDING."""
    _, queue = _ctx(db)
    _apply(queue.resolve, vacancy_id, note)


@main.command()
@click.argument("vacancy_id")
@click.option("--why", required=True, help="Justification. Required.")
@click.option("--db", default=DEFAULTS["db"])
def override(vacancy_id, why, db) -> None:
    """Apply despite an unreachable coverage ceiling. Justification required."""
    _, queue = _ctx(db)
    _apply(queue.override_unreachable, vacancy_id, why)


@main.command()
@click.argument("vacancy_id")
@click.option("--note", default="")
@click.option("--cv", "cv_pdf", type=click.Path(exists=True),
              help="The CV PDF actually submitted.")
@click.option("--cover-letter", type=click.Path(exists=True),
              help="The cover letter or essay actually submitted.")
@click.option("--archive-root", default=str(ARCHIVE_ROOT),
              help="Where applications are archived.")
@click.option("--no-archive", is_flag=True, help="Record the dispatch without archiving.")
@click.option("--cv-source", default=DEFAULTS["cv"],
              help="Canonical CV markdown to archive alongside the PDF.")
@click.option("--db", default=DEFAULTS["db"])
def dispatch(vacancy_id, note, cv_pdf, cover_letter, archive_root,
             no_archive, cv_source, db) -> None:
    """Record a submission YOU made, and archive what was sent.

    Vanguard never transmits. This records that you did, and writes the job
    description and CV to `Pipeline_Archive/` so the application can be
    reconstructed when an interview happens six weeks later and the advert has
    been taken down.
    """
    store, queue = _ctx(db)

    # Already dispatched? Archive the extra files without a transition.
    #
    # DISPATCHED is terminal and rightly so, but that left an operator who
    # dispatched and then realised the cover letter was not attached with no
    # way to add it. The transition is what must not repeat; archiving more
    # evidence of what was sent is never wrong.
    existing = store.queue_record(vacancy_id)
    already = existing is not None and existing["status"] == "DISPATCHED"

    if already:
        click.echo(f"  {ui.badge('ALREADY DISPATCHED', ui.Tone.MUTED)} "
                   f"{vacancy_id} — adding to the existing archive")
    else:
        _apply(queue.dispatch, vacancy_id, note)

    if no_archive:
        return

    vacancy = store.vacancy(vacancy_id)
    if vacancy is None:
        return

    record = store.queue_record(vacancy_id)
    score = store.latest_score(vacancy_id)
    default_cv = Path("out/cv.pdf")

    try:
        archived = Archive(Path(archive_root)).write(
            vacancy_id=vacancy_id,
            employer=vacancy["employer"],
            title=vacancy["title"],
            job_description=vacancy["description"],
            cv_markdown=Path(cv_source).read_text(encoding="utf-8")
                        if Path(cv_source).is_file() else "",
            cv_pdf=Path(cv_pdf) if cv_pdf else (default_cv if default_cv.is_file() else None),
            cover_letter=Path(cover_letter) if cover_letter else None,
            metadata={
                "url": vacancy["url"],
                "reference": vacancy["reference"],
                "submission_type": record["submission_type"] if record else "",
                "coverage": score["coverage"] if score else None,
                "ceiling": score["ceiling"] if score else None,
                "embedder": score["embedder"] if score else "",
            },
        )
    except ArchiveError as exc:
        click.echo(f"  not archived: {exc}", err=True)
        return

    click.echo(f"  archived {archived.summary()}")
    if not archived.complete:
        click.echo("  WARNING: no CV archived — pass --cv, or render out/cv.pdf first",
                   err=True)


def _min_terms() -> int:
    """The confidence floor. Imported lazily so the CLI starts without the
    scoring dependencies installed."""
    from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

    return MIN_TERMS_FOR_CONFIDENCE


def _letter_filename(employer: str, title: str, vacancy_id: str,
                     directory: Path) -> str:
    """A filename you can read at a glance.

    `cover_letter_linkedin_4f16fe0ad2a8cdf2.md` is safe and unreadable — with
    three letters open you would have to read each to know which is which.
    Employer and title identify it; the vacancy id is appended only when two
    letters would otherwise collide.
    """
    def clean(text: str) -> str:
        text = re.sub(r"[^A-Za-z0-9 _-]", "", (text or "").strip())
        return re.sub(r"\s+", "_", text).strip("_")[:48]

    employer_part = clean(employer) or "Employer"
    title_part = clean(title)

    stem = f"{employer_part}_{title_part}" if title_part else employer_part
    candidate = f"{stem}.md"

    if not (directory / candidate).exists():
        return candidate

    # Two vacancies with the same employer and title. Distinguish by the id's
    # own identifying part — the segment after the board name — rather than a
    # mid-string slice, which produced names like `din_other999`.
    tail = vacancy_id.rsplit(":", 1)[-1]
    tail = re.sub(r"[^A-Za-z0-9._-]", "", tail)[:10] or "2"
    return f"{stem}_{tail}.md"


def _cv_header(cv_path: str) -> tuple[str, str]:
    """Applicant name and contact, read from the CV's own header.

    Taken from the document rather than configured separately, so a letter
    and the CV beside it can never disagree about who sent them.
    """
    name, contact = "", ""
    try:
        for line in Path(cv_path).read_text(encoding="utf-8").splitlines()[:12]:
            line = line.strip()
            if line.startswith("# ") and not name:
                # CV headers are conventionally upper case; a letter is not.
                name = line[2:].strip()
                if name.isupper():
                    name = name.title()
            elif "@" in line and not contact:
                contact = line.strip("*").split("|")[1].strip() if "|" in line \
                    else line.strip("*").strip()
                contact = next((part.strip() for part in contact.split("|")
                                if "@" in part), contact)
    except OSError:
        pass
    return name, contact


def _coverage_cell(row) -> tuple[str, str]:
    """Coverage and its denominator — or a marker when it was not measured.

    A bare `1.000` for a vacancy scored on one requirement reads as the best
    match in the queue. It means the opposite.
    """
    from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

    total = row["terms_total"] or 0
    if total < MIN_TERMS_FOR_CONFIDENCE or bool(row["partial"]):
        return "not measured", f"{total} terms" if total else "no terms"
    return f"{row['coverage'] or 0:.3f}", f"{row['terms_matched']}/{total}"


def _select(store, *, status: str = "", min_coverage: float | None = None,
            max_coverage: float | None = None, employer: str = "",
            include_unmeasured: bool = False, limit: int = 500) -> list:
    """Queue records matching a filter, strongest first.

    Unmeasured scores are excluded by default. A record whose coverage was
    computed from fewer than six requirements is 0.000 or 1.000 depending on
    whether one term happened to match, and neither figure should decide a
    bulk action.
    """
    from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

    rows = store.list_queue(status.upper() if status else None, limit=limit)
    out = []
    for row in rows:
        total = row["terms_total"] or 0
        unmeasured = total < MIN_TERMS_FOR_CONFIDENCE or bool(row["partial"])
        if unmeasured and not include_unmeasured:
            continue

        coverage = row["coverage"]
        if min_coverage is not None and (coverage or 0) < min_coverage:
            continue
        if max_coverage is not None and (coverage or 0) > max_coverage:
            continue
        if employer and employer.lower() not in (row["employer"] or "").lower():
            continue
        out.append(row)
    return out


def _preview(rows, action: str) -> None:
    """Show exactly what a bulk operation would change, before it does."""
    click.echo(ui.rule(f"{action.upper()}  ·  {len(rows)} record(s)"))
    if not rows:
        click.echo("  nothing matched the filter")
        return
    click.echo(ui.table(
        [
            ui.Column("COVERAGE", 0.4, 8, "right"),
            ui.Column("TERMS", 0.3, 5, "right", tone=ui.Tone.MUTED),
            ui.Column("EMPLOYER", 1.0, 12),
            ui.Column("TITLE", 1.8, 16),
            ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
        ],
        [[f"{r['coverage'] or 0:.3f}",
          f"{r['terms_matched']}/{r['terms_total']}",
          r["employer"], r["title"], r["vacancy_id"]] for r in rows],
    ))


def _apply_bulk(fn, rows, note: str, action: str) -> int:
    """Transition many records. One failure does not stop the rest."""
    changed, refused = 0, []
    for row in rows:
        try:
            fn(row["vacancy_id"], note)
            changed += 1
        except (IllegalTransition, StoreError, ValueError) as exc:
            refused.append((row["vacancy_id"], str(exc)))

    click.echo(f"\n  {ui.badge(action.upper(), ui.Tone.GOOD)} {changed} record(s)")
    if refused:
        click.echo(f"  {ui.badge(f'{len(refused)} refused', ui.Tone.WARN)}")
        for vacancy_id, reason in refused[:8]:
            click.echo(f"      {vacancy_id:<28} {_clip(reason, 44)}")
    return changed


def _apply(fn, vacancy_id: str, arg: str) -> None:
    try:
        click.echo(f"{vacancy_id} -> {fn(vacancy_id, arg).value}")
    except IllegalTransition as exc:
        raise click.ClickException(str(exc)) from exc
    except (StoreError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


# ---------------------------------------------------------------------------
# Standalone
# ---------------------------------------------------------------------------

@main.command()
@click.option("--advert", required=True, type=click.Path(exists=True))
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--aliases", default=DEFAULTS["aliases"])
@click.option("--boards", default=DEFAULTS["boards"])
@click.option("--no-model", is_flag=True)
def score(advert, cv, aliases, boards, no_model) -> None:
    """Score one advert. No database, no queue — an honest gap report."""
    text = Path(advert).read_text(encoding="utf-8")
    canonical = load_cv(cv)
    embedder, name = _embedder(not no_model)

    try:
        gate = load_registry(boards).coverage_gate
    except Exception:
        gate = 0.94
    report = compute_coverage(extract(text), canonical, load_aliases(aliases), embedder,
                              threshold=gate)
    gaps = classify_all(report, canonical)
    spec = detect(text)

    click.echo(f"\n{report.summary()}   [{name}]")
    click.echo(f"S = {rank_score(canonical.full_text(), text, embedder):.3f} (ranking only)")
    click.echo(f"\n{spec.summary()}")
    click.echo(f"\n{gaps.summary()}")

    if report.excluded_gaps:
        click.echo("\nblocked by alias table (Tier C) — no CV edit permitted:")
        width = _terminal_width()
        for r in report.excluded_gaps:
            label = r.requirement.canonical or r.requirement.text
            click.echo(f"  {_clip(label, width - 4)}")

    other = [g for g in gaps.type_3 if not g.blocked_by_exclusion]
    if other:
        click.echo("\nunmet, not evidenced:")
        for g in other:
            click.echo(f"  {_clip(g.term, _terminal_width() - 4)}")


@main.command()
@click.option("--db", default=DEFAULTS["db"])
@click.option("--storage", is_flag=True, help="Row counts and database size.")
def stats(db, storage) -> None:
    """Coverage distribution and recurring gaps. The recalibration input."""
    store, queue = _ctx(db)
    rows = store.coverage_distribution()

    click.echo(f"queue: {queue.summary()}")
    click.echo(f"vacancies: {store.count_vacancies()}   reliably scored: {len(rows)}")

    unmeasured = store.unmeasured_count()

    if rows:
        values = sorted(r["coverage"] for r in rows if r["coverage"] is not None)
        mid = values[len(values) // 2]
        click.echo(
            f"\ncoverage ({len(values)} reliable)  min {values[0]:.3f}  "
            f"median {mid:.3f}  max {values[-1]:.3f}"
        )
        try:
            gate = float(registry_gate())
        except ValueError:
            gate = 0.60
        at_gate = sum(1 for v in values if v >= gate)
        click.echo(f"at or above the {gate:.2f} gate: {at_gate}/{len(values)}")
    else:
        click.echo("\nno reliable scores yet")

    if unmeasured:
        # Excluded deliberately. A score from fewer than six requirements is
        # 0.000 or 1.000 depending on whether the one extracted term matched,
        # and neither measures fit. Including them made the median 0.000
        # across 553 vacancies and put 65 records above 0.94, none a real
        # match — and that distribution is the input to gate recalibration.
        click.echo(f"{unmeasured} not measured — excluded from the "
                   "distribution (see `vanguard diagnose`)")

    if len(rows) < 30:
        click.echo(
            f"({30 - len(rows)} more reliable scores before the gate can be "
            "revisited against evidence — OUTSTANDING P-01)"
        )

    if storage:
        footprint = store.storage_footprint()
        counts = footprint["counts"]
        size_mb = footprint["bytes"] / 1_048_576
        per_vacancy = footprint["bytes_per_vacancy"]

        click.echo()
        click.echo(ui.rule("STORAGE"))
        click.echo(ui.table(
            [ui.Column("TABLE", 1.0, 12), ui.Column("ROWS", 0.4, 8, "right")],
            [[name, f"{n:,}"] for name, n in sorted(
                counts.items(), key=lambda kv: -kv[1])],
        ))
        click.echo()
        click.echo(ui.field_list([
            ("database", f"{size_mb:.1f} MB"),
            ("per vacancy", f"{per_vacancy / 1024:.1f} KB" if per_vacancy else "-"),
            ("projected", f"{per_vacancy * 75 * 365 / 1_073_741_824:.2f} GB/year "
                          "at 75 vacancies/day" if per_vacancy else "-"),
        ], indent="  "))
        click.echo()
        click.echo("  SQLite handles multi-gigabyte databases. The first symptom of")
        click.echo("  growth is slower queries, not disk. Measure before acting.")

    recurring = store.unmet_term_frequency(12)
    if recurring:
        click.echo("\nmost frequently unmet:")
        for r in recurring:
            click.echo(f"  {r['n']:>3}x  {_clip(r['term'], _terminal_width() - 10)}")


@main.command()
@click.option("--boards", default=DEFAULTS["boards"])
def boards(boards) -> None:
    """Registry health. Terms are re-verified before enabling a board."""
    registry = load_registry(boards)
    click.echo(
        f"{len(registry)} registered   {len(registry.enabled)} enabled   "
        f"{len(registry.automatable)} automatable   {len(registry.manual)} manual\n"
    )
    width = _terminal_width()
    detail_w = max(30, width - 40)
    for status in health_check_all(registry):
        entry = registry.get(status.board_id)
        mark = "ok " if status.reachable else "-- "
        lines = _wrap(status.detail, detail_w) or [""]
        click.echo(f"{mark} {entry.id:<20} {entry.tier.value:<13} {lines[0]}")
        for extra in lines[1:]:
            click.echo(f"{'':<38}{extra}")


@main.command()
@click.option("--db", default=DEFAULTS["db"])
@click.option("--limit", default=20, help="How many unrecognised headings to list.")
def diagnose(db, limit) -> None:
    """Why adverts refuse, and what their headings actually say.

    `classify_heading()` matches a fixed phrase list. Adverts whose headings
    fall outside it produce no requirements and cannot be scored. This reports
    those headings so the list can be widened from evidence rather than guesses.
    """
    store, _ = _ctx(db)
    width = _terminal_width()

    health = store.parse_health()
    if not health["total"]:
        click.echo("no diagnostics recorded — run `vanguard run` or `vanguard paste` first")
        return

    scored, total = health["scored"], health["total"]
    pct = (scored / total * 100) if total else 0
    click.echo(f"parsed {total} advert(s): {scored} yielded requirements ({pct:.0f}%), "
               f"{total - scored} refused")
    click.echo(f"{health['html']} were HTML")

    refusals = store.refusal_counts()
    if refusals:
        click.echo("\nrefusal reasons:")
        from vanguard.diagnostics import RefusalReason
        for reason, count in sorted(refusals.items(), key=lambda kv: -kv[1]):
            try:
                explanation = RefusalReason(reason).explanation
            except ValueError:
                explanation = ""
            click.echo(f"  {count:>3}x  {reason}")
            for line in _wrap(explanation, width - 12):
                click.echo(f"        {line}")

    gates = store.eligibility_gates()
    if gates:
        click.echo()
        click.echo(ui.rule(f"ELIGIBILITY GATES  ·  {len(gates)} vacanc(ies)"))
        click.echo("  conditions on whether you may apply, not on fit\n")
        for gate in gates[:10]:
            click.echo(f"  {ui.badge('GATE', ui.Tone.BAD)} "
                       f"{_clip(gate['title'], width - 20)}")
            for line in _wrap(gate["notes"][0], width - 10):
                click.echo(f"        {line}")

    unrecognised = store.unrecognised_headings(limit)
    if unrecognised:
        click.echo(f"\nunrecognised headings — candidates for classify_heading():")
        for row in unrecognised:
            click.echo(f"  {row['n']:>3}x  {_clip(row['heading'], width - 10)}")
        click.echo("\nAdd the requirement-bearing ones to _HEADING_RULES in structure.py.")
    else:
        click.echo("\nno unrecognised headings recorded")


@main.command("logs")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--boards", "boards_path", default=DEFAULTS["boards"])
@click.option("--limit", default=10, help="How many runs to show.")
@click.option("--errors", "errors_only", is_flag=True, help="Only failures.")
@click.option("--archive", "do_archive", is_flag=True,
              help="Move old records to archive.db and gzip old log files.")
def logs_cmd(db, boards_path, limit, errors_only, do_archive) -> None:
    """Run history and recorded errors.

    Two stores: this reads the structured one. The verbose file sits in the
    configured log directory and holds the API-level detail.
    """
    import sqlite3

    from vanguard.logs import LOG_SCHEMA, archive_old_records, compress_old_files

    config = _logging(boards_path)
    if not config.enabled:
        click.echo("logging is disabled — set logging.enabled in boards.yaml")
        return

    if do_archive:
        moved = archive_old_records(Path(db), older_than_days=config.archive_after_days)
        gzipped = compress_old_files(config.directory, older_than_days=config.retain_days)
        click.echo(f"archived {moved['runs']} run(s), {moved['events']} event(s) "
                   f"to archive.db; gzipped {gzipped} log file(s)")
        click.echo("nothing was deleted")
        return

    conn = sqlite3.connect(str(Path(db)))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(LOG_SCHEMA)
        runs = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        if errors_only:
            runs = [r for r in runs if (r["errors"] or 0) or r["outcome"] == "ERROR"]

        if not runs:
            click.echo("no runs recorded yet")
            return

        click.echo(ui.rule(f"RUNS  ·  most recent {len(runs)}"))
        click.echo(ui.table(
            [
                ui.Column("WHEN", 0.8, 16),
                ui.Column("COMMAND", 0.5, 7),
                ui.Column("OUTCOME", 0.5, 9),
                ui.Column("SECS", 0.3, 5, "right"),
                ui.Column("KEPT", 0.3, 4, "right"),
                ui.Column("SCORED", 0.3, 6, "right"),
                ui.Column("ERRORS", 0.3, 6, "right"),
            ],
            [[r["started_at"][:16].replace("T", " "), r["command"],
              r["outcome"] or "running", f"{r['duration_s'] or 0:.1f}",
              str(r["kept"] or 0), str(r["scored"] or 0), str(r["errors"] or 0)]
             for r in runs],
        ))

        recent = conn.execute(
            "SELECT * FROM events WHERE level IN ('ERROR','WARNING') "
            "ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
        if recent:
            width = _terminal_width()
            click.echo()
            click.echo(ui.rule("RECENT ERRORS AND WARNINGS"))
            for event in recent:
                tone = ui.Tone.BAD if event["level"] == "ERROR" else ui.Tone.WARN
                where = event["board_id"] or event["vacancy_id"] or event["source"] or ""
                click.echo(f"  {ui.badge(event['level'], tone, width=9)} "
                           f"{event['at'][:16].replace('T', ' ')}  {where}")
                for line in _wrap(event["message"], width - 6):
                    click.echo(f"      {line}")
    finally:
        conn.close()

    click.echo()
    click.echo(f"  verbose detail: {config.directory}/vanguard.log")
    click.echo("  vanguard logs --archive   move old records aside (nothing deleted)")


@main.command("archive")
@click.argument("vacancy_id", required=False)
@click.option("--root", default=str(ARCHIVE_ROOT))
@click.option("--limit", default=20)
def archive_cmd(vacancy_id, root, limit) -> None:
    """What was actually submitted, and when.

    An interview happens weeks after dispatch, by which time the advert has
    been taken down and the CV has been edited. This is the record of what
    was sent.
    """
    store = Archive(Path(root))
    applications = (store.for_vacancy(vacancy_id) if vacancy_id
                    else store.applications())

    if not applications:
        click.echo("nothing archived yet" if not vacancy_id
                   else f"nothing archived for {vacancy_id}")
        return

    width = _terminal_width()

    if vacancy_id or len(applications) == 1:
        for application in applications:
            click.echo()
            click.echo(ui.rule(_clip(f"{application.title} — {application.employer}",
                                     width - 8)))
            click.echo(ui.field_list([
                ("archived", application.archived_at[:16].replace("T", " ")),
                ("vacancy", application.vacancy_id),
                ("folder", str(application.directory)),
            ], indent="  "))
            click.echo()
            for key, path in sorted(application.files.items()):
                mark = "ok " if path.is_file() else "-- "
                click.echo(f"  {mark} {key:<20} {path.name}")
            if not application.complete:
                click.echo(f"\n  {ui.badge('INCOMPLETE', ui.Tone.WARN)} "
                           "no CV archived with this application")
        return

    click.echo(ui.rule(f"ARCHIVE  ·  {len(applications)} application(s)"))
    click.echo(ui.table(
        [
            ui.Column("WHEN", 0.6, 12),
            ui.Column("EMPLOYER", 1.1, 12),
            ui.Column("TITLE", 1.8, 16),
            ui.Column("FILES", 0.3, 5, "right"),
        ],
        [[a.archived_at[:16].replace("T", " "), a.employer, a.title,
          str(len(a.files))] for a in applications[:limit]],
    ))
    click.echo()
    click.echo("  vanguard archive <ID>   for one application in full")


@main.command("poll")
@click.option("--provider", type=click.Choice(["imap", "gmail"]), default=None,
              help="Override the provider. Default: VANGUARD_MAIL_PROVIDER, else imap.")
@click.option("--since-days", type=int, default=0, help="How far back to read.")
@click.option("--limit", default=100, help="Maximum messages to fetch.")
@click.option("--dry-run", is_flag=True, help="Classify and report; record nothing.")
@click.option("--verbose", is_flag=True, help="Show sender addresses and full subjects.")
@click.option("--show-uncorrelated", is_flag=True,
              help="List messages that matched no application.")
@click.option("--category", default="", help="Gmail tab: primary (default) or all.")
@click.option("--strategy", "strategy_name",
              type=click.Choice(["auto", "targeted", "window"]), default=None,
              help="How to narrow the mailbox. Default from boards.yaml, else auto.")
@click.option("--broad", is_flag=True, help="Alias for --strategy window.")
@click.option("--no-model", is_flag=True,
              help="Rules only. Faster, and misses wording no marker covers.")
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--db", default=DEFAULTS["db"])
@click.option("--archive-root", default=str(ARCHIVE_ROOT))
def poll_cmd(provider, since_days, limit, dry_run, verbose, show_uncorrelated,
             category, strategy_name, broad, no_model, cv, db,
             archive_root) -> None:
    """Read the mailbox, correlate replies to applications, classify them.

    Read-only. Never sends, never replies, never deletes.

    The monitored address is derived from the CV in use — an employer replies
    to whatever address the CV gave them, so configuring it separately would
    let the two drift.
    """
    from vanguard.mail import Application, classify, correlate
    from vanguard.mailbox import (
        MailboxConfig, MailboxError, build_provider, contact_address_from_cv,
    )

    store, queue = _ctx(db)
    address = contact_address_from_cv(cv)
    config = MailboxConfig.from_env(address, provider=provider or "imap")
    if provider:
        config.provider = provider
    if since_days:
        config.since_days = since_days
    if category:
        config.category = category.lower()

    click.echo(ui.rule(f"MAILBOX  ·  {config.address or '(no address in CV)'}  ·  "
                       f"{config.provider}"))

    try:
        mailbox = build_provider(config)
        reachable, detail = mailbox.health_check()
    except MailboxError as exc:
        raise click.ClickException(str(exc)) from exc

    if not reachable:
        click.echo(f"  {ui.badge('UNREACHABLE', ui.Tone.BAD)}  {detail}")
        click.echo("\n  Set VANGUARD_MAIL_HOST, VANGUARD_MAIL_USER and "
                   "VANGUARD_MAIL_PASSWORD in .env.")
        click.echo("  Use an APP PASSWORD, never the account password.")
        return

    click.echo(f"  {ui.badge('CONNECTED', ui.Tone.GOOD)}  {detail}")

    # Applications first: a targeted search is far more reliable than reading
    # the most recent N and correlating afterwards. Gmail's Primary tab is not
    # an IMAP folder, so INBOX returns promotions and social too — a genuine
    # reply can sit outside a recent-N window entirely.
    applications = _open_applications(store)

    # Which strategy, and why. A silent switch would be invisible, and a
    # change in behaviour with no stated cause is the failure this project
    # keeps finding.
    requested = FetchStrategy(
        "window" if broad else (strategy_name or _mail_strategy(boards_default())))
    threshold = _window_threshold(boards_default())
    strategy, reason = choose_strategy(requested, len(applications), threshold)

    extra_terms: list[str] = []
    if strategy is FetchStrategy.TARGETED:
        for app in applications:
            if app.reference:
                extra_terms.append(f'"{app.reference}"')
            employer = app.employer.split(",")[0].strip()
            if len(employer) > 3:
                extra_terms.append(f'"{employer}"')
        extra_terms = list(dict.fromkeys(extra_terms))
        if len(extra_terms) > MAX_SEARCH_TERMS:
            click.echo(f"  {ui.badge('TRUNCATED', ui.Tone.WARN)} "
                       f"{len(extra_terms)} terms exceeds {MAX_SEARCH_TERMS}. "
                       "Use --strategy window.")
            extra_terms = extra_terms[:MAX_SEARCH_TERMS]

    if strategy is FetchStrategy.TARGETED:
        click.echo(f"  {ui.badge('TARGETED', ui.Tone.INFO)} {len(extra_terms)} "
                   f"search term(s) in category:{config.category}")
    else:
        click.echo(f"  {ui.badge('WINDOW', ui.Tone.INFO)} category:"
                   f"{config.category}, last {config.since_days} days")
    click.echo(f"      {reason}")

    try:
        messages = mailbox.fetch(limit=limit, extra_terms=extra_terms)
    except MailboxError as exc:
        raise click.ClickException(str(exc)) from exc

    if not messages:
        click.echo(f"\n  no messages in the last {config.since_days} days")
        return

    # Only applications actually submitted can receive a reply.
    applications = []
    for row in store.list_queue(limit=500):
        if row["status"] not in ("DISPATCHED", "APPROVED"):
            continue
        vacancy = store.vacancy(row["vacancy_id"])
        applications.append(Application(
            vacancy_id=row["vacancy_id"], employer=row["employer"],
            title=row["title"],
            reference=(vacancy["reference"] if vacancy else "") or "",
            url=(vacancy["url"] if vacancy else "") or "",
        ))

    click.echo(f"\n  {len(messages)} message(s), {len(applications)} open "
               f"application(s)\n")

    archive = Archive(Path(archive_root))
    rows, uncorrelated = [], []
    ambiguous: list = []
    processes: list = []
    # Messages already correlated, so a reply to one is matched to the same
    # application without having to re-earn correlation on its own.
    threads = store.known_threads()

    # The local embedder, for messages no marker matches. Mail is at least as
    # personal as the CV, and the ruling that keeps embeddings off an API
    # applies here with more force.
    classifier, classifier_name = _embedder(not no_model)

    for message in messages:
        result = correlate(message, applications, known_threads=threads)
        if result.ambiguous:
            # Two live applications at one employer, and nothing in the reply
            # to tell them apart. Attaching it to either would put an
            # interview invitation — or a rejection — on the wrong vacancy.
            ambiguous.append((message, result))
            continue
        if not result.correlated:
            uncorrelated.append(message)
            continue

        outcome = classify(message, embedder=classifier)
        rows.append([
            outcome.state.value,
            _clip(result.application.employer, 20),
            _clip(message.sender, 28) if verbose else _clip(message.subject, 34),
            _clip(message.subject, 34) if verbose else result.method.value,
        ] + ([result.method.value] if verbose else []))

        if not dry_run:
            archive.add_message(
                result.application.vacancy_id, message.body,
                subject=message.subject, sender=message.sender,
                kind=outcome.state.value.lower(),
            )
            # Attach to the interview process. Opens one on the first
            # PROGRESS; closes it on OFFER or DECLINE. Nothing else ends it.
            store.record_response(
                result.application.vacancy_id, outcome.state.value,
                sender=message.sender, subject=message.subject,
                received_at=message.received.isoformat(timespec="seconds")
                if message.received else "",
                method=result.method.value,
                message_id=message.message_id, body=message.body,
                tokens=message.routing_tokens)
            process = ProcessStore(db).record(
                result.application.vacancy_id, outcome.state,
                subject=message.subject, sender=message.sender)
            if process is not None:
                processes.append((result.application, process, outcome.state))

    if rows:
        columns = [
            ui.Column("STATE", 0.4, 9),
            ui.Column("EMPLOYER", 0.8, 12),
        ]
        if verbose:
            columns += [
                ui.Column("SENDER", 1.2, 16, tone=ui.Tone.MUTED),
                ui.Column("SUBJECT", 1.4, 16),
                ui.Column("VIA", 0.4, 7, tone=ui.Tone.MUTED),
            ]
        else:
            columns += [
                ui.Column("SUBJECT", 1.6, 16),
                ui.Column("VIA", 0.4, 7, tone=ui.Tone.MUTED),
            ]
        click.echo(ui.table(columns, rows))

    if ambiguous:
        width = _terminal_width()
        click.echo()
        click.echo(ui.rule(f"AMBIGUOUS  ·  {len(ambiguous)}"))
        click.echo("  matched several applications. Resolve by hand — attaching\n"
                   "  one to the wrong vacancy is worse than leaving it queued.\n")
        for message, result in ambiguous:
            click.echo(f"  {ui.badge('WHICH?', ui.Tone.WARN)} "
                       f"{_clip(message.subject, width - 20)}")
            for candidate in result.candidates:
                click.echo(f"      {candidate.vacancy_id:<28} "
                           f"{_clip(candidate.title, width - 40)}")

    if uncorrelated:
        click.echo(f"\n  {ui.badge(f'{len(uncorrelated)} uncorrelated', ui.Tone.MUTED)} "
                   "— not matched to an application, and NOT classified")
        if show_uncorrelated or verbose:
            click.echo()
            click.echo(ui.table(
                [
                    ui.Column("SENDER", 1.2, 16, tone=ui.Tone.MUTED),
                    ui.Column("SUBJECT", 1.8, 20),
                ],
                [[m.sender, m.subject] for m in uncorrelated[:40]],
            ))
            if len(uncorrelated) > 40:
                # Silently showing half a list is how a message goes missing.
                # A Beatport reply sat in the hidden portion for two days
                # while the operator looked at the visible forty.
                click.echo(f"\n      {ui.badge(f'{len(uncorrelated) - 40} more not shown', ui.Tone.WARN)}"
                           "  --limit to raise the fetch, or search the mailbox")

    if processes:
        from vanguard.process import ProcessState, suggested_phase

        click.echo()
        click.echo(ui.rule("INTERVIEW PROCESSES"))
        for application, process, state in processes:
            tone = (ui.Tone.GOOD if process.state is ProcessState.OFFER
                    else ui.Tone.BAD if process.state is ProcessState.DECLINE
                    else ui.Tone.WARN)
            click.echo(f"  {ui.badge(process.state.value, tone)} "
                       f"{_clip(application.employer, 24)} — {process.summary()}")
            if process.active and state.value == "PROGRESS":
                from vanguard.lifecycle import Stage, infer_stage

                stage = infer_stage(message.subject, message.body)
                if stage is not Stage.UNKNOWN:
                    click.echo(f"      stage: {stage.value.lower()}")
                phase = suggested_phase(process.current_round)
                click.echo(f"      vanguard interview {application.vacancy_id} "
                           f"--phase {phase}")

    if dry_run:
        click.echo("\n  dry run — nothing recorded")
    click.echo("\n  read-only: nothing was sent, replied to or deleted")


# ---------------------------------------------------------------------------
# Advert folder — batch ingestion
# ---------------------------------------------------------------------------

@main.group("adverts")
def adverts_group() -> None:
    """A watched folder of pasted adverts, and their provenance.

    At volume, ingesting one file at a time is the bottleneck. This registers
    adverts with their employer and URL, then ingests every valid one in a
    single pass.

    Nothing here can prevent a file being dragged into the folder — no such
    hook exists without a filesystem driver. What it enforces is that a file
    with no valid manifest entry is NEVER ingested. The folder may be
    polluted; the pipeline will not act on it.
    """


@adverts_group.command("add")
@click.argument("filename")
@click.option("--employer", required=True, help="Required. Parsing it from prose is unreliable.")
@click.option("--url", required=True, help="Required. Without it the advert cannot be found again.")
@click.option("--board", default="linkedin", help="Registry id to attribute it to.")
@click.option("--note", default="")
@click.option("--dir", "directory", default=str(ADVERTS_DIR))
def adverts_add(filename, employer, url, board, note, directory) -> None:
    """Register one advert already in the folder."""
    from vanguard.adverts import AdvertManifest, ValidationError

    try:
        entry = AdvertManifest(Path(directory)).add(
            filename, employer, url, board=board, note=note)
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"  {ui.badge('REGISTERED', ui.Tone.GOOD)} {entry.filename} "
               f"-> {entry.employer}")


@adverts_group.command("list")
@click.option("--dir", "directory", default=str(ADVERTS_DIR))
def adverts_list(directory) -> None:
    """Everything in the folder, registered or not."""
    from vanguard.adverts import AdvertManifest

    manifest = AdvertManifest(Path(directory))
    entries = manifest.load()
    files = manifest.advert_files()

    if not files:
        click.echo(f"  no adverts in {directory}")
        return

    click.echo(ui.rule(f"ADVERTS  ·  {len(files)} file(s), "
                       f"{len(entries)} registered"))
    rows = []
    for path in files:
        entry = entries.get(path.name)
        rows.append([
            "registered" if entry else "UNREGISTERED",
            path.name,
            entry.employer if entry else "—",
            entry.url if entry else "—",
        ])
    click.echo(ui.table(
        [
            ui.Column("STATE", 0.5, 12),
            ui.Column("FILE", 1.0, 14),
            ui.Column("EMPLOYER", 0.9, 12),
            ui.Column("URL", 1.2, 14, tone=ui.Tone.MUTED),
        ],
        rows,
    ))

    unregistered = [p for p in files if p.name not in entries]
    if unregistered:
        click.echo(f"\n  {ui.badge(f'{len(unregistered)} will not be ingested', ui.Tone.WARN)}"
                   " — register with `vanguard adverts add`")


@adverts_group.command("register")
@click.option("--from-csv", "csv_path", type=click.Path(exists=True),
              help="filename,employer,url[,board] per line.")
@click.option("--dir", "directory", default=str(ADVERTS_DIR))
@click.option("--template", is_flag=True,
              help="Write a CSV listing unregistered files, ready to fill in.")
@click.option("--out", "out_path", default="",
              help="Where to write the template. Default <dir>/to_register.csv")
@click.option("--force", is_flag=True,
              help="Overwrite a template that already has entries filled in.")
def adverts_register(csv_path, directory, template, out_path, force) -> None:
    """Register many adverts at once from a CSV.

    At seventy adverts a day, `adverts add` one at a time is the bottleneck
    this command exists to remove.

    `--template` writes a CSV of every unregistered file with blank employer
    and url columns. Fill it in, then pass it back with `--from-csv`.
    """
    import csv as csv_module

    from vanguard.adverts import AdvertManifest, ValidationError

    manifest = AdvertManifest(Path(directory))

    if template:
        entries = manifest.load()
        unregistered = [p.name for p in manifest.advert_files()
                        if p.name not in entries]
        if not unregistered:
            click.echo("  everything in the folder is registered")
            return
        out = Path(out_path) if out_path else Path(directory) / "to_register.csv"

        # Refuse to destroy work in progress. Filling in seventy rows and
        # then re-running --template would silently blank the lot, and the
        # loss is invisible until the columns are noticed empty.
        if out.is_file() and not force:
            filled = _filled_rows(out)
            if filled:
                raise click.ClickException(
                    f"{out} already has {filled} completed row(s). Register it "
                    "first, pass --out to write elsewhere, or --force to "
                    "overwrite."
                )

        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv_module.writer(handle)
            writer.writerow(["filename", "employer", "url", "board"])
            for name in unregistered:
                writer.writerow([name, "", "", "linkedin"])
        click.echo(f"  wrote {out} with {len(unregistered)} row(s)")
        click.echo("  fill in employer and url, then: "
                   "vanguard adverts register --from-csv " + str(out))
        return

    if not csv_path:
        raise click.ClickException("pass --from-csv, or --template to create one")

    registered, failed = 0, []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        for row in csv_module.DictReader(handle):
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            try:
                manifest.add(
                    filename,
                    (row.get("employer") or "").strip(),
                    (row.get("url") or "").strip(),
                    board=(row.get("board") or "linkedin").strip() or "linkedin",
                )
                registered += 1
            except ValidationError as exc:
                failed.append((filename, str(exc)))

    click.echo(f"  {ui.badge('REGISTERED', ui.Tone.GOOD)} {registered}")
    if failed:
        width = _terminal_width()
        click.echo(f"\n  {ui.badge(f'{len(failed)} rejected', ui.Tone.WARN)}")
        for filename, reason in failed:
            click.echo(f"      {_clip(filename, 28):<30} {_clip(reason, width - 40)}")


@adverts_group.command("check")
@click.option("--dir", "directory", default=str(ADVERTS_DIR))
@click.option("--fix", is_flag=True, help="Drop entries whose file has gone.")
def adverts_check(directory, fix) -> None:
    """Every rule breach in the folder.

    `--fix` removes manifest entries for files that no longer exist. It never
    deletes an advert: removing the operator's data because a record is
    missing would be the wrong failure.
    """
    from vanguard.adverts import AdvertManifest

    manifest = AdvertManifest(Path(directory))

    if fix:
        removed, violations = manifest.reconcile()
        if removed:
            click.echo(f"  dropped {len(removed)} entr(ies) whose file has gone:")
            for name in removed:
                click.echo(f"      {name}")
        click.echo("  no advert file was deleted")
    else:
        violations = manifest.check()

    if not violations:
        click.echo(f"  {ui.badge('OK', ui.Tone.GOOD)} no violations")
        return

    width = _terminal_width()
    click.echo(ui.rule(f"VIOLATIONS  ·  {len(violations)}"))
    for violation in violations:
        click.echo(f"  {ui.badge(violation.rule.upper(), ui.Tone.WARN)} "
                   f"{_clip(violation.subject, width - 24)}")
        for line in _wrap(violation.detail, width - 8):
            click.echo(f"      {line}")


@adverts_group.command("ingest")
@click.option("--dir", "directory", default=str(ADVERTS_DIR))
@click.option("--move-to", default="", help="Move ingested files here afterwards.")
@click.option("--dry-run", is_flag=True, help="Report what would be ingested.")
@click.option("--boards", default=DEFAULTS["boards"])
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--aliases", default=DEFAULTS["aliases"])
@click.option("--db", default=DEFAULTS["db"])
@click.option("--no-model", is_flag=True)
def adverts_ingest(directory, move_to, dry_run, boards, cv, aliases, db,
                   no_model) -> None:
    """Score and queue every valid advert in the folder.

    Anything without a valid manifest entry is SKIPPED and reported. One bad
    advert never aborts the batch.
    """
    from vanguard.adverts import AdvertManifest
    from vanguard.adapters.manual import ManualEntryAdapter

    from vanguard.logs import RunLog

    store, queue = _ctx(db)
    manifest = AdvertManifest(Path(directory))
    registry = load_registry(boards)
    log_config = _logging(boards)

    ingestible = list(manifest.ingestible())
    skipped = [p.name for p in manifest.advert_files()
               if p.name not in {path.name for path, _ in ingestible}]

    click.echo(ui.rule(f"INGEST  ·  {len(ingestible)} valid, {len(skipped)} skipped"))
    for name in skipped:
        click.echo(f"  {ui.badge('SKIPPED', ui.Tone.WARN)} {name} — no valid entry")

    if not ingestible:
        click.echo("\n  nothing to ingest. `vanguard adverts add` to register")
        return

    if dry_run:
        for path, entry in ingestible:
            click.echo(f"  would ingest {path.name} -> {entry.employer}")
        click.echo("\n  dry run — nothing scored")
        return

    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    embedder, embedder_name = _embedder(not no_model)
    gate = registry.coverage_gate

    click.echo(f"\n  scoring {len(ingestible)} advert(s) [{embedder_name}] "
               f"gate {gate:.2f}\n")

    with RunLog("adverts ingest", db_path=Path(db), config=log_config) as run_log:
        outcomes: dict[str, int] = {}
        moved = 0

        for path, entry in ingestible:
            try:
                board_entry = registry.get(entry.board)
            except KeyError:
                board_entry = registry.get("linkedin")

            try:
                vacancy = ManualEntryAdapter(board_entry).submit(
                    path.read_text(encoding="utf-8"),
                    url=entry.url, employer=entry.employer)
                status = _score_and_queue(
                    vacancy, store, queue, canonical, alias_table,
                    embedder, embedder_name, gate=gate)
                outcomes[status] = outcomes.get(status, 0) + 1
            except Exception as exc:
                # One bad advert must not abort a batch of seventy.
                run_log.error(str(exc), source="adverts", detail=path.name)
                click.echo(f"  {ui.badge('ERROR', ui.Tone.BAD)} {path.name}: {exc}",
                           err=True)
                continue

            if move_to:
                destination = Path(move_to)
                try:
                    destination.mkdir(parents=True, exist_ok=True)
                    path.replace(destination / path.name)
                    manifest.remove(path.name)
                    moved += 1
                except OSError:
                    pass

        run_log.count(scored=sum(outcomes.values()), skipped=len(skipped))

    click.echo()
    click.echo(ui.rule("RESULT"))
    for label in ("PENDING", "FLAGGED", "UNREACHABLE"):
        if outcomes.get(label):
            click.echo(f"  {_status(label)}  {outcomes[label]}")
    if move_to and moved:
        click.echo(f"\n  moved {moved} file(s) to {move_to}")
    click.echo("\n  vanguard review   to work through them")


@main.command("interviews")
@click.argument("vacancy_id", required=False)
@click.option("--all", "show_all", is_flag=True, help="Closed processes too.")
@click.option("--withdraw", default="", help="Close a process, with a reason.")
@click.option("--db", default=DEFAULTS["db"])
def interviews_cmd(vacancy_id, show_all, withdraw, db) -> None:
    """Interview processes, across all their rounds.

    A process opens on the first PROGRESS and closes only on OFFER, DECLINE or
    your own withdrawal. Silence never closes one — employers go quiet between
    rounds and return.
    """
    from vanguard.process import ProcessState, ProcessStore, suggested_phase

    store, _ = _ctx(db)
    processes = ProcessStore(db)

    if withdraw:
        if not vacancy_id:
            raise click.ClickException("--withdraw needs a vacancy id")
        if not processes.withdraw(vacancy_id, withdraw):
            raise click.ClickException(f"no interview process for {vacancy_id}")
        click.echo(f"  {ui.badge('WITHDRAWN', ui.Tone.MUTED)} {vacancy_id}")
        click.echo(f"      {withdraw}")
        return

    if vacancy_id:
        process = processes.get(vacancy_id)
        if process is None:
            click.echo(f"no interview process for {vacancy_id}")
            return

        vacancy = store.vacancy(vacancy_id)
        width = _terminal_width()
        click.echo()
        click.echo(ui.rule(_clip(
            f"{vacancy['title']} — {vacancy['employer']}" if vacancy
            else vacancy_id, width - 8)))
        click.echo(ui.field_list([
            ("state", process.state.value),
            ("opened", process.opened_at[:16].replace("T", " ")),
            ("closed", process.closed_at[:16].replace("T", " ")),
            ("rounds", str(process.current_round)),
            ("messages", str(process.message_count)),
            ("outcome", process.outcome_note),
        ], indent="  "))

        if process.rounds:
            from vanguard.lifecycle import infer_stage

            click.echo()
            click.echo(ui.rule("ROUNDS"))
            click.echo(ui.table(
                [
                    ui.Column("#", 0.2, 3, "right"),
                    ui.Column("STAGE", 0.5, 10),
                    ui.Column("OPENED", 0.5, 12),
                    ui.Column("SUBJECT", 1.5, 16),
                ],
                [[str(r.number),
                  infer_stage(r.subject).value.lower(),
                  r.opened_at[:16].replace("T", " "), r.subject]
                 for r in process.rounds],
            ))

        if process.active:
            phase = suggested_phase(process.current_round)
            click.echo(f"\n  next:  vanguard interview {vacancy_id} --phase {phase}")
            click.echo(f"         vanguard interviews {vacancy_id} "
                       '--withdraw "..."')
        return

    listing = processes.all() if show_all else processes.active()
    if not listing:
        click.echo("no active interview processes"
                   if not show_all else "no interview processes recorded")
        return

    click.echo(ui.rule(f"INTERVIEWS  ·  {len(listing)}"))
    rows = []
    for process in listing:
        vacancy = store.vacancy(process.vacancy_id)
        rows.append([
            process.state.value,
            str(process.current_round),
            vacancy["employer"] if vacancy else "",
            vacancy["title"] if vacancy else "",
            process.vacancy_id,
        ])
    click.echo(ui.table(
        [
            ui.Column("STATE", 0.5, 9),
            ui.Column("RND", 0.2, 3, "right"),
            ui.Column("EMPLOYER", 1.0, 12),
            ui.Column("TITLE", 1.6, 14),
            ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
        ],
        rows,
    ))
    click.echo()
    click.echo("  vanguard interviews <ID>   for one process in full")


@main.command("evidence")
@click.option("--repo", "repos", multiple=True,
              help="A local path or a repository URL. Repeat for several.")
@click.option("--shallow", is_flag=True,
              help="Clone only recent history. Faster, but loses the commit span.")
@click.option("--vacancy", default="", help="Match against one vacancy's gaps.")
@click.option("--all-gaps", is_flag=True,
              help="Match against every recurring unmet requirement instead.")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--cv", default=DEFAULTS["cv"])
def evidence_cmd(repos, shallow, vacancy, all_gaps, db, cv) -> None:
    """Propose CV bullets from work in your own repositories.

    A repository evidences only what was BUILT. It can supply a Type 1 gap —
    something genuinely done but unstated — and never a Type 3 gap: AWS is not
    evidenced by a repository that never touched AWS.

    Every proposal needs your confirmation. The scanner can see that a test
    suite exists; it cannot know whether you wrote it, or whether you could
    defend it under questioning.
    """
    from vanguard.repo import CloneError, is_remote, propose_bullets, scan_target

    store, _ = _ctx(db)
    width = _terminal_width()

    if not repos:
        raise click.ClickException(
            "pass --repo, a local path or a URL. Own repositories only: "
            "attribution has to be certain")

    if vacancy:
        rows = store.gaps_for(vacancy)
        unmet = [r["term"] for r in rows if r["outcome"] == "GAP"]
        heading = f"gaps on {vacancy}"
    elif all_gaps:
        unmet = [r["term"] for r in store.unmet_term_frequency(40)]
        heading = "recurring unmet requirements"
    else:
        raise click.ClickException("pass --vacancy <id> or --all-gaps")

    if not unmet:
        click.echo("no unmet requirements to match against")
        return

    scans = []
    for target in repos:
        if is_remote(target):
            click.echo(f"  cloning {target} …")
        try:
            scans.append(scan_target(target, shallow=shallow))
        except CloneError as exc:
            # One unreachable repository must not stop the others.
            click.echo(f"  {ui.badge('FAILED', ui.Tone.BAD)} {exc}", err=True)
            continue

    if not scans:
        raise click.ClickException("no repository could be read")

    click.echo(ui.rule(f"REPOSITORIES  ·  {len(scans)}"))
    for scan in scans:
        click.echo(f"  {scan.summary()}")
        for item in scan.sufficient_evidence:
            click.echo(f"      {item.competency:<28} {item.describe()}")

    proposals = propose_bullets(scans, unmet)

    click.echo()
    click.echo(ui.rule(f"PROPOSALS  ·  {len(proposals)} of {len(unmet)} {heading}"))

    if not proposals:
        click.echo("  nothing in these repositories evidences the unmet")
        click.echo("  requirements. That is the honest outcome — a repository")
        click.echo("  evidences only what was built.")
        return

    for proposal in proposals:
        click.echo()
        click.echo(f"  {ui.badge('TYPE 1?', ui.Tone.WARN)} {proposal.requirement}")
        click.echo(f"      evidence   {proposal.citation()}")
        for line in _wrap(proposal.bullet, width - 18):
            click.echo(f"      draft      {line}")

    click.echo()
    click.echo(ui.rule("BEFORE YOU ADD ANY OF THESE"))
    for line in (
        "Each is a proposal. Ask, of each one:",
        "",
        "  Did I build this, or did someone else?",
        "  Could I answer three follow-up questions on it without inventing?",
        "  Which system, what period, what actually happened?",
        "",
        "If you hesitate, it is not a Type 1 gap. It stays unmet.",
        "",
        "Edit data/canonical_cv.md by hand, then re-score:",
        f"  vanguard review {vacancy or '<id>'}",
    ):
        click.echo(f"  {line}")


# ---------------------------------------------------------------------------
# Application channel
# ---------------------------------------------------------------------------

@main.command("apply")
@click.argument("vacancy_id")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--cv-pdf", default="out/cv.pdf", help="The CV you would submit.")
def apply_cmd(vacancy_id, db, cv_pdf) -> None:
    """What this application needs, and where to do it.

    **Vanguard does not apply.** It establishes what kind of application this
    is, whether you hold an account, and what you will need to hand — then
    gives you the URL and stops.

    Automated form-filling across arbitrary employer systems is out of scope.
    Different templates, labels and frameworks make it unreliable, and a form
    filled wrongly on your behalf is worse than no help at all.
    """
    from vanguard.channel import Channel, RegistrationStore, classify_channel

    store, _ = _ctx(db)
    width = _terminal_width()

    vacancy = store.vacancy(vacancy_id)
    if vacancy is None:
        raise click.ClickException(f"no vacancy {vacancy_id!r}")
    record = store.queue_record(vacancy_id)
    if record is None:
        raise click.ClickException(f"no queue record for {vacancy_id}")

    click.echo()
    click.echo(ui.rule(_clip(f"{vacancy['title']} — {vacancy['employer']}",
                             width - 8)))
    click.echo(f"  {_status(record['status'])}")

    if record["status"] not in ("PENDING", "APPROVED"):
        click.echo(f"\n  this record is {record['status']}, not ready to apply")
        if record["status"] == "DISPATCHED":
            click.echo("  already submitted — `vanguard archive` for what was sent")
        return

    # --- eligibility, before anything else --------------------------------
    diagnostic = store.diagnostic_for(vacancy_id)
    if diagnostic:
        import json as _json
        try:
            gates = (_json.loads(diagnostic["heading_kinds"] or "{}")
                     ).get("__eligibility__") or []
        except ValueError:
            gates = []
        if gates:
            click.echo()
            click.echo(ui.rule("ELIGIBILITY  ·  check before spending time"))
            for gate in gates:
                click.echo(f"  {ui.badge('GATE', ui.Tone.BAD)}")
                for line in _wrap(gate, width - 6):
                    click.echo(f"      {line}")

    # --- channel ----------------------------------------------------------
    guess = classify_channel(vacancy["url"] or "", vacancy["description"] or "",
                             board_id=vacancy["board_id"] or "")

    click.echo()
    click.echo(ui.rule("CHANNEL"))
    tone = ui.Tone.INFO if guess.certain else ui.Tone.WARN
    click.echo(f"  {ui.badge(guess.channel.value, tone)}")
    for line in _wrap(guess.reason, width - 6):
        click.echo(f"      {line}")

    # --- registration -----------------------------------------------------
    registrations = RegistrationStore(db)
    scope = "board" if guess.channel.name.startswith("BOARD") else "employer"
    key = guess.host or (vacancy["board_id"] or "")

    click.echo()
    click.echo(ui.rule("ACCOUNT"))

    if not key:
        click.echo(f"  {ui.badge('UNKNOWN', ui.Tone.WARN)} nothing to check "
                   "against — no URL and no board")
    else:
        existing = registrations.get(scope, key)
        if existing is None:
            click.echo(f"  {ui.badge('NOT RECORDED', ui.Tone.WARN)} {key}")
            if guess.registration_url:
                click.echo(f"      register at {guess.registration_url}")
            click.echo(f"\n      once you have an account:")
            click.echo(f"      vanguard registrations set {scope} {key}")
            if guess.channel.needs_profile:
                click.echo(f"      vanguard registrations set {scope} {key} "
                           "--profile-built")
        elif not existing.registered:
            click.echo(f"  {ui.badge('NOT REGISTERED', ui.Tone.BAD)} {key}")
            if existing.url or guess.registration_url:
                click.echo(f"      register at "
                           f"{existing.url or guess.registration_url}")
        elif guess.channel.needs_profile and not existing.profile_built:
            click.echo(f"  {ui.badge('PROFILE NEEDED', ui.Tone.WARN)} {key}")
            click.echo("      this board applies from a built profile, not an "
                       "uploaded CV")
        else:
            click.echo(f"  {ui.badge('READY', ui.Tone.GOOD)} "
                       f"{key} — {existing.describe()}")

    # --- what to have to hand ---------------------------------------------
    click.echo()
    click.echo(ui.rule("PACK"))

    submission = record["submission_type"] or "STANDARD_CV"
    anonymise = "ANONYMISE" in (record["flags"] or "")
    cv_path = Path(cv_pdf)

    click.echo(ui.field_list([
        ("submission", submission),
        ("CV", f"{cv_path} {'(present)' if cv_path.is_file() else '(NOT RENDERED)'}"),
        ("profile", "anonymised" if anonymise else "standard"),
        ("also needed", {
            "STANDARD_CV": "a cover letter, usually optional",
            "NARRATIVE_ESSAY": "a written statement of suitability",
            "SUCCESS_PROFILE": "an anonymised CV and a word-limited statement",
        }.get(submission, "")),
    ], indent="  "))

    if not cv_path.is_file():
        click.echo(f"\n  {ui.badge('NO CV', ui.Tone.BAD)} render it first:")
        click.echo("      python -c \"from vanguard.render import render; "
                   "render('data/canonical_cv.md','render/standard.css',"
                   "'out/cv.pdf')\"")

    recalled = registrations.answers()
    if recalled:
        click.echo()
        click.echo("  answers you have given before:")
        for question, answer in recalled[:10]:
            click.echo(f"      {_clip(question, 34):<36} {_clip(answer, width - 46)}")

    # --- and stop ---------------------------------------------------------
    click.echo()
    click.echo(ui.rule("APPLY"))
    if vacancy["url"]:
        click.echo(f"  {vacancy['url']}")
    else:
        click.echo("  no URL recorded for this vacancy")
    click.echo("\n  Vanguard does not submit. Apply there yourself, then:")
    click.echo(f"      vanguard dispatch {vacancy_id}")


@main.group("registrations")
def registrations_group() -> None:
    """Where you hold accounts. Asserted by you, never detected.

    Nothing logs in to check. Detection would need credentials for dozens of
    portals — a single file that, if leaked, opens every account — and
    repeated automated logins are the pattern security systems flag.
    """


@registrations_group.command("list")
@click.option("--db", default=DEFAULTS["db"])
def registrations_list(db) -> None:
    """Every board and portal you have recorded."""
    from vanguard.channel import RegistrationStore

    records = RegistrationStore(db).all()
    if not records:
        click.echo("  nothing recorded yet")
        click.echo("  vanguard registrations set board reed.co.uk")
        return

    click.echo(ui.rule(f"REGISTRATIONS  ·  {len(records)}"))
    click.echo(ui.table(
        [
            ui.Column("SCOPE", 0.3, 8),
            ui.Column("KEY", 1.0, 14, protected=True),
            ui.Column("STATE", 0.7, 12),
            ui.Column("NOTED", 0.5, 10, tone=ui.Tone.MUTED),
        ],
        [[r.scope, r.key, r.describe(), r.noted_at[:10]] for r in records],
    ))


@registrations_group.command("set")
@click.argument("scope", type=click.Choice(["board", "employer"]))
@click.argument("key")
@click.option("--profile-built", is_flag=True, help="A profile is complete there.")
@click.option("--not-registered", is_flag=True, help="Record that you are NOT.")
@click.option("--url", default="", help="Where to sign in.")
@click.option("--note", default="")
@click.option("--db", default=DEFAULTS["db"])
def registrations_set(scope, key, profile_built, not_registered, url, note,
                      db) -> None:
    """Record whether you hold an account somewhere."""
    from vanguard.channel import RegistrationStore

    record = RegistrationStore(db).set(
        scope, key, registered=not not_registered,
        profile_built=profile_built, url=url, note=note)
    tone = ui.Tone.GOOD if record.registered else ui.Tone.MUTED
    click.echo(f"  {ui.badge(record.describe().upper(), tone)} "
               f"{record.scope}:{record.key}")


@registrations_group.command("answer")
@click.argument("question")
@click.argument("answer")
@click.option("--db", default=DEFAULTS["db"])
def registrations_answer(question, answer, db) -> None:
    """Record an answer to a question that keeps coming up.

    A recall aid. You still type it into the employer's form — nothing is
    filled in on your behalf.
    """
    from vanguard.channel import RegistrationStore

    RegistrationStore(db).remember_answer(question, answer)
    click.echo(f"  {ui.badge('RECORDED', ui.Tone.GOOD)} {_clip(question, 50)}")


@main.command("session")
@click.option("--status", default="PENDING", help="Which state to work through.")
@click.option("--min-coverage", type=float, default=None)
@click.option("--employer", default="")
@click.option("--include-unmeasured", is_flag=True)
@click.option("--limit", default=0, help="Stop after this many records.")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--boards", "boards_path", default=DEFAULTS["boards"])
def session_cmd(status, min_coverage, employer, include_unmeasured, limit, db,
                boards_path) -> None:
    """Work through a queue one record at a time, in one invocation.

    Fifteen PENDING records currently means thirty commands and thirty copied
    ids. The decisions cannot be batched — fifteen vacancies is fifteen
    judgements — but the typing can.

    Shows each record, asks, moves on. Nothing is decided for you.
    """
    store, queue = _ctx(db)

    rows = _select(store, status=status, min_coverage=min_coverage,
                   employer=employer, include_unmeasured=include_unmeasured)
    if limit:
        rows = rows[:limit]

    if not rows:
        # "nothing matches" reads as "the queue is empty", which is wrong when
        # records were filtered out. Most FLAGGED records are flagged BECAUSE
        # they are unmeasured; resolving them sends them to PENDING still
        # unmeasured, and the default filter then hides them silently.
        total = len(store.list_queue(status.upper(), limit=500))
        if not total:
            click.echo(f"nothing in {status.upper()}")
            return

        with_unmeasured = len(_select(store, status=status,
                                      min_coverage=min_coverage,
                                      employer=employer,
                                      include_unmeasured=True))
        click.echo(f"nothing in {status.upper()} matches the filter — but "
                   f"there are {total} record(s) there")
        if with_unmeasured:
            click.echo(f"\n  {ui.badge(f'{with_unmeasured} not measured', ui.Tone.WARN)}"
                       " — excluded by default, because a coverage")
            click.echo("  computed from fewer than six requirements does not "
                       "measure fit.\n")
            click.echo(f"  vanguard session --status {status.upper()} "
                       "--include-unmeasured")
            click.echo("  vanguard diagnose            why they could not be scored")
        elif min_coverage is not None or employer:
            click.echo("\n  the coverage or employer filter excluded them all")
        return

    click.echo(ui.rule(f"SESSION  ·  {len(rows)} record(s) in {status.upper()}"))
    click.echo("  a approve   r reject   s skip   o show gaps   q quit\n")

    tally = {"approved": 0, "rejected": 0, "skipped": 0}
    width = _terminal_width()

    for index, row in enumerate(rows, 1):
        vacancy = store.vacancy(row["vacancy_id"])
        click.echo()
        click.echo(ui.rule(f"{index} of {len(rows)}"))
        click.echo(f"  {_clip(row['title'], width - 6)}")
        click.echo(ui.field_list([
            ("employer", row["employer"]),
            ("coverage", f"{row['coverage'] or 0:.3f}  "
                         f"({row['terms_matched']}/{row['terms_total']} terms, "
                         f"ceiling {row['ceiling'] or 0:.2f})"),
            ("location", (vacancy["location"] if vacancy else "") or ""),
            ("salary", (vacancy["salary_band"] if vacancy else "") or ""),
            ("id", row["vacancy_id"]),
        ], indent="  "))

        # Eligibility, if any. A gate is worth seeing before deciding.
        diagnostic = store.diagnostic_for(row["vacancy_id"])
        if diagnostic:
            import json as _json
            try:
                gates = (_json.loads(diagnostic["heading_kinds"] or "{}")
                         ).get("__eligibility__") or []
            except ValueError:
                gates = []
            for gate in gates[:2]:
                click.echo(f"\n  {ui.badge('GATE', ui.Tone.BAD)} "
                           f"{_clip(gate, width - 14)}")

        while True:
            choice = click.prompt("\n  [a/r/s/o/q]", default="s",
                                  show_default=False).strip().lower()[:1]

            if choice == "o":
                unmet = [g for g in store.gaps_for(row["vacancy_id"])
                         if g["outcome"] == "GAP"]
                if not unmet:
                    click.echo("      nothing unmet")
                for gap in unmet[:12]:
                    label = {1: "Type 1", 2: "Type 2", 3: "Type 3"}.get(
                        gap["gap_type"], "     —")
                    click.echo(f"      {label}  {_clip(gap['term'], width - 20)}")
                continue

            if choice == "a":
                try:
                    queue.approve(row["vacancy_id"], "")
                    tally["approved"] += 1
                    click.echo(f"      {ui.badge('APPROVED', ui.Tone.GOOD)} "
                               f"vanguard apply {row['vacancy_id']}")
                except (IllegalTransition, StoreError, ValueError) as exc:
                    click.echo(f"      refused: {exc}", err=True)
                break

            if choice == "r":
                reason = click.prompt("      reason", default="not a fit",
                                      show_default=True)
                try:
                    queue.reject(row["vacancy_id"], reason)
                    tally["rejected"] += 1
                    click.echo(f"      {ui.badge('REJECTED', ui.Tone.MUTED)}")
                except (IllegalTransition, StoreError, ValueError) as exc:
                    click.echo(f"      refused: {exc}", err=True)
                break

            if choice == "q":
                click.echo("\n  stopped. Nothing after this point was touched.")
                _session_summary(tally, index - 1, len(rows))
                return

            tally["skipped"] += 1
            break

    _session_summary(tally, len(rows), len(rows))


def _session_summary(tally: dict, seen: int, total: int) -> None:
    click.echo()
    click.echo(ui.rule("SESSION END"))
    click.echo(f"  {seen} of {total} record(s) seen")
    for label, tone in (("approved", ui.Tone.GOOD), ("rejected", ui.Tone.MUTED),
                        ("skipped", ui.Tone.WARN)):
        if tally[label]:
            click.echo(f"  {ui.badge(label.upper(), tone)}  {tally[label]}")
    if tally["approved"]:
        click.echo("\n  vanguard review --status APPROVED   what to apply to")


@main.command("todo")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--limit", default=40)
def todo_cmd(db, limit) -> None:
    """Everything waiting on you, in the order you would act on it.

    APPROVED first — those are decided and waiting to be applied to. PENDING
    after, as the reviewing still to do. Both in one view, because switching
    between two commands to answer "what now?" is friction the operator does
    not need.
    """
    store, _ = _ctx(db)
    width = _terminal_width()

    def _table(rows) -> None:
        click.echo(ui.table(
            [
                ui.Column("COVERAGE", 0.4, 8, "right"),
                ui.Column("TERMS", 0.3, 5, "right", tone=ui.Tone.MUTED),
                ui.Column("EMPLOYER", 1.0, 12),
                ui.Column("TITLE", 1.7, 16),
                ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
            ],
            [[_coverage_cell(r)[0], _coverage_cell(r)[1], r["employer"],
              r["title"], r["vacancy_id"]] for r in rows[:limit]],
        ))

    approved = store.list_queue("APPROVED", limit=500)
    pending = store.list_queue("PENDING", limit=500)

    if not approved and not pending:
        click.echo("nothing waiting. `vanguard run` or `vanguard adverts ingest`")
        return

    if approved:
        click.echo(ui.rule(f"APPLY TO THESE  ·  {len(approved)} approved"))
        _table(approved)
        click.echo()
        click.echo("  vanguard apply <ID>       what it needs, and where")
        click.echo("  vanguard dispatch <ID>    after you have applied")

    if pending:
        click.echo()
        click.echo(ui.rule(f"STILL TO REVIEW  ·  {len(pending)} pending"))
        _table(pending)
        click.echo()
        click.echo("  vanguard session          work through them in one go")

    click.echo()
    counts = store.counts_by_status()
    other = {k: v for k, v in counts.items()
             if k in ("FLAGGED", "UNREACHABLE") and v}
    if other:
        click.echo("  also queued: " + "   ".join(
            f"{label} {count}" for label, count in sorted(other.items())))


@main.command("rescore")
@click.option("--status", default="", help="Only records in this state.")
@click.option("--board", default="", help="Only vacancies from this board.")
@click.option("--all", "rescore_all", is_flag=True,
              help="Every vacancy in the store, whatever its state.")
@click.option("--dry-run", is_flag=True, help="Report what would be re-scored.")
@click.option("--boards", default=DEFAULTS["boards"])
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--aliases", default=DEFAULTS["aliases"])
@click.option("--db", default=DEFAULTS["db"])
@click.option("--no-model", is_flag=True)
def rescore_cmd(status, board, rescore_all, dry_run, boards, cv, aliases, db,
                no_model) -> None:
    """Re-score stored vacancies against the current CV.

    `vanguard run` only scores what a board returns today, so a pasted
    vacancy — or one a board has since delisted — keeps a score computed
    against an older CV. This re-scores from the stored advert text, so no
    board is contacted and no API call is spent.

    Operator decisions survive. APPROVED, REJECTED and DISPATCHED records are
    re-scored but keep their status: a CV edit does not undo a decision.
    """
    from vanguard.adapters.base import Vacancy
    from vanguard.logs import RunLog

    store, queue = _ctx(db)
    registry = load_registry(boards)
    log_config = _logging(boards)

    if not (status or board or rescore_all):
        raise click.ClickException(
            "pass --status, --board, or --all. Re-scoring the whole store "
            "silently is not something to do by accident")

    rows = store.list_queue(status.upper() if status else None, limit=2000)
    if board:
        rows = [r for r in rows if (r["board_id"] or "") == board]

    if not rows:
        click.echo("nothing matched")
        return

    click.echo(ui.rule(f"RESCORE  ·  {len(rows)} vacanc(ies) against {cv}"))

    if dry_run:
        click.echo(ui.table(
            [
                ui.Column("STATUS", 0.4, 9),
                ui.Column("WAS", 0.3, 6, "right"),
                ui.Column("BOARD", 0.3, 8, tone=ui.Tone.MUTED),
                ui.Column("TITLE", 1.6, 16),
                ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
            ],
            [[r["status"], _coverage_cell(r)[0], r["board_id"] or "",
              r["title"], r["vacancy_id"]] for r in rows[:40]],
        ))
        click.echo("\n  dry run — nothing re-scored")
        return

    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    embedder, embedder_name = _embedder(not no_model)
    gate = registry.coverage_gate

    click.echo(f"  [{embedder_name}] gate {gate:.2f}\n")

    moved, unchanged, failed = [], 0, 0

    with RunLog("rescore", db_path=Path(db), config=log_config) as run_log:
        for row in rows:
            record = store.vacancy(row["vacancy_id"])
            if record is None or not (record["description"] or "").strip():
                failed += 1
                continue

            before = row["coverage"]
            was_status = row["status"]

            vacancy = Vacancy(
                id=record["id"], board_id=record["board_id"],
                employer=record["employer"], title=record["title"],
                description=record["description"], url=record["url"] or "",
                reference=record["reference"] or "",
                description_is_partial=bool(record["partial"]),
            )

            try:
                new_status = _score_and_queue(
                    vacancy, store, queue, canonical, alias_table,
                    embedder, embedder_name, gate=gate)
            except Exception as exc:
                run_log.error(str(exc), source="rescore",
                              vacancy_id=row["vacancy_id"])
                failed += 1
                continue

            after = store.latest_score(row["vacancy_id"])

            # `_score_and_queue` returns what scoring CONCLUDED, which is not
            # what was written when the record was operator-set. Read the
            # record back rather than reporting a transition that did not
            # happen — an APPROVED vacancy shown as "APPROVED -> FLAGGED"
            # would be alarming and false.
            current = store.queue_record(row["vacancy_id"])
            actual_status = current["status"] if current else new_status

            delta = (after["coverage"] if after else 0) - (before or 0)
            if abs(delta) > 0.001 or actual_status != was_status:
                moved.append((row, before, after, was_status, actual_status))
            else:
                unchanged += 1

        run_log.count(scored=len(rows) - failed, moved=len(moved))

    click.echo()
    click.echo(ui.rule(f"CHANGED  ·  {len(moved)} of {len(rows)}"))

    if moved:
        moved.sort(key=lambda m: ((m[2]["coverage"] if m[2] else 0) - (m[1] or 0)),
                   reverse=True)
        click.echo(ui.table(
            [
                ui.Column("WAS", 0.3, 6, "right"),
                ui.Column("NOW", 0.3, 6, "right"),
                ui.Column("STATUS", 0.6, 12),
                ui.Column("TITLE", 1.6, 16),
                ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
            ],
            [[f"{was or 0:.3f}",
              f"{after['coverage']:.3f}" if after else "—",
              (f"{old} -> {new}" if old != new else old),
              row["title"], row["vacancy_id"]]
             for row, was, after, old, new in moved[:40]],
        ))

    click.echo(f"\n  {unchanged} unchanged" + (f", {failed} could not be scored"
                                               if failed else ""))
    click.echo("\n  decisions were preserved — a CV edit does not undo one")
    click.echo("  vanguard todo    what is waiting now")


@main.command("draft")
@click.argument("vacancy_id")
@click.option("--name", default="", help="Your name, as it should appear.")
@click.option("--contact", default="", help="Email or link for the sign-off.")
@click.option("--to", "hiring_manager", default="Hiring Manager")
@click.option("--out", "out_dir", default="out", help="Where to write it.")
@click.option("--show", is_flag=True, help="Print it instead of writing a file.")
@click.option("--boards", default=DEFAULTS["boards"])
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--aliases", default=DEFAULTS["aliases"])
@click.option("--db", default=DEFAULTS["db"])
def draft_cmd(vacancy_id, name, contact, hiring_manager, out_dir, show, boards,
              cv, aliases, db) -> None:
    """Draft a cover letter for one vacancy, framed to what it asks for.

    The opening names what this role calls for that your CV can evidence —
    drawn from the matched requirements, not copied from the advert. The
    three bullets are CV lines chosen for how many of the vacancy's
    requirements each answers.

    Nothing appears that the CV does not support. A term the CV cannot
    evidence is refused rather than written around.
    """
    from vanguard.coverage import compute_coverage
    from vanguard.extract import extract
    from vanguard.letter import DraftError, draft_cover_letter

    store, _ = _ctx(db)
    width = _terminal_width()

    record = store.vacancy(vacancy_id)
    if record is None:
        raise click.ClickException(f"no vacancy {vacancy_id!r}")
    if not (record["description"] or "").strip():
        raise click.ClickException("no advert text stored for this vacancy")

    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    report = compute_coverage(extract(record["description"]), canonical,
                              alias_table)

    # Name and contact come from the CV's own header, so the letter and the
    # CV cannot disagree about who sent them.
    header = _cv_header(cv)
    applicant = name or header[0]
    reach = contact or header[1]

    if not applicant:
        raise click.ClickException("could not read your name from the CV; pass --name")

    try:
        letter, plan = draft_cover_letter(
            report, canonical,
            job_title=record["title"], company=record["employer"],
            applicant_name=applicant, contact=reach,
            hiring_manager=hiring_manager, aliases=alias_table,
        )
    except DraftError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo()
    click.echo(ui.rule(_clip(f"{record['title']} — {record['employer']}",
                             width - 8)))
    for line in plan.explain():
        click.echo(f"  {_clip(line, width - 6)}")

    if plan.unmet_notable:
        click.echo(f"\n  {ui.badge('NOT MENTIONED', ui.Tone.MUTED)} "
                   + _clip(", ".join(plan.unmet_notable), width - 22))
        click.echo("      unmet requirements are never written into a letter")

    if show:
        click.echo()
        click.echo(letter)
        return

    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / _letter_filename(
        record["employer"], record["title"], vacancy_id, destination)
    path.write_text(letter, encoding="utf-8")

    click.echo(f"\n  {ui.badge('WRITTEN', ui.Tone.GOOD)} {path}")
    click.echo("\n  read it before you send it. It is drafted from your CV,")
    click.echo("  not written by someone who knows what you meant.")
    click.echo(f"\n  vanguard dispatch {vacancy_id} --cover-letter \"{path}\"")


@main.command("responses")
@click.argument("vacancy_id", required=False)
@click.option("--status", default="", help="ACK, PROGRESS, DECLINE, OFFER, QUERY, ADMIN.")
@click.option("--limit", default=40)
@click.option("--db", default=DEFAULTS["db"])
def responses_cmd(vacancy_id, status, limit, db) -> None:
    """Replies that correlated to an application, and what they were.

    Classifications were written to the archive and to the interview process,
    but nothing was queryable — the operator could not ask "what has been
    rejected?", which is what `vanguard feedback` needs to know.
    """
    store, _ = _ctx(db)
    width = _terminal_width()

    # One vacancy: show the messages themselves. AMBIGUOUS exists so a human
    # reads them, and reporting that one arrived without being able to show
    # it leaves the operator nowhere to go.
    if vacancy_id:
        messages = [r for r in store.responses(limit=500)
                    if r["vacancy_id"] == vacancy_id]
        if not messages:
            click.echo(f"no responses recorded for {vacancy_id}")
            return

        vacancy = store.vacancy(vacancy_id)
        click.echo()
        click.echo(ui.rule(_clip(
            f"{vacancy['title']} — {vacancy['employer']}" if vacancy
            else vacancy_id, width - 8)))

        for message in messages:
            click.echo()
            click.echo(ui.field_list([
                ("state", message["state"]),
                ("from", message["sender"] or ""),
                ("subject", message["subject"] or ""),
                ("received", (message["received_at"] or "")[:16].replace("T", " ")),
                ("matched by", message["method"] or ""),
            ], indent="  "))

            body = (message["body"] or "").strip()
            if not body:
                click.echo("\n      (no body retained — recorded before "
                           "bodies were kept)")
                continue
            click.echo()
            for line in body.splitlines():
                for wrapped in (_wrap(line, width - 8) or [""]):
                    click.echo(f"      {wrapped}")
        return

    rows = store.responses(status, limit=limit)

    if not rows:
        click.echo(f"no {status.upper() or 'correlated'} responses recorded")
        click.echo("  vanguard poll    to read the mailbox")
        return

    click.echo(ui.rule(f"RESPONSES  ·  {len(rows)}"
                       + (f"  ·  {status.upper()}" if status else "")))
    click.echo(ui.table(
        [
            ui.Column("STATE", 0.4, 9),
            ui.Column("WHEN", 0.4, 10, tone=ui.Tone.MUTED),
            ui.Column("EMPLOYER", 0.9, 12),
            ui.Column("SUBJECT", 1.4, 14),
            ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
        ],
        [[r["state"], (r["received_at"] or r["recorded_at"] or "")[:10],
          r["employer"] or "", r["subject"] or "", r["vacancy_id"]]
         for r in rows],
    ))

    click.echo("\n  vanguard responses <ID>   read the messages themselves")
    if (status or "").upper() == "DECLINE" or any(
            r["state"] == "DECLINE" for r in rows):
        click.echo('  vanguard feedback <ID> --name "..." --contact "..."')


@main.command("funnel")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--reasons", is_flag=True, help="Show every stated reason.")
def funnel_cmd(db, reasons) -> None:
    """Where applications get to, and where they stop.

    Every rejection looked alike: rejected on the CV and rejected after a
    final panel were the same state, and they mean opposite things — the
    second says the CV worked and something later did not.

    **Reasons are never inferred.** A rejection that gives none is recorded
    as giving none. Manufacturing a cause from an email that states one
    nowhere would be inventing exactly the kind of authoritative-sounding
    content this system exists to prevent.

    The answer is in the shape, not in any single message.
    """
    from vanguard.lifecycle import FUNNEL_ORDER, StageOutcome, build_lifecycle

    store, _ = _ctx(db)
    width = _terminal_width()

    dispatched = [r for r in store.list_queue(limit=1000)
                  if r["status"] == "DISPATCHED"]
    if not dispatched:
        click.echo("nothing dispatched yet — the funnel needs applications")
        return

    by_vacancy: dict[str, list[dict]] = {}
    for row in store.responses(limit=2000):
        by_vacancy.setdefault(row["vacancy_id"], []).append(dict(row))

    points = [build_lifecycle(row["vacancy_id"],
                              by_vacancy.get(row["vacancy_id"], []))
              for row in dispatched]

    silent = [p for p in points
              if not by_vacancy.get(p.vacancy_id)]

    click.echo()
    click.echo(ui.rule(f"FUNNEL  ·  {len(points)} application(s) dispatched"))

    rows = []
    for stage in FUNNEL_ORDER:
        reached = [p for p in points if p.depth >= FUNNEL_ORDER.index(stage)]
        failed = [p for p in points
                  if p.reached is stage and p.outcome is StageOutcome.FAILED]
        if not reached and not failed:
            continue
        rows.append([
            stage.value.title(),
            str(len(reached)),
            str(len(failed)) if failed else "—",
            ui.bar(len(reached), len(points), width=16),
        ])

    click.echo(ui.table(
        [
            ui.Column("STAGE", 0.6, 12),
            ui.Column("REACHED", 0.3, 7, "right"),
            ui.Column("ENDED", 0.3, 6, "right"),
            ui.Column("", 0.8, 18, tone=ui.Tone.MUTED),
        ],
        rows,
    ))

    offers = [p for p in points if p.outcome is StageOutcome.PASSED]
    live = [p for p in points if p.outcome is StageOutcome.PENDING
            and by_vacancy.get(p.vacancy_id)]

    click.echo()
    click.echo(ui.field_list([
        ("offers", str(len(offers)) if offers else "—"),
        ("still live", str(len(live))),
        ("no reply at all", str(len(silent))),
    ], indent="  "))

    # --- why, where anyone said -------------------------------------------
    stated = [p for p in points if p.reason_is_stated]
    failures = [p for p in points if p.outcome is StageOutcome.FAILED]

    if failures:
        click.echo()
        click.echo(ui.rule("WHY"))
        click.echo(f"  {len(stated)} of {len(failures)} rejection(s) gave a reason")

        if stated and (reasons or len(stated) <= 5):
            for point in stated:
                vacancy = store.vacancy(point.vacancy_id)
                click.echo()
                click.echo(f"  {_clip(vacancy['employer'] if vacancy else point.vacancy_id, 30)}"
                           f"  ({point.describe()})")
                for line in _wrap(point.stated_reason, width - 8):
                    click.echo(f"      {line}")
        elif stated:
            click.echo("  --reasons to read them")

        if len(stated) < len(failures):
            click.echo(f"\n  The other {len(failures) - len(stated)} gave none, "
                       "and none is inferred.")
            click.echo("  Where an application ends says more than any single "
                       "rejection does.")


@main.command("reclassify")
@click.option("--dry-run", is_flag=True, help="Report what would change.")
@click.option("--db", default=DEFAULTS["db"])
@click.option("--no-model", is_flag=True, help="Rules only.")
def reclassify_cmd(dry_run, db, no_model) -> None:
    """Re-run classification over messages already received.

    Needs no mailbox — the bodies are stored, so a classifier improved after
    the fact applies to everything already in the register.

    **Only AMBIGUOUS records are changed.** A message already classified
    DECLINE must not silently become something else because a threshold
    moved.
    """
    from datetime import datetime, timezone

    from vanguard.mail import Message, classify

    store, _ = _ctx(db)
    width = _terminal_width()
    classifier, classifier_name = _embedder(not no_model)

    def _classify(row) -> str:
        message = Message(
            message_id=row["message_id"] or "",
            sender=row["sender"] or "",
            subject=row["subject"] or "",
            body=row["body"] or "",
            received=datetime.now(timezone.utc),
        )
        return classify(message, embedder=classifier).state.value

    rows = [r for r in store.responses(limit=5000)
            if r["state"] == "AMBIGUOUS" and (r["body"] or "").strip()]

    click.echo(ui.rule(f"RECLASSIFY  ·  {len(rows)} ambiguous with a body "
                       f"[{classifier_name}]"))

    if not rows:
        without_body = sum(1 for r in store.responses(limit=5000)
                           if r["state"] == "AMBIGUOUS" and not (r["body"] or "").strip())
        if without_body:
            click.echo(f"  {without_body} ambiguous record(s) have no body "
                       "stored — `vanguard poll` fills them in")
        else:
            click.echo("  nothing to reclassify")
        return

    proposed = [(row, _classify(row)) for row in rows]
    moved = [(row, state) for row, state in proposed if state != "AMBIGUOUS"]

    if moved:
        click.echo(ui.table(
            [
                ui.Column("NOW", 0.4, 9),
                ui.Column("EMPLOYER", 0.9, 12),
                ui.Column("SUBJECT", 1.5, 16),
                ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED, protected=True),
            ],
            [[state, row["employer"] or "", row["subject"] or "",
              row["vacancy_id"]] for row, state in moved],
        ))

    if dry_run:
        click.echo(f"\n  dry run — {len(moved)} would change")
        return

    changed, total = store.reclassify(_classify)
    click.echo(f"\n  {ui.badge('RECLASSIFIED', ui.Tone.GOOD)} {changed}")
    if len(rows) > len(moved):
        click.echo(f"  {len(rows) - len(moved)} still ambiguous — read them "
                   "with `vanguard responses <ID>`")


# ---------------------------------------------------------------------------
# Response loop (Route 5) — classify only. Never sends.
# ---------------------------------------------------------------------------

@main.command("mail")
@click.option("--file", "path", type=click.Path(exists=True), required=True,
              help="Message body. Reads a single message.")
@click.option("--sender", default="", help="From address.")
@click.option("--subject", default="", help="Subject line.")
@click.option("--db", default=DEFAULTS["db"])
def mail_cmd(path, sender, subject, db) -> None:
    """Correlate and classify one inbound message. Records; never replies."""
    from vanguard.mail import Application, classify, correlate

    store, queue = _ctx(db)
    body = Path(path).read_text(encoding="utf-8")
    message = Message(message_id=Path(path).name, sender=sender,
                      subject=subject, body=body)

    apps = []
    for r in store.list_queue(limit=500):
        row = store.vacancy(r["vacancy_id"])
        apps.append(Application(
            vacancy_id=r["vacancy_id"], employer=r["employer"], title=r["title"],
            reference=(row["reference"] if row else "") or "",
            url=(row["url"] if row else "") or "",
        ))

    result = correlate(message, apps)
    if not result.correlated:
        click.echo("UNCORRELATED — queued for review, not classified")
        click.echo("  correlation failure is not a classification outcome")
        return

    # The same local embedder poll uses, so a message read from a file is
    # classified no worse than one read from the mailbox.
    classifier, _ = _embedder(True)
    outcome = classify(message, embedder=classifier)
    click.echo(f"correlated to {result.application.vacancy_id} via {result.method.value}")
    click.echo(f"{outcome}")
    if outcome.note:
        click.echo(f"  {outcome.note}")

    template = outcome.state.invites_template
    if template:
        verb = "interview" if template == "E" else "feedback"
        click.echo(
            f"\noperator may invoke Template {template}: "
            f"vanguard {verb} {result.application.vacancy_id}"
        )
    click.echo("\nno outbound action taken")


@main.command()
@click.option("--db", default=DEFAULTS["db"])
@click.option("--boards", default=DEFAULTS["boards"])
def dormant(db, boards) -> None:
    """Applications silent past silence_days. Derived state, never DECLINE."""
    from datetime import datetime, timezone
    from vanguard.mail import Application, dormant_sweep

    store, _ = _ctx(db)
    registry = load_registry(boards)

    apps = []
    for r in store.list_queue(limit=500):
        created = r["created_at"]
        try:
            submitted = datetime.fromisoformat(created)
        except (TypeError, ValueError):
            continue
        apps.append(Application(
            vacancy_id=r["vacancy_id"], employer=r["employer"],
            title=r["title"], submitted=submitted,
        ))

    candidates = dormant_sweep(apps, [], registry.silence_days_for)
    if not candidates:
        click.echo("no dormant applications")
        return

    click.echo(f"{len(candidates)} dormant — silence is not a rejection\n")
    for c in candidates:
        click.echo(f"  {c.days_silent:>3}d (limit {c.silence_days}d)  {c.vacancy_id}")


@main.command()
@click.argument("vacancy_id")
@click.option("--name", required=True, help="Your name, for the signature.")
@click.option("--contact", required=True)
@click.option("--recipient", default="Recruitment Team")
@click.option("--force", is_flag=True,
              help="Draft anyway — for a rejection that arrived by phone or portal.")
@click.option("--db", default=DEFAULTS["db"])
def feedback(vacancy_id, name, contact, recipient, force, db) -> None:
    """Draft a Template D feedback request. YOU send it; Vanguard does not."""
    from vanguard.interview import OperatorActionError, draft_feedback_request
    from vanguard.mail import State

    store, _ = _ctx(db)
    vacancy = store.vacancy(vacancy_id)
    if vacancy is None:
        raise click.ClickException(f"no vacancy {vacancy_id!r}")

    # The state was hardcoded to DECLINE, so this would draft a rejection
    # response for a vacancy that had not rejected anything. Sending that
    # would be worse than not having the command.
    latest = store.latest_response(vacancy_id)
    if not force and (latest is None or latest["state"] != "DECLINE"):
        seen = latest["state"] if latest else "nothing"
        raise click.ClickException(
            f"no DECLINE recorded for {vacancy_id} — last was {seen}. "
            "Run `vanguard poll` first, or `vanguard responses` to see what "
            "arrived. Use --force if the rejection came by phone or portal.")

    try:
        click.echo(draft_feedback_request(
            job_title=vacancy["title"], company=vacancy["employer"],
            applicant_name=name, contact=contact, recipient=recipient,
            state=State.DECLINE,
        ))
    except OperatorActionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("--- draft only. Review and send yourself. ---")


@main.command()
@click.argument("vacancy_id")
@click.option("--phase", type=click.IntRange(1, 3), default=1)
@click.option("--limit", default=5)
@click.option("--cv", default=DEFAULTS["cv"])
@click.option("--db", default=DEFAULTS["db"])
def interview(vacancy_id, phase, limit, cv, db) -> None:
    """Template E — three-phase interview simulation, graded D1-D5."""
    from vanguard.interview import PASS_LINE, Phase, build_session

    store, _ = _ctx(db)
    vacancy = store.vacancy(vacancy_id)
    if vacancy is None:
        raise click.ClickException(f"no vacancy {vacancy_id!r}")

    selected = Phase(phase)
    questions = build_session(
        load_cv(cv), company=vacancy["employer"],
        job_title=vacancy["title"], phase=selected, limit=limit,
    )

    click.echo(f"\nPHASE {phase}: {selected.title}")
    click.echo(f"{vacancy['title']} — {vacancy['employer']}")
    dims = "  ".join(f"D{int(d)}" for d in selected.dimensions)
    click.echo(f"graded on {dims}, 0-3 each (max {selected.max_aggregate}), "
               f"pass line {PASS_LINE}\n")

    for i, q in enumerate(questions, 1):
        click.echo(f"{i}. {q.text}")
        if q.cv_source:
            click.echo(f"   [{q.cv_source}]")
        click.echo()

    click.echo("D1 = 0 is terminal. Every score needs a one-line justification.")


if __name__ == "__main__":  # pragma: no cover
    main()
