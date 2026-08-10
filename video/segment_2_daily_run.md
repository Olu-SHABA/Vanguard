# VANGUARD — Video Script

## Segment 2 of 6: The daily run

**Target: 6–7 minutes** · Assumes segment 1

---

## Production notes

**Before recording:** clear the queue of anything distracting, or accept it and
narrate what is there. A realistic queue is better than a staged one.

**The run takes about 30 seconds.** Do not speed it up. Either cut to the
finished output, or let it play and fill the silence with the pipeline
explanation from segment 1 — the stages are happening as you speak.

**Have `vanguard boards` output visible** before starting the run. It explains
why only one board is polled.

---

## SCRIPT

---

### [0:00] Terminal, empty prompt

> This is the command you will run most days. Before I run it, one thing worth
> checking — what the system is actually configured to do.

**TYPE:**

```
vanguard boards
```

*[let it render — three seconds]*

> Ten boards registered. Four enabled. And notice this: only **one** is
> automatable.

**HIGHLIGHT** the summary line.

> That surprises people, so it is worth explaining, because there are two
> completely different reasons a board ends up manual.

---

### [0:45] The two reasons

**HIGHLIGHT** the LinkedIn row.

> LinkedIn. Their User Agreement prohibits automated collection. So the system
> does not attempt it — and not as a setting I could switch on. The adapter
> raises an exception if anything tries to fetch from it. There is no
> automated path to enable.
>
> That is a **terms** reason.

**HIGHLIGHT** the Adzuna row.

> Adzuna is different. Polling it is perfectly permitted. But its free API caps
> every job description at exactly five hundred characters.
>
> Five hundred characters is two sentences. It cannot contain a requirements
> list. So anything scored from it produces a number that looks like a
> measurement and is not.
>
> That is a **capability** reason.

*[beat]*

> Different causes, same outcome — I paste those by hand. Segment four covers
> that, and it is not a workaround. It is the design.

---

### [1:45] The run

**TYPE:**

```
vanguard run
```

*[let it play. Narrate over it, unhurried:]*

> While that runs — it is doing the five stages from the last segment.
> Ingesting, ranking, hydrating what survived, scoring, classifying.
>
> The slow part is hydration. Each vacancy needs a second API call to fetch its
> full advert text, and the board allows sixty an hour. That budget is the
> reason the ranking step exists at all.

*[wait for completion]*

---

### [2:30] Reading the output — ingestion

**HIGHLIGHT:**

```
collected 45 -> kept 42 (3 duplicate(s) logged)
```

> Forty-five fetched, forty-two kept. Three were duplicates — the same vacancy
> appearing under two search terms.
>
> Note the word **logged**, not discarded. The duplicates are recorded, because
> overlap between sources is something worth being able to measure. If two
> boards return largely the same corpus, I want to know that rather than
> quietly double-count.

**HIGHLIGHT** the truncation block.

> This is the system telling me the result is **incomplete**.
>
> Reed has three thousand nine hundred data scientist vacancies. I took fifteen.
> Not because fifteen is a good number — because fifteen per search term is
> what fits inside the hourly hydration budget.
>
> The important thing is that it says so. An earlier version of this took the
> first hundred and reported nothing, so a partial harvest was indistinguishable
> from a complete one.

---

### [3:30] The rank filter

**HIGHLIGHT:**

```
rank filter: 31 of 42 above 0.25 (11 not hydrated or scored)
```

> Eleven vacancies were dropped here, before any expensive work happened.
>
> Ranking costs one embedding — no API call, no requirement extraction, no gap
> classification. So the cheap measure runs first, and only what survives gets
> the expensive treatment.
>
> Before this existed, a Finance Business Partner role consumed exactly the
> same API call as a Machine Learning Engineer. That was a working slot spent
> on something I would never open.

---

### [4:00] The scoring lines

**HIGHLIGHT** a few individual result lines.

> Now each vacancy, with its status, its coverage, and either a ceiling or the
> words **not measured**.

**POINT AT** a PENDING line.

> Coverage zero point seven, ceiling zero point eight. That passed the gate.
> This is the one I will look at.

**POINT AT** an UNREACHABLE line.

> This one has a ceiling below the gate. Which means: even if I confirmed every
> gap the system thinks I could legitimately claim, it still could not pass.
>
> That is not a failure. It is a true statement about the distance between my
> CV and that role, and it took two seconds instead of half an hour.

**POINT AT** a `not measured` line.

> And this one was never scored at all. The advert did not yield enough
> requirements to compute anything meaningful, so the system declines to give
> me a number.

---

### [5:00] The result block

**HIGHLIGHT** the RESULT section.

> The summary. Four statuses, and they are not degrees of the same thing.
>
> **PENDING** — passed the gate. Ready for me. This is the good one.
>
> **FLAGGED** — something is unresolved. The system stopped rather than
> guessing. That word sounds positive and it is not.
>
> **UNREACHABLE** — real gaps block it.
>
> And the last line.

**HIGHLIGHT:**

```
no transmission occurred — Vanguard never submits
```

> It prints that on every single run. Not because I might forget, but because
> anyone else reading this output should never have to wonder.

---

### [5:45] What to do next

**TYPE:**

```
vanguard review
```

*[let it render]*

> The queue, ordered by rank score — strongest first.
>
> Rank score orders it. Coverage gates it. Those are different jobs, and
> conflating them was the original design's most serious mistake.

**POINT AT** the coverage column.

> And where the system could not measure something, it says so rather than
> printing a figure.

*[beat]*

> That is the daily cycle. Run it, look at what reached PENDING, ignore the
> rest unless the count looks wrong.
>
> Two things worth stopping for: if the error count is not zero, or if reliable
> scores drop sharply from the previous run. Segment six covers both.

---

### [6:30] Close

> Next segment: opening one of these records and actually deciding. Which is
> where the gap classification earns its place — and where the system stops
> and hands the judgement back.

---

## Notes for the editor

**6:30 spoken, roughly 7:15 with pauses.**

**The two-reasons explanation at 0:45 is the segment's core.** It answers the
question every viewer will have — why is only one board automated — and the
answer is more interesting than the question.

**If the run produces an error**, keep it. Narrate it and move on. It
demonstrates the failure isolation without staging anything.

**Do not cut the truncation block.** It looks like noise and it is the opposite:
the system declaring the limits of what it just did.
