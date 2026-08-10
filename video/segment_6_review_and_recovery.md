# VANGUARD — Video Script

## Segment 6 of 6: The weekly review, and when things break

**Target: 6 minutes** · Assumes segments 1–5

---

## Production notes

**Run the three commands beforehand** so you know what the numbers say. This
segment is about interpretation, and interpretation is hard to improvise.

**If you have a real failure in the logs, use it.** A genuine 401 or 503 is
worth more than any constructed example.

---

## SCRIPT

---

### [0:00] Terminal

> Once a week, three commands. They take about two minutes and they are the
> only thing standing between this system and quiet decay.

**TYPE:**

```
vanguard stats
```

*[let it render]*

---

### [0:30] Reading stats

**HIGHLIGHT** the coverage distribution.

> The spread across everything scored. Minimum, median, maximum.
>
> This is what recalibration will eventually be built on. The gate is currently
> zero point six. It was zero point nine four, and it passed nothing — the best
> genuine match I had could not structurally reach it.
>
> I lowered it on evidence, and I will raise it on evidence. Not because the
> queue feels crowded.

**HIGHLIGHT** the most-frequently-unmet list.

> And this is the part that is not really about software.
>
> A requirement appearing thirty times across the vacancies I am looking at is
> not a scoring artefact. It is a standing gap between where I am and where the
> market is.
>
> That is career information. It happens to be produced by a job application
> tool, but what it is telling me is what to go and learn.

---

### [1:30] Diagnose

**TYPE:**

```
vanguard diagnose
```

*[let it render]*

**HIGHLIGHT** the parse rate.

> Sixty-five percent of adverts yield requirements. The rest, the system could
> not read well enough to score.
>
> That number is the health check. A sustained fall means adverts have changed
> shape. A rise means something I fixed actually worked.

**HIGHLIGHT** the unrecognised headings.

> And this is why the command exists.
>
> The system looks for headings like "What you will need" or "Person
> Specification" to find the requirements section. These are headings it found
> and did not recognise.

*[beat]*

> The first time I ran this, I expected a list of legitimate requirement
> headings to add. That is not what came back.
>
> What came back was noise. Job titles. "Location colon". A bare comma,
> appearing three times. Recruiter names.
>
> Which inverted the whole diagnosis. The problem was not that the recognised
> list was too narrow. It was that the heading **detector** was too loose —
> treating field labels and stray punctuation as section headings.

*[beat]*

> I would have spent a day widening the wrong list. Two minutes of measurement
> pointed the other way.

---

### [3:00] Logs

**TYPE:**

```
vanguard logs
```

*[let it render]*

> Every run: when, how long, how many kept, how many scored, how many errors.

**HIGHLIGHT** the errors section.

> And errors that were caught and continued past.
>
> That distinction matters. The pipeline deliberately swallows some exceptions
> — one bad vacancy should not abort a run of forty. But swallowed means the
> reason is gone, unless something records it.

*[beat]*

> There was a period where this system hit a 401 from one board and a 503 from
> another, and neither left any trace. I only knew because I happened to be
> watching the terminal.
>
> If you schedule this to run at six in the morning, you are not watching the
> terminal.

---

### [3:45] Two stores

> Two places, holding different things.
>
> The **database** is structured and queryable. One row per run, one per error.
> How often has this board failed this month. A year of daily runs is a few
> thousand rows.
>
> The **file** is verbose and chronological. Every API call, every rate-limit
> wait. The detail you want when something broke overnight and you are reading
> it at nine.

**TYPE:**

```
vanguard logs --archive
```

> And nothing is ever deleted. Old records move to an archive database; old log
> files are compressed in place and stay readable.
>
> Deleting the record of how the system behaved destroys the evidence for the
> next question — which, in my experience of this project, is always one nobody
> anticipated.

---

### [4:30] When something breaks

> Diagnosis order, cheapest first, always the same.
>
> Logs — what happened. Boards — is the source reachable. Diagnose — is the
> parsing working. Pytest — is the code sound.
>
> Most things resolve at the first or second step.

---

### [5:00] The one rule for changes

> And one procedural rule, which this project learned the hard way.
>
> If a change makes things worse: **revert first, fix second.**

*[beat]*

> In August I tightened that heading detector on good evidence. It rejected
> real headings alongside the noise — anything short ending in a colon, which
> covers "Requirements colon" and "Essential colon".
>
> Reliable scores fell from twenty out of thirty-one to thirteen. The single
> PENDING vacancy disappeared.
>
> The right response was not to keep fixing forward. It was to revert, confirm
> the previous numbers came back, and only then reconsider.

---

### [5:30] Close

> Which is the principle underneath all of this.
>
> Four times in building this system, something was changed on the basis of a
> sample too small to be representative. A threshold set on a metric nobody had
> measured. Extraction designed against a single advert. A diagnosis drawn from
> twenty-nine examples. A detector tightened without re-measuring.
>
> Every one cost a rebuild or a revert.

*[beat]*

> Stats, diagnose and logs exist so that measuring is cheap.
>
> A change justified by evidence has to be verified by evidence before you keep
> it. That is the whole discipline, and it is the only thing I would insist on
> if you take this over.

---

## Notes for the editor

**5:30 spoken, roughly 6:15 with pauses.**

**The diagnose story at 2:00 is the best moment in the series** — an expectation
inverted by two minutes of measurement. Do not rush it.

**The closing principle should be delivered flat.** No emphasis, no summary
music. It is a statement, not a flourish.

**This is the last segment.** Some kind of sign-off is natural, but keep it
brief — the principle is a better ending than a thank-you.
