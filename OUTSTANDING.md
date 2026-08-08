# OUTSTANDING — Project Vanguard

Defects, deferrals and unverified assumptions raised during implementation.
Live document: add on discovery, strike on resolution.

**Scope: Project Vanguard only.** Work on other codebases belongs in their own
repositories.

Status: `OPEN` · `BLOCKED` · `DEFERRED` · `CLOSED`

---

## 1. Defects

| ID | Defect | Location | Severity | Status |
|---|---|---|---|---|
| B-01 | Board config overrides caller query. `cfg.get("what") or query.keywords` — a CLI-supplied job title is silently ignored | `adapters/adzuna.py:77`, `adapters/reed.py:66` | HIGH | **DEFERRED to D-01** — operator ruling: do not patch precedence in isolation |
| B-02 | Same precedence issue on location (`where`) | `adapters/adzuna.py`, `adapters/reed.py` | HIGH | **DEFERRED to D-01** |
| B-03 | `ingest()` has no board filter — cannot restrict a run to named boards | `ingest.py` | MEDIUM | OPEN |
| B-04 | Reed search returns truncated descriptions. `fetch_detail()` exists but `collect()` never calls it, so requirement extraction runs against partial adverts | `adapters/reed.py` | MEDIUM | OPEN |
| B-05 | Runs do not record which embedder produced them. A `LexicalEmbedder` result is degraded and indistinguishable from a real one in logs | `rank.py`, `coverage.py` | MEDIUM | OPEN |

## 1a. Future separate projects

### D-01 — Adaptive query configuration

**Status:** NOTED. Not scheduled, not designed. Supersedes B-01 and B-02.

Operator direction, 8 Aug 2026: rather than fixing B-01/B-02 with a precedence
rule, query configuration should be treated as a layer that composes and
evolves — drawing on hard-wired configuration, operator-provided input, and
other non-invasive variables. Configuration to be automatic and self-evolving.

To be scoped as a separate project. B-01/B-02 remain unpatched in the meantime;
their current behaviour is inert until a CLI exists.

---

> **Observations recorded during M4.** Not a design, not a scope, not a
> schedule. Whoever scopes D-01 owns every choice below and is free to discard
> all of it. Recorded only so it does not have to be rediscovered.

**Signals the pipeline already produces.** None require additional collection;
all are logged today or will be by M6.

| Signal | Source | What it might indicate |
|---|---|---|
| Coverage distribution per keyword | `coverage.py` | Terms consistently yielding low C may be poorly targeted |
| Type 3 gap frequency across vacancies | `gaps.py` | A requirement recurring as unmet is a standing skills gap, not a scoring artefact |
| Board yield after deduplication | `ingest.py` | Which sources contribute unique vacancies rather than overlap |
| Response outcomes | Stage II, M6 | The only signal connecting query terms to real results |

**Questions noted while writing the adapters.** Questions, not answers.

1. Is adaptation per-board, global, or both?
2. Does the operator see proposed changes before they take effect, or after?
   The gap classifier's proposes/confirms split is one existing precedent.
3. What prevents drift — a keyword set narrowing over time until it excludes
   roles the operator would have wanted?
4. Where does machine-written state live? `boards.yaml` is hand-maintained and
   hot-reloadable.

**Related existing ruling.** The directive's Objectivity Rule and the
coverage-gates/cosine-ranks decision both turn on outputs being explainable.
Whether that reasoning extends to an adapted query is a question for the design
pass, not a constraint asserted here.

---

## 2. Configuration

| ID | Item | Status |
|---|---|---|
| C-01 | `where: "{{ TARGET_LOCATION }}"` is an unresolved placeholder. Adzuna receives the literal string | OPEN |
| C-02 | Target keywords are `data scientist`, `machine learning engineer`, `network analytics`. Data engineering is excluded by the directive's target domains, but the operator's CV fits it well and the one real test advert is a data engineering role | OPEN — operator ruling |
| C-03 | Model names hardcoded in `rank.py`. Should be config if a fully airgapped setup is wanted (local filesystem paths instead of Hub repo IDs) | DEFERRED |

## 3. Unverified — no network in the build environment

| ID | Item | Consequence | Status |
|---|---|---|---|
| V-01 | WeasyPrint never installed. **No PDF has ever been rendered** | `render/standard.css` and `render/anonymised.css` are written blind. Most likely component to need work | BLOCKED |
| V-02 | pypdf never installed. PDF text-layer anonymisation scan untested against a real PDF | The pure `verify_text()` path is tested; the PDF path is not | BLOCKED |
| V-03 | sentence-transformers never installed. Stage 3 has never scored with a real model | Competency phrases resolve poorly under `LexicalEmbedder`; real coverage is likely higher | BLOCKED |
| V-04 | httpx never installed. No live API call to Adzuna or Reed | Adapters tested against injected fakes only | BLOCKED |
| V-05 | Tests run under an offline shim, not pytest | Assertions genuinely executed, but pytest fixtures/marks unexercised | BLOCKED |

All five clear on first `pip install -e ".[dev]"` and `pytest` on the operator's machine.

## 4. Not implemented

| ID | Item | Trigger |
|---|---|---|
| N-01 | `NHSJobsAPIAdapter` — declared in registry, raises "not yet implemented" | NHSBSA API access arranged |
| N-02 | `FindAJobAdapter` — disabled pending platform migration status | DWP replacement platform contract confirmed |
| N-03 | CLI (`cli.py`) with `--title` and `--boards` flags | M5 |
| N-04 | Queue, state machine, SQLite schema | M5 |
| N-05 | Mail ingestion, correlation, response classifier | M6 |

## 5. Authored parameters requiring real data

Per the directive's hallucination clause, these were authored rather than
derived and are estimates until measured.

| ID | Parameter | Value | Validation trigger |
|---|---|---|---|
| P-01 | Coverage gate | 0.94 | 30–40 logged applications |
| P-02 | MiniLM per-term soft-hit threshold | 0.75 | Soft-hit review history exists |
| P-03 | Type 1 proposal floor (`_TYPE_1_MIN_SCORE`) | 0.45 | Gap-classification review history |
| P-04 | `silence_days` | 21 / 30 | Real response-time data |
| P-05 | `MAX_REFACTOR_ITER` | 2 | Refactor outcome history |
| P-06 | Template F structure | — | Derived from **one** MoJ advert. Verify against a second before generalising |

## 6. Operator confirmations outstanding

| ID | Item | Basis | Status |
|---|---|---|---|
| O-01 | `/Pipeline_Archive/[Company]/` with timestamp prefixes | Applied by inference from the Scope Isolation Rule | OPEN |
| O-02 | Directive §5 Persistence bound to ROUTE 4 rather than a new ROUTE 6 | Applied by inference | OPEN |
| O-03 | Whether the repo or the Claude project is authoritative for `canonical_cv.md`, `boards.yaml`, `alias_table.yaml` | Duplicated in both; will drift | OPEN |

## 7. Security

| ID | Item | Status |
|---|---|---|
| S-01 | `canonical_cv.md` was public on GitHub. Repo now private, file gitignored, `git rm --cached` applied | CLOSED |
| S-02 | CV remains in git history in earlier commits. Reachable only with repo access | ACCEPTED — repo is private |
| S-03 | Search-engine indexing verified absent (`site:` query returned nothing) | CLOSED |
| S-04 | Third-party scrapers of GitHub's public event stream during the public window | ACCEPTED — unrecoverable, no action available |
| S-05 | If the repo is ever made public, commit a **redacted** `canonical_cv.md` produced by `render.anonymise()` and keep the real one gitignored | OPEN — prerequisite for any public release |

## 8. Design proposals — separate projects

### D-01 — Adaptive query configuration

**Status:** PROPOSED · **Supersedes:** B-01, B-02 · **Raised:** operator, 2026-08-08

**Proposal.** Rather than patching precedence so the caller always wins, treat
query configuration as a layer that composes and evolves from three sources:

1. **Hard-wired configuration** — `boards.yaml`. The declared floor
2. **Operator input** — job title, location, boards, supplied per run
3. **Non-invasive observed variables** — signals the pipeline already produces
   as a by-product, requiring no new collection

The layer merges rather than overrides, and adjusts over time from what the
pipeline learns about which queries produce vacancies worth applying to.

**Candidate observed variables**, all already logged or trivially derivable:

| Signal | Source | Possible use |
|---|---|---|
| Coverage per query term | scoring log | Down-weight terms that consistently produce UNREACHABLE vacancies |
| Rank score distribution | scoring log | Identify terms surfacing high-similarity vacancies |
| Operator approve/reject | queue transitions | The strongest signal — what was actually worth applying to |
| Board yield after dedup | ingestion run | Detect a board contributing only duplicates |
| Soft-hit terms | coverage stage 3 | Candidate alias rows, and candidate query terms |
| Response outcomes | Stage II classification | Slowest but truest signal of query quality |

**Why this is a separate project, not a patch**

- It is a learning system. It needs the logged data from 30–40 real
  applications before any adjustment can be evidence-based, which is the same
  trigger as threshold recalibration (P-01)
- Precedence stops being a two-line rule and becomes a merge policy with its
  own semantics: which sources add terms, which can remove them, which can
  only re-weight
- It interacts with the coverage gate. A query layer that narrows toward
  high-coverage vacancies will narrow toward roles the CV already matches, and
  progressively stop surfacing roles worth stretching for

**Risks to design against**

| Risk | Note |
|---|---|
| Silent narrowing | Optimising for coverage selects for what the CV already says. Needs a floor that keeps exploratory terms in rotation |
| Unexplainable behaviour | An evolved config must be able to answer *why is this term here*. Same audit duty the coverage gate carries — every adjustment cites its evidence |
| Config drift with no rollback | Evolved state must be versioned and revertible to the declared floor |
| Over-fitting to a small sample | Adjustments before ~30 applications would be noise |
| Scope creep into the multi-user question | Per-user adaptive config is a materially harder problem than single-user |

**Prerequisites**

- M5 complete: the queue and its transitions are where approve/reject signal lives
- Instrumentation running: coverage, rank score and gap list logged per vacancy
- 30–40 real applications, so adjustment is measured rather than assumed

**Until then.** Behaviour stays as built: `boards.yaml` is authoritative and
the caller query acts as a fallback. This is documented rather than accidental,
and B-01/B-02 remain recorded so the current semantics are not mistaken for a
considered design.

---

## 9. Deferred by design

| Item | Trigger |
|---|---|
| Threshold recalibration | 30–40 logged applications |
| Requirement-extraction refinement | Real adverts, not designed in advance |
| Alias table growth | Every stage-3 soft hit is a candidate row |
| Multi-user architecture | Single-user system mechanically stable |

---

## Log

| Date | Change |
|---|---|
| 2026-08-08 | Created. Consolidates items raised across M0–M4 |
| 2026-08-08 | B-01/B-02 deferred to D-01 (adaptive query configuration) per operator direction. Observations from M4 recorded under D-01, explicitly non-binding |
| 2026-08-08 | B-01/B-02 deferred to D-01. Adaptive query configuration proposed as a separate project |
