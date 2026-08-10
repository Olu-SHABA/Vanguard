# VANGUARD — Video Script

## Segment 1 of 6: What this is and why it refuses to lie

**Target: 4–5 minutes** · Cold open, no prior knowledge assumed

---

## Series plan

| # | Segment | Length | Covers |
|---|---|---|---|
| **1** | **What this is, and why it refuses to lie** | **4–5 min** | **Purpose, the truthfulness constraints, the pipeline** |
| 2 | The daily run | 6–7 min | `run`, reading the output, `review` |
| 3 | Reading a record and deciding | 7–8 min | Gap types, `approve`, `reject`, `override` |
| 4 | Vacancies you find yourself | 4 min | `paste`, why manual is permanent |
| 5 | When a recruiter replies | 5 min | `mail`, `interview`, `feedback` |
| 6 | Weekly review and when things break | 6 min | `stats`, `diagnose`, `logs`, recovery |

Segments stand alone. Someone needing only the daily routine watches 2 and 3.

---

## Production notes

**Terminal:** 100 columns, dark background, 16pt minimum. Run `vanguard` with
default settings — the Unicode output reads better on video than ASCII.

**Pace:** leave two seconds after each command completes before speaking again.
The viewer is reading.

**Do not** speed up terminal output. If a command takes 30 seconds, cut — do
not accelerate. Sped-up text is unreadable and looks evasive.

**On screen throughout:** nothing. No lower thirds, no logo. The terminal is
the content.

---

## SCRIPT

---

### [0:00] Cold open — no terminal yet, just the speaker or a black screen

> Applying for senior data roles has a scaling problem.
>
> To have a real chance, every application needs tailoring to the advert. Which
> requirements does this employer actually care about? Does your CV answer
> them? Which ones does it not?
>
> Do that properly and it takes half an hour a vacancy. Do it for forty
> vacancies and you have lost a working week.
>
> So you automate it. And that introduces a completely different problem.

*[beat]*

> A system that optimises for a match score will learn to fabricate
> qualifications. Not maliciously — it is just doing what it was asked. Ask
> software to maximise a number and it will maximise the number.
>
> That is the failure this system is built to prevent. Everything else follows
> from it.

---

### [0:45] Cut to terminal — empty prompt

> Let me show you the constraint before I show you a single feature. Because if
> you understand this, the rest makes sense on its own.

**TYPE:**

```
vanguard review reed:57092035
```

*[let the record render fully — three seconds of silence]*

> This is a Machine Learning Engineer role the system scored. Look at the
> section headed UNMET.

**HIGHLIGHT** the Type 3 block on screen.

> Type 3 means: this employer asked for something, and there is no basis for it
> in my employment history.
>
> Read what it says underneath. *"No test suite exists in the operator's
> employment history."* That is not a soft warning. The system is stating a
> fact about me, and recording that the requirement is unmet.

*[beat]*

> Here is what makes it different from a warning. The refactor engine — the
> part that rewords the CV to better match an advert — **cannot touch a Type 3
> gap.** Not by policy. The data layer rejects the edit. The code will raise an
> exception before it will write that change.
>
> I could not make it lie here if I wanted to.

---

### [1:45] Second constraint

> There is a second one, and it catches a subtler failure.

**TYPE:**

```
vanguard review --status FLAGGED
```

*[let it render]*

> Look at the coverage column. Some of these say a number. Some say **not
> measured**.
>
> Earlier in the build, this column showed a figure for every row. And one of
> those figures was one point zero zero zero — perfect coverage — sitting at
> the top of the queue.

*[beat]*

> It was a Service Centre Team Manager role.
>
> What had happened: the advert was a two-sentence summary. The system
> extracted exactly one requirement from it — the word "data". My CV contains
> the word "data". One out of one. Perfect score.
>
> The number was arithmetically correct and completely meaningless. And because
> it sorted highest, it looked like the best match I had.

**HIGHLIGHT** a `not measured` row.

> Now, when an advert does not yield enough requirements to measure anything,
> the system says so. It does not show a number.
>
> A confident-looking wrong answer is worse than a refusal. That is a design
> position, and it cost real capability to hold — you will see fewer scores
> than you might expect.

---

### [3:00] Third constraint

> The third one is the shortest to explain.

**TYPE:**

```
vanguard dispatch reed:57092035
```

*[let it complete]*

> That command did not send anything.
>
> It recorded that **I** submitted an application. There is no outbound path in
> this codebase. No command sends an email. No command submits to a portal.
> `feedback` drafts a message for me to send myself, and then stops.
>
> The system prepares and presents. A human transmits. Always.

---

### [3:30] The pipeline — screen shows the ASCII diagram from SOP.md Part 1

> With those three constraints understood, the pipeline is straightforward.

**READ SLOWLY, pointing at each stage:**

> It **ingests** vacancies from configured job boards and removes duplicates.
>
> It **ranks** them — one cheap similarity measure each, no API call. That is a
> filter, not a judgement.
>
> Then it **hydrates** only what survived — fetching the full advert text.
> That step costs an API call per vacancy against a small hourly budget, which
> is exactly why it comes after ranking rather than before.
>
> It **scores** what remains: pull the requirements out of the advert, match
> each one against the CV.
>
> It **classifies** every unmatched requirement — evidenced but unstated,
> evidenced under a different name, or not evidenced at all.
>
> And then it **stops.** It writes a queue record and exits.

*[beat]*

> Everything after that point is mine. Approve, reject, override, ignore.
>
> The system's job is to do the reading. The deciding is not delegated.

---

### [4:30] Close

> Two numbers you will see constantly, and they are not interchangeable.
>
> **Coverage** — matched requirements over total requirements. That is the
> gate. A vacancy passes or fails on it.
>
> **Rank score** — document similarity. That only orders the queue. It never
> gates anything.
>
> The reason for the split: a gate has to be able to tell you *which
> requirement failed*. An embedding cannot do that. It gives you a number and
> no account of itself.
>
> The original design gated on similarity, at a threshold that turned out to be
> mathematically unreachable. A CV and a job advert are different kinds of
> document — one has salary bands and company boilerplate, the other does not.
> They never converge.
>
> That was the first thing this project had to fix.

*[beat]*

> Next segment: the daily run. What it does, what the output means, and what to
> look at first.

---

## Notes for the editor

**Timing.** 4:30 spoken, 5:15 with the pauses. Do not trim the pauses.

**Two moments carry the segment:** the Type 3 exclusion at 1:15, and the
Service Centre Team Manager story at 2:15. Both need the terminal visible and
unhurried.

**Do not add music.** The register is a colleague explaining something, not a
product demo.

**If a command errors during recording**, keep it and address it. A system that
never fails on camera looks staged, and this one has honest failure modes worth
seeing.

---

## Segment 2 outline — for approval before drafting

| Time | Content |
|---|---|
| 0:00 | `vanguard boards` — what is configured and why some sources are manual |
| 1:00 | `vanguard run` — narrate the stages against the earlier diagram |
| 2:30 | Reading the output: collected/kept, truncations, the rank filter line |
| 4:00 | The RESULT block and the four statuses |
| 5:00 | `vanguard review` — the queue, and why rank orders it |
| 6:00 | What to do first each morning |
