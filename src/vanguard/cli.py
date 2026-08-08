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

import sys
from pathlib import Path

try:
    import click
except ImportError:  # pragma: no cover
    sys.exit("click required: pip install -e '.[dev]'")

from vanguard.adapters.base import Query, load_registry
from vanguard.coverage import compute_coverage, load_aliases
from vanguard.cv import load as load_cv
from vanguard.extract import extract
from vanguard.gaps import classify_all
from vanguard.ingest import health_check_all, ingest
from vanguard.mail import Message
from vanguard.queue import IllegalTransition, QueueManager, Status
from vanguard.rank import LexicalEmbedder, rank_score
from vanguard.refactor import refactor
from vanguard.store import Store, StoreError
from vanguard.submission import detect

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



def _score_and_queue(vacancy, store, queue, canonical, alias_table, embedder, name) -> str:
    """Score one vacancy, classify, and write the queue record. Returns status."""
    spec_early = detect(vacancy.description)
    if spec_early.vacancy_reference and not vacancy.reference:
        vacancy.reference = spec_early.vacancy_reference
    store.upsert_vacancy(vacancy)
    requirements = extract(vacancy.description)
    outcome = refactor(requirements, canonical, alias_table, embedder)
    gaps = classify_all(outcome.final, canonical)
    spec = detect(vacancy.description)

    store.record_score(
        vacancy.id, outcome.final,
        rank_score(canonical.full_text(), vacancy.description, embedder),
        embedder=name, gaps=gaps,
    )

    status = Status(outcome.status)
    note = outcome.exit_reason.value
    if spec.flagged:
        status, note = Status.FLAGGED, spec.flag_reason
    elif gaps.requires_operator and status is Status.PENDING:
        status = Status.FLAGGED
        note = f"{len(gaps.unconfirmed)} gap proposal(s) awaiting confirmation"

    queue.enqueue(
        vacancy.id, status,
        submission_type=spec.submission_type.value,
        flags={"ANONYMISE": spec.anonymise, "WORD_LIMIT": spec.word_limit,
               "CRITERIA": len(spec.assessed_criteria)},
        note=note,
    )
    click.echo(
        f"  {status.value:<12} C={outcome.final.coverage:.3f} "
        f"ceiling={outcome.final.ceiling:.3f}  {vacancy.title[:44]}"
    )
    return status.value


def _ctx(db: str):
    store = Store(Path(db))
    store.initialise()
    return store, QueueManager(store)


@click.group()
@click.version_option("0.1.0", prog_name="vanguard")
def main() -> None:
    """Project Vanguard — semi-autonomous job application pipeline."""


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
    canonical = load_cv(cv)
    alias_table = load_aliases(aliases)
    embedder, embedder_name = _embedder(not no_model)

    click.echo(f"ingesting from {len(registry.automatable)} automatable board(s)")
    result = ingest(registry, Query(keywords=tuple(title), location=location))
    click.echo(result.summary())

    if not result.vacancies:
        click.echo("no vacancies. exiting.")
        return

    click.echo(f"\nscoring {len(result.vacancies)} vacanc(ies) [{embedder_name}]")
    for vacancy in result.vacancies:
        try:
            _score_and_queue(vacancy, store, queue, canonical, alias_table,
                             embedder, embedder_name)
        except Exception as exc:
            # One vacancy failing must not abort the run.
            click.echo(f"  ERROR        {vacancy.title[:44]}: {exc}", err=True)

    click.echo(f"\n{queue.summary()}")
    click.echo("run complete — no transmission occurred")


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
    _score_and_queue(vacancy, store, queue, canonical, alias_table, embedder, name)
    click.echo(f"\n{vacancy.id}\nvanguard review {vacancy.id}")


# ---------------------------------------------------------------------------
# Interactive
# ---------------------------------------------------------------------------

@main.command()
@click.argument("vacancy_id", required=False)
@click.option("--status", default="PENDING", help="Filter: PENDING, FLAGGED, ...")
@click.option("--db", default=DEFAULTS["db"])
def review(vacancy_id, status, db) -> None:
    """List queued records, or show one in full."""
    store, queue = _ctx(db)

    if vacancy_id:
        record = store.queue_record(vacancy_id)
        if record is None:
            raise click.ClickException(f"no queue record for {vacancy_id!r}")
        vacancy = store.vacancy(vacancy_id)
        score = store.latest_score(vacancy_id)

        click.echo(f"\n{vacancy['title']} — {vacancy['employer']}")
        click.echo(f"{vacancy['location']}  {vacancy['salary_band']}")
        click.echo(f"status {record['status']}   type {record['submission_type']}")
        if record["note"]:
            click.echo(f"note: {record['note']}")
        if score:
            click.echo(
                f"\nC={score['coverage']:.3f}  ceiling={score['ceiling']:.3f}  "
                f"S={score['rank_score'] or 0:.3f}  "
                f"{score['terms_matched']}/{score['terms_total']} terms  "
                f"[{score['embedder']}]"
            )

        rows = store.gaps_for(vacancy_id)
        unmet = [r for r in rows if r["outcome"] == "GAP"]
        if unmet:
            click.echo(f"\nunmet ({len(unmet)}):")
            for r in unmet:
                tag = f"Type {r['gap_type']}" if r["gap_type"] else "—"
                reason = f"  [{r['exclusion'][:56]}]" if r["exclusion"] else ""
                click.echo(f"  {tag:<7} {r['term'][:48]}{reason}")

        click.echo("\nhistory:")
        for frm, to, at in queue.history(vacancy_id):
            click.echo(f"  {at}  {frm} -> {to}")
        if vacancy["url"]:
            click.echo(f"\n{vacancy['url']}")
        return

    rows = store.list_queue(status.upper())
    if not rows:
        click.echo(f"no records with status {status.upper()}")
        return
    click.echo(f"{status.upper()} — {len(rows)} record(s), strongest first\n")
    for r in rows:
        click.echo(
            f"  C={r['coverage'] or 0:.3f} S={r['rank_score'] or 0:.3f}  "
            f"{r['employer'][:24]:<24} {r['title'][:38]:<38} {r['vacancy_id']}"
        )


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
@click.option("--no-model", is_flag=True)
def score(advert, cv, aliases, no_model) -> None:
    """Score one advert. No database, no queue — an honest gap report."""
    text = Path(advert).read_text(encoding="utf-8")
    canonical = load_cv(cv)
    embedder, name = _embedder(not no_model)

    report = compute_coverage(extract(text), canonical, load_aliases(aliases), embedder)
    gaps = classify_all(report, canonical)
    spec = detect(text)

    click.echo(f"\n{report.summary()}   [{name}]")
    click.echo(f"S = {rank_score(canonical.full_text(), text, embedder):.3f} (ranking only)")
    click.echo(f"\n{spec.summary()}")
    click.echo(f"\n{gaps.summary()}")

    if report.excluded_gaps:
        click.echo("\nblocked by alias table (Tier C) — no CV edit permitted:")
        for r in report.excluded_gaps:
            click.echo(f"  {r.requirement.canonical or r.requirement.text[:44]}")

    other = [g for g in gaps.type_3 if not g.blocked_by_exclusion]
    if other:
        click.echo("\nunmet, not evidenced:")
        for g in other:
            click.echo(f"  {g.term[:60]}")


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
            click.echo(f"  {r['n']:>3}x  {r['term'][:56]}")


@main.command()
@click.option("--boards", default=DEFAULTS["boards"])
def boards(boards) -> None:
    """Registry health. Terms are re-verified before enabling a board."""
    registry = load_registry(boards)
    click.echo(
        f"{len(registry)} registered   {len(registry.enabled)} enabled   "
        f"{len(registry.automatable)} automatable   {len(registry.manual)} manual\n"
    )
    for status in health_check_all(registry):
        entry = registry.get(status.board_id)
        mark = "ok " if status.reachable else "-- "
        click.echo(f"{mark} {entry.id:<20} {entry.tier.value:<13} {status.detail[:66]}")


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
