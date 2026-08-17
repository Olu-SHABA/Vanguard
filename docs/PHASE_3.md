# PHASE 3 — MARKET POSITIONING

**16 August 2026** · Specification. Nothing here is built.

| | |
|---|---|
| Trigger | Operator ruling: the system is not for a single CV or a single job type |
| Governs | `PROJECT_VANGUARD_DIRECTIVE.md` still wins on any conflict |
| Depends on | Phase 2 complete. Outcome data from Phase 1 use is **not** required |

---

# 0 · WHAT CHANGES

Phases 1 and 2 built a job application pipeline: one CV, one market, one
answer. Phase 3 makes it a **market positioning tool** that happens to also
apply for jobs.

The question changes from *"is this vacancy worth applying to?"* to **"which
version of myself does this market want, and what is the distance?"**

That is a better question, and there is no cheap way to answer it. A single
CV needs no software to tell you your gaps — you know them. Three CVs across
five hundred vacancies is arithmetic nobody does by hand.

## Three capabilities

| | |
|---|---|
| **Profile-keyed scoring** | Several CVs, the same corpus, comparable results |
| **Trend analysis** | Requirement frequency over time, from the score history |
| **Positioning report** | Ranked gaps with the evidence, per profile |

## One thing this deliberately does not do

**It does not recommend certifications.**

Going from *"Azure appeared 33 times"* to *"take AZ-104"* requires a mapping
from requirements to qualifications that is maintained, not derived — vendors
rename certifications and restructure paths, and a stale recommendation costs
someone months and several hundred pounds.

What can be said honestly: **"Azure appeared in 33 of 553 adverts, more than
any other unmet requirement, and rising. No repository of yours evidences
it."**

What would be guessing: which exam to sit.

Same architecture as everywhere else. The system reads; the person decides.

---

# 1 · PROFILE-KEYED SCORING

## The problem

`scores` is keyed on `(vacancy_id, computed_at)`. Score one vacancy against
two CVs and the second silently replaces the first in every aggregate. There
is no profile column anywhere, and `cv.py` has no notion of one.

## Model

```
profiles
  id            TEXT PRIMARY KEY     'data_scientist', 'network_ops'
  label         TEXT                 'Data Scientist'
  cv_path       TEXT                 data/cv_data_scientist.md
  alias_path    TEXT                 config/alias_data_scientist.yaml
  contact       TEXT                 derived from the CV, for mail correlation
  active        INTEGER              scored on every run
  created_at    TIMESTAMP
```

`scores` gains `profile_id`, and its primary key becomes
`(vacancy_id, profile_id, computed_at)`. Every aggregate — the distribution,
the unmet frequency, the queue join — filters or groups by it.

**A migration, not a rewrite.** `MIGRATIONS` already handles added columns;
existing rows take a `default` profile so nothing is lost.

## Per-profile alias tables

The alias table encodes one person's domain vocabulary against one CV. A
Network Operations profile needs different Tier A entries and, more
importantly, **different exclusions** — what is Type 3 for a data profile may
be evidenced in a network one.

Sharing one table across profiles would let an alias resolve against evidence
that is not in the CV being scored, which is precisely the failure Tier C
exists to prevent.

## What the operator sees

```
vanguard profiles list
vanguard profiles add network_ops --cv data/cv_network.md --aliases config/alias_network.yaml

vanguard run                          # scores every active profile
vanguard review --profile network_ops
vanguard compare reed:57092035        # one vacancy, every profile
```

```
  Machine Learning Engineer — Sanderson

  PROFILE           COVERAGE  CEILING  UNMET
  data_scientist       0.700    0.800  AWS, Azure, MLOps
  network_ops          0.350    0.500  Python, ML, Spark, Databricks, +6
  hybrid               0.550    0.727  AWS, Azure, Kubernetes
```

**That comparison is the product.** Not which vacancy to apply to — which
profile to lead with.

---

# 2 · TREND ANALYSIS

## What the data already supports

`scores` retains history, and `gaps` retains every unmet term per vacancy with
a timestamp. Requirement frequency over time is computable today; nothing
computes it.

## What it answers

```
vanguard trends --since 2026-06-01
```

```
  REQUIREMENT      JUN    JUL    AUG    DIRECTION
  Azure            12%    19%    31%    rising sharply
  AWS              28%    30%    29%    flat
  Kubernetes        4%     7%    11%    rising
  Hadoop            9%     5%     2%    falling
```

Percentages are **of adverts sampled in that window**, not of all adverts —
and the report must say so. A requirement appearing in 31% of the adverts
Vanguard happened to fetch is not a claim about the UK market.

## The honest caveats, stated in the output

**Sampling.** One board, three keywords, fifteen results each. That is a
narrow slice and the report says which.

**Volume.** Below roughly 50 adverts in a window, a percentage swings on one
or two vacancies. The report shows the denominator and suppresses direction
where it is not supportable.

**Seasonality.** Two months is not a trend. The report should refuse to state
a direction until there are at least three windows.

---

# 3 · THE POSITIONING REPORT

The output that makes the rest worth having.

```
vanguard position --profile data_scientist
```

```
  DATA SCIENTIST · 553 adverts sampled, 2026-06-14 to 2026-08-16

  WHERE YOU STAND
    median coverage        0.286
    best                   0.700   Machine Learning Engineer, Sanderson
    reachable at 0.60      15 of 441 reliably scored

  THE GAP, RANKED
    1  Azure          33 adverts   rising      no repository evidence
    2  AWS            32 adverts   flat        no repository evidence
    3  GCP            20 adverts   —           no repository evidence
    4  CI/CD          19 adverts   flat        EVIDENCED in vanguard (1 workflow)
    5  Docker         11 adverts   rising      no repository evidence

  ONE CLUSTER ACCOUNTS FOR 115 OF 155 UNMET REQUIREMENTS
    Cloud and deployment: Azure, AWS, GCP, Docker, Terraform, Kubernetes

  WHAT YOUR REPOSITORIES ALREADY EVIDENCE
    automated testing      25 files     unstated on the CV
    technical documentation 88 files    unstated on the CV

  WHAT THIS DOES NOT TELL YOU
    Which certification to take. That mapping is maintained, not derived,
    and a stale recommendation costs months. The frequencies above are the
    evidence; the choice is yours.
```

## Clustering

Six separate gaps that are one gap matters more than the ranking. Azure, AWS,
GCP, Docker, Terraform and Kubernetes are **cloud and deployment**, and
reporting them as six lines understates the concentration.

Clusters are declared in configuration, not inferred. An inferred cluster is
a claim about the market; a declared one is a claim the operator can inspect
and correct.

```yaml
clusters:
  cloud_and_deployment: [AWS, Azure, GCP, Docker, Kubernetes, Terraform, ...]
  distributed_compute:  [Spark, Databricks, Snowflake, Hadoop, dbt]
  mlops:                [MLflow, Kubeflow, model deployment, feature store]
```

---

# 4 · BUILD SEQUENCE

| | Effort | Why in this order |
|---|---|---|
| **1 · Profile model and migration** | 2 days | Everything else keys on it |
| **2 · Per-profile alias tables** | 1 day | Sharing one would defeat Tier C |
| **3 · `compare`** | 1 day | The comparison is the product; build it early and use it |
| **4 · `trends`** | 2 days | Needs profile-keyed history to mean anything |
| **5 · `position`** | 2 days | Assembles the rest |
| **6 · Cluster configuration** | 1 day | Refines `position` |

**Roughly 9 days.**

Nothing here needs outcome data. Phase 3 is answerable from the corpus alone,
which is what makes it buildable now while the calibration parameters wait
for volume.

---

# 5 · OUT OF SCOPE

| | Why |
|---|---|
| **Certification recommendations** | A maintained mapping, not derivable. Stale advice costs months |
| **Salary analysis** | Advert salary bands are unreliable and often absent |
| **Inferred clusters** | A claim about the market. Declared clusters can be inspected |
| **Market claims beyond the sample** | One board, three keywords. The report says so |
| **Profile auto-selection** | Which profile to lead with is the operator's decision, and the point of the comparison |

---

# 6 · WHAT WOULD SHOW IT WORKED

| Part | Verified by |
|---|---|
| Profiles | One vacancy scored against three CVs, three distinct results retained |
| Alias isolation | A term evidenced in one profile's CV does not resolve for another |
| Migration | Existing scores survive, attributed to a `default` profile |
| Trends | A requirement's frequency changes measurably across three windows |
| Position | The cloud cluster is identified as one gap, not six |
| Honesty | Every percentage states its denominator and its sample |

**Measured with the commands themselves.** Not by inspection.

---

# 7 · WHAT THIS IS, HONESTLY

The applicant-facing job matcher competes with fifty tools and differentiates
on a property applicants do not want — refusing to inflate.

*"Here is what this market asks for, here is what you can evidence, here is
the distance, and here is which version of you fits best"* — with the receipts
— is a different proposition, and the truthfulness controls are what make it
credible rather than what hold it back.

It also remains, first, a tool for one operator to find one job. Phase 3 does
not change that. It changes what the same corpus can be asked.
