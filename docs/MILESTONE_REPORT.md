# PROJECT VANGUARD — MILESTONE REPORT

**16 August 2026**

| | |
|---|---|
| Modules | 13,062 lines · 32 files |
| Tests | 7,982 lines · 26 files · **1,021 passing** |
| Documentation | 3,962 lines · 11 files |
| Commands | 24 |
| Defect register | 83 items · **2 open** |

Verified in both credential states — with API keys configured and without.

---

# 1 · MILESTONE CHART

```
  DESIGN                                                          COMPLETE
  ├── Specification audit ─────────────────────────────────────── 21 defects, 4 blockers
  ├── Corpus: directive, blueprint, 6 templates, alias table ──── consistent
  └── Build plan: walking skeleton, M0-M6 ──────────────────────── superseded by delivery

  PHASE 1 · BUILD                                                 COMPLETE
  ├── M0  Foundations ─────────────────────────────────────────── packaging, environment
  ├── M1  Render chain ────────────────────────────────────────── 2-page PDF, anonymisation
  ├── M2  Scoring core ────────────────────────────────────────── coverage, aliases, rank
  ├── M3  Drafting ────────────────────────────────────────────── gaps, refactor, B/C/F
  ├── M4  Ingestion ───────────────────────────────────────────── 5 adapters, dedup
  ├── M5  Governance ──────────────────────────────────────────── store, queue, CLI
  └── M6  Response loop ───────────────────────────────────────── correlation, classifier

  PHASE 1 · LIVE OPERATION                                        COMPLETE
  ├── Reed and Adzuna credentialed ────────────────────────────── real vacancies scored
  ├── 553 vacancies through the pipeline ──────────────────────── 7 dispatched
  └── 30+ defects found by running it ─────────────────────────── none by inspection

  PHASE 2 · DERIVED FROM LIVE OPERATION                           COMPLETE
  ├── A.1 Archive on dispatch ─────────────────────────────────── archive.py
  ├── A.2 Mailbox polling ─────────────────────────────────────── mailbox.py  IMAP + Gmail
  ├── A.3 Multi-round interviews ──────────────────────────────── process.py
  ├── —   Batch advert ingestion ──────────────────────────────── adverts.py  (out of sequence)
  ├── B   Repository evidence ─────────────────────────────────── repo.py
  └── C   Application channel ─────────────────────────────────── channel.py

  DOCUMENTATION                                                   COMPLETE
  ├── Reference, SOP, 4 step-by-step guides ───────────────────── 3,962 lines
  └── 13 drift guards, self-deriving ──────────────────────────── fail the suite

  ═══════════════ EVERYTHING PLANNED IS BUILT ═══════════════

  REMAINING                                                       NOT CODE
  ├── Calibration: 7 authored parameters ──────────────────────── needs volume
  ├── 2 register items open ───────────────────────────────────── low value
  ├── 2 adapters ──────────────────────────────────────────────── blocked externally
  └── 3 rulings applied by inference ──────────────────────────── needs confirmation
```

---

# 2 · WHAT WAS DELIVERED

## Phase 1 — the pipeline

| | |
|---|---|
| **Ingestion** | Registry-driven, 10 boards, 3 access tiers. Rate limiting, deduplication, expiry and staleness filtering before hydration |
| **Scoring** | Coverage gates, cosine ranks. Three-stage per-term resolution with a curated alias table and an exclusion tier that cannot be overridden |
| **Drafting** | Type 1/2/3 gap taxonomy, bounded refactoring, three submission types, six templates |
| **Governance** | SQLite store, queue state machine, 24-command CLI, append-only audit trail |
| **Response** | Four-stage correlation, seven-state classifier, dormancy |

## Phase 2 — from what live operation exposed

| | Problem it solved |
|---|---|
| **Archive** | Applications were dispatched with no record of what was submitted |
| **Mailbox polling** | Replies had to be saved to a file by hand |
| **Interview tracking** | One message, one classification — no notion of a process across weeks |
| **Batch ingestion** | 70 pastes a day, one command each |
| **Repository evidence** | Unstated work recoverable from the operator's own repositories |
| **Application channel** | A PENDING record said a vacancy was worth applying to and nothing about how |

## Defects found by running it — 49 in the B series

The register's most useful finding. **Almost none were findable by inspection.**

| Class | Examples |
|---|---|
| Silent truncation | Pagination capped at one page; search terms dropped at 20; partial results indistinguishable from complete |
| Misleading figures | `C=1.000` from one requirement; 533% parse rate; `FLAGGED 520` for a run that scored 14; unmeasured scores polluting the recalibration data |
| Correlation | A LinkedIn advert attached to an open application; ATS acknowledgements never matching; employer replies failing for board-sourced vacancies |
| Platform | Clones never deleted on Windows, silently |
| Tests | Nine defects were in the tests, not the code. Every one passed when written |

---

# 3 · WHAT REMAINS

## Calibration — the substantial item

Seven parameters were authored rather than measured. Each is labelled as such
and each needs volume to settle.

| | Current | Settles when |
|---|---|---|
| **P-01** Coverage gate | 0.60 | 30–40 logged applications |
| **P-02** MiniLM threshold | 0.75 | Soft-hit review history |
| **P-03** Type 1 floor | 0.45 | Gap-classification history |
| **P-04** `silence_days` | 21 / 30 | Real response times |
| **P-05** `MAX_REFACTOR_ITER` | 2 | Refactor outcome history |
| **P-06** Template F | — | A second Success Profile advert |
| **P-07** Mail window threshold | 40 | Running at volume |

P-01 has already moved once on evidence — from 0.94, which passed nothing and
which the best genuine match could not structurally reach.

## Open in the register — 2

| | |
|---|---|
| **B-03** | `ingest()` has no board filter. Low value |
| **B-09** | Near-duplicate requirements survive deduplication. Low value |

## Blocked externally — 2

| | |
|---|---|
| **N-01** NHS Jobs adapter | API access arranged via NHSBSA, not self-service |
| **N-02** Find a Job adapter | Platform migration status unverified |

Both are hand-fed in the meantime, and everything downstream runs identically.

## Awaiting your confirmation — 3

Rulings applied by inference rather than instruction. Each is recorded with its
basis.

## Deferred by ruling

**D-01** adaptive query configuration · **D-03** prose extraction ·
**D-04** broad repository mining · **D-05** supportability as a product

---

# 4 · THE ONE THING THAT MOVES THIS FORWARD

**Use it at volume.**

Every remaining parameter is an empirical question. None can be answered
faster than applications and responses accumulate, and none should be answered
by judgement — that is what produced the 0.94 gate that passed nothing.

The intended test is 75 vacancies a day, roughly 95% pasted. Phase 2's batch
ingestion, mail polling and application channel were built for exactly that
load.

```
  Week 1-2    apply at volume ──────────── produces the evidence
      │
      ▼
  Days        ratchet P-01 to P-07 ─────── on numbers, with reasons recorded
      │
      ▼
  ══════ COMPLETE under the operational definition ══════
```

**Roughly one week of development remains, and four to six weeks of elapsed
time.** The imbalance is correct: the work left is measurement.

---

# 5 · THE PRINCIPLE THIS BUILD ESTABLISHED

Five times a change was made against a sample too small to be representative —
a threshold on a metric nobody had measured, extraction designed against one
advert, a diagnosis drawn from 29 examples, a detector tightened without
re-measuring, and a documentation guard hardcoding the list it was meant to
derive.

Each cost a rebuild or a revert.

`vanguard diagnose`, `vanguard stats` and `vanguard logs` exist so measurement
is cheap. Thirteen tests exist so documentation cannot quietly stop being true.

**A change justified by evidence must be verified by evidence before it is
kept.**
