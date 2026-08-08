# Project Vanguard

Semi-autonomous job application pipeline. Ingests vacancies, scores them
against a canonical CV, classifies gaps, drafts artefacts, and queues them
for human approval. It never submits without authorisation and never invents
experience.

Governing documents: `PROJECT_VANGUARD_DIRECTIVE.md` (behaviour),
`PROJECT_VANGUARD_SPECIFICATION.md` (architecture), `BUILD_PLAN.md` (work).

## Status

| Milestone | State |
|---|---|
| M0 Foundations | Complete |
| M1 Render chain | Code complete; PDF output unverified |
| M2 Scoring core | Complete |
| M3 Drafting | Complete |
| M4 Ingestion | Complete |
| M5 Governance and queue | Complete |
| **M6 Response loop** | **Complete — 417 tests passing** |

**All milestones complete.**

Open defects, deferrals and unverified assumptions: **`OUTSTANDING.md`**.

## Install

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### WeasyPrint system libraries

WeasyPrint renders through cairo, pango and gdk-pixbuf. `pip` installs the
Python package but not those.

**Windows.** Install the GTK3 runtime from
`github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases`
(`gtk3-runtime-*-win64.exe`), accepting the default path and ticking
*Set up PATH environment variable*.

Then, in an **Administrator** PowerShell, work around a DLL naming mismatch —
GTK ships `libgobject-2.0-0.dll`, WeasyPrint looks for `gobject-2.0-0.dll`:

```powershell
cd "C:\Program Files\GTK3-Runtime Win64\bin"
Copy-Item libgobject-2.0-0.dll gobject-2.0-0.dll
```

**Restart the machine**, then verify:

```powershell
python -m weasyprint --info
```

**Linux.** `apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`
**macOS.** `brew install pango`

Symptom when missing: `OSError: cannot load library 'libgobject-2.0-0'`.
The three PDF tests skip rather than fail when the runtime is absent.

Milestone 2 adds torch (~2GB) and is a separate extra:

```bash
pip install -e ".[scoring]"
```

## Test

```bash
pytest                  # PDF tests skip automatically if weasyprint is absent
pytest -m "not slow"
ruff check .
```

## Score an advert against the CV

```python
from vanguard.cv import load
from vanguard.extract import extract
from vanguard.coverage import load_aliases, compute_coverage
from vanguard.rank import SentenceTransformerEmbedder, DOCUMENT_MODEL, rank_score

cv = load("data/canonical_cv.md")
aliases = load_aliases("config/alias_table.yaml")
advert = open("advert.txt").read()

report = compute_coverage(extract(advert), cv, aliases,
                          SentenceTransformerEmbedder())
print(report.summary())          # C, ceiling, PASS / REFACTOR / UNREACHABLE
for gap in report.gaps:
    print(gap)                   # itemised, with Tier C reasons attached
```

`LexicalEmbedder` substitutes for the model when `[scoring]` is not installed.
It is synonym-blind and flagged as degraded — useful for testing the pipeline,
not for real scoring.

## Run it

```bash
vanguard boards                     # registry health, credential check
vanguard run                        # autonomous: fetch, score, queue, exit
vanguard paste --file advert.txt    # Tier 3: hand-feed one vacancy
vanguard review                     # PENDING, strongest first
vanguard review <id>                # coverage, itemised gaps, history
vanguard approve <id>
vanguard override <id> --why "..."  # apply despite an unreachable ceiling
vanguard dispatch <id>              # record a submission YOU made
vanguard stats                      # coverage distribution, recurring gaps
vanguard score --advert advert.txt  # standalone, no database

vanguard mail --file reply.txt      # correlate + classify one message
vanguard dormant                    # applications silent past silence_days
vanguard feedback <id> --name ...   # Template D draft (you send it)
vanguard interview <id> --phase 1   # Template E, graded D1-D5
```

Response classification: **DECLINE is checked before PROGRESS.** Rejections
open warmly, and checking progress first would misread them as invitations.
`DORMANT` is derived state — silence is not a rejection and never triggers
Template D.

`run` never blocks and never prompts — it writes state and exits. Everything
else is interactive. **Vanguard never transmits**: `dispatch` records that you
submitted an application, it does not send one.

Credentials come from the environment: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
`REED_API_KEY`.

## Ingest vacancies

```python
from vanguard.adapters.base import load_registry, Query
from vanguard.ingest import ingest, health_check_all

registry = load_registry("config/boards.yaml")
for status in health_check_all(registry):
    print(status)

run = ingest(registry, Query(keywords=("data engineer",), location="UK"))
print(run.summary())        # collected -> kept, with per-board overlap
```

Credentials come from the environment, never from `boards.yaml`:
`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`.

Tier 3 boards are hand-fed and everything downstream still runs on them:

```python
from vanguard.adapters.manual import ManualEntryAdapter
vacancy = ManualEntryAdapter(registry.get("linkedin")).submit(pasted_text, url=...)
```

## Draft an application

```python
from vanguard.submission import detect
from vanguard.refactor import refactor
from vanguard.templates import render_for, Achievement

spec = detect(advert)                    # type + ANONYMISE / WORD_LIMIT / criteria
result = refactor(requirements, cv, aliases, embedder)
print(result.summary())                  # exit reason -> queue status
```

Injection constraints are enforced in code. An achievement whose evidence is
absent from the CV, a figure not present in the CV, or a Type 3 gap written
into outbound text all raise `InjectionError` rather than rendering.

## Render a CV

```python
from vanguard.render import render, render_anonymised

render("data/canonical_cv.md", "render/standard.css", "out/cv.pdf")

# Anonymised: raises AnonymisationError if anything identifying survives
render_anonymised("data/canonical_cv.md", "render/anonymised.css", "out/anon.pdf")
```

## Anonymisation

Identifying content is removed from the **Markdown before rendering**, not
hidden with CSS. Hidden text remains in the PDF text layer and can be copied
out. The rendered file is then scanned; any hit raises rather than returning.

Suppressed: name, address/town, email, telephone, all portfolio URLs.
Retained: employer names, dates, titles, achievements, metrics — career
history, not identity.

## Layout

```
config/     boards.yaml, alias_table.yaml
data/       canonical_cv.md — single source of truth
render/     standard.css, anonymised.css
src/vanguard/
tests/
```

`data/canonical_cv.md` is the only place employment history is edited. PDFs
are disposable outputs; regenerate rather than repair.
