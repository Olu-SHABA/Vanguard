# PROJECT VANGUARD — Standard Operating Procedure

**Version 1.0 · 10 August 2026**

Two audiences, two reading paths.

| You are | Start at | Then |
|---|---|---|
| **Picking this up cold** | [Part 1 — Orientation](#part-1--orientation) | Read Part 2 before touching anything |
| **The operator, returning** | [Part 3 — Routine](#part-3--routine-operation) | Checklists. Reasoning is in Part 2 when you need it |

**Reference:** `COMMANDS.md` for every command and option. This document is
what to *do*; that one is what things *are*.

---

# PART 1 — Orientation

*Read this if you have not used Vanguard before. Skip to Part 3 if you have.*

## What this system is for

Applying to senior data roles at volume requires tailoring each application to
the advert. Doing that by hand does not scale. Automating it introduces a
different risk: a system optimising for a match score will invent
qualifications.

Vanguard exists to do the first without doing the second.

## The one thing to understand before anything else

**The system will not lie on your behalf, and this is not a preference — it is
enforced in code.**

Three mechanisms:

**Type 3 gaps permit no CV edit.** If a job asks for something with no basis in
your employment history, it is recorded as unmet. The refactor engine cannot
touch it. Not by convention — the data layer rejects the edit.

**Injection constraints.** A figure cannot appear in a cover letter unless it
appears in the CV submitted alongside it. Attempting it raises rather than
rendering.

**Unreliable scores cannot pass the gate.** If an advert yielded too few
requirements to measure, the system says `not measured` rather than showing a
number. A confident-looking wrong answer is worse than a refusal.

If you find yourself working around any of these, stop. They are the reason the
system is trustworthy.

## The second thing: it never transmits

No command sends an email or submits an application. `dispatch` records that
*you* submitted one. `feedback` drafts text for you to send. There is no
outbound path in the codebase, deliberately.

## How the pipeline works

```
  boards.yaml          which sources, what terms, what limits
       |
       v
  INGEST               fetch vacancies, deduplicate across sources
       |
       v
  RANK                 one embedding each, no API call. Cheap filter.
       |
       v
  HYDRATE              full advert text — only for what survived ranking
       |
       v
  SCORE                extract requirements, match against the CV
       |
       v
  CLASSIFY             every unmatched requirement typed 1, 2 or 3
       |
       v
  QUEUE                a record, a status, and it exits
       |
       v
  === YOU DECIDE ===   approve, reject, override, or ignore
```

Hydration sits after ranking because each full advert costs one API call
against a small hourly budget. Spending it before knowing whether a vacancy is
remotely relevant wastes most of it.

## The numbers you will see

| | Means |
|---|---|
| **C** — coverage | Matched requirements ÷ total requirements. **This gates** |
| **ceiling** | The best coverage attainable if every Type 3 gap stays unmet |
| **S** — rank score | Document similarity. Orders the queue. **Never gates** |
| **not measured** | Too few requirements extracted, or the advert text was partial |

**Coverage gates and similarity ranks.** This split is the system's central
design decision. A gate must be able to answer *which requirement failed*, and
an embedding cannot. The original design gated on similarity at 0.94, which is
structurally unreachable between a CV and a job advert — they are different
genres of document.

**A ceiling below the gate means the vacancy cannot pass**, however much the
CV is reworded. That is a true finding, not a failure.

## The four statuses

| | Meaning | You |
|---|---|---|
| **PENDING** | Passed the gate. Ready | Review it. This is the good one |
| **FLAGGED** | Something unresolved — see the record for why | Read, then resolve or reject |
| **UNREACHABLE** | Real gaps block it | Skip, or override with a justification |
| **APPROVED / DISPATCHED / REJECTED** | You decided | Done |

`FLAGGED` is not positive. It means the system stopped rather than guessing.

## Where the truth lives

| File | Holds |
|---|---|
| `canonical_cv.md` | **Single source of truth.** All employment history and metrics. Gitignored — it is personal data |
| `config/alias_table.yaml` | Which terms count as which, and which are permanently excluded |
| `config/boards.yaml` | Sources, thresholds, limits, logging |
| `PROJECT_VANGUARD_DIRECTIVE.md` | Governs behaviour. Where documents disagree, this wins |
| `OUTSTANDING.md` | Every open defect, deferral and unverified assumption |

## Before you touch anything

1. Read `PROJECT_VANGUARD_DIRECTIVE.md` — it is short and it governs
2. Read the Tier C section of `alias_table.yaml` — those exclusions are
   deliberate and each has a stated reason
3. Run `pytest`. If it is not green, stop and find out why
4. Run `vanguard boards` — see what is configured

---

# PART 2 — Judgement calls

*The decisions the system deliberately does not make for you.*

## Confirming a Type 1 gap

The classifier proposes; you confirm. It cannot know what you actually did.

**Confirm when** the competency is genuinely demonstrable from work already on
the CV, and you could defend it in an interview with specifics — what system,
what period, what outcome.

**Do not confirm when** it is adjacent but not the same. "Managed incidents" is
not "line management". "Scheduled a job" is not "CI/CD".

The test: could you answer three follow-up questions about it without
inventing anything? If not, it is Type 3.

## Overriding an UNREACHABLE

`vanguard override <id> --why "..."` requires a justification because the
system found something true — the ceiling is below the gate, and no rewording
closes it.

**Reasonable:** the blocking gaps are peripheral to the role, or the advert
lists desirables as though they were essentials, or you have a relationship
with the employer that changes the calculus.

**Not reasonable:** you want to apply anyway and the number is inconvenient.
That is what the justification field exists to make visible to your future
self.

## Ratcheting the coverage gate

Currently 0.60, in `boards.yaml`. It was 0.94 and passed nothing — the best
genuine fit had a ceiling of 0.800 and could not reach it.

**Raise it when** something has changed to justify it: the CV strengthened, the
alias table learned a real equivalence, extraction improved.

**Do not raise it** because the queue feels crowded. That is not filtering; it
is narrowing the field until it matches what you already believed.

**Record the reason beside the number.** A gate with a dated justification is
auditable; a bare number is arbitrary.

```yaml
# 0.60 -> 0.65, 15 Sep 2026: added test-suite evidence to the CV;
# three vacancies that previously blocked on testing now resolve.
coverage_gate: 0.65
```

## Adding an alias

An alias table is a machine for turning unmatched terms into matches — which
makes it also a machine for quietly converting Type 3 gaps into false hits.

**Rule, enforced by the loader:** no entry may exist without a
`canonical_cv.md` line behind it.

**Before adding, ask:** is this the same thing, or merely nearby? `git` and
`pull requests` looked like one concept; individual version control is
evidenced and team workflow is not, so they became two entries.

## Moving something out of Tier C

Tier C is what you cannot claim. Moving something out is legitimate **only when
the evidence changed** — you learned the skill, and the CV now says so.

Not when a job wants it.

Worked example, 9 August 2026: `git` moved to Tier B because sustained use with
an auditable commit history had accumulated. `pytest` stayed in Tier C at the
same sitting, because the tests in the repository were not written by the
operator, and claiming authorship would fail interrogation.

## When the system and your judgement disagree

Trust your judgement about your own history. Trust the system about
arithmetic.

If a vacancy scores badly and you know you are a strong fit, the interesting
question is *why* — usually the advert uses vocabulary the alias table has not
learned. That is a table entry, not a reason to ignore the score.

---

# PART 3 — Routine operation

## Daily

```
[ ] vanguard run
[ ] check the RESULT block — any PENDING?
[ ] vanguard review                    if PENDING > 0
[ ] vanguard review <id>               read the gaps before deciding
[ ] vanguard approve <id>  |  reject <id> --reason "..."
[ ] apply, then: vanguard dispatch <id>
```

**Stop and investigate if:**

- `ERRORS` in the run summary is non-zero → `vanguard logs`
- Reliable scores drop sharply from the previous run → `vanguard diagnose`
- A board that worked yesterday reports unreachable → `vanguard boards`

## When a vacancy arrives by hand

LinkedIn, Adzuna, or anywhere you browse. Per-board detail in
**`MANUAL_ENTRY.md`**.

**Several at once** — see `HOW_TO_ADD_MANY_JOBS.md`:

```
[ ] save every advert into adverts\
[ ] vanguard adverts register --template     writes a CSV to fill in
[ ] vanguard adverts register --from-csv adverts\to_register.csv
[ ] vanguard adverts ingest --move-to done\
```

```
[ ] copy the WHOLE advert, including the requirements section
[ ] vanguard paste --file advert.txt --employer "..." --url "..."
[ ] vanguard review --status <whatever it reported>
```

A truncated paste produces the same problem as an unhydrated fetch: too few
requirements, and the score is marked `not measured`.

## When a recruiter replies

Step by step in **`HOW_TO_HANDLE_REPLIES.md`**.

```
[ ] vanguard poll --dry-run          see what is there, record nothing
[ ] vanguard poll                    correlate, classify, archive
[ ] vanguard interviews              anything progressing?
```

`poll` reads the mailbox directly. `vanguard mail --file` remains for a
message saved by hand — a forward, or something the search did not reach.

Then, by classification:

| | Do |
|---|---|
| `PROGRESS` | A round opens. `vanguard interviews <id>` names the phase to rehearse |
| `OFFER` | The process closes. Nothing further to do here |
| `DECLINE` | `vanguard feedback <id> --name "..." --contact "..."` then send it yourself |
| `QUERY` | Answer it. Nothing automated |
| `ACK` | Nothing to do. Receipt only |
| `ADMIN` | Logistics. Attaches to the current round |
| `AMBIGUOUS` | No marker fired. Read it yourself |
| `UNCORRELATED` | Not matched to an application. Check manually |

## Working an interview

```
[ ] vanguard interviews                    active processes
[ ] vanguard interviews <id>               rounds, messages, next phase
[ ] vanguard interview <id> --phase N      rehearse before the round
```

A process opens on the first PROGRESS and closes **only** on OFFER, DECLINE or
your own withdrawal:

```
[ ] vanguard interviews <id> --withdraw "accepted another role"
```

Silence never closes one. Employers go quiet between rounds and return.

## Clearing a FLAGGED record

```
[ ] vanguard review <id>               read WHY it flagged
[ ] resolve the ambiguity, if there is one
[ ] vanguard resolve <id> --note "..."      returns to PENDING
```

Or, if it is not worth pursuing:

```
[ ] vanguard reject <id> --reason "salary below range"
```

`resolve` returns a record to PENDING for review — never straight to approval.
A resolved ambiguity still needs the same judgement as any other candidate.

## Checking a vacancy without ingesting it

```
[ ] save the advert text
[ ] vanguard score --advert advert.txt
```

No database write, no queue record. Useful for testing a change to the CV or
the alias table against an advert you already know well.

## Weekly

```
[ ] vanguard stats                     coverage distribution, recurring gaps
[ ] vanguard diagnose                  parse rate, unrecognised headings
[ ] vanguard interviews                anything waiting on you
[ ] vanguard dormant                   applications gone quiet
[ ] vanguard logs                      any errors during the week
```

**What to look at:**

**`stats` — most frequently unmet.** A requirement appearing 30 times is a
standing skills gap. That is career information, not software output.

**`diagnose` — the parse rate.** Currently around 65%. A sustained fall means
adverts changed shape. A rise means a fix worked.

**`dormant`.** Silence is not rejection. It never triggers a feedback request,
and it should not trigger one from you either — employers do go quiet and
return.

## Monthly

```
[ ] vanguard stats --storage           row counts, database size
[ ] vanguard logs --archive            move old records aside, gzip old files
[ ] review boards.yaml                 still the right keywords and location?
[ ] check OUTSTANDING.md               anything now answerable?
[ ] re-render the CV if it changed
```

### What grows, and what does not

Measured at 75 vacancies in one batch, not estimated. Full detail in
`COMMANDS.md`.

| File | Grows? | Bounded by |
|---|---|---|
| `data/vanguard.db` | **Yes** | Nothing. ~12 KB per vacancy |
| `Pipeline_Archive/` | **Yes** | Applications submitted, not vacancies scored |
| `logs/vanguard.log` | No | Rotation — new file each midnight |
| `archive.db` | Slowly | Only records past retention |
| `adverts/manifest.yaml` | No | Files currently in the folder |
| `adverts/to_register.csv` | No | Unregistered files only. Overwritten each time |
| `out/cv.pdf` | No | Replaced each render |

**Only two grow without bound**, and only one is a database.

**Do not act on size.** SQLite handles multi-gigabyte databases. The first
symptom is `review` and `stats` becoming slow to run. When that happens, add
indices or extend `logs --archive` to cover vacancies — and decide on the
numbers `stats --storage` reports, not on a projection.

## After changing the CV

```
[ ] edit data/canonical_cv.md
[ ] pytest                             round-trip test must pass
[ ] python -c "from vanguard.render import render; render('data/canonical_cv.md','render/standard.css','out/cv.pdf')"
[ ] open out/cv.pdf and look at it
[ ] python -c "from vanguard.render import render_anonymised; render_anonymised('data/canonical_cv.md','render/anonymised.css','out/cv_anon.pdf')"
```

The anonymised render raises if anything identifying survives. Silence is the
pass.

---

# PART 4 — When something goes wrong

## Diagnosis order

Always the same, cheapest first:

```
1. vanguard logs          what happened, and when
2. vanguard boards        is the source reachable
3. vanguard diagnose      is the parsing working
4. pytest                 is the code sound
```

## By symptom

| Symptom | Likely cause | Do |
|---|---|---|
| `vanguard` not recognised | Entry point not registered | `pip install -e ".[dev]"` |
| A board reports missing credentials | `.env` not loaded or incomplete | Check `.env` exists in the repo root and has no quotes |
| `no vacancies` | No automatable board configured | `vanguard boards` — is anything `ok` and automatable? |
| Many `not measured` | Advert structure unrecognised | `vanguard diagnose` — check the refusal reasons |
| `RateLimitExceeded` | Hydration budget exhausted | Reduce `max_results` in `boards.yaml` |
| `illegal transition` | The state machine refused | Read the message; it names what is permitted |
| `AnonymisationError` | Identifying content survived a render that must not carry it | The message names what leaked. **Do not send that file** |
| `permission denied` writing a PDF | The file is open in a viewer | Close it |
| `cannot load library 'libgobject'` | GTK3 runtime missing | See README |
| Run hangs | Rate limiter waiting, or a live API call | Ctrl+C, then `vanguard logs` |

## A run failed overnight

```
[ ] vanguard logs --errors
[ ] read logs/vanguard.log for the same timestamp
[ ] vanguard boards            still reachable?
[ ] re-run manually
```

The database says *what* failed; the file says *why*. Both are needed.

## The database looks wrong

**Do not delete it.** It holds the scoring history that threshold
recalibration depends on, and that history cannot be reconstructed.

```
[ ] cp data/vanguard.db data/vanguard.db.backup
[ ] python -c "import sqlite3; sqlite3.connect('data/vanguard.db').execute('PRAGMA integrity_check')"
[ ] vanguard logs              anything recorded around the time it broke?
```

Migrations run automatically on every command, so a schema mismatch usually
resolves itself on the next invocation.

## A change made things worse

This has happened, and the response is established.

```
[ ] revert first, fix second
[ ] re-run and confirm the previous numbers return
[ ] only then attempt the fix again
```

**Precedent, 9 August 2026:** the heading detector was tightened on good
evidence and rejected real headings alongside the noise. Reliable scores fell
from 20 of 31 to 13, and the only PENDING vacancy was lost. Reverting first
meant nothing was worse than before while the fix was reconsidered.

---

# PART 5 — The principle

Four times during this build a change was made against a sample too small to
be representative: a 0.94 gate on a metric never measured, extraction designed
against one advert, a diagnosis drawn from 29 examples, and a heading detector
tightened without re-measuring. Each cost a rebuild or a revert.

`vanguard diagnose`, `vanguard stats` and `vanguard logs` exist so that
measurement is cheap.

**A change justified by evidence must be verified by evidence before it is
kept.**

That applies to the coverage gate, to alias entries, to anything touching
extraction — and to whoever is reading this, including six months from now.
