# VANGUARD — Video Script

## Segment 4 of 6: Vacancies you find yourself

**Target: 4 minutes** · Assumes segments 1–3

Short, and more important than its length suggests. The manual path is
permanent architecture, not a workaround.

---

## Production notes

**Have a real LinkedIn advert open in a browser** before recording. Show the
copy, not just the paste.

**Copy the WHOLE advert.** If you demonstrate a partial copy and it scores
badly, that is a useful accident — keep it and explain.

---

## SCRIPT

---

### [0:00] Browser, a job advert on screen

> Most of the roles worth applying for, I find myself. Browsing, or somebody
> sends me a link.
>
> LinkedIn in particular is probably the densest source of senior data roles in
> the country. And the system will never fetch a single one of them.

**CUT** to terminal.

---

### [0:30] Why

> Their User Agreement prohibits automated collection. So the adapter for
> LinkedIn does not have a disabled fetch method — it has one that raises an
> exception.

**TYPE:**

```
vanguard boards
```

**HIGHLIGHT** the LinkedIn row.

> *"Manual adapter — no endpoint. Operator paste is the ingress."*
>
> There is nothing to switch on. The compliance decision is expressed in the
> code rather than in a setting, because a setting is something someone changes
> at eleven at night when they are frustrated.

---

### [1:00] The paste

**CUT** to the browser. **Select the whole advert.** Copy.

> The whole advert. Including the requirements section — that is the part that
> matters.

**CUT** to terminal.

**TYPE:**

```
vanguard paste --file advert.txt --employer "Acme Analytics" --url "https://..."
```

*[let it complete]*

> And that is it. Scored, classified, queued.

---

### [1:45] The point

> Here is what I want to be clear about, because it sounds like a compromise
> and is not.
>
> Everything downstream is **identical.** Requirement extraction, coverage
> scoring, the alias table, gap classification, the refactor engine, template
> drafting, the queue, the state machine, response correlation.
>
> The only difference is that one step is hand-fed.

*[beat]*

> A pasted vacancy is not a second-class vacancy. It is often a better one,
> because I have the complete advert rather than whatever an API chose to
> return.

---

### [2:15] Adzuna

> Adzuna is worth mentioning here, because it ended up in the same place for a
> completely different reason.

**HIGHLIGHT** the Adzuna row in `vanguard boards`.

> Polling Adzuna is permitted. I have credentials. It worked.
>
> And every description it returned was capped at exactly five hundred
> characters. Not approximately — exactly. Two sentences.

*[beat]*

> A Service Centre Team Manager role scored one point zero zero zero from one
> of those summaries. One requirement extracted, and it was the word "data".
>
> So Adzuna moved to manual as well. Not because of terms — because it cannot
> supply enough text to assess anything. Good for finding vacancies, useless
> for judging them.
>
> I browse it, and I paste what looks worth assessing.

---

### [3:00] The rule

> Which gave us a rule worth stating plainly.
>
> A board that cannot supply the full advert text is not processed through its
> API at all. It defaults to paste.

**SHOW** the `supplies_full_text` line in `boards.yaml`.

> That is a capability flag, separate from the tier. Tier records what a
> board's terms **permit**. This records whether what it returns is **enough**.
>
> A board can be perfectly legal to poll and still useless to score. Those are
> different questions and they needed different answers.

---

### [3:30] Close

> So: two boards automated, everything else by hand, and the by-hand path is
> not a lesser one.
>
> If you take one thing from this segment — when you paste, paste the whole
> advert. A truncated paste produces exactly the same problem as a truncated
> fetch. The system will tell you it could not measure anything, and it will be
> right.

*[beat]*

> Next: what happens when somebody replies.

---

## Notes for the editor

**3:30 spoken, roughly 4:00 with pauses.**

**The Adzuna story at 2:15 is the segment's payload.** Terms and capability
producing the same outcome by different routes is the idea worth landing.

**Keep it short.** The temptation is to expand it to match the others. Resist —
the message is simple and repetition weakens it.
