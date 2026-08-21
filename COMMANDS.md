# PROJECT VANGUARD — Command Reference

Sixteen commands. Every option, what each output field means, and when to use
what.

**Authority:** descriptive. `PROJECT_VANGUARD_DIRECTIVE.md` governs behaviour.

---

## Contents

| Group | Commands |
|---|---|
| [Setup and health](#setup-and-health) | `boards` |
| [Getting vacancies in](#getting-vacancies-in) | `run` · `paste` · `adverts` · `rescore` |
| [Looking at results](#looking-at-results) | `todo` · `review` · `score` · `stats` · `diagnose` · `evidence` |
| [Deciding](#deciding) | `session` · `approve` · `reject` · `resolve` · `override` · `draft` · `apply` · `dispatch` |
| [Accounts](#accounts) | `registrations` |
| [Responses](#responses) | `poll` · `responses` · `funnel` · `mail` · `dormant` · `feedback` · `interview` · `interviews` |
| [Operations](#operations) | `logs` · `archive` |
| [What grows](#what-grows-and-what-does-not) | Which files accumulate, and when to act |

---

## Step-by-step guides

This document is the reference — what each command *is*. For what to *do*:

| Guide | For |
|---|---|
| `HOW_TO_ADD_A_JOB.md` | Entering one vacancy by hand |
| `HOW_TO_ADD_MANY_JOBS.md` | Entering fifty at once |
| `HOW_TO_APPLY.md` | Applying, after review |
| `HOW_TO_HANDLE_REPLIES.md` | Replies, interviews and rejections |
| `HOW_TO_USE_REPOSITORY_EVIDENCE.md` | Finding CV evidence in your repositories |
| `SOP.md` | The daily, weekly and monthly routine |

---

## Conventions

**Two execution contexts.** `run` is autonomous — it never blocks, never
prompts, and exits when done. Everything else is interactive, where waiting
for you is correct.

**Vanguard never transmits.** No command sends an email or submits an
application. `dispatch` records that *you* did; `feedback` drafts text for you
to send yourself.

**Accessibility.** Presentation adapts to the terminal, and status is always
shown as a **symbol and a word** — never colour alone. Nothing in the output
depends on distinguishing red from green.

| Flag | Environment | Effect |
|---|---|---|
| `--plain` | `VANGUARD_PLAIN=1` | No colour, boxes or symbols. Emits **zero** escape sequences — for screen readers, logs and pipes |
| `--no-color` | `NO_COLOR=1` | Colour off; symbols and words remain |
| `--ascii` | `VANGUARD_ASCII=1` | ASCII instead of Unicode box drawing |
| `--high-contrast` | `VANGUARD_CONTRAST=high` | Drops dim styling, which is unreadable on many themes |
| `--width N` | — | Override detected terminal width |
| `--log` / `--no-log` | — | Override the logging setting in `boards.yaml` for one invocation |

Plain mode is applied automatically when output is not a terminal, and
`TERM=dumb` degrades to monochrome ASCII.

**Status symbols**

| Symbol | ASCII | Meaning |
|---|---|---|
| `●` | `*` | Good — ready, passed |
| `◐` | `!` | Needs attention |
| `○` | `x` | Blocked or terminal |
| `▸` | `>` | Informational |
| `·` | `.` | Secondary detail |

**Shared options.** `--db` (default `data/vanguard.db`), `--cv`
(`data/canonical_cv.md`), `--aliases` (`config/alias_table.yaml`), `--boards`
(`config/boards.yaml`). Change these only to work against alternate files.

**`--no-model`** forces the lexical fallback instead of MiniLM. Faster, and
markedly worse — it cannot see synonyms. Useful for a quick structural check,
not for real scoring. Runs record which was used.

---

# Setup and health

## `vanguard boards`

Registry status and credential check. Run this first, and whenever a run
returns less than expected.

```bash
vanguard boards
```

```
10 registered   4 enabled   1 automatable   3 manual

ok  reed                 api_official  api key present, tier 1 api_official
--  adzuna               manual        manual adapter — no endpoint...
```

**Reading it:**

| Field | Meaning |
|---|---|
| `ok` / `--` | Reachable, or not — the detail says why |
| `registered` | Boards in `boards.yaml`, enabled or not |
| `enabled` | Boards the pipeline will consider |
| `automatable` | Boards `run` will actually poll |
| `manual` | Boards requiring `vanguard paste` |

**Why a board may be manual.** Two different reasons. *Terms* — LinkedIn
prohibits automated collection. *Capability* — Adzuna caps descriptions at 500
characters, too little to extract requirements from. Both end in paste; the
`supplies_full_text` flag distinguishes them.

---

# Getting vacancies in

## `vanguard run`

Fetch, rank, hydrate, score, queue, exit. The autonomous command.

```bash
vanguard run
vanguard run --title "data scientist" --location "Manchester"
```

| Option | Effect |
|---|---|
| `--title` | Query keywords. **Currently overridden by `boards.yaml`** — see B-01 |
| `--location` | Query location. Same caveat |
| `--no-model` | Lexical fallback |

**What happens, in order:**

1. **Ingest** — polls automatable boards, deduplicates across sources
2. **Rank** — one embedding per vacancy, no API call
3. **Filter** — drops anything below `rank_floor`
4. **Hydrate** — fetches full advert text for survivors only
5. **Score** — extract requirements, compute coverage, classify gaps
6. **Queue** — writes a record, exits

**Reading the output:**

```
collected 45 -> kept 42 (3 duplicate(s) logged)
  INCOMPLETE — 3 truncation(s):
    reed for 'data scientist': stopped at 15 — board reported 3925 total
rank filter: 31 of 42 above 0.25 (11 not hydrated or scored)
scoring 31 vacanc(ies) [minilm] gate 0.60
  PENDING      C=0.700 ceiling=0.800  Machine Learning Engineer
  FLAGGED      C=0.000 UNRELIABLE   Finance Business Partner
```

| Line | Meaning |
|---|---|
| `collected -> kept` | Fetched, then after deduplication |
| `INCOMPLETE` | More vacancies existed than were taken. Not an error — the cap doing its job |
| `skipped — posted more than N days ago` | Stale vacancies dropped before hydration. Tune `max_days_old` in `boards.yaml` |
| `skipped — closing date already passed` | Expired vacancies dropped before hydration |
| `rank filter` | How many survived the cheap pre-filter |
| `[minilm]` | Which embedder produced these numbers |
| `gate 0.60` | The coverage threshold in force |
| `C=` | Coverage — matched requirements ÷ total requirements |
| `ceiling=` | Best coverage achievable if every Type 3 gap stays unmet |
| `UNRELIABLE` | Not measured. Too few requirements, or partial advert text |

**Why hydration is deferred.** Each full advert costs one API call against 60
per hour. Ranking first means the budget goes to plausible vacancies rather
than whatever the search returned first.

---

## `vanguard paste`

Ingest a vacancy by hand, then score it identically.
*Step by step: `HOW_TO_ADD_A_JOB.md`.*

```bash
vanguard paste --file advert.txt --employer "Acme" --url "https://..."
vanguard paste --board adzuna --file advert.txt
cat advert.txt | vanguard paste
```

| Option | Effect |
|---|---|
| `--file` | Advert text. Reads stdin if omitted |
| `--url` | Vacancy URL, stored for the archive |
| `--board` | Registry id to attribute it to. Default `linkedin` |
| `--employer`, `--title` | Override anything parsed from the text |

**This is not a fallback.** Tier 3 boards are permanent architecture. LinkedIn
is likely the densest source of relevant senior roles and can never be
automated. Everything downstream — scoring, gap classification, drafting,
queueing — runs identically on a pasted advert.

Paste the **whole** advert including the requirements section. A truncated
paste produces the same problem as an unhydrated fetch.

---

# Looking at results

## `vanguard adverts`

A watched folder of pasted adverts, ingested in one pass.
*Step by step: `HOW_TO_ADD_MANY_JOBS.md`.*

```bash
vanguard adverts list                                   # what is there
vanguard adverts register --template                    # CSV of unregistered files
vanguard adverts register --from-csv adverts\to_register.csv
vanguard adverts add job.txt --employer "Acme" --url "https://..."
vanguard adverts check                                  # rule breaches
vanguard adverts check --fix                            # drop dead entries
vanguard adverts ingest                                 # score and queue them all
vanguard adverts ingest --dry-run --move-to done\
```

**Why it exists.** At seventy adverts a day, `vanguard paste` one file at a
time is the bottleneck. This registers provenance once, then ingests the lot.

### What makes an entry valid

Four conditions. Fail any one and the file is skipped.

| | |
|---|---|
| **Filename** | The primary key. Plain name, no path separators, no Windows-unsafe characters, a text suffix. `.txt.txt` is rejected — Notepad appends an extension when the save type is not All Files |
| **Employer** | Required. Placeholders (`unknown`, `n/a`, `tbc`) are refused: if the employer is unknown, the advert should not be in the folder |
| **URL** | Required, a real `http(s)` address. Without it the advert cannot be found again from the record |
| **The file** | Must exist and be non-empty |

```yaml
# adverts/manifest.yaml
acme-ml-engineer.txt:
  employer: Acme Analytics
  url: https://www.linkedin.com/jobs/view/1234567890/
  added_at: 2026-08-12T10:00:00+00:00
  board: linkedin
```

Employer and URL live in the manifest, not in the advert text — you should not
have to edit a pasted advert to record where it came from.

### What is enforced, and what is not

**Nothing can prevent a file being dragged into the folder.** No such hook
exists without a filesystem driver, and that does not belong in this project.

What *is* enforced: a file with no valid entry is **never ingested**. It is
reported and skipped. The folder may be polluted; the pipeline will not act on
it.

### Lifetime

An entry is valid only while its file exists. `check --fix` drops entries whose
file has gone. It **never deletes an advert** — removing your data because a
record is missing would be the wrong failure.

### Options

| Command | Option | Effect |
|---|---|---|
| `add` | `--employer`, `--url` | Both required |
| | `--board`, `--note` | Attribution and free text |
| `register` | `--template` | Write a CSV of unregistered files to fill in |
| | `--from-csv` | Register many at once. Bad rows are reported, not fatal |
| `check` | `--fix` | Drop entries whose file has gone |
| `ingest` | `--dry-run` | Report what would be ingested |
| | `--move-to` | Move files elsewhere once ingested |
| all | `--dir` | Folder location. Default `adverts` |

One bad advert never aborts the batch — the error is logged and the run
continues.

---

## `vanguard todo`

Everything waiting on you, in the order you would act on it.

```bash
vanguard todo
vanguard todo --limit 60
```

```
APPLY TO THESE  ·  2 approved
  COVERAGE  TERMS  EMPLOYER    TITLE                      ID
     0.700  14/20  Sanderson   Machine Learning Engineer  reed:57092035
     0.650  13/20  Hyperfinity  Data Scientist            reed:57204511

  vanguard apply <ID>       what it needs, and where
  vanguard dispatch <ID>    after you have applied

STILL TO REVIEW  ·  3 pending
  ...
  vanguard session          work through them in one go

  also queued: FLAGGED 18   UNREACHABLE 12
```

**APPROVED first**, because those are decided and waiting to be applied to.
**PENDING after**, as the reviewing still to do. FLAGGED and UNREACHABLE are
counted but not listed — they are not waiting on you today.

Switching between two commands to answer *"what now?"* is friction the
operator does not need.

---

## `vanguard rescore`

Re-score stored vacancies against the current CV.

```bash
vanguard rescore --all --dry-run
vanguard rescore --all
vanguard rescore --board linkedin          # pasted vacancies only
vanguard rescore --status FLAGGED
```

| Option | Effect |
|---|---|
| `--all` | Every vacancy in the store |
| `--status` | Only records in this state |
| `--board` | Only vacancies from this board |
| `--dry-run` | Report what would be re-scored |

**Why it exists.** `vanguard run` only scores what a board returns today. A
pasted vacancy — or one a board has since delisted — keeps a score computed
against an older CV. After editing `canonical_cv.md`, those records are stale
and nothing else would notice.

**No board is contacted.** The advert text is already stored, so this spends
no API call and works offline.

**Operator decisions survive.** APPROVED, REJECTED and DISPATCHED records are
re-scored but keep their status — a CV edit does not undo a decision, and
rescoring five hundred records must not silently reopen everything already
applied to.

The report shows what actually changed:

```
CHANGED  ·  4 of 12
    WAS    NOW  STATUS                  TITLE
  0.300  0.520  UNREACHABLE -> FLAGGED  Senior Data Engineer
  0.300  0.480  DISPATCHED              Data Scientist
```

The second row improved its coverage and kept its status, which is correct.

**A filter is required.** Re-scoring the whole store silently is not something
to do by accident.

---

## `vanguard review`

The queue, or one record in full.

```bash
vanguard review                          # PENDING, strongest first
vanguard review --status FLAGGED
vanguard review reed:57092035            # one record
```

**List view** shows coverage, rank score, employer, title and id, ordered by
rank score.

**Detail view** shows everything known about one vacancy:

```
Machine Learning Engineer — Sanderson
London  60,000 - 75,000
status PENDING   type STANDARD_CV
closes 2026-09-30

C=0.700  ceiling=0.800  S=0.392  14/20 terms  [minilm]

unmet (6):
  Type 3  pytest
            No test suite exists in the operator's employment history...
  Type 1  orchestration

history:
  2026-08-09T18:19:07+00:00  - -> PENDING
```

| Field | Meaning |
|---|---|
| `C` | Coverage |
| `ceiling` | Attainable coverage with Type 3 gaps excluded |
| `S` | Rank score. Orders the queue; **never gates** |
| `14/20 terms` | Matched requirements out of total |
| `Type 1` | Evidenced but unstated — you may confirm and add it |
| `Type 2` | Evidenced under different wording |
| `Type 3` | **Not evidenced. No CV edit permitted** |
| `not scored:` | Extraction refused. The reason and headings found are shown |

---

## `vanguard score`

Score one advert without touching the database.

```bash
vanguard score --advert advert.txt
```

No queue record, no persistence. For checking a vacancy before deciding
whether to ingest it, or for testing changes to the CV or alias table.

Reports coverage, submission type, gap counts, and lists Tier C exclusions
with their reasons.

---

## `vanguard stats`

Distribution across everything scored — the recalibration input.

```bash
vanguard stats
```

```
queue: FLAGGED 524  PENDING 1  UNREACHABLE 18
vacancies: 543   scored: 543

coverage  min 0.000  median 0.143  max 0.700
at or above 0.94: 0/543
(29 more logged applications before the 0.94 threshold can be revisited)

most frequently unmet:
   31x  pytest
   28x  AWS
```

| Option | Effect |
|---|---|
| `--storage` | Row counts, database size, and a projection at 75 vacancies/day |

**The unmet list is the useful part.** A requirement appearing 31 times is a
standing skills gap, not a scoring artefact. That is career information, not
software output.

---

## `vanguard evidence`

Propose CV bullets from work in your own repositories.
*Step by step: `HOW_TO_USE_REPOSITORY_EVIDENCE.md`.*

```bash
vanguard evidence --repo C:\path\to\project --all-gaps
vanguard evidence --repo https://github.com/you/project --all-gaps
vanguard evidence --repo . --repo github.com/you/other --vacancy reed:57092035
```

| Option | Effect |
|---|---|
| `--repo` | A local path **or a repository URL**. Repeat for several |
| `--shallow` | Clone only recent history. Faster, but loses the commit span |
| `--vacancy` | Match against one vacancy's unmet requirements |
| `--all-gaps` | Match against every recurring unmet requirement |

### Local or remote

A path is read where it sits. A URL is **cloned to a temporary directory,
scanned, and the clone removed** — nothing is left behind.

```
--repo .                                   local
--repo C:\Users\USER\project              local
--repo https://github.com/you/project      cloned
--repo github.com/you/project              cloned, https:// assumed
--repo git@github.com:you/project.git      cloned over SSH
```

**Private repositories work** if your git credentials already do — a
credential helper, an SSH key, or a token in the URL. Vanguard never asks for
credentials and never stores them.

A full clone by default, because **the commit span is part of the evidence**:
sustained work over two years is a different claim from a weekend, and a
shallow clone cannot tell them apart. `--shallow` trades that for speed.

One unreachable repository does not stop the others.

**A repository evidences only what was built.** It can supply a **Type 1**
gap — something genuinely done but absent from your CV's wording. It cannot
supply a **Type 3** gap: AWS is not evidenced by a repository that never
touched AWS, however thoroughly it is mined.

So this recovers unstated claims, never absent ones. A vacancy at 0.20
demanding cloud platforms stays at 0.20.

### Own repositories only

Attribution has to be certain. Scoring anyone else's public repository carries
a coverage bias — public repositories favour open-source contributors and
permissive employers, while most enterprise work sits behind a firewall.

### What counts as evidence

Not commit counts. A thousand commits may be careful iteration or committing
every save, and frequency is not competence.

**Artefacts** count: a test suite evidences testing, a Dockerfile evidences
containerisation, a CI workflow evidences CI. Each had to be built and made to
work. A single incidental file does not — one Dockerfile among two hundred
Python files is a detail; twenty test files are a test suite.

Dependency trees are never scanned. Counting `site-packages` would evidence
competencies nobody demonstrated.

### Every proposal needs your confirmation

The scanner can see that a test suite exists. It cannot know whether you wrote
it, or whether you could defend it under questioning.

The command asks, of each proposal:

- Did I build this, or did someone else?
- Could I answer three follow-up questions without inventing anything?
- Which system, what period, what actually happened?

**If you hesitate, it is not a Type 1 gap.** It stays unmet.

> **A worked example.** Run against the Vanguard repository itself, this
> proposes a bullet for `pytest` — 25 test files, genuine evidence. It should
> be rejected: the assistant wrote those tests, not the operator. The evidence
> is real and the claim would not be. That is the confirmation step doing its
> job, not the scanner failing.

Nothing is written to the CV. You edit `data/canonical_cv.md` by hand, then
re-score.

---

## `vanguard diagnose`

Why adverts refuse, and what their headings say.

```bash
vanguard diagnose
vanguard diagnose --limit 40
```

```
parsed 31 advert(s): 20 yielded requirements (65%), 11 refused

refusal reasons:
    8x  no_requirement_heading
        advert has headings, but none matched the requirement phrase list

unrecognised headings — candidates for classify_heading():
    4x  Machine Learning Engineer
    3x  Location:
```

| Refusal | Meaning |
|---|---|
| `no_requirement_heading` | Headings found, none recognised as requirements |
| `no_headings_at_all` | Continuous prose, no structure |
| `empty_requirement_section` | Heading recognised but carried no content |
| `not_html_no_sections` | Plain text with no section headings |

**This is evidence, not decoration.** The first run of this command inverted
an assumption — the unrecognised headings turned out to be noise rather than
missing requirement headings, which meant the fix was to tighten detection
rather than widen classification.

---

# Deciding

All five change queue state. Illegal transitions raise rather than log.

```
PENDING     -> APPROVED | REJECTED | FLAGGED | UNREACHABLE
FLAGGED     -> PENDING | REJECTED
UNREACHABLE -> PENDING (override) | REJECTED
APPROVED    -> DISPATCHED | REJECTED
REJECTED, DISPATCHED are terminal
```

## `vanguard session`

Work through a queue one record at a time, in **one invocation**.

```bash
vanguard session                              # PENDING
vanguard session --status FLAGGED
vanguard session --status PENDING --min-coverage 0.50
vanguard session --employer Sanderson --limit 10
```

| Option | Effect |
|---|---|
| `--status` | Which state to work through. Default `PENDING` |
| `--min-coverage` | Only records at or above |
| `--employer` | Only records matching |
| `--include-unmeasured` | Include records whose coverage was never measured |
| `--limit` | Stop after this many |

**Why it exists.** Fifteen PENDING records meant thirty commands and thirty
copied ids. The decisions cannot be batched — fifteen vacancies is fifteen
judgements — but the invocations can.

Each record shows its coverage, terms, ceiling, location, salary and any
eligibility gate. Then:

```
  a approve   r reject   s skip   o show gaps   q quit
```

`q` stops immediately and **nothing after that point is touched**.

---

## Bulk operations

`approve` and `reject` accept a filter instead of an id.

```bash
vanguard reject --status UNREACHABLE --dry-run
vanguard reject --status UNREACHABLE --reason "ceiling below gate" --yes
vanguard approve --status PENDING --min-coverage 0.65 --dry-run
```

| Option | On | Effect |
|---|---|---|
| `--status` | both | Every record in this state |
| `--min-coverage` | `approve` | At or above |
| `--max-coverage` | `reject` | At or below |
| `--employer` | both | Matching this employer |
| `--include-unmeasured` | `reject` | Include never-measured records |
| `--dry-run` | both | Show what would change |
| `--yes` | both | Skip the confirmation |

**Every filtered action previews first and asks.** Nothing changes until you
confirm.

**A filter is required.** Rejecting the entire queue by accident should not be
one keystroke.

**Unmeasured records are excluded by default.** A coverage of 0.000 or 1.000
computed from one requirement should not decide a bulk action. `reject` can
include them explicitly; `approve` cannot.

**One refusal does not stop the rest.** A record in a terminal state is
reported and skipped; the others still transition.

### Where the line sits

Batching **one decision across many records** — "reject everything
unreachable" — is one judgement, and doing it fifteen times is typing rather
than thinking.

Batching **many decisions** is not available, and should not be. Approving is
where a claim gets made on your behalf. `session` exists so that fifteen
judgements cost one invocation rather than thirty.

---

## `vanguard approve <id>`

Mark ready to submit. **Only APPROVED is dispatch-eligible.**

```bash
vanguard approve reed:57092035 --note "strong on 4 of 5 criteria"
```

## `vanguard reject <id>`

Archive. Terminal.

```bash
vanguard reject reed:57204511 --reason "salary below range"
```

## `vanguard resolve <id>`

Mark a FLAGGED ambiguity resolved. Returns to PENDING for review — not
straight to approval.

## `vanguard override <id> --why "..."`

Apply despite an unreachable ceiling. **Justification mandatory.**

```bash
vanguard override reed:57204511 --why "3 of 4 sift criteria strong; SDLC gap accepted"
```

UNREACHABLE is a true finding about the gap between your CV and the role.
Overriding it is a deliberate, recorded act rather than a click.

## `vanguard draft <id>`

Draft a cover letter for one vacancy, framed to what it asks for.

```bash
vanguard draft reed:57092035
vanguard draft reed:57092035 --show
vanguard draft reed:57092035 --to "Dr Sarah Chen" --out letters\
```

| Option | Effect |
|---|---|
| `--show` | Print it instead of writing a file |
| `--to` | Addressee. Default "Hiring Manager" |
| `--out` | Where to write it. Default `out/` |
| `--name`, `--contact` | Override the CV header |

### What "framed to the vacancy" means

The opening names **what this role calls for that your CV can evidence** —
drawn from the matched requirements, in your vocabulary:

> I am applying for the Senior Data Engineer position at Ministry of Justice.
> The role calls for data visualisation, ETL and Python, and each is something
> I have built and run rather than studied.

**Not the advert parroted back.** Copying an employer's own responsibility
text at them reads as exactly what it is.

**Only matched requirements can frame it.** Claiming a role centres on
something you cannot demonstrate invites the one question you cannot answer.
Generic terms — "teamwork", "communication" — are excluded: naming them says
nothing.

### The three bullets

CV lines, chosen by how many of the vacancy's requirements each answers, with
one bullet per subject — the reporting engine appears twice in the CV, and
citing both makes one point twice.

Long bullets are shortened to whole leading sentences. The result is a strict
**subset** of the CV line: the letter may say less than the CV, never more.

### What it refuses

**A term the CV cannot evidence.** Unmet requirements never appear — a cover
letter is not the place to enumerate what you cannot do.

**A letter it cannot support.** If fewer than three CV bullets answer the
vacancy, it raises rather than padding to length. That is usually the advert
failing to parse (`vanguard diagnose`) or the role genuinely not fitting.

### Where it goes

`out\Sagacity_Data_Scientist.md` — employer and title, so a folder of letters
is readable at a glance. Where two vacancies share both, the vacancy id is
appended.

**`out/`, not `Pipeline_Archive/`.** The archive is written at dispatch. A
letter drafted for a vacancy you then decide against would otherwise leave a
folder for an application never sent.

### Then

```bash
vanguard dispatch <id> --cover-letter out\Sagacity_Data_Scientist.md
```

**Read it before you send it.** It is drafted from your CV, not written by
someone who knows what you meant.

---

## `vanguard apply <id>`

What this application needs, and where to do it.

```bash
vanguard apply reed:57092035
vanguard apply reed:57092035 --cv-pdf out\cv_anon.pdf
```

| Option | Effect |
|---|---|
| `--cv-pdf` | The CV you would submit. Default `out/cv.pdf` |

**Vanguard does not apply.** It establishes what kind of application this is,
whether you hold an account, and what you will need to hand — then gives you
the URL and stops.

Automated form-filling across arbitrary employer systems is **out of scope and
stays there**. Different templates, labels and frameworks make it unreliable,
and a form filled wrongly on your behalf is worse than no help at all.

### What it reports, in order

**Eligibility first.** A role needing clearance you do not hold is not worth
reading further, whatever the coverage score says.

**Channel** — how this vacancy is applied to:

| Type | Meaning | You need |
|---|---|---|
| `BOARD_DIRECT` | Apply on the board, upload a CV | A board account |
| `BOARD_PROFILE` | The board applies from a built profile | An account **and** a complete profile |
| `EMPLOYER_ATS` | The link goes to the employer's own system | An account on that portal |
| `UNKNOWN` | Not classifiable | To decide once; it is remembered |

Advert phrasing overrides the URL. A Reed listing saying *"apply on the
company website"* is an `EMPLOYER_ATS` application whatever the link looks
like.

**Account** — whether you are registered, from the `registrations` table.

**Pack** — submission type, whether the CV is rendered, standard or
anonymised profile, and any answers you have given before.

**The URL, and then it stops.**

---

## `vanguard dispatch <id>`

Record that **you** submitted the application, and archive what was sent.
Vanguard sends nothing.

```bash
vanguard dispatch reed:57092035
vanguard dispatch reed:57092035 --cv out\cv.pdf --cover-letter out\letter.pdf
vanguard dispatch reed:57092035 --no-archive
```

| Option | Effect |
|---|---|
| `--note` | Free text recorded on the transition |
| `--cv` | The CV PDF actually submitted. Defaults to `out/cv.pdf` if present |
| `--cover-letter` | The cover letter or essay actually submitted |
| `--cv-source` | Canonical CV markdown archived alongside the PDF |
| `--archive-root` | Where applications are archived. Default `Pipeline_Archive` |
| `--no-archive` | Record the dispatch without writing an archive |

**Why it archives.** An interview happens six weeks after dispatch. By then the
advert has been taken down and the CV has been edited. Without this there is no
record of what was actually sent.

---

# Responses

## `vanguard poll`

Read the mailbox, correlate replies to applications, classify them.
*Step by step: `HOW_TO_HANDLE_REPLIES.md`.*

```bash
vanguard poll
vanguard poll --dry-run
vanguard poll --since-days 60 --limit 200
vanguard poll --provider gmail
```

| Option | Effect |
|---|---|
| `--provider` | `imap` or `gmail`. Default from `VANGUARD_MAIL_PROVIDER`, else `imap` |
| `--since-days` | How far back to read. Default 30 |
| `--limit` | Maximum messages to fetch. Default 100 |
| `--dry-run` | Classify and report; record nothing |
| `--verbose` | Show sender addresses alongside subjects |
| `--show-uncorrelated` | List messages that matched no application |
| `--category` | Gmail tab: `primary` (default) or `all` |
| `--strategy` | `auto` (default), `targeted` or `window` |
| `--broad` | Alias for `--strategy window` |
| `--cv` | The CV whose contact address is monitored |
| `--archive-root` | Where correspondence is filed |

**Read-only.** Never sends, replies or deletes. The mailbox is opened read-only
unless `VANGUARD_MAIL_MARK_SEEN` is set.

### Gmail tabs are not IMAP folders

Primary, Promotions and Social are a display layer. IMAP sees one `INBOX`
containing all of them, so reading "the most recent 100" fills with promotional
mail and **a genuine employer reply can fall outside the window entirely**.

Two things address it:

**Category.** `category:primary` is applied by default via Gmail's `X-GM-RAW`
search, restricting to the tab where employer replies land. `--category all`
reads everything.

### Two fetch strategies

| | Targeted | Window |
|---|---|---|
| Query | `after:date category:primary {"19568" "Beatport" ...}` | `after:date category:primary` |
| Query length | Grows with applications | **Fixed** |
| Messages fetched | Few, pre-filtered | All in the window |
| Correlation | On a small set | On everything |
| Best when | Few applications | **Many applications** |

**The trade inverts with volume.** At 7 open applications a search is a real
filter — most of the inbox is irrelevant. At 500 it is a thousand-term query
narrowing almost nothing, and it runs into IMAP command length and Gmail's own
query limits.

`auto` switches at `window_threshold` in `boards.yaml`, default 40. That number
is an **estimate, not a measurement** — 40 applications is roughly 80 search
terms, still a short query, but the right value depends on how much
non-application mail arrives in the monitored tab.

```yaml
defaults:
  mail:
    strategy: auto           # auto | targeted | window
    window_threshold: 40     # ESTIMATE. Revisit with real volume
```

**Every run states which strategy it used and why.** A silent switch would be
invisible, and a change in behaviour with no stated cause is exactly the
failure this project keeps finding.

Neither applies to non-Gmail providers, which fall back to a plain `SINCE`
search.

**The address follows the CV.** An employer replies to whatever address the CV
gave them, so it is derived from `canonical_cv.md` rather than configured
separately — configuring it twice lets the two drift, and the symptom is
replies that never correlate.

### Credentials

In `.env`, never in a tracked file.

```
VANGUARD_MAIL_PROVIDER=imap
VANGUARD_MAIL_HOST=            # inferred for gmail, outlook, yahoo, icloud
VANGUARD_MAIL_USER=you@example.com
VANGUARD_MAIL_PASSWORD=        # APP PASSWORD, never the account password
VANGUARD_MAIL_FOLDER=INBOX
VANGUARD_MAIL_SINCE_DAYS=30
```

**Use an app password.** Most providers refuse the account password over IMAP
once two-factor authentication is on, and an app password can be revoked
without changing the account.

- Gmail: `myaccount.google.com/apppasswords`
- Outlook: `account.microsoft.com/security`

### Gmail API instead

```
VANGUARD_MAIL_PROVIDER=gmail
VANGUARD_MAIL_TOKEN=secrets/gmail_token.json
```

Needs a Google Cloud project with the Gmail API enabled and an OAuth client.
Scope is `gmail.readonly` — the pipeline cannot send or delete even if
something later asks it to. More secure, more setup.

### Several mailboxes

Where different CVs carry different addresses, configure each with its own
prefix: `VANGUARD_MAIL_*`, `VANGUARD_MAIL2_*`.

---

## `vanguard mail`

Correlate and classify one message from a file. `poll` does this for a whole
mailbox; this is for a message you have saved by hand.

```bash
vanguard mail --file reply.txt --sender "recruit@company.com" --subject "Your application"
```

**Correlation runs first**, matching by application reference, then sender
domain, then employer plus title in the subject. An uncorrelated message is
queued for review and **never classified** — guessing which application it
belongs to would attach a decline to the wrong vacancy.

### Correlation stages

Four, strongest first. A message that matches none is reported and **never
classified** — guessing which application a message belongs to would attach a
decline to the wrong vacancy.

| Stage | Matches on | Example |
|---|---|---|
| `thread` | **An ATS routing token, or a reply to a message already correlated** | `job+…+124894@app.bamboohr.com` |
| `reference` | The vacancy reference in the text | "Regarding vacancy 19568" |
| `sender_domain` | Sender domain is the employer's | `careers@beatport.com` |
| `ats` | Applicant-tracking system, employer named in the subject | `no-reply@ashbyhq.com`, "Thank you for applying to Sardine" |
| `fuzzy` | Employer and title in the subject, from a plausible sender | `hiring@beatport-talent.com` |
| `ambiguous` | **Several applications matched equally well** | Two live applications at one employer, and nothing to tell them apart |

**Ambiguity is reported, never guessed.** With two live applications at the
same employer and a reply carrying no reference and no distinguishing title,
the system names both and leaves the message queued. Attaching an interview
invitation — or a rejection — to the wrong vacancy is worse than leaving it
for you.

A later stage may still resolve it: the sender domain identifies the employer,
and the subject may identify which vacancy. Where one job title contains
another, the longer and more specific one wins.

**A routing token is checked before anything else.** An applicant-tracking
system puts a per-application identifier in `Reply-To`:

```
dc4+job+4e1f51283c7290391212f9eb552404910f3514d0+124894@app.bamboohr.com
```

`124894` is the vacancy and the hex string the application. **Every message
about that application carries it, whatever the subject says.** A subject
reading "A quick note from Rob" — no employer, no title, no applied-phrase —
correlates on the token alone.

This outranks every other stage because it is the only one that is not
inference. Everything below reads wording and guesses; the header states the
answer.

**Vendor-agnostic, judged by shape.** Every ATS embeds an identifier and they
all differ:

| | |
|---|---|
| BambooHR | `dc4+job+<40 hex>+124894@app.bamboohr.com` |
| Lever | `<uuid>@hire.lever.co` |
| Greenhouse | `no-reply+<24 hex>@greenhouse.io` |
| Ashby | `no-reply+<24 mixed-case>@ashbyhq.com` |
| Workday | `reply-2847193@myworkdayjobs.com` |

A token qualifies on shape rather than on a per-vendor pattern, so a system
Vanguard has never seen still works: a UUID, sixteen or more hex characters,
five or more digits, or twenty or more mixed alphanumerics containing a digit.

UUIDs are matched whole before anything is split — splitting on `-` turned
Lever's identifier into five useless fragments.

Words that identify nothing are excluded outright. `careers`, `noreply` and
`bewerbung` pass any length test and would correlate every message an
employer ever sent.

**Thread correlation runs next.** Every other stage is tuned for machines —
a reference, an employer domain, an applied-phrase, an employer-plus-title
subject. A human writing *"Re: next steps"* from a personal address matches
none of them, while replying to a message the system has already correlated.

Matched on `In-Reply-To` and `References`, falling back to the subject with
reply prefixes stripped. A subject under twelve characters cannot thread —
too many messages share "Re: Hi".

**A newsletter is not an acknowledgement.** A subject that both advertises
roles and mentions an application is marketing: *"Two fresh DS leads in
Edinburgh + application update"* was exempted from the broadcast filter by
"application update", correlated on the sender domain, classified PROGRESS,
and reached round five of an interview process that never existed.

**The ATS stage requires applied-language.** An acknowledgement and a job
advert are both third parties naming an employer; the difference is intent,
and it is visible in the subject. "Thank you for applying at X" correlates;
"apply now to X" does not.

| State | Meaning |
|---|---|
| `DECLINE` | Application closed unsuccessfully |
| `OFFER` | The role was offered. Terminates the interview process |
| `PROGRESS` | Interview, call, assessment or further information requested |
| `ACK` | Receipt only, no decision |
| `QUERY` | A question needing a human answer |
| `ADMIN` | Logistics, no decision |
| `AMBIGUOUS` | Nothing fired. Review manually |

**DECLINE is checked before PROGRESS, deliberately.** Rejection emails open
warmly — *"we were very impressed"*, *"we'd like to keep your details"*.
Checking progress first would read a large share of rejections as invitations.

No classification triggers an outbound action. The output suggests a template;
invoking it is your choice.

## `vanguard dormant`

Applications silent past `silence_days` — 21 by default, 30 for public sector.

```bash
vanguard dormant
```

DORMANT is **derived state, not a classification**. Silence is an absence of
information, not a rejection. It never triggers a feedback request, because
employers do go quiet and return.

## `vanguard responses`

Replies that correlated to an application, and what they were.

```bash
vanguard responses
vanguard responses --status DECLINE
vanguard responses linkedin:c56f76c4cbf8a346    # read the messages themselves
```

| Option | Effect |
|---|---|
| `--status` | `ACK`, `PROGRESS`, `DECLINE`, `OFFER`, `QUERY`, `ADMIN`, `AMBIGUOUS` |
| `--limit` | How many to show. Default 40 |

**Why it exists.** Classifications were written to the archive as files and to
the interview process, but nothing was queryable — you could not ask *"what
has been rejected?"*, which is exactly what `vanguard feedback` needs to know.

```
RESPONSES  ·  3
  STATE     WHEN        EMPLOYER  SUBJECT                 ID
  DECLINE   2026-08-18  Sagacity  Your application        reed:0
  ACK       2026-08-18  Beatport  Thank you for applying  reed:1
  PROGRESS  2026-08-18  Harnham   Interview invitation    reed:2
```

### Reading one

Pass a vacancy id and the messages are printed in full — sender, subject,
classification, and the body.

**`AMBIGUOUS` exists so a human reads the message.** Reporting that one
arrived without being able to show it left nowhere to go, and the archive
holds a copy only where the vacancy was dispatched.

Bodies are truncated at 8,000 characters: a reply is a few hundred words, and
quoted threads and marketing footers add megabytes without adding
information.

**A message recorded before bodies were kept fills one in on the next
`vanguard poll`**, provided it is still in the mailbox. A body already stored
is never overwritten — employers do edit and resend, and the first version is
the one that was acted on.

Records are kept after a terminal state. A rejection followed by an
administrative message is worth being able to see.

---

## `vanguard feedback <id>`

Draft a feedback request after a decline.

```bash
vanguard feedback reed:57092035 --name "Your Name" --contact "you@example.com"
vanguard feedback reed:57092035 --name "..." --contact "..." --recipient "Sarah Chen"
```

| Option | Effect |
|---|---|
| `--name` | Your name, for the signature. Required |
| `--contact` | Email or link, for the signature. Required |
| `--recipient` | Addressee. Defaults to "Recruitment Team" |
| `--force` | Draft anyway, for a rejection that arrived by phone or portal |

Prints a draft. **You review and send it.**

**Requires a recorded DECLINE.** Asking for feedback on a decision nobody made
is worse than silence. This was documented from the start and only enforced on
19 Aug 2026 — the state had been hardcoded, so any vacancy id produced a
letter.

Find one with `vanguard responses --status DECLINE`. Where the rejection came
by phone or through a portal there is no classified message, and `--force`
covers that.

## `vanguard funnel`

Where applications get to, and where they stop.

```bash
vanguard funnel
vanguard funnel --reasons
```

```
FUNNEL  ·  9 application(s) dispatched
  STAGE        REACHED  ENDED
  Application        9      4  ################ 9/9 (100%)
  Screen             2      —  ####------------ 2/9 (22%)
  Assessment         2      1  ####------------ 2/9 (22%)
  Panel              1      —  ##-------------- 1/9 (11%)

  offers           —
  still live       3
  no reply at all  1

WHY
  1 of 5 rejection(s) gave a reason

  Theta  (ended at assessment)
      We are looking for someone with more experience in Spark.

  The other 4 gave none, and none is inferred.
```

**Every rejection used to look alike.** Rejected on the CV and rejected after
a final panel were the same state, and they mean opposite things — the second
says the CV worked and something later did not.

### Stages are inferred from the invitation

`SCREEN`, `ASSESSMENT`, `INTERVIEW`, `PANEL`, `FINAL`. Employers name what
they are inviting you to, and the vocabulary is small. Where one names
nothing, `UNKNOWN` — a guess would put the application at the wrong depth,
and the shape is the output that matters.

### Outcomes are inferred from what follows

An invitation to a later stage means the earlier one was passed. A decline
means the current stage was failed. **Silence means neither**, and stays
pending rather than being counted as a rejection.

### Reasons are never inferred

This is the line that matters. A stated reason is extracted **verbatim** and
labelled as stated; where none is given, the record says so.

Softeners are excluded. *"We had many strong applicants"* says nothing about
your application, and recording it as a reason would fill the register with
noise that reads as insight.

**The answer is in the shape, not in any single message.** Twelve of twenty
ending at CV stage tells you more about why than any rejection email will.

---

## `vanguard interviews`

Interview processes, across all their rounds.

```bash
vanguard interviews                       # active processes
vanguard interviews --all                 # closed ones too
vanguard interviews reed:57092035         # one process in full
vanguard interviews reed:57092035 --withdraw "accepted another role"
```

| Option | Effect |
|---|---|
| `--all` | Include closed processes |
| `--withdraw` | Close a process, with a reason |

**A process opens on the first PROGRESS** correlated to a dispatched
application, and every subsequent message attaches to it.

| Message | Effect |
|---|---|
| `PROGRESS` | Opens a new round |
| `ADMIN`, `QUERY`, `ACK`, `AMBIGUOUS` | Attach to the current round |
| `OFFER` | **Closes** the process |
| `DECLINE` | **Closes** the process |
| operator `--withdraw` | **Closes** the process |

**Nothing else closes one.** Not silence, not an administrative message.
Employers go quiet between rounds and return, so dormancy is never an outcome.

A message arriving after closure is recorded and changes nothing — a rejection
must not reopen because a mailing list mentions the company afterwards.

**Rounds drive the rehearsal.** Template E has three phases: CV claims, a
runtime case study, an executive behavioural test. The process suggests the
phase matching the round you are entering.

---

## `vanguard interview <id>`

Three-phase mock interview, generated from the CV you actually submitted.

```bash
vanguard interview reed:57092035 --phase 1
vanguard interview reed:57092035 --phase 3
```

| Phase | Focus | Graded on |
|---|---|---|
| 1 | CV claims verification | D1–D4 (max 12) |
| 2 | Runtime case study | D1–D4 (max 12) |
| 3 | Executive behavioural | D1–D5 (max 15) |

**Dimensions**, scored 0–3 with behavioural anchors:

| | | Pass line |
|---|---|---|
| D1 | CV grounding — traceable to the submitted CV | 2 |
| D2 | Quantification — figure, baseline, method | 2 |
| D3 | Constraint awareness — limits and their effect | 2 |
| D4 | Decision justification — alternatives rejected on stated grounds | 2 |
| D5 | Narrative structure — Phase 3 only | 2 |

**D1 = 0 is terminal.** An unsupported claim cannot be rescued by good
reasoning, and catching it here is cheaper than a panel catching it.

Never compare a Phase 3 total against a Phase 1–2 total — different ranges.

---

# Typical sessions

**Daily**

```bash
vanguard run
vanguard review
vanguard review <id>
vanguard approve <id>
```

**A vacancy found by hand**

```bash
vanguard paste --file advert.txt --employer "Acme" --url "https://..."
vanguard review --status PENDING
```

**A reply arrives**

```bash
vanguard mail --file reply.txt --sender "..." --subject "..."
vanguard interview <id> --phase 1     # if PROGRESS
vanguard feedback <id> --name "..." --contact "..."   # if DECLINE
```

**Weekly**

```bash
vanguard stats
vanguard diagnose
vanguard dormant
```

---

# Tuning

Both thresholds live in `config/boards.yaml` under `defaults`. Changing them
needs no code change.

```yaml
defaults:
  coverage_gate: 0.60    # ratchet upward as the CV strengthens
  rank_floor: 0.25       # below this, not hydrated or scored
```

**Record the reason beside the number when you move it.** A gate raised
because the queue felt crowded is not filtering — it is narrowing the field to
match what you already believed.

```yaml
# 0.60 -> 0.65, 15 Sep 2026: added test-suite evidence to the CV;
# three vacancies that previously blocked on testing now resolve.
coverage_gate: 0.65
```

---

# Troubleshooting

| Symptom | Cause |
|---|---|
| `vanguard` not recognised | Re-run `pip install -e ".[dev]"` |
| Board shows `--` with a credentials message | Missing from `.env` |
| `no vacancies` | No automatable board configured, or all filtered out |
| Many `UNRELIABLE` | Advert structure unrecognised. Run `vanguard diagnose` |
| `RateLimitExceeded` | Reduce `max_results` in `boards.yaml` |
| `illegal transition` | The state machine refused. The message names what is permitted |
| `AnonymisationError` | Identifying content survived into a document that must not carry it. The message names what leaked |
| `permission denied` writing a PDF | The file is open in a viewer |
| `cannot load library 'libgobject-2.0-0'` | GTK3 runtime missing — see README |

---

# Operations

## `vanguard logs`

Run history and recorded errors.

```bash
vanguard logs                  # last 10 runs plus recent errors
vanguard logs --limit 30
vanguard logs --errors         # only runs that failed
vanguard logs --archive        # move old records aside
```

| Option | Effect |
|---|---|
| `--limit` | How many runs to show. Default 10 |
| `--errors` | Only runs with failures |
| `--archive` | Move records past the retention window to `archive.db`, gzip old log files. **Nothing is deleted** |

**Two stores, holding different things.**

| | Contents | Bounded by |
|---|---|---|
| **Database** | One row per run, one per error. Started, duration, counts, what failed | What is worth querying — a year of daily runs is a few thousand rows |
| **File** | Every API call, swallowed exception, rate-limit wait | Rotation |

`vanguard logs` reads the database. The file holds the API-level detail and
lives in the configured directory.

**Rotation is hybrid, time-led.** A new file at each midnight, because runs are
daily and *"yesterday's run is in yesterday's file"* is how it will actually be
read. `max_bytes` is a backstop so a runaway loop cannot fill the disk between
midnights.

**Nothing is ever deleted.** Database rows past `archive_after_days` move to
`archive.db`; files past `retain_days` are gzipped in place and remain readable
with `zgrep`. Deleting the record of how the system behaved destroys the
evidence for the next question, which is usually one nobody anticipated.

**Why this matters.** `collect()` and `hydrate_many()` catch exceptions so one
bad vacancy cannot abort a run. Without logging, the reason is lost with the
terminal — the Adzuna 401 and the 503 encountered on 9 August left no record at
all.

### Configuration

In `config/boards.yaml` under `defaults`. **Recommended on.**

```yaml
defaults:
  logging:
    enabled: true
    level: INFO              # DEBUG for API-level detail
    directory: logs
    rotate_hours: 24
    max_bytes: 10485760      # 10 MB backstop
    retain_days: 30          # then gzipped, not removed
    archive_after_days: 180  # then moved to archive.db, not removed
    to_database: true
    to_file: true
```

Override for a single invocation with the global `--log` / `--no-log` flags.


## `vanguard archive`

What was submitted, and when.

```bash
vanguard archive                    # every application, newest first
vanguard archive reed:57092035      # one application in full
vanguard archive --limit 50
vanguard archive --root elsewhere
```

| Option | Effect |
|---|---|
| `--root` | Archive location. Default `Pipeline_Archive` |
| `--limit` | How many applications to list. Default 20 |

### Layout

```
Pipeline_Archive/
└── Ministry_of_Justice/
    └── 20260812T1015_reed-57092035/
        ├── 20260812T1015_Job_Specs.txt
        ├── 20260812T1015_Optimized_CV.md
        ├── 20260812T1015_Optimized_CV.pdf
        ├── 20260812T1015_Cover_Letter.pdf
        ├── 20260812T1015_Answers.json
        └── manifest.json
```

**A subfolder per vacancy, not per employer.** Applying to one employer twice
would otherwise produce files with the same timestamp prefix and no way to tell
which application either belonged to.

`manifest.json` records the vacancy id, reference, submission type, coverage,
ceiling and which embedder produced them — so a score can be explained months
later.

Correspondence is filed alongside the application it concerns: acknowledgements,
interview invitations and rejections land in the same folder.

**Written at dispatch, not at approval.** Approval means eligible for dispatch,
not submitted. Archiving at approval would create folders for applications never
sent.


---

# WHAT GROWS, AND WHAT DOES NOT

Measured at 75 vacancies in one batch, not estimated.

| File | Created | Grows? | Bounded by |
|---|---|---|---|
| `data/vanguard.db` | First command run | **Yes** | Nothing. ~12 KB per vacancy; ~0.3 GB/year at 75/day |
| `Pipeline_Archive/` | First `dispatch` | **Yes** | Applications actually submitted, not vacancies scored |
| `logs/vanguard.log` | First run with logging on | **No** | Rotation. New file each midnight, size cap as backstop |
| `archive.db` | First `logs --archive` | Slowly | Only records past the retention window |
| `adverts/manifest.yaml` | First `adverts add` | **No** | Files currently in the folder. Entries die with their file |
| `adverts/to_register.csv` | `adverts register --template` | **No** | Unregistered files only. Overwritten, never appended |
| `out/cv.pdf` | Rendering the CV | **No** | Replaced each render |
| `.env`, `config/*.yaml` | By hand | **No** | — |

**Only two grow without bound**, and only one is a database.

## Inside the database

| Table | Rows per vacancy |
|---|---|
| `gaps` | ~21 |
| `vacancies`, `scores`, `queue`, `transitions` | 1 each |
| `diagnostics` | 1 per scoring run |

`gaps` is the bulk. It is also the most useful table — the recurring-unmet
report comes from it.

## When to act

**Not on size.** SQLite handles multi-gigabyte databases without complaint.

The first symptom is **slower queries** — `review` and `stats` scan the whole
table. Watch for those becoming noticeable, then add indices or extend
`logs --archive` to cover vacancies.

```bash
vanguard stats --storage
```

Run it weekly during heavy use. Decide on the numbers, not on a projection.


---

# Accounts

## `vanguard registrations`

Where you hold accounts. **Asserted by you, never detected.**

```bash
vanguard registrations list
vanguard registrations set board reed.co.uk
vanguard registrations set board linkedin.com --profile-built
vanguard registrations set employer careers.acme.com --url "https://..."
vanguard registrations set board monster.co.uk --not-registered
vanguard registrations answer "What is your notice period?" "1 month"
```

| Command | Option | Effect |
|---|---|---|
| `set` | `--profile-built` | A profile is complete there, not just an account |
| | `--not-registered` | Record that you are **not** — it stops the question recurring |
| | `--url` | Where to sign in |
| | `--note` | Free text |
| `answer` | — | Record an answer to a question that keeps coming up |

### Why nothing logs in to check

Detection would need credentials for dozens of employer portals — a single
file that, if leaked, opens every account you have. Repeated automated logins
across many portals is also the pattern security systems flag as credential
stuffing, and most ATS terms prohibit automated access.

You know whether you are registered. It is one question, once per portal.

### Two scopes

**`board`** — a small fixed set: Reed, LinkedIn, Civil Service Jobs.

**`employer`** — unbounded, keyed by hostname, growing with every application
to a company running its own portal.

### Recurring answers

Notice period, salary expectation, right to work, relocation — the questions
every form asks. Recorded once and offered back on the next application.

**A recall aid, not a form-filler.** You still type it in.

Rewording is handled: *"What is your notice period?"* and *"Notice period"*
find the same answer.
