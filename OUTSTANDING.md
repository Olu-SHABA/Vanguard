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
| B-04 | Reed search returns truncated descriptions; `collect()` never called `fetch_detail()`. Requirement extraction ran against snippets | `adapters/reed.py` | **HIGH** | **CLOSED** — `BoardAdapter.hydrate()` hook added; Reed fetches the full advert per vacancy |
| B-13 | A snippet produced a confident score. First live run: Service Centre Team Manager scored C=1.000 on \|R\|=1 while a Senior Data Engineer scored 0.000. Coverage on a denominator of 1-2 is meaningless | `coverage.py`, `refactor.py` | **HIGH** | **CLOSED** — `CoverageReport.unreliable` blocks the gate when the source is partial or \|R\| < 6; refactor exits `UNRELIABLE_SOURCE` -> FLAGGED |
| B-06 | `_to_competency()` trimmed at `", and"`, discarding the clause carrying alias evidence. Found on the first real MiniLM run | `extract.py` | HIGH | **CLOSED** — `source_bullet` retained on every Requirement |
| B-07 | Alias lookup ran against the trimmed phrase only. "communicating with stakeholders" failed stage 2 and fell to stage 3 at 0.513 | `coverage.py` | HIGH | **CLOSED** — resolution tries trimmed then full bullet; Tier C checked across both so an exclusion cannot be evaded by trimming |
| B-08 | Civil Service Behaviours extracted as coverage requirements. Assessed at interview, not sift — inflated \|R\| and depressed C on every Success Profile advert | `extract.py` | HIGH | **CLOSED** — named behaviours excluded; `submission.detect()` still reports them separately |
| B-11 | Adzuna hardcoded to `search/1`; Reed sent no `resultsToSkip`. Everything past the first page was silently discarded | `adapters/adzuna.py`, `adapters/reed.py` | HIGH | **CLOSED** — both paginate to `Query.max_results`, capped by `max_pages` |
| B-12 | Truncation was not reported. A partial harvest was indistinguishable from a complete one | `adapters/base.py`, `ingest.py` | HIGH | **CLOSED** — `Truncation` records board, keyword, count and reason; `IngestionRun.complete` is False and the summary says INCOMPLETE |
| B-10 | No vacancy reference extracted or stored, so correlation stage 1 (reference match) could never fire for any vacancy | `submission.py`, `adapters/base.py`, `store.py` | HIGH | **CLOSED** — M6. Reference extracted from advert text, persisted, used in correlation |
| B-14 | Adzuna free API caps every description at exactly 500 characters with no detail endpoint. 255 vacancies scored on two sentences | `config/boards.yaml` | **HIGH** | **CLOSED** — demoted to `tier: manual`, `supplies_full_text: false`. Discovery only; assessment by paste |
| B-15 | `collect()` swallowed `RateLimitExceeded` during hydration. ~240 of 300 Reed vacancies scored on snippets with no indication | `adapters/base.py` | **HIGH** | **CLOSED** — hydration stops on rate limit and records a truncation naming the count |
| B-16 | `description_is_partial` was never persisted, so degraded scores could not be queried — it had to be inferred from average description length | `store.py` | MEDIUM | **CLOSED** — `vacancies.partial` column, migrated |
| B-17 | Requirement extraction assumes a "Person Specification" / "Essential" section | `extract.py` | **HIGH** | **PARTIALLY CLOSED** — a share of the "prose" failures were HTML: Reed returns markup and the bullet pattern matches line starts, so `<ul><li>` requirement lists were invisible. HTML is now flattened before extraction. Genuinely unstructured adverts remain — see D-03 |
| B-20 | Every bulleted line was counted as a requirement — duties, benefits, application steps. Reed adverts bullet all of them. \|R\| reached 38 with C=0.026 and ceiling 1.000, the system asserting an AI Marketing role was fully attainable | `extract.py`, `structure.py` | **HIGH** | **CLOSED** — `structure.py` parses the DOM, binds each list to the heading above it, and classifies headings into requirement / responsibility / benefit / process / company. Only REQUIREMENT sections contribute |
| B-19 | Vacancies with a passed closing date were fetched, hydrated and scored. Each consumed one of a 60/hour hydration budget | `extract.py`, `adapters/base.py` | **HIGH** | **CLOSED** — closing date parsed from the advert; expired vacancies dropped BEFORE hydration, so a closed posting no longer costs a working slot |
| B-18 | `max_results` in boards.yaml was inert — adapters read only `Query.max_results`. Reed fetched 300 and hydrated 57; the other 243 were scored on snippets | `adapters/base.py`, `adzuna.py`, `reed.py` | **HIGH** | **CLOSED** — `effective_max_results()` takes the smaller of config and caller. Reed capped at 15/keyword to fit inside 60 calls/hour |
| B-21 | `list_queue()` joined `scores` without restricting to the latest row. Two vacancies rendered as twenty queue records after ten runs | `store.py` | **HIGH** | **CLOSED** — correlated subquery on MAX(computed_at). Score history retained deliberately; `score_history()` exposes it |
| B-22 | `collect()` reported "could not be hydrated" when hydration was never attempted. A correct run appeared to have failed | `adapters/base.py` | MEDIUM | **CLOSED** — reported only when `hydrate=True` |
| B-23 | HTML adverts with no recognised requirement heading fell back to flat extraction, counting duties and benefits as requirements. Produced \|R\|=38 with ceiling 1.000 — the system asserting an AI Marketing role was fully attainable | `extract.py` | **HIGH** | **CLOSED** — operator ruling 9 Aug 2026: refuse rather than fall back. Returns no terms; coverage reports UNRELIABLE and the vacancy is FLAGGED for manual review. Plain-text adverts are unaffected |
| B-24 | Nothing recorded WHY an advert refused or what its headings said. 14 of 31 adverts went unscored with no evidence for fixing it | `diagnostics.py`, `store.py` | **HIGH** | **CLOSED** — `diagnostics` table captures headings, classifications, bullet counts, refusal reason and pipeline decisions per advert. `vanguard diagnose` ranks unrecognised headings by frequency |
| B-25 | Heading detector fired on job titles, field labels, recruiter names and bare punctuation. A false heading orphans the content belonging to the real one | `structure.py` | MEDIUM | **REVERTED, REOPENED** — the strict version rejected REAL headings: any run of two words or fewer ending in a colon, which covers `Requirements:`, `Essential:`, `About you:`. Reliable scores fell 20/31 -> 13/31 and the only PENDING vacancy was lost. Reverted to rejecting only bare punctuation, overlong runs and the repeated job title. A tolerated false heading costs diagnostic noise; a rejected real one costs the whole advert |
| B-09 | Near-duplicate requirements survive dedup when the same bullet appears in two advert sections with different trimming | `extract.py` | LOW | OPEN |
| B-05 | Runs do not record which embedder produced them | `rank.py`, `coverage.py` | MEDIUM | **CLOSED** — `scores.embedder` column added in M5; `run`/`paste`/`score` all report it |

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

### D-02 — CLI presentation layer

**Status:** NOTED. Not scheduled.

Three output defects were fixed 8 Aug 2026 — word-boundary truncation, terminal-width
awareness, and collapsing skipped boards in `run`. What was NOT done, deliberately:

- `rich.Table` for the list views (`review`, `boards`, `stats`). `rich` is already
  proven in the operator's other codebase and would handle alignment and width
  properly. Held until the CLI has been used for a fortnight — styling all nine
  views on a guess about which matter is the wrong order.
- `--json` output flag. Useful if any GUI or dashboard follows.
- Any graphical interface. The system has scored two real adverts. Designing an
  interface before the daily workflow is established risks building for imagined use.

Tables suit list views. They suit the `review <id>` record view badly — exclusion
reasons are prose of varying length and a grid would clip them, which is the defect
that was just fixed.

---

### D-03 — Coverage assumes structured adverts

**Status:** NOTED. Not scheduled.

Coverage-as-gate assumes an advert states discrete, extractable requirements.
Government Success Profiles do. Commercial adverts largely do not — they are
prose. On the first live run, 516 of 530 vacancies extracted fewer than six
terms.

Of the 27 that extracted properly, the ranking was still poor: an AI Trainer
scored 0.700 against a Senior Data Engineer at 0.444, and two identically
titled Senior Data Engineer roles scored 0.625 and 0.444.

> Observations, not a design. Recorded 9 Aug 2026 so they need not be
> rediscovered. Whoever scopes D-03 owns every choice.

The original audit replaced cosine with coverage because cosine could not
answer *which requirement failed*. That reasoning stands. What was not
tested is that extraction only works on one advert type — the metric was
validated against a single MoJ Success Profile advert.

Open questions:

1. Should coverage gate at all when \|R\| is small, or should such vacancies
   route to a different assessment path entirely?
2. Is there a reliable way to extract requirements from prose adverts, or is
   the honest answer that only structured adverts can be scored?
3. What ranks the rest — rank score alone, operator triage, something else?
4. Does the Type 1/2/3 gap taxonomy survive if requirements are not discrete?

---

## 2. Configuration

| ID | Item | Status |
|---|---|---|
| C-01 | `where: "{{ TARGET_LOCATION }}"` unresolved | **PARTIALLY CLOSED** — placeholders are now detected and treated as unset rather than sent literally. The operator must still decide the target location |
| C-02 | Target keywords are `data scientist`, `machine learning engineer`, `network analytics`. Data engineering is excluded by the directive's target domains, but the operator's CV fits it well and the one real test advert is a data engineering role | OPEN — operator ruling |
| C-03 | Model names hardcoded in `rank.py`. Should be config if a fully airgapped setup is wanted (local filesystem paths instead of Hub repo IDs) | DEFERRED |

## 3. Unverified — no network in the build environment

| ID | Item | Consequence | Status |
|---|---|---|---|
| V-01 | First PDF rendered 8 Aug 2026 after GTK3 install. Three defects found and fixed: compound hyphens lost from the text layer, 3-page overrun, role split across a page break | CSS revised but **the revision is itself unverified** — re-render required | OPEN — re-render pending |
| V-02 | pypdf never installed. PDF text-layer anonymisation scan untested against a real PDF | The pure `verify_text()` path is tested; the PDF path is not | BLOCKED |
| V-03 | sentence-transformers never installed. Stage 3 has never scored with a real model | Competency phrases resolve poorly under `LexicalEmbedder`; real coverage is likely higher | BLOCKED |
| V-04 | httpx never installed. No live API call to Adzuna or Reed | Adapters tested against injected fakes only | BLOCKED |
| V-05 | Tests run under an offline shim, not pytest | **CLOSED** — 254 passed under real pytest on the operator's machine, 8 Aug 2026 |

All five clear on first `pip install -e ".[dev]"` and `pytest` on the operator's machine.

## 4. Not implemented

| ID | Item | Trigger |
|---|---|---|
| N-01 | `NHSJobsAPIAdapter` — declared in registry, raises "not yet implemented" | NHSBSA API access arranged |
| N-02 | `FindAJobAdapter` — disabled pending platform migration status | DWP replacement platform contract confirmed |
| N-03 | CLI (`cli.py`) | **CLOSED** — M5. `--title`/`--location` present on `run`; note B-01 still causes board config to win |
| N-04 | Queue, state machine, SQLite schema | **CLOSED** — M5 |
| N-05 | Correlation, response classifier, DORMANT sweep, Templates D and E | **CLOSED** — M6 |
| N-06 | IMAP/Gmail mailbox connection. `vanguard mail` takes a message file; nothing polls a mailbox | Operator decision on provider and credentials |

## 5. Authored parameters requiring real data

Per the directive's hallucination clause, these were authored rather than
derived and are estimates until measured.

| ID | Parameter | Value | Validation trigger |
|---|---|---|---|
| P-01 | Coverage gate | **0.60** (was 0.94) | **First measurement 9 Aug 2026:** of 43 reliable scores, ZERO reached 0.94 and the best genuine fit (ML Engineer, C=0.700) had a ceiling of 0.800 — structurally unable to pass. Operator ruling: start low and ratchet up. 0.85 was modelled and would also pass zero. 0.60 passes 2 and puts 15 within refactor reach. Now config, not code |
| P-02 | MiniLM per-term soft-hit threshold | 0.75 | **First real measurement 8 Aug 2026.** Top stage-3 score 0.613 on the MoJ advert; nothing reached 0.75. Threshold NOT changed — the low scores were caused by B-06/B-07, and lowering to catch 0.513 would also admit 0.613, a Behaviour statement rather than a skill. Revisit once soft-hit history exists |
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
| 2026-08-08 | `.env` loading added so credentials survive between shell sessions; `.env.example` committed. Unresolved `{{ TOKEN }}` placeholders no longer sent as literal query values (C-01, partial) |
| 2026-08-09 | `COMMANDS.md` written — all 16 commands, every option, and what each output field means. Three tests assert the reference cannot drift from the CLI: every command documented, every option documented, and no documented command that no longer exists |
| 2026-08-09 | B-25 reverted after measurement. The tightening was the right diagnosis and the wrong implementation — it was tested against the noise cases and against colon-free headings, never against `Requirements:` or `Essential:`, which are common. The test suite passed because the tests covered the cases the author had thought of. Lesson: a change justified by diagnostics must be VERIFIED by diagnostics before it is kept |
| 2026-08-09 | First `vanguard diagnose` run inverted the expected finding. 65% of adverts yielded requirements, better than estimated — and the unrecognised headings were almost entirely NOISE (job titles, `Location:`, `,`, recruiter names), not requirement headings needing to be added. The phrase list was not too narrow; the DETECTOR was too loose. Fixed by tightening detection rather than widening classification — the opposite of what was proposed before the evidence existed |
| 2026-08-09 | Diagnostics added on operator specification: (1) why an advert was rejected, (2) what was gathered per advert, (3) an audit trail of pipeline decisions. Purpose is not troubleshooting alone — the unrecognised headings recorded are the direct evidence for widening `classify_heading()`, which is now the binding constraint on D-03 |
| 2026-08-09 | Operator ruling on the D-03 fallback: stop reverting to flat extraction when no requirement heading is recognised. A refusal that surfaces the advert for review beats a plausible-looking wrong score. Expect MORE vacancies reported UNRELIABLE and fewer bogus ceiling=1.000 lines — that is the intended trade |
| 2026-08-09 | Rank pre-filter added on operator observation that irrelevant vacancies were consuming the hydration budget. Hydration moved out of `collect()`; vacancies are ranked by document similarity (one embedding, no API call) and only those above `rank_floor` are hydrated and scored. `coverage_gate` and `rank_floor` moved into config so ratcheting needs no code change |
| 2026-08-09 | Operator ruling: `git` reclassified Tier C -> B on changed evidence — sustained day-to-day use with an auditable commit history. Team workflow (pull requests, code review, branching strategy) split into `EXCLUDED_collaborative_git` and remains blocked. `pytest` NOT reclassified: the 500+ Vanguard tests were written by the assistant, not the operator, so claiming authorship would fail D1 in the assistant's own interview rubric |
| 2026-08-09 | Operator proposal: the regex flattener was too basic and should be replaced with structural parsing. Correct — flattening destroyed the heading-to-list binding, which is exactly what distinguishes a requirements list from a benefits list. `structure.py` added, using stdlib `html.parser`. Reed headings are inline `<strong>` followed by `<br /><br />`, not `<h3>`, so heading detection is length- and position-based. Verified against real Reed markup: 3 duty bullets and 2 benefit bullets correctly excluded, 2 requirements retained |
| 2026-08-09 | Operator observation while reading raw advert text: Reed returns HTML, and the closing date is stated in it. Two fixes followed — HTML flattened before extraction (recovering `<li>` requirement lists previously diagnosed as prose), and expired vacancies dropped before hydration. A Reed ML advert that previously extracted 0-1 terms now yields 7 and scores C=0.714 reliably |
| 2026-08-09 | Hydration budget bug (B-18): the per-board cap existed in config but no adapter read it. Both values are limits, so the smaller now wins — which resolves the case without touching the deferred B-01/D-01 precedence question |
| 2026-08-09 | Operator ruling: a board that cannot supply full advert text is not processed through its API — it defaults to operator paste. Implemented as `supplies_full_text`, validated at config load. Adzuna and Civil Service demoted; Reed retained via its detail endpoint. Board topology now 1 automatable, 3 manual |
| 2026-08-09 | First live run against Adzuna and Reed exposed B-04 and B-13. Reed search returns snippets, so extraction found 1-2 terms per advert and produced C=1.000 for irrelevant roles. Hydration added; unreliable scores can no longer pass the gate. Five further tests were found to depend on machine credentials — they passed only on an unconfigured machine |
| 2026-08-08 | CLI output defects fixed: fixed-width slicing cut mid-word and lost the operative half of exclusion reasons and adapter status; widths were hardcoded to ~100 columns; `run` printed seven skip lines before any result. Now word-boundary clipping, terminal-width detection, wrapped reasons, collapsed skips. Styling (rich tables, --json, GUI) deliberately deferred — see D-02 |
| 2026-08-08 | B-11/B-12 fixed: pagination added to both API adapters, truncation recorded rather than swallowed. Ceiling per run is now `max_results x keywords x boards`, defaults 100 x 3 x 2 = 600 before dedup. Two test doubles were themselves defective — a shared result pool across keywords, and assertions written for one keyword when board config supplies three (B-01) |
| 2026-08-08 | M6 complete. B-10 found during the first mail test: the stored vacancy id is a content hash, and the employer's real reference (19568) was extracted nowhere — stage 1 correlation was dead on arrival. Fixed |
| 2026-08-08 | First MiniLM run produced coverage identical to the lexical fallback (C=0.304), which surfaced B-06/B-07/B-08. After fixes: \|R\| 23 -> 21, C 0.304 -> 0.381. P-02 left at 0.75 on the evidence |
| 2026-08-08 | M5 complete: SQLite store, queue state machine, operator CLI. `vanguard paste` added — the manual adapter had no CLI entry point, which would have left LinkedIn unusable |
| 2026-08-08 | First PDF rendered. Compound hyphens (`cloud-based` -> `cloudbased`) were being lost from the text layer — an ATS miss and a coverage-engine miss. Fixed with U+2011 substitution in `protect_compounds()`. CSS tightened for two-page fit; orphans/widows added to keep role blocks together |
| 2026-08-08 | Skip guard for PDF tests corrected: tested package presence, not importability, so a missing GTK runtime failed instead of skipping |
| 2026-08-08 | B-01/B-02 deferred to D-01 (adaptive query configuration) per operator direction. Observations from M4 recorded under D-01, explicitly non-binding |
| 2026-08-08 | `.env` loading added so credentials survive between shell sessions; `.env.example` committed. Unresolved `{{ TOKEN }}` placeholders no longer sent as literal query values (C-01, partial) |
| 2026-08-09 | `COMMANDS.md` written — all 16 commands, every option, and what each output field means. Three tests assert the reference cannot drift from the CLI: every command documented, every option documented, and no documented command that no longer exists |
| 2026-08-09 | B-25 reverted after measurement. The tightening was the right diagnosis and the wrong implementation — it was tested against the noise cases and against colon-free headings, never against `Requirements:` or `Essential:`, which are common. The test suite passed because the tests covered the cases the author had thought of. Lesson: a change justified by diagnostics must be VERIFIED by diagnostics before it is kept |
| 2026-08-09 | First `vanguard diagnose` run inverted the expected finding. 65% of adverts yielded requirements, better than estimated — and the unrecognised headings were almost entirely NOISE (job titles, `Location:`, `,`, recruiter names), not requirement headings needing to be added. The phrase list was not too narrow; the DETECTOR was too loose. Fixed by tightening detection rather than widening classification — the opposite of what was proposed before the evidence existed |
| 2026-08-09 | Diagnostics added on operator specification: (1) why an advert was rejected, (2) what was gathered per advert, (3) an audit trail of pipeline decisions. Purpose is not troubleshooting alone — the unrecognised headings recorded are the direct evidence for widening `classify_heading()`, which is now the binding constraint on D-03 |
| 2026-08-09 | Operator ruling on the D-03 fallback: stop reverting to flat extraction when no requirement heading is recognised. A refusal that surfaces the advert for review beats a plausible-looking wrong score. Expect MORE vacancies reported UNRELIABLE and fewer bogus ceiling=1.000 lines — that is the intended trade |
| 2026-08-09 | Rank pre-filter added on operator observation that irrelevant vacancies were consuming the hydration budget. Hydration moved out of `collect()`; vacancies are ranked by document similarity (one embedding, no API call) and only those above `rank_floor` are hydrated and scored. `coverage_gate` and `rank_floor` moved into config so ratcheting needs no code change |
| 2026-08-09 | Operator ruling: `git` reclassified Tier C -> B on changed evidence — sustained day-to-day use with an auditable commit history. Team workflow (pull requests, code review, branching strategy) split into `EXCLUDED_collaborative_git` and remains blocked. `pytest` NOT reclassified: the 500+ Vanguard tests were written by the assistant, not the operator, so claiming authorship would fail D1 in the assistant's own interview rubric |
| 2026-08-09 | Operator proposal: the regex flattener was too basic and should be replaced with structural parsing. Correct — flattening destroyed the heading-to-list binding, which is exactly what distinguishes a requirements list from a benefits list. `structure.py` added, using stdlib `html.parser`. Reed headings are inline `<strong>` followed by `<br /><br />`, not `<h3>`, so heading detection is length- and position-based. Verified against real Reed markup: 3 duty bullets and 2 benefit bullets correctly excluded, 2 requirements retained |
| 2026-08-09 | Operator observation while reading raw advert text: Reed returns HTML, and the closing date is stated in it. Two fixes followed — HTML flattened before extraction (recovering `<li>` requirement lists previously diagnosed as prose), and expired vacancies dropped before hydration. A Reed ML advert that previously extracted 0-1 terms now yields 7 and scores C=0.714 reliably |
| 2026-08-09 | Hydration budget bug (B-18): the per-board cap existed in config but no adapter read it. Both values are limits, so the smaller now wins — which resolves the case without touching the deferred B-01/D-01 precedence question |
| 2026-08-09 | Operator ruling: a board that cannot supply full advert text is not processed through its API — it defaults to operator paste. Implemented as `supplies_full_text`, validated at config load. Adzuna and Civil Service demoted; Reed retained via its detail endpoint. Board topology now 1 automatable, 3 manual |
| 2026-08-09 | First live run against Adzuna and Reed exposed B-04 and B-13. Reed search returns snippets, so extraction found 1-2 terms per advert and produced C=1.000 for irrelevant roles. Hydration added; unreliable scores can no longer pass the gate. Five further tests were found to depend on machine credentials — they passed only on an unconfigured machine |
| 2026-08-08 | CLI output defects fixed: fixed-width slicing cut mid-word and lost the operative half of exclusion reasons and adapter status; widths were hardcoded to ~100 columns; `run` printed seven skip lines before any result. Now word-boundary clipping, terminal-width detection, wrapped reasons, collapsed skips. Styling (rich tables, --json, GUI) deliberately deferred — see D-02 |
| 2026-08-08 | B-11/B-12 fixed: pagination added to both API adapters, truncation recorded rather than swallowed. Ceiling per run is now `max_results x keywords x boards`, defaults 100 x 3 x 2 = 600 before dedup. Two test doubles were themselves defective — a shared result pool across keywords, and assertions written for one keyword when board config supplies three (B-01) |
| 2026-08-08 | M6 complete. B-10 found during the first mail test: the stored vacancy id is a content hash, and the employer's real reference (19568) was extracted nowhere — stage 1 correlation was dead on arrival. Fixed |
| 2026-08-08 | First MiniLM run produced coverage identical to the lexical fallback (C=0.304), which surfaced B-06/B-07/B-08. After fixes: \|R\| 23 -> 21, C 0.304 -> 0.381. P-02 left at 0.75 on the evidence |
| 2026-08-08 | M5 complete: SQLite store, queue state machine, operator CLI. `vanguard paste` added — the manual adapter had no CLI entry point, which would have left LinkedIn unusable |
| 2026-08-08 | First PDF rendered. Compound hyphens (`cloud-based` -> `cloudbased`) were being lost from the text layer — an ATS miss and a coverage-engine miss. Fixed with U+2011 substitution in `protect_compounds()`. CSS tightened for two-page fit; orphans/widows added to keep role blocks together |
| 2026-08-08 | Skip guard for PDF tests corrected: tested package presence, not importability, so a missing GTK runtime failed instead of skipping |
| 2026-08-08 | B-01/B-02 deferred to D-01. Adaptive query configuration proposed as a separate project |
