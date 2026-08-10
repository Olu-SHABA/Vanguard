# VANGUARD — Video Script

## Segment 3 of 6: Reading a record and deciding

**Target: 7–8 minutes** · Assumes segments 1 and 2

The most important segment in the series. Everything before it produces a
number; this is where the number meets judgement.

---

## Production notes

**Pick a record with real Type 1 and Type 3 gaps.** If the queue does not have
one, run against a known advert first. A record with only Type 3 gaps makes the
judgement section abstract.

**Slow down at the Type 1 section.** That is the decision the system
deliberately does not make, and it is the hardest thing to convey.

**Have a second terminal or a paused shot** of `alias_table.yaml` Tier C ready
for the 4:30 mark.

---

## SCRIPT

---

### [0:00] Terminal

> One vacancy passed the gate. Let us open it properly.

**TYPE:**

```
vanguard review reed:57092035
```

*[let the whole record render. Four seconds of silence — it is dense.]*

> There is a lot here. Take it in sections.

---

### [0:30] The header

**HIGHLIGHT** title, employer, location, closes.

> Title, employer, location. And a closing date, pulled out of the advert text.
>
> That last one matters more than it looks. Before it existed, the system was
> fetching, hydrating and scoring vacancies that had closed a month earlier —
> each one spending an API call from a budget of sixty an hour.
>
> Now anything past its closing date is dropped before hydration. If no date is
> stated, the vacancy is treated as open. Guessing a date could discard a live
> opportunity, and that is the worse error.

---

### [1:00] The score

**HIGHLIGHT** the score block and the bar.

> Coverage zero point seven — fourteen of twenty requirements matched. The bar
> is just a convenience; the figures are the information.
>
> Ceiling zero point eight. That is the highest coverage this vacancy could
> ever reach, given the requirements that are permanently unmet.
>
> The gap between them — zero point seven and zero point eight — is what
> confirming the right gaps could recover. It is not much, and that is honest.

**HIGHLIGHT** the embedder line.

> And it records which model produced these numbers. There is a fallback that
> runs without the language model, and it is markedly worse. A score produced
> by the fallback should not be compared against one produced by the real
> thing, so the system records which it was rather than hoping I remember.

---

### [2:00] The gaps — Type 1

**HIGHLIGHT** the Type 1 block.

> Now the part that matters.
>
> Type one: **evidenced, but unstated.** The system is saying — you have
> probably done this, but your CV does not say so in words this employer would
> match.

*[beat]*

> It is a proposal. Not a decision.
>
> The system cannot know what I actually did. It can see that my CV describes
> incident coordination across three roles, and it can see that this advert
> asks for "responding to incident reports". It can suggest those are the same
> thing. It cannot know.

**READ** one Type 1 term aloud from the screen.

> So the question is mine, and here is the test I use.
>
> Could I answer three follow-up questions about this in an interview, with
> specifics, without inventing anything? Which system. What period. What
> actually happened.
>
> If yes, confirm it, and the refactor engine adds it to the CV citing the role
> it came from. If I hesitate — if the honest answer is "sort of, adjacent" —
> then it is not a type one. It is a type three, and it stays unmet.

*[beat]*

> Nobody is watching me make that call. That is exactly why the test has to be
> a real one.

---

### [3:30] Type 3

**HIGHLIGHT** the Type 3 block.

> Type three: not evidenced. And notice each one carries a reason.

**READ** the pytest exclusion aloud:

> *"No test suite exists in the operator's employment history. Runtime error
> handling and data validation are not code testing."*
>
> I wrote that. Months ago, thinking clearly, about my own history.
>
> The value of writing it down is that it now applies whether I am thinking
> clearly or not. When I am forty applications deep and a role I want asks for
> pytest, that sentence is already sitting there, and it does not care how much
> I want the job.

---

### [4:30] The exclusion list — cut to alias_table.yaml Tier C

> These come from a file. Tier C of the alias table.

**SCROLL** slowly through the Tier C entries.

> AWS. CI/CD. Distributed compute. Line management. Each with a reason.
>
> Here is why this exists. An alias table is a machine for turning unmatched
> terms into matches. Which makes it, equally, a machine for quietly converting
> things I cannot claim into things that look claimed.
>
> Writing the exclusions down makes that impossible by accident.

*[beat]*

> Entries can move. Git was in this list. It came out in August, because
> sustained day-to-day use with an auditable commit history had accumulated —
> the evidence genuinely changed.
>
> Pytest stayed in, at the same sitting, in the same conversation. There are
> six hundred tests in this repository and I did not write them. Claiming
> otherwise would collapse in the first interview that probed it.
>
> The distinction between those two decisions is the whole discipline.

---

### [5:30] Deciding

**CUT BACK** to the record.

**HIGHLIGHT** the `next:` line.

> The record tells me which commands are legal from here. It is a state
> machine, and it will refuse anything else.

**TYPE:**

```
vanguard approve reed:57092035
```

*[let it complete]*

> Approved. Which means eligible for dispatch — and nothing more. It has not
> submitted anything.
>
> I go to the employer's site, apply as a human being, and then come back and
> record that I did.

**TYPE:**

```
vanguard dispatch reed:57092035
```

---

### [6:15] The refusals

> Try something illegal and watch what happens.

**TYPE:** *(a command the state machine will reject)*

```
vanguard approve reed:57204511
```

*[let the error render]*

> It refuses, and it names what **is** permitted from the current state.
>
> That vacancy is UNREACHABLE — its ceiling sits below the gate. There is a way
> through, and it costs something.

**TYPE:**

```
vanguard override reed:57204511 --why "3 of 4 sift criteria strong; SDLC gap accepted"
```

> The justification is mandatory. Not because the system is checking my
> reasoning — it cannot — but because it goes into the permanent record.
>
> In three months, when I am looking at why this application went nowhere, that
> sentence will be sitting there in my own words.

---

### [7:00] Close

> That is the cycle. The system reads, extracts, matches and classifies. Then
> it stops.
>
> It will not confirm a Type 1 gap for me. It will not override an unreachable
> ceiling for me. It will not decide that adjacent is close enough.
>
> Those are the only decisions that actually matter, and they are the ones it
> deliberately does not make.

*[beat]*

> Next segment: vacancies you find yourself. Which is most of the good ones.

---

## Notes for the editor

**7:00 spoken, roughly 8:00 with pauses. The longest segment, and it should be.**

**Do not trim the Type 1 section.** It is the conceptual centre of the whole
series. Everything else is mechanism.

**The git-versus-pytest passage at 5:00** is the most persuasive thing in the
series — a real decision, made both ways, on the same day. Give it room.

**Keep the refusal at 6:15 on screen long enough to read.** The error message
naming what is permitted is a design property worth seeing, not a hiccup.
