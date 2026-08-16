# PROJECT VANGUARD — Progress Report and Roadmap

**9 August 2026** · version 2, supersedes version 1 of the same date

| | |
|---|---|
| Modules | 8,111 lines, 25 files |
| Tests | **912 passing, 0 failed** |
| Documentation | 1,255 lines, 4 files |
| Register | 54 items, 8 open |
| Verified | With and without credentials configured |

---

# PART 1 — Where the project stands

## Complete and verified

**Design.** 21 defects from the specification audit, all closed. Four blocking.

**Build.** All six milestones. Render chain producing a two-page PDF with a
passing anonymisation scan. Coverage engine, alias resolution, rank scoring.
Gap taxonomy, bounded refactor, six templates. Five board adapters with
registry-driven ingestion. SQLite store, queue state machine, 16-command CLI.
Correlation, six-state classifier, dormancy.

**Live operation.** Running against Reed and Adzuna. One PENDING record — a
Machine Learning Engineer at C=0.700, ceiling 0.800.

**Diagnostics.** Every advert's parse observed: headings found, how each
classified, refusal reason, pipeline decisions. `vanguard diagnose` ranks
unrecognised headings by frequency.

**Documentation.** `COMMANDS.md` covers all 16 commands and every option, with
three tests asserting it cannot drift from the CLI.

**Presentation.** `ui.py`, stdlib only. Colour is never the only signal;
`NO_COLOR` honoured; plain mode emits zero escape sequences; Unicode capability
detected from the stream encoding rather than guessed.

## Defects found by running it — 26

Most were invisible to inspection and appeared only against real data:

| | |
|---|---|
| B-04, B-13 | Snippets scored as though they were full adverts |
| B-10 | Vacancy reference never extracted — correlation dead on arrival |
| B-11, B-12 | Pagination silently capped at one page |
| B-14 | Adzuna cannot supply enough text to assess |
| B-15 | Hydration failure swallowed; 240 of 300 scored on snippets |
| B-17, B-20 | HTML unread; duties and benefits counted as requirements |
| B-18 | Per-board result cap inert |
| B-21 | Score history multiplied queue rows twentyfold |
| B-23 | Flat fallback produced confident wrong numbers |
| B-25 | Heading detector tightened, then **reverted** — it rejected real headings |
| B-26 | Queue printed coverage figures that were never measured |

## Calibration — measured, not authored

**P-01 was 0.94.** Of 43 vacancies, zero reached it, and the best genuine fit
had a ceiling of 0.800 — structurally incapable of passing. Now **0.60**, on
the operator's ratchet ruling. Both thresholds live in config.

---

# PART 2 — What remains

## Open in the register — 8

| ID | Item | Blocked on |
|---|---|---|
| **B-17 / D-03** | ~35% of adverts have no recognised requirement heading | More adverts |
| **B-25** | Heading detector reverted; noise headings tolerated | Cosmetic; reopened after the revert |
| **B-03** | `ingest()` has no board filter | Low value |
| **B-09** | Near-duplicate requirements survive dedup | Low value |
| **C-02** | `data engineer` excluded from search keywords | Operator ruling |
| **O-01** `/Pipeline_Archive/` path · **O-02** §5 bound to ROUTE 4 · **O-03** repo vs project authority | Applied by inference, never confirmed | Operator ruling |
| **S-05** | Redacted CV needed before any public release | Only if publishing |

## Deferred by ruling

**D-01** adaptive query configuration · **B-01/B-02** folded into it

## Awaiting evidence

| Parameter | Current | Trigger |
|---|---|---|
| P-01 coverage gate | 0.60 | 30–40 logged applications |
| P-02 MiniLM threshold | 0.75 | Soft-hit review history |
| P-03 Type 1 floor | 0.45 | Gap-classification history |
| P-04 `silence_days` | 21 / 30 | Real response times |
| P-06 Template F | — | A second Success Profile advert |

## Not built

**N-01** NHS Jobs · **N-02** Find a Job — both blocked on external access.

**Built since this document was written:** N-06 mailbox polling, N-07 archive,
N-08 batch ingestion, N-09 multi-round interview tracking, N-10 repository
evidence loop. **Phase 2 A and B are complete**; C is next. See
`docs/PHASE_2.md`.

## Cosmetic

Two column-alignment issues in the queue list and result summary. Ten lines.
Seen and left by operator ruling.

---

# PART 3 — Dependencies: the standing position

Every third-party library considered so far has been **declined in favour of
the standard library**, and each decision has a trigger that would reverse it.

| Library | Considered for | Decision | Would be justified by |
|---|---|---|---|
| `beautifulsoup4` | DOM parsing | Declined — `html.parser` sufficed | A run of `no_headings_at_all` refusals on adverts that visibly have structure |
| `lxml` | Faster, stricter parsing | Declined | Only alongside BeautifulSoup |
| `html5lib` | Browser-spec recovery | Declined | Systematically malformed markup from a new board |
| `rich` | Terminal UI | Declined — `ui.py` works | Nothing foreseen |

**Why the bar is high.** Each dependency is installation risk on the
operator's machine, and none can be tested in the environment where the code
is written — which is how the render CSS needed three correction rounds.

**On BeautifulSoup specifically.** It would bring CSS selectors (some boards
mark requirement blocks with a class), table handling, and better malformed-
markup recovery. None of those addresses the current failure: the refusals are
`no_requirement_heading`, which is *classification*, not parsing. A better
parser fixes none of them. `vanguard diagnose` is the instrument that would
show the picture changing.

---

# PART 4 — Roadmap

Definition **A — operational**: the tool reliably supports the job search.

## PHASE 1 — Use it

**Effort: none. Duration: 2–4 weeks.**

Everything in Phase 2 is blocked on evidence this phase produces. Building
before it exists is what put a 0.94 gate on an unreachable metric, designed
extraction against a single advert, and produced a heading fix reverted within
the hour.

- [ ] Review the PENDING record; apply if it fits
- [ ] Paste LinkedIn and Adzuna roles worth assessing
- [ ] Run `vanguard mail` on recruiter replies
- [ ] `vanguard diagnose` weekly — the parse rate is the D-03 signal

**Exit:** 30+ vacancies scored · 10+ applications submitted · first responses
classified.

## PHASE 2 — Evidence-driven correction

**Superseded 12 Aug 2026 by `docs/PHASE_2.md`**, which is derived from Phase 1
operation rather than anticipated before it. The parameter work below remains
valid; the flowchart and build sequence are in that document.

**Effort: 3-5 days for parameters, ~15 days for the Phase 2 build.**

| Item | What the evidence decides |
|---|---|
| P-01 to P-04 | Whether each authored parameter survives contact with data |
| **D-03** | Whether prose extraction is tractable, or should be declined |
| C-01, C-02 | Keyword list, once yield per keyword is visible |
| BeautifulSoup | Only if the refusal profile shifts to parser failures |

**Exit:** every authored parameter measured or explicitly retained with a
recorded reason. Reliable-score rate above 75%.

## PHASE 3 — Optional

| Item | Value | Cost |
|---|---|---|
| N-06 mailbox polling | Closes the last manual step in the response loop | 2 days |
| Alignment fixes | Readability | 10 minutes |
| N-01 NHS Jobs | A well-matched sector | Blocked on NHSBSA |
| D-01 adaptive config | Self-tuning search | Unscoped |
| `--json` output | Feeds any future interface | 1 day |

## PHASE 4 — Multi-user service

Out of scope. Prerequisite, per the operator: the single-user build stable and
vigorously tested first — which it now is.

Carries over: coverage-gates-cosine-ranks, the truthfulness controls, the
board registry, Success Profile handling.

Does not: the alias table encodes one person's domain knowledge, and the
Type 1/2/3 distinction requires knowing what an applicant actually did. Both
are open problems, not implementation work.

---

# Critical path

```
  Phase 1  use it                    2-4 weeks elapsed, no development
     |
     v
  Phase 2  evidence-driven           3-5 days
     |
     v
  === COMPLETE under definition A ===
     |
     +--> Phase 3 items individually, if wanted
     +--> Phase 4, a separate project
```

**4–6 weeks, of which roughly one week is development.**

The dominant cost is waiting for applications and responses. That is the
correct shape: every remaining parameter is an empirical question and cannot
be answered faster.

---

# The principle this build established

Four times a change was made against a sample too small to be representative —
the 0.94 gate, extraction designed against one advert, the D-03 diagnosis from
29 examples, and the heading detector tightened without re-measuring. Each cost
a rebuild or a revert.

The diagnostics now make measurement cheap.

**A change justified by evidence must be verified by evidence before it is
kept.**
