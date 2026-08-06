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
| M2 Scoring core | Complete — 95 tests passing |
| M3 Drafting | Not started |

## Install

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

WeasyPrint needs system libraries (cairo, pango, gdk-pixbuf). On Windows the
simplest route is GTK for Windows Runtime; see the WeasyPrint install docs for
your platform. If `import weasyprint` fails, that is the cause.

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
