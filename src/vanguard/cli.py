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
from vanguard.coverage import compute_coverage, load_aliases
from vanguard.cv import load as load_cv
from vanguard.extract import extract
from vanguard.gaps import classify_all
from vanguard.ingest import health_check_all, ingest
from vanguard.logs import LogConfig, RunLog, configure
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
    """
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
    from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

    def _coverage_cell(row) -> tuple[str, str]:
        """Coverage and its denominator — or a marker when it was not measured.

        A bare `1.000` for a vacancy scored on one requirement reads as the
        best match in the queue. It means the opposite: nothing was measured.
        Printing the figure at all was the defect.
        """
        total = row["terms_total"] or 0
        unreliable = total < MIN_TERMS_FOR_CONFIDENCE or bool(row["partial"])
        if unreliable:
            return "not measured", f"{total} terms" if total else "no terms"
        return f"{row['coverage'] or 0:.3f}", f"{row['terms_matched']}/{total}"

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
            ui.Column("ID", 0.9, 12, tone=ui.Tone.MUTED),
        ],
        body,
    ))

    click.echo()
    if unmeasured:
        click.echo(
            f"  {ui.badge(f'{unmeasured} not measured', ui.Tone.WARN)} — advert had "
            f"fewer than {MIN_TERMS_FOR_CONFIDENCE} requirements, or partial text. "
            "Run `vanguard diagnose`."
        )
    click.echo("  vanguard review <ID>   for the full record")


@main.command()
@click.argument("vacancy_id")
@click.option("--note", default="")
@click.option("--db", default=DEFAULTS["db"])
def approve(vacancy_id, note, db) -> None:
    """Approve for dispatch. Only APPROVED is dispatch-eligible."""
    _, queue = _ctx(db)
    _apply(queue.approve, vacancy_id, note)


@main.command()
@click.argument("vacancy_id")
@click.option("--reason", default="")
@click.option("--db", default=DEFAULTS["db"])
def reject(vacancy_id, reason, db) -> None:
    """Reject and archive."""
    _, queue = _ctx(db)
    _apply(queue.reject, vacancy_id, reason)


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
@click.option("--db", default=DEFAULTS["db"])
def dispatch(vacancy_id, note, db) -> None:
    """Record a submission YOU made. Vanguard never transmits."""
    _, queue = _ctx(db)
    _apply(queue.dispatch, vacancy_id, note)


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
def stats(db) -> None:
    """Coverage distribution and recurring gaps. The recalibration input."""
    store, queue = _ctx(db)
    rows = store.coverage_distribution()

    click.echo(f"queue: {queue.summary()}")
    click.echo(f"vacancies: {store.count_vacancies()}   scored: {len(rows)}")

    if rows:
        values = sorted(r["coverage"] for r in rows)
        mid = values[len(values) // 2]
        click.echo(
            f"\ncoverage  min {values[0]:.3f}  median {mid:.3f}  max {values[-1]:.3f}"
        )
        at_gate = sum(1 for v in values if v >= 0.94)
        click.echo(f"at or above 0.94: {at_gate}/{len(values)}")
        if len(values) < 30:
            click.echo(
                f"({30 - len(values)} more logged applications before the 0.94 "
                "threshold can be revisited against evidence — OUTSTANDING P-01)"
            )

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
        ))

    result = correlate(message, apps)
    if not result.correlated:
        click.echo("UNCORRELATED — queued for review, not classified")
        click.echo("  correlation failure is not a classification outcome")
        return

    outcome = classify(message)
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
@click.option("--db", default=DEFAULTS["db"])
def feedback(vacancy_id, name, contact, recipient, db) -> None:
    """Draft a Template D feedback request. YOU send it; Vanguard does not."""
    from vanguard.interview import OperatorActionError, draft_feedback_request
    from vanguard.mail import State

    store, _ = _ctx(db)
    vacancy = store.vacancy(vacancy_id)
    if vacancy is None:
        raise click.ClickException(f"no vacancy {vacancy_id!r}")

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
