# PROJECT VANGUARD — Roadmap to Completion

| Field | Value |
|---|---|
| **Date** | 9 August 2026 |
| **Status** | All six build milestones complete. 543 tests passing. Running against live boards |
| **Authority** | Descriptive. `PROJECT_VANGUARD_DIRECTIVE.md` governs behaviour |

---

## The definition problem

`BUILD_PLAN.md` is finished. Every milestone delivered, verified on real
infrastructure. So "completion" now means something the project has not yet
defined, and three answers are defensible:

| Definition | Completion is... | Remaining work |
|---|---|---|
| **A — Operational** | The tool reliably supports the operator's job search | Weeks. Mostly use, not code |
| **B — Feature-complete** | Every item in `OUTSTANDING.md` is closed or explicitly declined | Months |
| **C — Service** | Multi-user, per the operator's stated longer-term intent | A different project |

**This roadmap assumes A, with B as an optional extension.** C is out of scope
and depends on A being reached first — the operator's own condition was that
the single-user build be "implemented, vigorously tested and highly stable"
before anything further.

---

# PHASE 1 — Operational use

**Goal:** the tool earns its keep. **Effort:** none. **Duration:** 2–4 weeks.

No code. The system works; what it lacks is usage.

| Task | Why |
|---|---|
| Review the PENDING queue after each run | The only way to learn whether coverage matches your judgement |
| Apply to what looks right | The point of the exercise |
| Paste LinkedIn and Adzuna roles worth assessing | Tier 3 boards are permanent design, not a gap |
| Run `vanguard mail` on recruiter replies | Exercises correlation and classification on real messages |

### Exit criteria

- [ ] 30+ vacancies scored and reviewed
- [ ] 10+ applications submitted
- [ ] Coverage scores compared against your own judgement of fit
- [ ] First recruiter responses correlated and classified

### What this unlocks

Everything in Phase 2 is currently blocked on evidence this phase produces.
Building further before it exists repeats the error that put a 0.94 gate on
an unreachable metric.

---

# PHASE 2 — Evidence-driven correction

**Goal:** close the items that need real data. **Trigger:** Phase 1 exit
criteria met. **Effort:** 3–5 days.

| Item | Decision it enables |
|---|---|
| **P-01** coverage gate | Ratchet 0.60 upward. Record the reason beside the number |
| **P-02** MiniLM 0.75 | Tune against accumulated soft-hit review history |
| **P-03** Type 1 floor 0.45 | Tune against gap-classification review history |
| **P-04** `silence_days` | Replace 21/30 with observed response times |
| **D-03 / B-17** prose extraction | ~100 real adverts is a corpus. 29 was not |

### D-03 in particular

The largest open question. Extraction falls back to flat mode on roughly a
third of adverts. Four sub-questions are recorded and deliberately unanswered:
whether coverage should gate at all when |R| is small, whether prose extraction
is tractable, what ranks the remainder, and whether the Type 1/2/3 taxonomy
survives non-discrete requirements.

### Exit criteria

- [ ] Every authored parameter either measured or explicitly retained with a reason
- [ ] D-03 scoped, or declined on evidence
- [ ] Reliable-score rate above 75% (currently ~70%)

---

# PHASE 3 — Optional capability

**Goal:** convenience. **Trigger:** operator wants it. **Effort:** 1–2 weeks.

None of this is required for A. Each item is independently declinable.

| Item | Value | Cost |
|---|---|---|
| **N-06** mailbox polling | Response loop becomes autonomous | 2 days + credential decision |
| **N-01** NHS Jobs adapter | A whole sector, well matched to the CV | Blocked on NHSBSA access |
| **N-02** Find a Job adapter | Overlaps Adzuna heavily — verify value first | Blocked on platform migration status |
| **D-02** CLI tables, `--json` | Readability | 1 day |
| **D-01** adaptive query config | Self-tuning search terms | Unscoped |

### Sequencing note

N-06 is the highest value: it closes the last manual step in the response
loop. D-01 is the largest and should follow Phase 2, since its most useful
signal is response outcomes.

---

# PHASE 4 — Multi-user service

**Out of scope. Listed for completeness.**

Operator's stated intent. Prerequisite, in their own words: the single-user
build must be stable and vigorously tested first.

What carries over: coverage-gates-cosine-ranks, the truthfulness controls,
Success Profile handling, the board registry.

What does not: the alias table — 33 entries encoding one person's domain
knowledge — and the Type 1/2/3 distinction, which requires knowing what an
applicant actually did. Both are open problems, not implementation work.

Also changes character entirely: local embeddings (privacy rationale inverts),
"never transmits" (users will expect submission), and board terms (individual
use differs from commercial redistribution).

---

# Housekeeping — anytime

Small, independent, no dependencies.

- [ ] Confirm or overrule the two inferred rulings (`/Pipeline_Archive/`, §5 → ROUTE 4)
- [ ] Align the git commit identity with the `Olu-SHABA` account
- [ ] Amdari CV section: nine bullets with two near-duplicate pairs
- [ ] Condensed reporting-engine bullet (drafted, never ruled on)
- [ ] Write a pytest suite for the reporting engine — would move `pytest` out of Tier C
- [ ] `README.md` badge or note if the repo is ever made public (see S-05)

---

# Critical path to A

```
  Phase 1 (use it, 2-4 weeks)
        │
        ▼
  Phase 2 (evidence-driven, 3-5 days)
        │
        ▼
  ═══ COMPLETE under definition A ═══
        │
        ├──► Phase 3 items, individually, if wanted
        └──► Phase 4, a separate project
```

**Estimated: 4–6 weeks to A, of which ~1 week is development.**

The dominant cost is elapsed time waiting for applications and responses, not
engineering. That is the correct shape: every remaining parameter is an
empirical question, and answering it faster is not possible.

---

# Principle

Nothing in Phase 2 or 3 should be built before the evidence that justifies it
exists. The original 0.94 gate, the 29-advert D-03 diagnosis, and the
extraction assumption validated against a single MoJ advert were all the same
error — designing against a sample too small to be representative.

Phase 1 is not a pause before the real work. It is how the real work becomes
possible.
