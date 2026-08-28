# OUTSTANDING — Project Vanguard

Defects, deferrals and unverified assumptions raised during implementation.
Live document: add on discovery, strike on resolution.

**Scope: Project Vanguard only.** Work on other codebases belongs in their own
repositories.

Status: `OPEN` · `BLOCKED` · `DEFERRED` · `CLOSED`

**Last full audit: 9 August 2026.** 26 defects closed by running the system
against real data. 5 items open. Every claim below was checked against the
code and the live runs on that date — not carried forward on assumption.

---

## 1. Defects

| ID | Defect | Location | Severity | Status |
|---|---|---|---|---|
| B-01 | Board config overrides caller query. `cfg.get("what") or query.keywords` — a CLI-supplied job title is silently ignored | `adapters/adzuna.py:77`, `adapters/reed.py:66` | HIGH | **DEFERRED to D-01** — operator ruling: do not patch precedence in isolation |
| B-02 | Same precedence issue on location (`where`) | `adapters/adzuna.py`, `adapters/reed.py` | HIGH | **DEFERRED to D-01** |
| B-03 | `ingest()` has no board filter — cannot restrict a run to named boards | `ingest.py` | MEDIUM | OPEN — **CLOSED 22 Aug 2026 by N-18.** `vanguard run --board/--skip` narrows a run; `vanguard board enable/disable` makes it permanent. |
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
| B-26 | The queue list printed a coverage figure for scores that were never measured. Eleven records showed `C=1.000` at the top of the queue, which reads as the best match and means the opposite — one requirement extracted | `cli.py`, `store.py` | **HIGH** | **CLOSED** — unmeasured records show `not measured` and the term count; measured ones show their denominator (`0.429  9/21`). A footer counts the unmeasured and points at `vanguard diagnose` |
| B-27 | No operational logging. Errors caught to keep a run going — the Adzuna 401 and 503 among them — were lost with the terminal | `logs.py`, `cli.py` | **HIGH** | **CLOSED** — two stores: a structured `runs`/`events` database and a verbose rotating file. Hybrid rotation, time-led with a size backstop. Archive-not-delete retention. Enabled by default, overridable per run with `--log`/`--no-log` |
| B-28 | `parse_health()`, `refusal_counts()` and `unrecognised_headings()` counted every diagnostic row rather than the latest per vacancy. Reported "176 yielded requirements (533%), -143 refused" across 33 adverts | `store.py` | **HIGH** | **CLOSED** — all three aggregate over the latest row per vacancy. **Same defect as B-21**, which was fixed in `list_queue()` and left uncorrected here |
| B-29 | Eligibility conditions — right to work, sponsorship, security clearance — were treated as ordinary text. A role demanding DV clearance scored on fit alone, though it is unavailable to anyone without it | `structure.py`, `diagnostics.py`, `cli.py` | **HIGH** | **CLOSED** 10 Aug 2026 — `SectionKind.ELIGIBILITY` added, detected under headings AND in body prose, surfaced in `review` and `diagnose`. Never scored: only the operator knows their own status |
| B-30 | `_extract_structured()` skipped bullets under 8 characters, dropping single-tool requirements like `AWS`, `SQL`, `ETL` | `extract.py` | MEDIUM | **CLOSED** — the floor now applies only where no tool was recognised |
| B-31 | `enqueue()` overwrote operator decisions. An application DISPATCHED at 22:15 returned to PENDING after a run at 22:22, and `review` then offered `approve` on something already submitted | `store.py` | **BLOCKER** | **CLOSED** 10 Aug 2026 — `OPERATOR_SET` states (APPROVED, REJECTED, DISPATCHED) are preserved; machine-set states are still recomputed. Metadata still refreshes |
| B-32 | Every re-enqueue wrote a transition with no from-state. One vacancy accumulated 27 history lines, 24 of them identical `- -> PENDING` | `store.py` | HIGH | **CLOSED** — a transition is written only when the status actually changes, and records the real previous state |
| B-33 | Stale vacancies scored as though current. Reed returns the posted date on every result and nothing filtered on it — a DV Data Scientist role posted 18 days earlier reached the queue. `Query.max_days_old` existed and only Adzuna used it, which is now a manual board, so the setting did nothing at all | `adapters/base.py`, `boards.yaml` | **HIGH** | **CLOSED** 10 Aug 2026 — age filter runs before hydration, so a stale advert no longer spends an API call. Reed capped at 14 days. An absent date is treated as current: unknown is not stale |
| B-34 | The RESULT block reported the whole queue under a heading describing the run just completed — 543 records for a run that scored 14 | `cli.py` | **HIGH** | **CLOSED** 10 Aug 2026 — "this run scored N" and "queue total, all runs" are now separate, labelled blocks |
| B-35 | `test_health_check_reports_missing_credentials` cleared only the two `ADZUNA_` variables. When the assertion moved to `reed`, the clearing did not follow, so the test depended on whether the operator had `REED_API_KEY` set | `tests/test_ingest.py` | MEDIUM | **CLOSED** 12 Aug 2026 — `BOARD_CREDENTIALS` names every variable, with a test asserting it matches every `${VAR}` in boards.yaml |
| B-36 | Job adverts correlated to applications. `jobs-noreply@linkedin.com` advertising a Beatport vacancy matched a Beatport application, because fuzzy correlation only needs the employer name and a job title in the subject — which every advert has by construction | `mail.py` | **HIGH** | **CLOSED** 12 Aug 2026 — broadcasts excluded before any correlation stage, by sender local-part and subject pattern. Fuzzy matching additionally refuses job-board sender domains |
| B-37 | `employer_domain` was never populated, so sender-domain correlation could not fire. A named recruiter writing from the employer's own domain — the commonest shape of a real reply — fell through to fuzzy matching, which needs the employer name in the subject | `mail.py`, `cli.py` | **HIGH** | **CLOSED** — derived from the vacancy URL, excluding job-board hosts |
| B-36 | Fuzzy correlation attributed a LinkedIn job advert to an open Beatport application. The subject carried the employer name and job title, which was the whole test. Found on the first live poll | `mail.py` | **HIGH** | **CLOSED** 12 Aug 2026 — broadcasts filtered before correlation; fuzzy matching additionally requires the sender to be plausibly the employer. `no-reply@` is NOT treated as a broadcast: employers send genuine acknowledgements from such addresses |
| B-37 | Gmail Primary/Promotions/Social are not IMAP folders. `INBOX` returns everything, so a recent-N fetch is dominated by promotional mail and a genuine reply can fall outside the window entirely | `mailbox.py`, `cli.py` | **HIGH** | **CLOSED** 12 Aug 2026 — `category:primary` applied via `X-GM-RAW`, and the poll now SEARCHES for the employers and references of open applications rather than reading the most recent N. A missed reply is silent; a false positive is visible. This was the worse defect |
| B-38 | `X-GM-RAW` search sent as a quoted string. The query already contains double quotes around multi-word employer names, so the result was nested quotes and `BAD Could not parse command` — the poll returned nothing at all | `mailbox.py` | **HIGH** | **CLOSED** 12 Aug 2026 — sent as an IMAP literal with a byte count, which needs no quoting. Falls back to a plain SINCE search if the server refuses |
| B-39 | Four genuine acknowledgements failed to correlate — BambooHR for Beatport, Ashby for Sardine and Faculty, Reed for Method Resourcing. An ATS mails on the employer's behalf, so the sender domain is never the employer's and the employer name is in the SUBJECT | `mail.py` | **HIGH** | **CLOSED** 12 Aug 2026 — fourth correlation stage for known ATS domains, requiring applied-language so an advert from the same sender still does not qualify |
| B-40 | Poll search terms silently capped at 20, roughly ten applications' worth. Terms beyond that were dropped with no indication | `cli.py` | MEDIUM | **CLOSED** — raised to 120 and reported when hit |
| B-41 | `vanguard stats` reported a coverage distribution including unmeasured scores. Median 0.000 across 553 vacancies, and 65 records at or above 0.94 — none a genuine match. That distribution is the input to gate recalibration (P-01), so recalibrating would have set the gate from scores that measured nothing | `store.py`, `cli.py` | **HIGH** | **CLOSED** 12 Aug 2026 — the distribution excludes scores below MIN_TERMS_FOR_CONFIDENCE or from partial text; unmeasured records are counted separately. The gate reported is now read from config rather than hardcoded at 0.94 |
| B-42 | Vacancy ids were truncated in the queue list (`linkedin:a4a582bc5…`), so the row could not be acted on — the id is the input to every subsequent command | `ui.py`, `cli.py` | **HIGH** | **CLOSED** — `Column.protected` takes its full width before flexible columns are sized. The title absorbs the shrinking instead |
| B-44 | Sender-domain correlation compared against `employer_domain`, derived from the vacancy URL. A job-board URL correctly yields none — Reed is not the employer — so `hr@sanderson.com` did not correlate to an application at Sanderson. Since most vacancies come from boards, most genuine employer replies would have failed to correlate | `mail.py` | **BLOCKER** | **CLOSED** 12 Aug 2026 — falls back to comparing the sender domain against the employer NAME, on distinctive tokens of four characters or more. Common words are excluded so `services.com` does not match every employer |
| B-45 | Correlation picked the first match when several applications matched equally well. Two live applications at one employer and a reply with nothing to tell them apart would attach an interview invitation, or a rejection, to the wrong vacancy | `mail.py`, `cli.py` | **HIGH** | **CLOSED** 12 Aug 2026 — `Correlation.AMBIGUOUS` names every candidate and leaves the message queued. Ambiguity at one stage is carried forward so a later, more specific stage can still resolve it; where one job title contains another, the longer wins |
| B-46 | Cloned repositories were not deleted on Windows. Git marks `.git/objects` read-only; `rmtree(ignore_errors=True)` swallowed the failure, so every `vanguard evidence` run left a copy of the operator's source code in `%TEMP%`, permanently and silently | `repo.py` | **HIGH** | **CLOSED** 12 Aug 2026 — the error handler clears the read-only bit and retries, and a clone that still survives is warned about rather than ignored |
| B-47 | Repository name parsed by splitting on `/` only, so a Windows `file://C:/...` URL yielded the whole path as the name. An unnamed or mis-named repository cannot be cited in a proposal | `repo.py` | MEDIUM | **CLOSED** — splits on either separator |
| B-09 | Near-duplicate requirements survive dedup when the same bullet appears in two advert sections with different trimming | `extract.py` | LOW | OPEN |
| B-05 | Runs do not record which embedder produced them | `rank.py`, `coverage.py` | MEDIUM | **CLOSED** — `scores.embedder` column added in M5; `run`/`paste`/`score` all report it |

## 1a. Design proposals — index

Recorded, not scheduled. Full treatment in section 8.

| ID | Proposal | Raised | Supersedes |
|---|---|---|---|
| **D-01** | Adaptive query configuration | operator, 8 Aug | B-01, B-02 |
| **D-02** | CLI presentation layer | 9 Aug | — |
| **D-03** | Coverage assumes structured adverts | 9 Aug | B-17 (partly) |
| **D-04** | Repository history as CV evidence | operator, 12 Aug | — |
| **D-05** | Supportability as a separate product | operator, 12 Aug | — |

D-02 was implemented 9 Aug (`ui.py`); the remainder are unscoped.

## 2. Configuration

| ID | Item | Status |
|---|---|---|
| C-01 | `where: "{{ TARGET_LOCATION }}"` unresolved | **CLOSED** 9 Aug 2026 — operator ruling: `where: "UK"` for Adzuna, empty for Reed (its `locationName` carries a 10-mile default radius). Unresolved placeholders are also detected and treated as unset rather than sent literally |
| C-02 | Target keywords are `data scientist`, `machine learning engineer`, `network analytics`. Data engineering is excluded by the directive's target domains, but the operator's CV fits it well and the one real test advert is a data engineering role | OPEN — operator ruling |
| C-03 | Model names hardcoded in `rank.py`. Should be config if a fully airgapped setup is wanted (local filesystem paths instead of Hub repo IDs) | DEFERRED |

## 3. Verification — cleared on the operator's machine, 8-9 Aug 2026

| ID | Item | Consequence | Status |
|---|---|---|---|
| V-01 | WeasyPrint / CSS | **CLOSED** 8 Aug 2026 — GTK3 installed, two-page PDF rendered and inspected. Three defects found and fixed in the process: compound hyphens lost from the text layer, 3-page overrun, role split across a page break |
| V-02 | pypdf / anonymisation scan | **CLOSED** 8 Aug 2026 — `render_anonymised()` produced a clean PDF and the text-layer scan passed against it |
| V-03 | sentence-transformers / stage 3 | **CLOSED** 9 Aug 2026 — MiniLM scoring live. Runs record which embedder produced them. The first real run surfaced B-06/B-07/B-08 |
| V-04 | httpx / live API calls | **CLOSED** 9 Aug 2026 — Adzuna and Reed both credentialed and returning real vacancies |
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
| N-06 | Mailbox connection | **CLOSED** 12 Aug 2026 — `mailbox.py` with both IMAP and Gmail providers behind one interface, since the operator maintains several CVs with different addresses. Monitored address derived from the CV in use rather than configured separately. Read-only |

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
| P-08 | `SEMANTIC_THRESHOLD` / `SEMANTIC_MARGIN` | **0.60 / 0.04 — MEASURED** | **AUTHORED.** Below it a message is left AMBIGUOUS, which asks the operator to read it; above it a state is assigned on similarity alone. Tune against classified mail once there is enough of it |
| P-07 | Mail `window_threshold` | 40 | **ESTIMATE.** 40 applications is ~80 search terms, still a short query. The right value depends on how much non-application mail arrives in the monitored tab. Revisit once the operator is running at the intended 75 applications/day |
| P-06 | Template F structure | — | Derived from **one** MoJ advert. Verify against a second before generalising |

## 6. Operator confirmations outstanding

| ID | Item | Basis | Status |
|---|---|---|---|
| N-07 | `/Pipeline_Archive/` specified in directive §5, never implemented. Every application dispatched during Phase 1 left no record of what was submitted | **CLOSED** 12 Aug 2026 — `archive.py`, written at dispatch, one subfolder per vacancy. **Directive §5 amended to match**, with an amendment record; the code and the governing document now agree |
| N-08 | Batch ingestion. At the operator's intended 75 vacancies/day, ~95% pasted, `vanguard paste` one file at a time was the bottleneck — roughly 70 invocations a day | **CLOSED** 12 Aug 2026 — `vanguard adverts` group: a watched folder with a manifest keyed by filename, bulk registration from CSV, and a single-pass ingest. Enforcement is at ingest, not at the filesystem: nothing can prevent a file being dragged in, but a file with no valid entry is never ingested |
| N-09 | Multi-round interview tracking. The model handled one message and one classification; an interview is several rounds over weeks, and nothing knew when to stop monitoring | **CLOSED** 12 Aug 2026 — `process.py`. Opens on the first PROGRESS, closes only on OFFER, DECLINE or operator withdrawal |
| B-43 | No `OFFER` classification state. A job offer fell through to AMBIGUOUS — the single worst message to leave unclassified, and the one that terminates a process | **CLOSED** — added between DECLINE and PROGRESS, because an offer routinely invites a further conversation and would otherwise read as another interview round |
| N-10 | Phase 2 B — repository evidence loop. Local paths **and repository URLs**: a remote is cloned to a temporary directory, scanned, and the clone removed | **CLOSED** 12 Aug 2026 — `repo.py` and `vanguard evidence`. The narrow form of D-04: own repositories only, artefacts rather than commit counts, one proposal per competency, every proposal operator-confirmed. Verified against this repository: proposes testing and documentation, proposes NOTHING for AWS, Azure, Terraform, Docker or Kubernetes, because none exist here |
| N-11 | Phase 2 C — application channel | **CLOSED** 12 Aug 2026 — `channel.py`, `vanguard apply`, `vanguard registrations`. Classification from URL with advert phrasing overriding it; registration state per board and per employer portal, asserted never detected; pack assembly with eligibility surfaced first; recurring answers as a recall aid. **No automated form-filling**, enforced by a test |
| N-12 | Working a queue was O(N) in INVOCATIONS. Fifteen PENDING records meant thirty commands and thirty copied ids | **CLOSED** 16 Aug 2026 — `vanguard session` walks a filtered queue in one invocation; `approve` and `reject` accept filters with a mandatory preview. The decisions are not batched and should not be: fifteen vacancies is fifteen judgements, and approving is where a claim is made on the operator's behalf |
| N-13 | No single view of what is waiting to be acted on, and no guide for the steps after `session`. The operator had to switch between two commands to answer "what now?", and the guides stopped at review | **CLOSED** 17 Aug 2026 — `vanguard todo` lists APPROVED then PENDING in one view; `HOW_TO_APPLY.md` covers todo → apply → dispatch → poll |
| B-48 | `vanguard session` reported "nothing in PENDING matches" when the queue held records that were filtered out for being unmeasured. Reads as "the queue is empty", which is wrong — and most FLAGGED records are flagged BECAUSE they are unmeasured, so resolving them produces exactly this state | **CLOSED** — an empty result now states how many records are there, how many were excluded and why, and names `--include-unmeasured` |
| N-14 | Nothing re-scored stored vacancies. `vanguard run` only scores what a board returns today, so after a CV edit every pasted vacancy — and every delisted one — kept a score computed against the old CV | **CLOSED** 17 Aug 2026 — `vanguard rescore` works from the stored advert text, so no board is contacted and no API call is spent. Operator decisions survive: a CV edit does not undo one |
| N-15 | Template B existed and was tested but nothing called it — no cover letter could be produced. Its opening was also fixed text, identical on every application | **CLOSED** 17 Aug 2026 — `letter.py` and `vanguard draft`. The opening names what the role asks for THAT THE CV CAN EVIDENCE, drawn from matched requirements rather than copied from the advert. Bullets are CV lines ranked by how many requirements each answers, one per subject, condensed to a strict subset of the CV line |
| B-50 | `vanguard draft` crashed on writing the file — `re` was used at module scope but never imported. The letter drafted correctly; only the write failed. `--show` was tested and the file path was not | `cli.py` | MEDIUM | **CLOSED** 17 Aug 2026 — imported, and a test now lets the command actually write a file. Every command that writes one needs a test that exercises the write |
| B-51 | `vanguard dispatch` refused a second run, so an operator who dispatched and then realised the cover letter was not attached had no way to add it. The state machine was right to refuse the transition; the archiving should not have been blocked with it | `cli.py` | MEDIUM | **CLOSED** 19 Aug 2026 — an already-DISPATCHED record skips the transition and archives into the existing folder. One transition, one folder, more files |
| B-54 | `vanguard poll` crashed reading `message.received_at`; the field is `received`. This broke poll entirely, not just the new response recording. The poll tests skip without credentials, so nothing exercised the path | `cli.py` | **BLOCKER** | **CLOSED** 19 Aug 2026 — corrected, and two tests added: one exercising the recording with a message built as poll builds one, and one asserting that every `message.<attr>` read in `cli.py` exists on `Message` |
| B-65 | Routing-token extraction worked for BambooHR and failed for three other vendors. Splitting on every separator shredded Lever's UUID into five short pieces, and a hex-only rule missed Ashby's mixed-case tokens entirely | `mail.py` | MEDIUM | **CLOSED** 20 Aug 2026 — **operator-identified.** Judged on shape rather than per-vendor pattern: UUIDs matched whole before splitting, mixed alphanumerics accepted at a higher length, and words identifying nothing excluded. Verified against seven vendors |
| B-83 | `Store.initialise()` runs on every command and was re-running the response deduplication each time — a DROP INDEX, UPDATE, DELETE and CREATE INDEX per invocation. Once the index exists the collapse has happened, and the ON CONFLICT clause on every write keeps it correct | `store.py` | LOW | **CLOSED** 22 Aug 2026 — skipped where the index is present. 11ms to 1ms per command, and it is paid by every command, not only by tests. Test fixtures also reduced from sixty records to twelve: what was under test was ordering and paging arithmetic, neither of which needs volume |
| B-81 | `vanguard review --status FLAGGED` returned fifty of 523 records, ordered by rank — which is meaningless for a record flagged BECAUSE its score could not be measured. The operator saw a tenth of the queue, in arbitrary order, with no indication either was happening | `store.py`, `cli.py` | **HIGH** | **CLOSED** 22 Aug 2026 — **operator-identified.** `--sort` with five orderings, defaulting to date for anything unscored; `--limit 0` for all; and the hidden remainder is counted and named |
| B-82 | A `click.Choice` option with `default=""` rejects its own default and the command fails before doing anything. Made three times — `--strategy`, `--remote`, `--sort` — each found by the operator | `cli.py`, `tests` | MEDIUM | **CLOSED** — a structural test now walks every choice option and asserts its default is valid |
| B-80 | Semantic classification computed similarities pairwise: sixty decision lines against forty-five references is 2,700 dot products of 384-dimensional vectors in pure Python, per message. Three seconds each, and most of the cost of classifying a mailbox. The B-79 caching fix addressed the model load and saved only six seconds because the load was never the problem | `mail.py` | LOW | **CLOSED** 22 Aug 2026 — embedded once and multiplied as a matrix, with the loop retained for an embedder exposing no `embed`. Verified identical to ten decimal places, same winning line, with numpy present and absent |
| B-79 | `_embedder` loaded MiniLM afresh on every call, and several commands ask for it. One test cost 21 seconds of a 107-second suite; the same waste applied wherever a command asked twice | `cli.py` | LOW | **CLOSED** 22 Aug 2026 — cached per process, keyed on the preference so `--no-model` is unaffected. The model is stateless once loaded, so reuse changes nothing but the time. **Found by measurement** after two rounds of guessing at the cause |
| B-78 | Three near-identical Reed dispatch receipts classified ACK, AMBIGUOUS and AMBIGUOUS. Their bodies differ only in a "recommended jobs" block, which moved the scores a few hundredths either side of the margin — a fixed string decided by a coin flip. A Workable receipt echoing the submitted form classified QUERY, because the applicant's own answers were read as the employer asking something | `mail.py` | **HIGH** | **CLOSED** 22 Aug 2026 — **operator-identified.** Board dispatch receipts and submission confirmations are matched deterministically. A board's receipt is a small closed set, unlike employer phrasing, so a marker is the right tool and semantics the wrong one |
| B-77 | A record written with a wrong DECISIVE state was permanent. `reclassify` only touched provisional states, so seven acknowledgements frozen as DECLINE and OFFER by an earlier classifier could never be corrected — the classifier was reading them right and the store was ignoring it | `store.py`, `cli.py` | **BLOCKER** | **CLOSED** 22 Aug 2026 — `reclassify --force`. Off by default, because overwriting a decision the operator has acted on is not something to do silently |
| B-76 | **Seven of twenty-six responses were acknowledgements given a decisive state** — DECLINE, OFFER, QUERY and ADMIN. Not seven defects but one: sentence embeddings rank TOPIC above polarity, so "We've sent your application to Sanderson" and "We will not be taking your application any further" score close together, and a 0.55 threshold read the gap as a decision | `mail.py` | **BLOCKER** | **CLOSED** 22 Aug 2026 — thresholds set from MiniLM scores on the operator's own mail, verified against all five; `responses --explain` supplies the numbers. Originally raised to 0.72 and a margin of 0.08 required over the next state; `responses --explain` exposes the scores. **Both numbers are still authored.** They must be set from the operator's real mail, which is what `--explain` exists to supply |
| B-75 | An ATS submission receipt classified AMBIGUOUS. Workable confirms a submission rather than thanking the applicant — "Your application for the Associate Data Scientist job was submitted successfully" — and no ACK marker covered that wording | `mail.py` | MEDIUM | **CLOSED** 22 Aug 2026 — submission wording added to the markers and to the references. The whole Ki thread is now a test: two acknowledgements and a decline, kept together because the value is in the sequence |
| B-74 | Acknowledgements classified **OFFER** — a regression introduced by the B-72 fix, which let any decisive state win "whenever it clears the bar". A warm welcome scoring just above threshold against "we are pleased to offer you the position" beat the same message scoring far higher against an acknowledgement | `mail.py` | **BLOCKER** | **CLOSED** 22 Aug 2026 — **operator-identified.** A decisive state now needs a clearly higher score to override, and OFFER is unreachable by meaning at all. A false offer could stop the operator applying elsewhere; a missed one is recoverable |
| B-72 | Pflegia's rejection classified ACK. It opened "Thank you for your interest in the position" and closed "we are not able to move forward in the recruiting process with you" — the opener is formulaic and matched an acknowledgement reference closely, the rejection is oddly worded and matched less closely, and the single highest score won | `mail.py` | **HIGH** | **CLOSED** 22 Aug 2026 — **operator-identified.** The best score is taken per state, and a decisive state outranks a provisional one whenever it clears the threshold |
| B-73 | A recruiter digest still correlated: "Technical Lead ML at Bjak + Lead Data Scientist at Ki" carried no listing marker and matched an employer on sender domain | `mail.py` | MEDIUM | **CLOSED** — a subject naming two or more roles is a listing by SHAPE. No acknowledgement mentions two employers |
| B-71 | An application to a company called **Ki** never appeared at all. Three independent length gates excluded a two-character employer name: it was never built into the search query, `_domain_resembles_employer` required a four-character token, and the ATS stage required three. The floors were written for routing tokens and applied to employer names by accident | `cli.py`, `mail.py` | **HIGH** | **CLOSED** 22 Aug 2026 — **operator-identified.** Any name of two or more characters is searched for and can correlate. Short names match at a word boundary, so `ki` finds Ki without matching `working`, `skills`, `taking` or `wiki.com` |
| B-69 | An acknowledgement classified DECLINE. Faculty's confirmation explained its own process — "We will then either invite you to an introductory video call, or let you know we will not be progressing your application on this occasion" — and `will not be progressing` matched as a marker. A described outcome is not a decision, and a false DECLINE drafts a feedback letter for a rejection nobody sent | `mail.py` | **HIGH** | **CLOSED** 21 Aug 2026 — conditional framing excluded from both markers and meaning, checked per sentence so a real rejection can still explain what happens next |
| B-70 | Faculty's genuine rejection was stored ACK and could never change. The write path only replaced AMBIGUOUS, so a correct DECLINE was discarded on every poll | `store.py`, `cli.py` | **HIGH** | **CLOSED** — a DECISIVE state now replaces a PROVISIONAL one (AMBIGUOUS, ACK, ADMIN). A decided state is never overwritten. `vanguard funnel` counted two rejections where three had declined, for this reason alone |
| B-68 | A rejection written as a subordinate clause scored below threshold. WPP Media wrote "While the team has decided to proceed with other candidates, we want to assure you that your skills, dedication, and the impact you are making are deeply valued" — the decision is one clause and the rest is reassurance. Scored whole: 0.80. The clause alone: 0.96 | `mail.py` | **HIGH** | **CLOSED** 21 Aug 2026 — long sentences are also offered as clauses. Verified the matching WPP acknowledgement still classifies ACK, and that more candidate strings did not make classification eager |
| B-67 | Widening the classifier changed nothing visible. `record_response` used `ON CONFLICT DO UPDATE` and updated `body`, `message_id` and `tokens` but **not `state`** — so every re-poll re-classified correctly and threw the result away. The state was frozen at whatever the first poll decided | `store.py` | **BLOCKER** | **CLOSED** 21 Aug 2026 — an AMBIGUOUS record accepts a better classification; a decided one is never overwritten. `vanguard reclassify` re-runs over stored bodies without a mailbox |
| B-66 | Classification used a phrase list of five DECLINE markers while correlation had been widened to fourteen phrases and five stages. "While the team has decided to proceed with other candidates" — an unmistakable rejection — matched nothing, and nine of fifteen responses sat AMBIGUOUS | `mail.py` | **HIGH** | **CLOSED** 21 Aug 2026 — **operator-identified.** Semantic classification on the local embedder, as a fallback where no marker fires. Rules stay first because they are deterministic and explainable; meaning catches the wording nobody anticipated. Verified not to classify job alerts, bank statements or newsletters |
| B-64 | Correlation read wording when the headers stated the answer. An ATS puts a per-application identifier in `Reply-To` — `job+<hash>+124894@app.bamboohr.com` — and every message about that application carries it. The system was inferring from subject phrasing what the header says outright | `mail.py`, `mailbox.py`, `store.py` | **HIGH** | **CLOSED** 20 Aug 2026 — **operator-identified.** Routing tokens are extracted from `Reply-To`, recorded against the application, and checked before every other stage. A subject reading "A quick note from Rob" now correlates |
| B-62 | A Beatport reply from a named person — "Thank you for your interest in Beatport", via BambooHR, 18 Aug — correlated to nothing. The ATS stage requires an applied-phrase and the list knew only "applying" and "application"; employers write "interest" as often, and it is the standard opener for a REJECTION, which is the worst message to lose | `mail.py` | **HIGH** | **CLOSED** 20 Aug 2026 — fourteen further phrases, verified not to admit adverts |
| B-63 | `poll --show-uncorrelated` displayed forty of 87 with no indication it had truncated. The missing reply sat in the hidden portion for two days while the operator read the visible forty | `cli.py` | MEDIUM | **CLOSED** — the remainder is counted and reported |
| B-60 | Human replies did not correlate. Every stage was tuned for machines — a reference, an employer domain, an applied-phrase, an employer-plus-title subject — so a person writing "Re: next steps" from a personal address matched nothing, while replying to a message the system had ALREADY correlated. Beatport sent an automated acknowledgement and then a human reply; only the first was seen | `mail.py`, `mailbox.py`, `store.py`, `cli.py` | **HIGH** | **CLOSED** 20 Aug 2026 — thread correlation as the first stage, on `In-Reply-To` and `References` with a subject-root fallback. `Message` now captures both headers |
| B-61 | A recruiter newsletter reached round five of an interview process. "Two fresh DS leads in Edinburgh + application update" was exempted from the broadcast filter by the phrase "application update", correlated on sender domain, and classified PROGRESS — five times | `mail.py` | **HIGH** | **CLOSED** — a subject that both advertises roles and mentions an application is a listing, and a listing subject is a broadcast whoever sent it. A small recruiter mails from `hello@`, so the sender said nothing |
| B-59 | Message bodies could not be backfilled. `INSERT OR IGNORE` skipped any message already recorded, so the thirteen responses captured before bodies were kept could never gain one — the retention feature was useless for every message the operator actually had | `store.py` | **HIGH** | **CLOSED** 19 Aug 2026 — `ON CONFLICT DO UPDATE` fills a MISSING body on a later poll without duplicating the row, and never overwrites one already stored |
| B-58 | The B-55 fix left duplicates in place. Keying on the mailbox's message id created TWO schemes: rows written before the id was captured carried a synthetic key, rows after carried the real one, and the same message survived under both | `store.py` | **HIGH** | **CLOSED** 19 Aug 2026 — keyed on the NATURAL identity of a message (vacancy, sender, subject, received time), which is stable across the change and across a mailbox supplying no id. `message_id` is still stored, for tracing |
| B-55 | `vanguard responses` showed every reply twice. The table had no message id and no unique constraint, so each `poll` re-recorded everything it read. **Third occurrence of this class** after B-21 (score history multiplied queue rows) and B-32 (every re-enqueue wrote a duplicate transition) | `store.py` | **HIGH** | **CLOSED** 19 Aug 2026 — keyed on (vacancy_id, message_id) with `INSERT OR IGNORE`; where the mailbox supplies no id, sender, subject and time identify the message. Existing duplicates are collapsed on migration, keeping the earliest row so `recorded_at` says when the reply was first seen |
| B-56 | `test_poll_reports_which_strategy_it_used` connected to the operator's REAL mailbox. Its docstring said "with no credentials" and nothing ensured there were none, so on a configured machine the test logged into Gmail and read email — 32 seconds of a 94-second suite, non-deterministic, and touching data no test should touch | `cli.py`, `tests` | **HIGH** | **CLOSED** 19 Aug 2026 — `VANGUARD_NO_ENV_FILE` suppresses the file, the test sets it, and a structural guard asserts any test invoking `poll` does the same |
| B-57 | `test_reed_rate_limit_records_truncation` slept for real on a 429, costing six seconds. The behaviour under test is that truncation is recorded, not that the sleep happens | `tests` | LOW | **CLOSED** — the limiter's sleep is replaced. 6.5s to 0.6s |
| B-52 | Nothing recorded that a reply arrived. Classifications went to the archive as files and to the interview process, but were not queryable — the operator could not ask "what has been rejected?", which is what `vanguard feedback` needs | `store.py`, `cli.py` | **HIGH** | **CLOSED** 19 Aug 2026 — `responses` table, written by `poll`, and a `vanguard responses [--status]` command |
| B-53 | `vanguard feedback` hardcoded `State.DECLINE`, so it drafted a rejection response for any vacancy id including ones that had rejected nothing | `cli.py` | **HIGH** | **CLOSED** — requires a recorded DECLINE, with `--force` for a rejection that arrived by phone or portal |
| B-49 | Linking a matched requirement back to the CV bullet that satisfies it is not recorded anywhere. The coverage engine stores a text window, often from the summary paragraph rather than any bullet | `coverage.py` | MEDIUM | **OPEN** — worked around in `letter.py` by using the alias table's `cv_evidence` where a requirement resolved through it, and word-stem matching otherwise. Real adverts draft well; sparse synthetic ones can fail to find three bullets. The proper fix is for the resolver to record which bullet satisfied each requirement |
| N-21 | The registration template wrote three empty columns, so every advert's employer had to be re-typed from a file that already named it | **CLOSED** 22 Aug 2026 — **operator-identified.** Employer and title are read from the advert; LinkedIn's byline (`Sagacity · London · 2 weeks ago`) carries the employer in its first segment. A guess is refused rather than made: bulleted lines match the byline shape exactly and mean nothing, and a wrong pre-fill nobody notices is worse than a blank cell. The URL stays blank because no advert contains its own address |
| N-19 | `vanguard search` — builds board search URLs and prints them. **Nothing is fetched.** LinkedIn's User Agreement prohibits automated COLLECTION, not searching; building a URL is writing down where to look. A structural test asserts no HTTP client ever enters that module | **CLOSED** 22 Aug 2026 — **operator-identified.** Windows from 6 hours to a month, with location, remote, contract type and seniority. LinkedIn wants seconds in `f_TPR`, Indeed wants days in `fromage`; the module remembers which |
| N-20 | `vanguard discover` — lists vacancies from a board that cannot supply scoreable text, recording employer, title, salary and URL. `vanguard paste --id` then fills in the advert against a record that already knows the rest, removing the search and the re-typing | **CLOSED** 22 Aug 2026 — Adzuna restored to `api_official` with `discovery_only: true`. The 9 Aug demotion to `manual` put a CAPABILITY limit in the field meant for TERMS, and the two are separate fields on the same dataclass. That conflation cost the discovery route for six weeks |
| N-18 | Board selection. `boards.yaml` could only be edited by hand, so trying a board out meant a permanent change | **CLOSED** 22 Aug 2026 — `vanguard run --board/--skip` for one run, `vanguard board enable/disable` for a permanent one. The permanent edit changes only the `enabled:` line, preserving every note — the notes record why a board is at its tier |
| N-17 | Listings were chronological only. An operator scanning a list is almost always looking for one company, and a chronological order makes that the one thing you cannot do | **CLOSED** 21 Aug 2026 — `--sort` on `responses`, `poll` and `funnel`, defaulting to employer. `state` orders by what needs attention rather than alphabetically; `via` shows which correlation stage matched, and that column is now displayed rather than only sortable |
| N-16 | Application lifecycle. A round was not a stage — "round 2" said nothing about whether it was a phone screen, a take-home or a panel — and every rejection looked alike, so rejected on the CV and rejected after a final panel were the same state | **CLOSED** 20 Aug 2026 — `lifecycle.py` and `vanguard funnel`. Stages inferred from the invitation, outcomes from what follows, and **reasons never inferred**: a stated reason is kept verbatim, softeners are excluded, and where none was given the record says so |
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

### D-02 — CLI presentation layer

**Status:** IMPLEMENTED 9 Aug 2026. `ui.py`, stdlib only.

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

### D-04 — Repository history as CV evidence

**Status:** NOTED. Not scoped, not designed.

Operator proposal, 12 Aug 2026: commit history is evidence of work in a way a
CV bullet is not — timestamped, sequenced, and hard to fabricate after the
fact. And repositories hold more than code: documentation, notebooks,
infrastructure-as-code, runbooks, papers.

Precedent exists in this project. `git` moved Tier C -> B on 9 Aug because
sustained commit history had accumulated. That judgement was made by hand;
D-04 asks whether it can be sourced from the repository directly.

> **Observations recorded 12 Aug 2026.** Not a design, not a scope. Whoever
> scopes D-04 owns every choice below and is free to discard all of it.

**The narrow version, which is tractable now.** Read the operator's own
repositories to propose CV bullets. Vanguard itself has a 700-test suite, a
documented architecture and a defect register, none of which appears on the
canonical CV. Attribution is certain — the operator's machine, the operator's
repository — so this is a Type 1 proposal generator sourced from evidence
rather than from semantic similarity.

**The broad version, which is not.** Scoring any applicant's public repository
as part of a supportability assessment. Three difficulties, the third
disqualifying on its own:

| Difficulty | |
|---|---|
| Activity is not competence | A thousand commits may be careful iteration or committing every save |
| Attribution is unreliable | Forks, squashed merges, pair work, work accounts. This project's own commits are authored as `Scarfacee8900` while the CV cites `Olu-SHABA` — a naive tool finds nothing |
| **Coverage bias** | Public repositories favour open-source contributors and employers who permit publication. Most enterprise work sits behind a firewall. A twenty-year network engineer has no public footprint and is not less qualified for it |

**The framing that survives all three: corroboration, not scoring.** A
repository may *support* a claim the CV already makes. Its absence supports
nothing either way. "The CV claims Python; the linked repository shows 400
Python commits over 18 months" is a legitimate signal. "No repository,
therefore weaker" is a discrimination problem wearing a score.

Open questions:

1. Which artefacts count as evidence for which competencies, and who decides?
2. How is authorship established when commit identity differs from CV identity?
3. Does a private repository count if the operator vouches for it?
4. Does this belong in Vanguard at all, or in the separate supportability
   product noted under D-05?

---

### D-05 — Supportability as a separate product

**Status:** NOTED. Not scoped. Commercial direction, not a Vanguard feature.

Discussed 12 Aug 2026. Vanguard's truthfulness controls answer a question no
applicant-facing tool wants answered: *is this claim actually supported by the
rest of the document?*

Applicants want a higher score. Employers want a truer one. The controls built
here are aimed the wrong way for the former and the right way for the latter.

Market check, same date: the existing tools detect **who wrote** a document —
Originality.ai, GPTZero, Copyleaks and similar — with false positive rates of
20-30% on resumes, because short documents give too little text for
statistical patterns. Assessing internal consistency is a different question
and does not have that failure mode.

The distinction the industry has settled on is AI-as-editor (accepted) versus
AI-as-ghostwriter (treated as misrepresentation, where the candidate cannot
defend the bullets). The second is exactly what the Type 3 rule identifies.

**The property worth preserving if this is ever built: it explains itself.**
Every Tier C entry in `alias_table.yaml` carries a written reason. A
supportability score that cannot say *why* is another opaque number, and the
market has plenty.

**The caution.** Unsupported is not untrue. The operator's own CV said "cloud
computing" in a catch-all line — thin, not false. Applied to one CV that costs
an application. Applied to 400 strangers it decides who gets read, and the
people worst served would be those who write plainly rather than fluently.
Which correlates with things no hiring filter should correlate with.

So the defensible product is a **flag, not a filter**: *"here are the claims
nothing else in this document supports"*, surfaced to a human who decides.
The same architecture as Vanguard — the system reads, the human decides.

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
| 2026-08-12 | Directive §5 amended by operator ruling. The original specified a flat employer folder, which overwrites on a second application to the same employer, and archiving at approval, which records applications never sent. Its own prose already referred to "the vacancy folder" while the diagram showed a flat one — the amendment resolves that inconsistency. An amendment record is now kept at the foot of the directive |
| 2026-08-12 | First real poll: 300 messages, 297 uncorrelated, and every one a broadcast — no genuine employer reply in the inbox at all. The three that DID correlate were LinkedIn adverts. Operator observed the results looked like Gmail's Promotions tab; IMAP has no tabs, so INBOX returns everything and the most recent 300 were dominated by alerts. Both defects found were in correlation, not in polling |
| 2026-08-12 | B-46 found by the operator's Windows test run. Two of the three failures were real defects rather than platform quirks: clones were never being deleted, and `ignore_errors=True` meant nothing said so. A tool that copies source code to a temporary directory and leaves it there had to be caught — and only running on Windows caught it |
| 2026-08-22 | Operator's criticism, accepted: each fix had been tested against the single message that prompted it and never against the ones already working, and B-74 was a regression caused that way. Seven misclassifications were being treated as seven defects when they were one — the semantic threshold was set by judgement and never measured. `--explain` was added so the next change is made from numbers rather than from another guess |
| 2026-08-21 | The operator's objection to phrase lists was correct and general: a list of markers is a treadmill where every new employer wording is a defect, and the last four mail defects were all of that shape. The system already carried a local embedder, kept off any API because the CV holds personal data — mail holds more. Rules remain first for explainability; meaning is the fallback. AMBIGUOUS is retained as the honest answer where neither is sure |
| 2026-08-20 | The lifecycle work drew a line worth recording. WHERE an application failed is inferrable and reliable; WHY it failed usually is not, because rejections give no reason. Extracting a stated reason verbatim is honest; generating one from an email that states none would be manufacturing authoritative-sounding content, which is the failure this system exists to prevent. The aggregate answers the question the individual email cannot: twelve of twenty ending at CV stage says more than any rejection letter |
| 2026-08-20 | B-64 came from the operator reading the raw headers of a message the system had missed and asking why correlation was not using them. It was the right question: four stages of phrase-matching were approximating what `Reply-To` states exactly. A lesson about where to look — the wording was the visible thing, and the headers were the reliable one |
| 2026-08-19 | B-55 is the third time a table has multiplied rows because a repeated operation had no idempotency key. The pattern: anything read repeatedly from an external source — a mailbox, a board, a re-scoring run — writes duplicates unless something identifies what has already been seen. Worth checking on every new table rather than after the operator notices |
| 2026-08-19 | B-54 is the second field-name assumption this session — `source_id` in `letter.py`, `received_at` here. Both were written without checking the dataclass. The second reached the operator and broke a working command. The new guard is structural rather than behavioural: it reads every `message.<attr>` out of `cli.py` and asserts each exists on `Message`, so the same class of mistake fails the suite rather than the terminal |
| 2026-08-17 | The guide-index guard produced a false positive: it demanded `OUTSTANDING.md` list every guide, because the log entry recording that a guide was written counted as a reference. "Mentions a guide" was too loose — an index names SEVERAL. Scoped to two or more, which separates a table of contents from a passing mention. A guard that fires on correct work trains the operator to ignore it |
| 2026-08-17 | Operator hit B-48 after resolving FLAGGED records: `session` said nothing matched while the queue held three. The filter was correct; the message was not. Also asked for a combined view of what is waiting and documentation of everything after `session` — both were genuine gaps, since the guides ended at review and the operator was left to work out applying for themselves |
| 2026-08-16 | Operator identified the queue bottleneck and framed it as O(N) to O(log N) by analogy with vectorisation. The framing needed correcting — vectorisation is a constant-factor win, not a complexity change, and fifteen decisions cannot be compressed below fifteen without the system deciding for the operator. The bottleneck was real but was in the INVOCATIONS, not the decisions. Both were addressed: `session` for many decisions in one invocation, filtered bulk operations for one decision across many records |
| 2026-08-16 | Operator clarified the project's intent: not for a single CV or a single job type. That reframes it — the value is not matching one CV to vacancies but comparing SEVERAL profiles against a corpus, and reporting the distance. `docs/PHASE_3.md` specifies it: profile-keyed scoring, trend analysis, and a positioning report. Certification recommendations are explicitly out of scope — that mapping is maintained, not derived, and stale advice costs months |
| 2026-08-12 | Operator asked whether the documentation guards themselves can drift. Three of them could: the phase mapping, the working-directory list and the reference-document list were all hardcoded — the same failure the guards exist to prevent, one level up. All three now derive from the repository: phases from the module names in their own headings, directories from `.gitignore`, reference documents from whichever already link a guide. Verified by reverting a phase heading and watching the guard fire |
| 2026-08-12 | **Phase 2 complete.** C built to the specification's "brink of autonomous" scope: the system establishes what kind of application this is, whether the operator holds an account and what they will need, then gives them the URL and stops. Automated form-filling stays out of scope, and a test now asserts `channel.py` contains no HTTP posting, no browser automation and no `selenium` — the constraint is in the suite rather than in anyone's memory |
| 2026-08-12 | Phase 2 B built. The constraint held in its first real test: scanned against the twelve recurring unmet requirements, it proposed bullets for pytest and documentation and nothing at all for AWS, Azure, GCP, Docker, Terraform or Kubernetes. A repository evidences only what was built, and the top of the gap list is a cloud platform gap no amount of mining can close |
| 2026-08-12 | B-45 found in the same run as B-44: the reply correlated to `reed:57205320` rather than the dispatched `reed:57092035`, both at Sanderson. Stage 2 identifies the EMPLOYER; it cannot identify which vacancy when an operator has two open at one company. Now surfaced rather than guessed |
| 2026-08-12 | B-44 found by the operator running the interview loop end to end with a realistic message. The system correctly refused to correlate a subject with nothing identifying in it — but testing that exposed a far worse case: a real employer reply from a real employer domain also failed, because the employer domain is only known when the vacancy was hosted on the employer's own site. Almost none are |
| 2026-08-12 | A.3 complete: multi-round interview tracking. Building it surfaced B-43 — there was no OFFER state at all, so a job offer classified as AMBIGUOUS. Ordering matters: OFFER is checked before PROGRESS, since "we would like to offer you the position, and would like to arrange a call" contains progress phrasing and is not another round |
| 2026-08-12 | B-41 is the fifth instance of the same shape: a figure that looks like it measures one thing and measures another. Previously C=1.000 in the queue, the 533% parse rate, FLAGGED 520 for a run that scored 14, and the diagnostics aggregates. Each time the underlying data was correct and the framing was not. B-42 came from the same run — an id truncated to fit a column is an id that cannot be used |
| 2026-08-12 | Batch ingestion built ahead of A.3, on the reasoning that at 70 pastes a day the ingest path is the bottleneck and the interview path is weeks away. The advert manifest designed earlier and paused was completed: filename as primary key (sound, since a directory cannot hold two files with the same name), employer and url held in the manifest rather than in the advert text, and entries destroyed when their file is removed |
| 2026-08-12 | Operator stated the intended test volume: 75 vacancies reviewed and applied for per day, ~95% by pasting. At that rate a targeted mail search becomes a thousand-term query within a week and hits IMAP command length and Gmail's query limits. Two strategies now, switching automatically: targeted below 40 open applications, window above. The threshold is authored and labelled as such (P-07) |
| 2026-08-12 | The Gmail primary search worked and immediately exposed B-39: four real acknowledgements, none correlated. The distinction missed was between a job board ADVERTISING a vacancy and an ATS ACKNOWLEDGING an application — both are third parties naming an employer, and the plausibility check treated them alike. They separate on intent, which is visible in the subject |
| 2026-08-12 | First live poll surfaced B-36 immediately: `jobs-noreply@linkedin.com` advertising a Beatport vacancy was correlated to the open Beatport application. An advert, not a reply. Filed under that application it would have been archived as correspondence and, had the wording matched, classified as a decline. The operator also identified B-37 — that Gmail's tabs are not IMAP folders, so the fetch window is filled by promotional mail |
| 2026-08-12 | A.2 complete: mailbox polling. Both providers built rather than one — the operator maintains several CVs with different contact addresses, so a single-provider design would have boxed the system in. The monitored address is DERIVED from the CV in use: an employer replies to whatever address the CV gave them, and configuring it separately would let the two drift silently |
| 2026-08-12 | Phase 2 build began. A.1 complete: application archive on dispatch. One deviation from directive §5 recorded — archiving happens at DISPATCH not approval, since approval means eligible-for-dispatch rather than submitted, and archiving there would create folders for applications never sent |
| 2026-08-12 | Operator proposal: repository history as CV evidence (D-04), and supportability assessment as a separate commercial product (D-05). Both recorded, neither scoped. The narrow form of D-04 — reading the operator's OWN repositories to propose Type 1 bullets — is tractable and has certain attribution. The broad form carries a coverage bias that would favour open-source-adjacent careers over enterprise ones |
| 2026-08-12 | B-35: the same test broke twice for the same reason — clearing a subset of credentials and depending on the rest. Fixed properly by deriving the list from boards.yaml and asserting they match, so adding a board with new credentials fails the suite rather than silently coupling a test to the environment |
| 2026-08-10 | B-34: fourth instance of the same failure shape — a number that looks like it describes what just happened and describes something else. Previously: C=1.000 from an unmeasured score, 533% parse rate, twenty duplicate queue rows. Each time the data was correct and the framing was not |
| 2026-08-10 | Operator observation: the configured boards return stale vacancies. Confirmed — the posted date was captured and persisted from the first Reed run and never used. `max_days_old` was an API parameter only, on a board since demoted to manual. Third time in this build a setting existed but nothing read it (B-18, C-01, B-33) |
| 2026-08-10 | B-31 found by the operator immediately after the first real application: dispatch was undone by the next scheduled run. The rule established — **machine-set states may be recomputed; operator-set states are preserved**. A scheduled run does not get to overturn a human decision |
| 2026-08-10 | Operator correction: the sponsorship notice in the unrecognised-heading list was dismissed as noise. It is an ELIGIBILITY GATE — a condition on whether one may apply at all, categorically different from a requirement. Coverage measures fit; this measures permission. Now detected, surfaced before the gaps, and never scored |
| 2026-08-10 | Five headings added to `_HEADING_RULES` on diagnostic evidence: two requirement-bearing (Technical and Professional Expertise, Systems Tools and Technology), two responsibilities, one benefit. Each appeared on two adverts that had refused |
| 2026-08-10 | B-28: the diagnostics aggregates repeated B-21 exactly — one row per advert per run, counted as though each were a distinct advert. Fixed in `list_queue()` on 9 Aug and not checked elsewhere. Lesson: when a defect is found in one aggregate, audit every other aggregate over the same table |
| 2026-08-10 | Logging built to operator specification: database AND file, optional but recommended on, hybrid rotation (time-led at midnight, size cap as backstop against a pathological day), and archive-rather-delete retention — old rows move to archive.db, old files are gzipped in place. The operator corrected an initial proposal to prune records: deleting history destroys the evidence for the next question |
| 2026-08-09 | B-26 found by reading the new queue view: it printed `1.000` for eleven vacancies whose scores were UNRELIABLE. The figure was never wrong — the run output had always said UNRELIABLE — but the list view dropped that signal, so a number meaning "not measured" sorted to the top looking like the best match. Presentation can lie by omission |
| 2026-08-09 | UI built (`ui.py`). Stdlib rather than `rich` — no dependency, and the output is a string the module produces, so it is assertable in tests rather than eyeballed. Accessibility designed in: colour is never the only signal, NO_COLOR honoured, plain mode emits zero escape sequences, ASCII fallback, high-contrast mode, width detection with a floor. `run` and `review` redesigned around it |
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
| 2026-08-12 | Directive §5 amended by operator ruling. The original specified a flat employer folder, which overwrites on a second application to the same employer, and archiving at approval, which records applications never sent. Its own prose already referred to "the vacancy folder" while the diagram showed a flat one — the amendment resolves that inconsistency. An amendment record is now kept at the foot of the directive |
| 2026-08-12 | First real poll: 300 messages, 297 uncorrelated, and every one a broadcast — no genuine employer reply in the inbox at all. The three that DID correlate were LinkedIn adverts. Operator observed the results looked like Gmail's Promotions tab; IMAP has no tabs, so INBOX returns everything and the most recent 300 were dominated by alerts. Both defects found were in correlation, not in polling |
| 2026-08-12 | B-46 found by the operator's Windows test run. Two of the three failures were real defects rather than platform quirks: clones were never being deleted, and `ignore_errors=True` meant nothing said so. A tool that copies source code to a temporary directory and leaves it there had to be caught — and only running on Windows caught it |
| 2026-08-22 | Operator's criticism, accepted: each fix had been tested against the single message that prompted it and never against the ones already working, and B-74 was a regression caused that way. Seven misclassifications were being treated as seven defects when they were one — the semantic threshold was set by judgement and never measured. `--explain` was added so the next change is made from numbers rather than from another guess |
| 2026-08-21 | The operator's objection to phrase lists was correct and general: a list of markers is a treadmill where every new employer wording is a defect, and the last four mail defects were all of that shape. The system already carried a local embedder, kept off any API because the CV holds personal data — mail holds more. Rules remain first for explainability; meaning is the fallback. AMBIGUOUS is retained as the honest answer where neither is sure |
| 2026-08-20 | The lifecycle work drew a line worth recording. WHERE an application failed is inferrable and reliable; WHY it failed usually is not, because rejections give no reason. Extracting a stated reason verbatim is honest; generating one from an email that states none would be manufacturing authoritative-sounding content, which is the failure this system exists to prevent. The aggregate answers the question the individual email cannot: twelve of twenty ending at CV stage says more than any rejection letter |
| 2026-08-20 | B-64 came from the operator reading the raw headers of a message the system had missed and asking why correlation was not using them. It was the right question: four stages of phrase-matching were approximating what `Reply-To` states exactly. A lesson about where to look — the wording was the visible thing, and the headers were the reliable one |
| 2026-08-19 | B-55 is the third time a table has multiplied rows because a repeated operation had no idempotency key. The pattern: anything read repeatedly from an external source — a mailbox, a board, a re-scoring run — writes duplicates unless something identifies what has already been seen. Worth checking on every new table rather than after the operator notices |
| 2026-08-19 | B-54 is the second field-name assumption this session — `source_id` in `letter.py`, `received_at` here. Both were written without checking the dataclass. The second reached the operator and broke a working command. The new guard is structural rather than behavioural: it reads every `message.<attr>` out of `cli.py` and asserts each exists on `Message`, so the same class of mistake fails the suite rather than the terminal |
| 2026-08-17 | The guide-index guard produced a false positive: it demanded `OUTSTANDING.md` list every guide, because the log entry recording that a guide was written counted as a reference. "Mentions a guide" was too loose — an index names SEVERAL. Scoped to two or more, which separates a table of contents from a passing mention. A guard that fires on correct work trains the operator to ignore it |
| 2026-08-17 | Operator hit B-48 after resolving FLAGGED records: `session` said nothing matched while the queue held three. The filter was correct; the message was not. Also asked for a combined view of what is waiting and documentation of everything after `session` — both were genuine gaps, since the guides ended at review and the operator was left to work out applying for themselves |
| 2026-08-16 | Operator identified the queue bottleneck and framed it as O(N) to O(log N) by analogy with vectorisation. The framing needed correcting — vectorisation is a constant-factor win, not a complexity change, and fifteen decisions cannot be compressed below fifteen without the system deciding for the operator. The bottleneck was real but was in the INVOCATIONS, not the decisions. Both were addressed: `session` for many decisions in one invocation, filtered bulk operations for one decision across many records |
| 2026-08-16 | Operator clarified the project's intent: not for a single CV or a single job type. That reframes it — the value is not matching one CV to vacancies but comparing SEVERAL profiles against a corpus, and reporting the distance. `docs/PHASE_3.md` specifies it: profile-keyed scoring, trend analysis, and a positioning report. Certification recommendations are explicitly out of scope — that mapping is maintained, not derived, and stale advice costs months |
| 2026-08-12 | Operator asked whether the documentation guards themselves can drift. Three of them could: the phase mapping, the working-directory list and the reference-document list were all hardcoded — the same failure the guards exist to prevent, one level up. All three now derive from the repository: phases from the module names in their own headings, directories from `.gitignore`, reference documents from whichever already link a guide. Verified by reverting a phase heading and watching the guard fire |
| 2026-08-12 | **Phase 2 complete.** C built to the specification's "brink of autonomous" scope: the system establishes what kind of application this is, whether the operator holds an account and what they will need, then gives them the URL and stops. Automated form-filling stays out of scope, and a test now asserts `channel.py` contains no HTTP posting, no browser automation and no `selenium` — the constraint is in the suite rather than in anyone's memory |
| 2026-08-12 | Phase 2 B built. The constraint held in its first real test: scanned against the twelve recurring unmet requirements, it proposed bullets for pytest and documentation and nothing at all for AWS, Azure, GCP, Docker, Terraform or Kubernetes. A repository evidences only what was built, and the top of the gap list is a cloud platform gap no amount of mining can close |
| 2026-08-12 | B-45 found in the same run as B-44: the reply correlated to `reed:57205320` rather than the dispatched `reed:57092035`, both at Sanderson. Stage 2 identifies the EMPLOYER; it cannot identify which vacancy when an operator has two open at one company. Now surfaced rather than guessed |
| 2026-08-12 | B-44 found by the operator running the interview loop end to end with a realistic message. The system correctly refused to correlate a subject with nothing identifying in it — but testing that exposed a far worse case: a real employer reply from a real employer domain also failed, because the employer domain is only known when the vacancy was hosted on the employer's own site. Almost none are |
| 2026-08-12 | A.3 complete: multi-round interview tracking. Building it surfaced B-43 — there was no OFFER state at all, so a job offer classified as AMBIGUOUS. Ordering matters: OFFER is checked before PROGRESS, since "we would like to offer you the position, and would like to arrange a call" contains progress phrasing and is not another round |
| 2026-08-12 | B-41 is the fifth instance of the same shape: a figure that looks like it measures one thing and measures another. Previously C=1.000 in the queue, the 533% parse rate, FLAGGED 520 for a run that scored 14, and the diagnostics aggregates. Each time the underlying data was correct and the framing was not. B-42 came from the same run — an id truncated to fit a column is an id that cannot be used |
| 2026-08-12 | Batch ingestion built ahead of A.3, on the reasoning that at 70 pastes a day the ingest path is the bottleneck and the interview path is weeks away. The advert manifest designed earlier and paused was completed: filename as primary key (sound, since a directory cannot hold two files with the same name), employer and url held in the manifest rather than in the advert text, and entries destroyed when their file is removed |
| 2026-08-12 | Operator stated the intended test volume: 75 vacancies reviewed and applied for per day, ~95% by pasting. At that rate a targeted mail search becomes a thousand-term query within a week and hits IMAP command length and Gmail's query limits. Two strategies now, switching automatically: targeted below 40 open applications, window above. The threshold is authored and labelled as such (P-07) |
| 2026-08-12 | The Gmail primary search worked and immediately exposed B-39: four real acknowledgements, none correlated. The distinction missed was between a job board ADVERTISING a vacancy and an ATS ACKNOWLEDGING an application — both are third parties naming an employer, and the plausibility check treated them alike. They separate on intent, which is visible in the subject |
| 2026-08-12 | First live poll surfaced B-36 immediately: `jobs-noreply@linkedin.com` advertising a Beatport vacancy was correlated to the open Beatport application. An advert, not a reply. Filed under that application it would have been archived as correspondence and, had the wording matched, classified as a decline. The operator also identified B-37 — that Gmail's tabs are not IMAP folders, so the fetch window is filled by promotional mail |
| 2026-08-12 | A.2 complete: mailbox polling. Both providers built rather than one — the operator maintains several CVs with different contact addresses, so a single-provider design would have boxed the system in. The monitored address is DERIVED from the CV in use: an employer replies to whatever address the CV gave them, and configuring it separately would let the two drift silently |
| 2026-08-12 | Phase 2 build began. A.1 complete: application archive on dispatch. One deviation from directive §5 recorded — archiving happens at DISPATCH not approval, since approval means eligible-for-dispatch rather than submitted, and archiving there would create folders for applications never sent |
| 2026-08-12 | Operator proposal: repository history as CV evidence (D-04), and supportability assessment as a separate commercial product (D-05). Both recorded, neither scoped. The narrow form of D-04 — reading the operator's OWN repositories to propose Type 1 bullets — is tractable and has certain attribution. The broad form carries a coverage bias that would favour open-source-adjacent careers over enterprise ones |
| 2026-08-12 | B-35: the same test broke twice for the same reason — clearing a subset of credentials and depending on the rest. Fixed properly by deriving the list from boards.yaml and asserting they match, so adding a board with new credentials fails the suite rather than silently coupling a test to the environment |
| 2026-08-10 | B-34: fourth instance of the same failure shape — a number that looks like it describes what just happened and describes something else. Previously: C=1.000 from an unmeasured score, 533% parse rate, twenty duplicate queue rows. Each time the data was correct and the framing was not |
| 2026-08-10 | Operator observation: the configured boards return stale vacancies. Confirmed — the posted date was captured and persisted from the first Reed run and never used. `max_days_old` was an API parameter only, on a board since demoted to manual. Third time in this build a setting existed but nothing read it (B-18, C-01, B-33) |
| 2026-08-10 | B-31 found by the operator immediately after the first real application: dispatch was undone by the next scheduled run. The rule established — **machine-set states may be recomputed; operator-set states are preserved**. A scheduled run does not get to overturn a human decision |
| 2026-08-10 | Operator correction: the sponsorship notice in the unrecognised-heading list was dismissed as noise. It is an ELIGIBILITY GATE — a condition on whether one may apply at all, categorically different from a requirement. Coverage measures fit; this measures permission. Now detected, surfaced before the gaps, and never scored |
| 2026-08-10 | Five headings added to `_HEADING_RULES` on diagnostic evidence: two requirement-bearing (Technical and Professional Expertise, Systems Tools and Technology), two responsibilities, one benefit. Each appeared on two adverts that had refused |
| 2026-08-10 | B-28: the diagnostics aggregates repeated B-21 exactly — one row per advert per run, counted as though each were a distinct advert. Fixed in `list_queue()` on 9 Aug and not checked elsewhere. Lesson: when a defect is found in one aggregate, audit every other aggregate over the same table |
| 2026-08-10 | Logging built to operator specification: database AND file, optional but recommended on, hybrid rotation (time-led at midnight, size cap as backstop against a pathological day), and archive-rather-delete retention — old rows move to archive.db, old files are gzipped in place. The operator corrected an initial proposal to prune records: deleting history destroys the evidence for the next question |
| 2026-08-09 | B-26 found by reading the new queue view: it printed `1.000` for eleven vacancies whose scores were UNRELIABLE. The figure was never wrong — the run output had always said UNRELIABLE — but the list view dropped that signal, so a number meaning "not measured" sorted to the top looking like the best match. Presentation can lie by omission |
| 2026-08-09 | UI built (`ui.py`). Stdlib rather than `rich` — no dependency, and the output is a string the module produces, so it is assertable in tests rather than eyeballed. Accessibility designed in: colour is never the only signal, NO_COLOR honoured, plain mode emits zero escape sequences, ASCII fallback, high-contrast mode, width detection with a floor. `run` and `review` redesigned around it |
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
