# HOW TO USE JOB BOARDS

Which boards Vanguard reads, how to turn them on and off, and why some can
never be automated.

---

## THE SHORT VERSION

```powershell
vanguard search data scientist --within 6h    # links to open; fetches nothing
vanguard discover --board adzuna              # list vacancies, no scoring
vanguard boards                        # what is registered, and its state
vanguard run                           # read every enabled, automatable board
vanguard run --board reed              # read only Reed, this run
vanguard run --skip adzuna             # everything except Adzuna, this run
vanguard board enable totaljobs        # permanent
vanguard board disable totaljobs       # permanent
```

**`--board` and `--skip` are one-off.** They do not touch `boards.yaml`.
Editing the file to try something out is how a temporary choice becomes a
permanent one.

---

## WHY MOST BOARDS ARE NOT AUTOMATED

Only one board is read automatically today. That is not a gap — it is what
the sources allow.

### Three ways in

| | What it does | Fetches? |
|---|---|---|
| `vanguard run` | Fetches and scores, end to end | yes |
| `vanguard discover` | Lists vacancies; you paste the advert | yes, listings only |
| `vanguard search` | **Builds links you open yourself** | **no** |

`vanguard search` exists for LinkedIn. The User Agreement prohibits automated
**collection**, not searching — so Vanguard writes the URL and stops. You
click it, LinkedIn serves the page to your browser as a normal visit, and you
read the results.

```powershell
vanguard search data scientist --within 6h --remote remote --level senior
```

Windows: `6h`, `12h`, `24h`, `3d`, `1w`, `2w`, `1m`. LinkedIn expects seconds
(`f_TPR=r21600`), Indeed expects days (`fromage=1`). Vanguard remembers which.

### What each board can supply

| Board | Finding vacancies | Getting the advert |
|---|---|---|
| **Reed** | API | **full text** — nothing to paste |
| **Adzuna** | API, via `discover` | capped at 500 characters |
| **Civil Service** | email alerts | summaries only |
| **NHS Jobs** | email alerts | summaries only |
| **LinkedIn** | `search` builds the link; you browse | you copy it |

**Reed is the only source that supplies a complete advert.**

A truncated advert does not score badly — it scores *meaninglessly*. Adzuna's
500-character cap produced `C=1.000` on a Service Centre Team Manager,
because two requirements were extracted and the CV matched both. So the
choice was: fetch automatically and get scores that look authoritative and
measure nothing, or paste and get real ones. Scoring integrity won.

### Why the reason barely matters to you

In practice it makes no difference. Whether a board is manual because of its
terms or because of truncation, **you still open the posting and copy the
description**.

It matters only for what might change. A terms restriction is permanent —
LinkedIn will always be paste. A truncation is a capability limit, and if a
full-text tier appears the board can be promoted without any other change.

**Tier 3 is not second-class.** Scoring, gap classification, drafting and
tracking all run identically on a pasted vacancy. Only the fetch is by hand.

### The rest

**Totaljobs and CWJobs** — no public candidate API. Both StepStone-owned, so
expect heavy mutual overlap. Email alerts available.

**CV-Library and Monster** — no public candidate API. Email alerts available.

**Find a Job (DWP)** — its corpus is substantially Adzuna's, so polling both
double-counts. Platform migration status needs verifying.

### The NHS question, settled

The NHS Jobs API is a **publisher** API: it lets trusts push vacancies *out*
to third-party sites. It does not let a candidate search. Arranging NHSBSA
access would never have helped, because the endpoint does the wrong thing —
and it sat as "pending access" for weeks on that misreading.

The candidate route is a saved search on `jobs.nhs.uk` with email alerts, then
paste.

---

## TURNING A BOARD ON

```powershell
vanguard board enable totaljobs
vanguard boards
```

This edits `boards.yaml` in place, changing only the `enabled:` line. Every
comment and note is preserved — the notes record *why* a board is in the
state it is, and losing them would lose the reasoning.

**Enabling a Tier 3 board does not make `vanguard run` read it.** It makes the
board available to paste against, so its vacancies are attributed correctly
and its `silence_days` applies.

To turn it off again:

```powershell
vanguard board disable totaljobs
```

---

## CHOOSING BOARDS FOR ONE RUN

```powershell
vanguard run --board reed
vanguard run --board reed --board adzuna
vanguard run --skip linkedin
```

A typo is refused rather than ignored:

```
Error: unknown board(s): reeed. Known: adzuna, civil_service_jobs, ...
```

A selection that leaves nothing enabled is refused too.

---

## ADDING A BOARD THAT IS NOT REGISTERED

Two files, in this order.

### 1. Decide the tier — honestly

Read the site's terms first. If automated collection is prohibited, the board
is **Tier 3**, whatever is technically possible. That decision is not
reversible by finding a clever way round it.

### 2. Add the registry entry

In `config/boards.yaml`:

```yaml
  - id: example_jobs
    adapter: ManualEntryAdapter        # or your new adapter class
    enabled: true
    tier: manual                       # api_official | feed | manual
    priority: 5                        # lowest integer wins on a duplicate
    silence_days: 21
    portal_url: "https://example.com/jobs"
    note: "Why this board is at this tier. Cite the terms if they decide it."
```

**The `note` is not decoration.** It is why the next person — including you in
three months — does not undo a decision without knowing what it rested on.

### 3. If it is Tier 1 or 2, write the adapter

`src/vanguard/adapters/example.py`, implementing `fetch`, `normalise` and
`health_check` from `BoardAdapter`. Then:

```powershell
vanguard boards                        # health check per adapter
vanguard run --board example_jobs      # try it alone before trusting it
```

**No board is ever named in the pipeline.** Adding one is a config change plus
an adapter class, and nothing else.

---

## IF SOMETHING GOES WRONG

**`vanguard run` fetches nothing** — check `vanguard boards` for credentials.
Only `api_official` boards are read; a Tier 3 board contributing nothing is
correct.

**Duplicates across boards** — expected. Deduplicated on employer, title,
location and salary; the lowest `priority` wins and the duplicate is logged
rather than discarded, so overlap stays measurable.

**Rate limited** — 60 calls an hour, exponential backoff. `vanguard logs
--errors` shows what was truncated.

---

*Pasting a vacancy: `HOW_TO_ADD_A_JOB.md`. Many at once:
`HOW_TO_ADD_MANY_JOBS.md`. Full reference: `COMMANDS.md`.*
