# PHASE 2 — FLOWCHART AND SPECIFICATION

**12 August 2026** · Derived from Phase 1 operation. Supersedes the Phase 2
section of `ROADMAP.md`.

| | |
|---|---|
| Trigger | Phase 1 observations, recorded below |
| Sequencing | A → B → C, agreed |
| Governs | `PROJECT_VANGUARD_DIRECTIVE.md` still wins on any conflict |

---

# 0 · WHAT CHANGED, AND WHY

Phase 1 produced three findings that the existing design does not handle.

| Finding | Consequence |
|---|---|
| A PENDING vacancy has no application path modelled | The operator is told a role is worth applying to, and given nothing about how |
| `C = 1.000` means `\|R\| < 6`, not a perfect match | The FLAGGED branch must diagnose parsing, not celebrate alignment |
| Low coverage is sometimes an unstated claim, not an absent one | A remediation loop is possible, bounded by what the repository can evidence |

**One correction carried into every branch below.** `C = 1.000` is not a
perfect match. It is a score computed from fewer than six requirements. A
genuine 1.000 across a full requirement set has not been observed in any run.

---

# 1 · TOP-LEVEL FLOW

```
                        vanguard run
                             │
                             ▼
                    ┌─────────────────┐
                    │  QUEUE RECORD   │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
    ┌─────────┐        ┌──────────┐       ┌──────────────┐
    │ PENDING │        │ FLAGGED  │       │ UNREACHABLE  │
    │ C≥gate  │        │          │       │ ceiling<gate │
    └────┬────┘        └────┬─────┘       └──────┬───────┘
         │                  │                    │
         ▼                  ▼                    ▼
    [SECTION 2]        [SECTION 3]          [SECTION 4]
    apply channel      remediate            skip, justified
         │                  │                    │
         └──────────┬───────┘                    │
                    ▼                            ▼
              ┌──────────┐                  ┌─────────┐
              │ DISPATCH │                  │ ARCHIVE │
              └────┬─────┘                  └─────────┘
                   ▼
             [SECTION 5]
             after submit
```

---

# 2 · PENDING — THE APPLICATION CHANNEL

**New capability.** Nothing currently models how a vacancy is applied to.

**Scope: brink of autonomous, not autonomous.** The system establishes what
kind of application this is, what is needed, and whether the operator is
already registered. The operator does the clicking. Automated form-filling
across arbitrary employer ATS systems is out of scope — different templates,
labels, anchors and frameworks make it unreliable, and unreliable is
unacceptable when the artefact is a job application.

```
   PENDING record
        │
        ▼
   ┌────────────────────────────────┐
   │ CLASSIFY APPLICATION CHANNEL   │
   │ from the vacancy URL + advert  │
   └────────────┬───────────────────┘
                │
     ┌──────────┼──────────────┬──────────────────┐
     ▼          ▼              ▼                  ▼
  BOARD_    BOARD_PROFILE   EMPLOYER_ATS      UNKNOWN
  DIRECT                                          │
     │          │              │                  ▼
     │          │              │            prompt operator
     │          │              │            to classify once
     │          │              │            (learned, stored)
     └──────────┴──────┬───────┴──────────────────┘
                       ▼
          ┌────────────────────────────┐
          │ REGISTRATION CHECK         │
          │ registrations table        │
          └────────────┬───────────────┘
                       │
           ┌───────────┴───────────┐
           ▼                       ▼
      registered              not registered
           │                       │
           │                       ▼
           │              ┌──────────────────┐
           │              │ PROMPT: register │
           │              │ at <url>         │
           │              │ then confirm     │
           │              └────────┬─────────┘
           │                       │
           └───────────┬───────────┘
                       ▼
          ┌────────────────────────────┐
          │ PREPARE PACK               │
          │  • CV (rendered, correct   │
          │    profile: standard or    │
          │    anonymised)             │
          │  • cover letter / essay    │
          │    per submission type     │
          │  • eligibility gates,      │
          │    surfaced first          │
          │  • known questionnaire     │
          │    answers, if any         │
          └────────────┬───────────────┘
                       ▼
          ┌────────────────────────────┐
          │ OPERATOR APPLIES           │
          │ system opens the URL       │
          │ and stops                  │
          └────────────┬───────────────┘
                       ▼
              vanguard dispatch <id>
```

## Channel types

| Type | Meaning | What the operator needs |
|---|---|---|
| `BOARD_DIRECT` | Apply on the board. Upload CV, optionally a cover letter | Board account |
| `BOARD_PROFILE` | Board requires a built profile, applies from that | Board account + profile complete |
| `EMPLOYER_ATS` | Board redirects to the employer's own system | Account on that employer's portal |
| `UNKNOWN` | Not classifiable from the URL | Operator classifies once; stored |

## Registration state — two tables

Both are needed. Boards are a small fixed set; employer portals are unbounded
and grow with every application.

```
registrations
  scope         'board' | 'employer'
  key           board id, or the ATS hostname
  registered    bool
  profile_built bool
  url           where to register
  noted_at      timestamp
  PRIMARY KEY (scope, key)
```

**Registration is asserted by the operator, never detected.** Nothing logs in
to check. The system asks once per portal and remembers.

## Questionnaires

Out of scope for automation. In scope as a **record**: when the operator
answers a question that recurs (notice period, salary expectation, right to
work, relocation), it is stored and offered back on the next application.

```
answers
  question_key   normalised question text
  answer         the operator's answer
  updated_at     timestamp
```

A recall aid, not a form-filler.

---

# 3 · FLAGGED — REMEDIATION

Two causes, and the correct branch depends on which.

```
   FLAGGED record
        │
        ▼
   ┌────────────────────────┐
   │ WHY?                   │
   └───────┬────────────────┘
           │
   ┌───────┴────────────────────────┐
   ▼                                ▼
 |R| < 6                        C < gate
 (shown as "not measured",      but |R| adequate
  includes every C = 1.000)          │
   │                                 │
   ▼                                 ▼
[SECTION 3a]                    [SECTION 3b]
parsing failure                 evidence gap
```

## 3a · `|R| < 6` — the advert was not read

**Not a match quality problem. A parsing problem.**

```
   |R| < 6
      │
      ▼
   ┌──────────────────────────┐
   │ vanguard diagnose <id>   │
   │ why did extraction fail? │
   └──────────┬───────────────┘
              │
   ┌──────────┼──────────────┬────────────────────┐
   ▼          ▼              ▼                    ▼
no_requirement  no_headings  empty_requirement   partial
_heading        _at_all      _section            text
   │              │              │                 │
   ▼              ▼              ▼                 ▼
heading not    advert is     binding bug      snippet, not
recognised     prose         in the parser    full advert
   │              │              │                 │
   ▼              ▼              ▼                 ▼
add to         REJECT as     fix parser        re-paste the
_HEADING_      unassessable  (defect)          full advert
RULES,                                              │
re-score                                            ▼
   │                                            re-score
   └──────────────────┬─────────────────────────────┘
                      ▼
          ┌───────────────────────┐
          │ |R| ≥ 6 now?          │
          └───────┬───────────────┘
                  │
          ┌───────┴────────┐
          ▼                ▼
        yes              no
          │                │
          ▼                ▼
    apply the        REJECT
    3b branch        "advert cannot be assessed"
```

**A genuine `C = 1.000` across a full requirement set** — 15 or more terms,
all matched — progresses straight to PENDING. It has not been observed and it
is not impossible.

## 3b · `C < gate` with adequate `|R|` — the evidence loop

**This is D-04 in its remediation form.**

```
   C < gate, |R| ≥ 6
        │
        ▼
   ┌─────────────────────────────┐
   │ LIST UNMET REQUIREMENTS     │
   │ by gap type                 │
   └────────────┬────────────────┘
                │
     ┌──────────┴──────────┐
     ▼                     ▼
  Type 3                Type 1 / 2
  (Tier C excluded)     (potentially recoverable)
     │                     │
     ▼                     ▼
  NOT RECOVERABLE   ┌──────────────────────────┐
  cannot be         │ SEARCH REPOSITORIES      │
  claimed           │ public and private,      │
     │              │ operator's own only      │
     │              └──────────┬───────────────┘
     │                         │
     │              ┌──────────┴──────────┐
     │              ▼                     ▼
     │        evidence found         nothing found
     │              │                     │
     │              ▼                     │
     │   ┌──────────────────────┐         │
     │   │ ASSESS SUFFICIENCY   │         │
     │   │ does the repo really │         │
     │   │ demonstrate this?    │         │
     │   └──────────┬───────────┘         │
     │              │                     │
     │      ┌───────┴───────┐             │
     │      ▼               ▼             │
     │  sufficient     insufficient       │
     │      │               │             │
     │      ▼               └─────────────┤
     │  ┌──────────────────────┐          │
     │  │ PROPOSE CV EDIT      │          │
     │  │ citing the repo as   │          │
     │  │ source. OPERATOR     │          │
     │  │ CONFIRMS. Never      │          │
     │  │ automatic            │          │
     │  └──────────┬───────────┘          │
     │             ▼                      │
     │      ┌─────────────┐               │
     │      │  RE-SCORE   │               │
     │      └──────┬──────┘               │
     │             │                      │
     └─────────────┼──────────────────────┘
                   ▼
        ┌──────────────────────┐
        │ NEW SCORE?           │
        └──────────┬───────────┘
                   │
      ┌────────────┼────────────┐
      ▼            ▼            ▼
   ≥ gate     improved but   no change
      │        < gate            │
      ▼            │             ▼
   PENDING         ▼          REJECT
                PROMPT:       recommended
                pending or
                reject?
                   │
                   ▼
             if operator picks
             PENDING: warn that
             coverage is below
             gate, and recommend
             a revised CV
```

## The binding constraint

**A repository evidences only what was built.** It can supply a Type 1 gap —
something genuinely done but unstated. It cannot supply a Type 3 gap — AWS is
not evidenced by a repository that never touched AWS.

So this loop recovers **unstated claims, never absent ones**, and a 0.20
vacancy demanding cloud platforms stays at 0.20.

The operator confirms every proposed edit. The classifier proposes; it does
not decide. That rule is unchanged from Phase 1 and is not negotiable.

---

# 4 · UNREACHABLE — SKIP, JUSTIFIED

**Current behaviour retained**, per operator ruling.

```
   UNREACHABLE
        │
        ▼
   ┌──────────────────────────────┐
   │ RECORD THE REASON            │
   │ which Type 3 gaps put the    │
   │ ceiling below the gate       │
   └────────────┬─────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
     default        operator override
        │                │
        ▼                ▼
     SKIP          vanguard override <id> --why "..."
        │          justification mandatory,
        ▼          recorded permanently
     ARCHIVE            │
                        ▼
                     PENDING
```

Override remains available. It has been used correctly and should not be
removed.

---

# 5 · AFTER SUBMIT

Partly built. Three additions.

```
   vanguard dispatch <id>
        │
        ▼
   ┌────────────────────────────────┐
   │ ARCHIVE THE APPLICATION  [NEW] │
   │ /Pipeline_Archive/<employer>/  │
   │   <ts>_job_description.txt     │
   │   <ts>_cv.pdf                  │
   │   <ts>_cover_letter.pdf        │
   │   <ts>_answers.json            │
   └────────────┬───────────────────┘
                ▼
   ┌────────────────────────────────┐
   │ START MONITORING               │
   │ 21 days (30 public sector)     │
   └────────────┬───────────────────┘
                ▼
   ┌────────────────────────────────┐
   │ MAILBOX POLLING          [NEW] │
   │ IMAP or Gmail API              │
   │ correlate → classify           │
   │ archive every message          │
   └────────────┬───────────────────┘
                │
   ┌────────────┼──────────────┬─────────────┐
   ▼            ▼              ▼             ▼
  ACK        PROGRESS       DECLINE      21 days
   │            │              │         silent
   ▼            ▼              ▼             │
archive,    [SECTION 5a]   Template D        ▼
keep         interview     feedback      DORMANT
monitoring   sequence      draft         not a rejection
                              │          keep monitoring
                              ▼
                          stop monitoring
                          advise: try again
```

## 5a · Interview sequence — multi-round tracking `[NEW]`

Current model handles one message, one classification. An interview process is
several rounds over weeks.

```
   PROGRESS received
        │
        ▼
   ┌────────────────────────────────┐
   │ OPEN AN INTERVIEW RECORD       │
   │ rounds table, keyed to vacancy │
   └────────────┬───────────────────┘
                ▼
   ┌────────────────────────────────┐
   │ Template E, phase per round    │
   │  1 CV claims verification      │
   │  2 runtime case study          │
   │  3 executive behavioural       │
   └────────────┬───────────────────┘
                ▼
   ┌────────────────────────────────┐
   │ CONTINUE MONITORING            │
   │ each new message classified    │
   │ and attached to the record     │
   └────────────┬───────────────────┘
                │
     ┌──────────┼──────────┬──────────────┐
     ▼          ▼          ▼              ▼
 next round  QUERY      OFFER         DECLINE
     │          │          │              │
     ▼          ▼          ▼              ▼
 loop to     operator   congratulate   advise
 Template E  answers    STOP           try again
             manually   monitoring     STOP
```

**Terminal states only:** OFFER, DECLINE, or operator closure. Monitoring stops
on a terminal state and on nothing else.

---

# 6 · BUILD SEQUENCE

Agreed A → B → C.

## A · Foundations — **COMPLETE, 12 August 2026**

| | State |
|---|---|
| `/Pipeline_Archive/` on dispatch | **Done.** `archive.py`. Directive §5 amended to match: written at dispatch, one subfolder per vacancy |
| Mailbox polling — IMAP or Gmail | **Done.** `mailbox.py`. Both providers, since several CVs carry different addresses. Monitored address derived from the CV in use |
| Interview record, multi-round | **Done.** `process.py`. Opens on the first PROGRESS, closes only on OFFER, DECLINE or withdrawal |

**Also built, out of sequence:** batch advert ingestion (`adverts.py`). Moved
ahead of A.3 because at the intended 75 vacancies/day the ingest path is the
bottleneck, while the interview path is weeks away.

**Defects surfaced by building A:**

| | |
|---|---|
| B-36 | A LinkedIn advert correlated to an open application |
| B-37 | Gmail Primary is not an IMAP folder — genuine replies fell outside the fetch window |
| B-38 | `X-GM-RAW` sent as a quoted string; the poll returned nothing |
| B-39 | ATS acknowledgements failed to correlate — the sender is never the employer |
| B-41 | Coverage distribution included unmeasured scores, polluting P-01 |
| B-42 | Vacancy ids truncated in the queue, so rows could not be acted on |
| B-43 | No `OFFER` state at all. A job offer classified as AMBIGUOUS |

## B · Repository evidence loop

| | Effort |
|---|---|
| Read local and remote repositories | 2 days |
| Map artefacts to competencies | 2 days |
| Propose Type 1 edits, operator confirms | 1 day |

**Why second:** it needs the FLAGGED branch defined, which section 3b does.
Bounded by truthfulness — recovers unstated claims only.

## C · Application channel — brink of autonomous

| | Effort |
|---|---|
| Channel classification from URL | 1 day |
| `registrations` table, both scopes | 1 day |
| Application pack assembly | 2 days |
| `answers` recall table | 1 day |

**Why last:** largest surface, least certain. **No automated form-filling.**
The system prepares and informs; the operator applies.

---

# 7 · WHAT IS EXPLICITLY OUT OF SCOPE

| | Why |
|---|---|
| Automated form submission | Unreliable across ATS variants. An unreliable job application is worse than none |
| Automated CV edits | Every edit is operator-confirmed. Unchanged from Phase 1 |
| Repository mining for other people | D-04 records the coverage bias. Own repositories only |
| Detecting registration by logging in | Registration is asserted, never detected |
| Automated interview responses | Template E rehearses. It does not answer |

---

# 8 · WHAT WOULD SHOW EACH PART WORKED

The register's discipline: a change justified by evidence is verified by
evidence.

| Part | Verified by |
|---|---|
| Archive | Every DISPATCHED record has a folder with JD and CV |
| Mail polling | A real reply correlated and classified with no manual step |
| Multi-round | An interview process tracked start to finish |
| Repository loop | At least one Type 1 gap recovered from repository evidence, operator-confirmed, coverage measurably improved |
| Channel | Every PENDING record states its channel and registration status |
| Questionnaire recall | A recurring question answered once and offered back |

**Measured with `vanguard stats`, `vanguard diagnose` and `vanguard logs`.**
Not by inspection.
