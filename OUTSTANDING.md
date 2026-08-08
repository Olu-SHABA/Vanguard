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
| B-01 | Board config overrides caller query. `cfg.get("what") or query.keywords` — a CLI-supplied job title would be silently ignored. Should be `query.keywords or cfg.get("what")` | `adapters/adzuna.py:77`, `adapters/reed.py:66` | HIGH | OPEN |
| B-02 | Same precedence bug on location (`where`) | `adapters/adzuna.py`, `adapters/reed.py` | HIGH | OPEN |
| B-03 | `ingest()` has no board filter — cannot restrict a run to named boards | `ingest.py` | MEDIUM | OPEN |
| B-04 | Reed search returns truncated descriptions. `fetch_detail()` exists but `collect()` never calls it, so requirement extraction runs against partial adverts | `adapters/reed.py` | MEDIUM | OPEN |
| B-05 | Runs do not record which embedder produced them. A `LexicalEmbedder` result is degraded and indistinguishable from a real one in logs | `rank.py`, `coverage.py` | MEDIUM | OPEN |

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

## 8. Deferred by design

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
