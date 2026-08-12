# ADDING VACANCIES BY HAND

**Per-board detail and configuration.**

> **Just want the steps?** See **`HOW_TO_ADD_A_JOB.md`** — five steps, one page.
> This document is the reference behind it.

---

## Why this exists

Only **one** board is polled automatically: Reed. Everything else is hand-fed,
for one of two reasons.

| Reason | Boards | Meaning |
|---|---|---|
| **Terms** | LinkedIn | Their agreement prohibits automated collection. The adapter raises rather than fetching — there is nothing to switch on |
| **Capability** | Adzuna, Civil Service | Permitted to poll, but they return summaries too short to assess. Adzuna caps every description at 500 characters |

**Not yet built:** NHS Jobs and Find a Job (DWP) have adapters declared but
unimplemented, so they are hand-fed too.

**This is not a workaround.** Everything downstream — scoring, gap
classification, refactoring, drafting, the queue, response correlation — runs
identically on a pasted vacancy. The only difference is that one step is
manual.

---

# THE PROCEDURE

## Step 1 — Copy the whole advert

Open the vacancy in your browser. Select **everything** from the job title down
to the end of the requirements.

```
[ ] Job title
[ ] Employer name
[ ] Location and salary if shown
[ ] The full description
[ ] The requirements or person specification section  <-- ESSENTIAL
[ ] Closing date if stated
```

**The requirements section is the one that matters.** Without it the system
extracts nothing and reports `not measured`. That is the commonest mistake and
it produces exactly the same problem as a truncated API fetch.

Do not worry about including navigation text, "similar jobs", or cookie
notices. They are ignored.

## Step 2 — Save it to a file

Create a text file anywhere convenient. A `pasted/` folder in the repo works
well and is gitignored.

**In Notepad:** paste, then Save As → `pasted/ml-engineer-acme.txt`.

**Turn on file extensions first** — Explorer hides them, and Notepad will
silently save `advert.txt.txt`. View → Show → File name extensions.

**Or straight from PowerShell:**

```powershell
notepad pasted\advert.txt
```

## Step 3 — Ingest it

```powershell
vanguard paste --file pasted\advert.txt --employer "Acme Analytics" --url "https://..."
```

| Option | Needed? | Why |
|---|---|---|
| `--file` | Yes | The advert text. Reads stdin if omitted |
| `--employer` | Recommended | Parsing the employer from prose is unreliable |
| `--url` | Recommended | So you can find the advert again from the record |
| `--title` | If wrong | Overrides whatever was parsed |
| `--board` | Sometimes | Which board to attribute it to. Default `linkedin` |

You will see:

```
ingested 'Machine Learning Engineer' from Acme Analytics [minilm]
  ◐ FLAGGED     0.417  ceiling 0.67    Machine Learning Engineer

reed:...
vanguard review <id>
```

## Step 4 — Review it

```powershell
vanguard review <the-id-it-printed>
```

From here it is identical to any automatically-fetched vacancy. Read the score,
check the ELIGIBILITY block, read the unmet list, then approve or reject.

---

# PER-BOARD NOTES

## LinkedIn

**Attribution:** `--board linkedin` (the default)

```powershell
vanguard paste --file pasted\advert.txt --employer "Acme" --url "https://www.linkedin.com/jobs/view/1234567890/"
```

**Copying:** click **See more** to expand the description before selecting.
LinkedIn truncates by default and the collapsed text will not contain the
requirements.

**Why it can never be automated:** their User Agreement prohibits automated
collection. This is enforced in code — `ManualEntryAdapter.fetch()` raises
`TermsViolation`. There is no setting.

LinkedIn is probably the densest source of senior data roles in the country, so
this path will be the most used.

## NHS Jobs

**Attribution:** `--board nhs_jobs`

The board is registered but **disabled**, so attribution will fail until it is
enabled. Two options:

**Simplest** — attribute to LinkedIn and note the source in the URL:

```powershell
vanguard paste --file pasted\nhs.txt --employer "NHS Greater Glasgow and Clyde" --url "https://www.jobs.nhs.uk/candidate/jobadvert/..."
```

**Or enable it as manual** — edit `config/boards.yaml`:

```yaml
  - id: nhs_jobs
    adapter: ManualEntryAdapter        # was NHSJobsAPIAdapter
    enabled: true                      # was false
    tier: manual
    supplies_full_text: true
    priority: 2
    silence_days: 30
    note: "Manual entry pending NHSBSA API access."
```

Then `--board nhs_jobs` works, and the 30-day silence window applies — NHS
recruitment moves more slowly than commercial.

**Copying:** NHS adverts have a clear **Person specification** section with
Essential and Desirable subsections. Include all of it — that structure is
exactly what the extractor is looking for, and NHS adverts tend to score well.

## Civil Service Jobs

**Attribution:** `--board civil_service_jobs`

Already enabled as manual, so this works immediately.

```powershell
vanguard paste --file pasted\cs.txt --employer "Ministry of Justice" --url "https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=..."
```

**Two things to include or the submission type will be misdetected:**

- The **Behaviours** list
- The **Personal Statement** word limit

With both present, the system detects `SUCCESS_PROFILE`, sets the `ANONYMISE`
flag, extracts the word limit, and builds a per-criterion word budget. Without
them it falls back to a standard CV submission.

**Never fetch the portal.** It serves a bot-detection interstitial and sets
`noindex` — automated collection is explicitly discouraged. The `portal_url` in
the config is for you to configure a saved search, not for the pipeline.

## Adzuna

**Attribution:** `--board adzuna`

```powershell
vanguard paste --file pasted\adzuna.txt --employer "Acme" --url "https://www.adzuna.co.uk/details/..."
```

**Follow the link through to the employer's own site and copy from there.**
Adzuna's own page shows the same 500-character summary its API returns, which
is not enough to assess.

Adzuna is good for **discovery** and useless for **assessment**. Browse it,
follow the link, paste the real advert.

## Indeed, Glassdoor, Otta, anywhere else

No configuration needed. The `--board` flag is only a label:

```powershell
vanguard paste --file pasted\advert.txt --employer "Acme" --url "https://uk.indeed.com/viewjob?jk=..."
```

To track a source separately, add a block to `config/boards.yaml`:

```yaml
  - id: indeed
    adapter: ManualEntryAdapter
    enabled: true
    tier: manual
    supplies_full_text: true
    priority: 9
    note: "Operator pastes URL or text. Verify terms before any automated route."
```

Config change only. No code, no rebuild.

---

# WHEN IT GOES WRONG

| Symptom | Cause | Fix |
|---|---|---|
| `not measured` | Requirements section missing from the paste | Re-copy, include the full requirements |
| `could not determine job title` | The text does not start with a recognisable title | Add `--title "..."` |
| `unknown board 'x'` | Not in `boards.yaml`, or disabled | Use `--board linkedin`, or enable it |
| Employer shows `(not stated)` | Not parsed from the text | Add `--employer "..."` |
| `no advert text supplied` | Empty file, or wrong path | Check the file; watch for `.txt.txt` |

## Checking what the system actually read

```powershell
vanguard diagnose
```

If your pasted advert refused, this shows why — and which headings it found but
did not recognise. Those are evidence, not noise: an unrecognised requirement
heading appearing repeatedly is a candidate for the phrase list.

---

# QUICK REFERENCE

```powershell
# The common case
vanguard paste --file pasted\advert.txt --employer "Acme" --url "https://..."

# Civil Service, so the Success Profile is detected
vanguard paste --file pasted\cs.txt --board civil_service_jobs --employer "MoJ" --url "https://..."

# Title parsed wrongly
vanguard paste --file pasted\advert.txt --title "Senior Data Engineer" --employer "Acme"

# Straight from the clipboard, no file
vanguard paste
# paste, then Ctrl+Z and Enter
```

Then, always:

```powershell
vanguard review              # or --status FLAGGED
vanguard review <id>
vanguard approve <id>  |  vanguard reject <id> --reason "..."
vanguard dispatch <id>       # after you have actually applied
```

---

# THE ONE RULE

**Paste the whole advert, including the requirements.**

Everything else is recoverable — a wrong employer name, a missing URL, the
wrong board label. A truncated paste is not: the system will tell you it could
not measure anything, and it will be right.
