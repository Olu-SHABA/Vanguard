# PROJECT VANGUARD — AUDIT

**22 August 2026**

| | |
|---|---|
| Modules | 16,612 lines · 35 files |
| Tests | 11,160 lines · 29 files · **1,315 passing** |
| Documentation | 5,620 lines · 15 files |
| Commands | 34 |
| Register | 127 items · **7 open** |

Verified in both credential states, with and without API keys.

---

# 1 · WHAT IS BUILT

```
  PHASE 1 · BUILD                                              COMPLETE
  ├── M0 Foundations · M1 Render · M2 Scoring
  └── M3 Drafting · M4 Ingestion · M5 Governance · M6 Response

  PHASE 2 · FROM LIVE OPERATION                                COMPLETE
  ├── A.1 Archive on dispatch ──────────────── archive.py
  ├── A.2 Mailbox polling ──────────────────── mailbox.py
  ├── A.3 Multi-round interviews ───────────── process.py
  ├── B   Repository evidence ──────────────── repo.py
  └── C   Application channel ──────────────── channel.py

  BUILT SINCE, FROM USE                                        COMPLETE
  ├── Batch advert ingestion ───────────────── adverts.py
  ├── Cover letter drafting ────────────────── letter.py
  ├── Application lifecycle and funnel ─────── lifecycle.py
  ├── Search link builder ──────────────────── search.py
  ├── Board discovery ──────────────────────── discover
  └── Session mode and bulk operations ─────── session, filters

  PHASE 3 · MARKET POSITIONING                                 SPECIFIED
  └── docs/PHASE_3.md — profile-keyed scoring, trends, positioning
```

## The pipeline, end to end

```
  FIND        search (links only)  ·  discover  ·  run  ·  paste
       │
  SCORE       coverage · alias resolution · gap classification
       │
  DECIDE      session  ·  approve/reject with filters  ·  todo
       │
  APPLY       draft  ·  apply  ·  dispatch  ·  archive
       │
  TRACK       poll  ·  responses  ·  interviews  ·  funnel
       │
  LEARN       stats  ·  diagnose  ·  evidence  ·  rescore
```

---

# 2 · WHAT REMAINS

## Seven open register items

| | | Weight |
|---|---|---|
| **B-09** | Near-duplicate requirements survive deduplication | Low |
| **B-17** | ~35% of adverts have unrecognised headings | Medium |
| **B-49** | Nothing records which CV bullet satisfied which requirement, so letter bullet selection is a heuristic | Medium |
| **C-02** | `data engineer` excluded from target keywords — operator ruling pending | Low |
| **O-01, O-02, O-03** | Three rulings applied by inference, unconfirmed | Low |

None blocks daily use.

## Eight parameters still authored

| | Current | Settles on |
|---|---|---|
| **P-01** Coverage gate | 0.60 | 30–40 applications with outcomes |
| **P-02** MiniLM soft-hit | 0.75 | Soft-hit review history |
| **P-03** Type 1 floor | 0.45 | Gap confirmations |
| **P-04** `silence_days` | 21 / 30 | Real response times |
| **P-05** `MAX_REFACTOR_ITER` | 2 | Refactor outcomes |
| **P-06** Template F | — | A second Success Profile advert |
| **P-07** Mail window | 40 | Running at volume |
| **P-08** Semantic threshold | 0.60 / 0.04 | Measured on five messages — wants twenty |

**P-01 is the one that matters.** It decides what is worth applying to, and it
has never been tested against whether high-coverage applications actually get
responses.

## Blocked externally

**Find a Job (DWP)** — corpus substantially duplicates Adzuna's; platform
migration unverified.

**Totaljobs, CWJobs, CV-Library, Monster** — no public candidate API. Email
alerts are the route, and none is set up.

## Deferred by ruling

**D-01** adaptive query configuration · **D-03** prose extraction ·
**D-04** broad repository mining · **D-05** supportability as a product

---

# 3 · WHAT THE SYSTEM HAS ACTUALLY FOUND

Twenty applications dispatched, with responses tracked.

```
  Application       20      4  ████████████████ 20/20 (100%)
  Screen             0      —
  Assessment         0      —
  Interview          0      —
```

**Nothing has passed the CV stage.** Four rejections, nine acknowledged and
silent, seven awaiting.

That is the finding, and it is not a tooling problem. The most frequent unmet
requirements are Azure 33, AWS 32, GCP 20, CI/CD 19, Docker 11, Terraform 10 —
**one cloud-and-deployment gap accounting for three-quarters of the total.**

---

# 4 · WHAT THE BUILD COST

**82 defects in the B series.** Almost none were findable by inspection.

| Class | Examples |
|---|---|
| Silent truncation | Pagination capped at one page; search terms dropped at 20; uncorrelated list showing 40 of 87 |
| Misleading figures | `C=1.000` from one requirement; 533% parse rate; unmeasured scores polluting recalibration |
| Correlation | ATS acknowledgements never matching; employer replies failing for board-sourced vacancies; a two-character employer invisible to three length gates |
| Classification | A rejection read as a thank-you because the opener was formulaic; an acknowledgement read as an offer; a described outcome read as a decision |
| State | A wrong classification frozen permanently because only AMBIGUOUS could be replaced |
| Platform | Clones never deleted on Windows, silently |
| Tests | Nine defects were in the tests. One was reading the operator's real Gmail for 32 seconds |

**Nine of the last twelve were found by the operator reading real output.**

---

# 5 · WHAT WOULD MOVE THIS FORWARD

**Not more building.**

Every remaining parameter is an empirical question, and none can be answered
faster than applications and responses accumulate.

The system is now good enough to say where applications stop. What it says
next depends on applying.

```
  Apply at volume ────────► responses accumulate
        │
        ▼
  P-01 settles on outcomes, not on distribution
        │
        ▼
  Phase 3 becomes worth building — profile comparison needs
  a corpus and a baseline, and has neither yet
```

**Roughly one week of development remains against four to six weeks of
elapsed time.** That imbalance is correct: the work left is measurement.

---

# 6 · THE PRINCIPLE THIS BUILD ESTABLISHED

Six times a change was made against a sample too small to be representative —
a threshold on a metric nobody had measured, extraction designed against one
advert, a diagnosis drawn from 29 examples, a detector tightened without
re-measuring, a documentation guard hardcoding the list it was meant to
derive, and a semantic threshold set three times by judgement before anyone
looked at the numbers.

Each cost a rebuild or a revert.

`vanguard diagnose`, `vanguard stats`, `vanguard logs` and
`vanguard responses --explain` exist so measurement is cheap. Sixteen guard
tests exist so documentation cannot quietly stop being true.

**A change justified by evidence must be verified by evidence before it is
kept.**
