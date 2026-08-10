# VANGUARD — Video Script

## Segment 5 of 6: When a recruiter replies

**Target: 5 minutes** · Assumes segments 1–4

---

## Production notes

**You need two real messages**: a rejection that opens warmly, and anything
else. Anonymise the sender if you like — the classification does not depend on
who wrote it.

**The soft-rejection demonstration is the whole segment.** Everything else is
supporting.

---

## SCRIPT

---

### [0:00] Terminal

> Applications generate replies. Most of them are one of about six things, and
> reading forty of them a week is its own small tax.

**TYPE:**

```
vanguard mail --file reply.txt --sender "recruit@company.com" --subject "Your application"
```

*[let it complete]*

> Correlated to an application, and classified.

---

### [0:45] Correlation runs first

> Two operations there, in a strict order, and the order matters.
>
> **Correlation** first — which application is this about? By reference number,
> then sender domain, then employer and job title in the subject.
>
> Only then classification.

*[beat]*

> If it cannot correlate a message, it records that and stops. It does not
> classify.
>
> Because guessing which application a message belongs to means eventually
> attaching a rejection to the wrong vacancy. And then I stop trusting the
> whole thing.

---

### [1:30] The six states

> Six classifications, mutually exclusive.
>
> **DECLINE.** **PROGRESS** — an interview, a call, an assessment. **ACK** —
> receipt only. **QUERY** — they want an answer from a human. **ADMIN** —
> scheduling. **AMBIGUOUS** — nothing matched, read it yourself.

---

### [2:00] The rule that earns its place

> Now the one thing in this segment worth remembering.

**SHOW** the rejection email on screen. **READ IT ALOUD:**

> *"Thank you for your interest in this role. We were very impressed with the
> calibre of applications and would like to keep your details on file for
> future opportunities."*

*[beat]*

> Two sentences in and that reads like good news.

**READ ON:**

> *"Unfortunately, on this occasion you have not been successful."*

**TYPE:**

```
vanguard mail --file decline.txt --sender "..." --subject "..."
```

**HIGHLIGHT:**

```
DECLINE (rule 1: not been successful)
```

> DECLINE.
>
> The classifier checks decline markers **before** progress markers.
> Deliberately. A decline phrase always wins over a progress phrase in the same
> message.

*[beat]*

> Because rejection emails are written to soften. They open with warmth. If you
> check for progress first, you misread a substantial share of rejections as
> invitations — and the cost of that is somebody preparing for an interview
> that does not exist.

---

### [3:00] Matching discipline

> The matching is whole-phrase and word-boundary anchored. No bare substrings.
>
> The original design matched the word "call" as a substring. Which fires on
> *recall*. As in *"we will recall your details"* — a phrase that appears in
> rejection emails.

**TYPE:**

```
vanguard mail --file recall.txt --sender "..." --subject "..."
```

**HIGHLIGHT** the AMBIGUOUS result.

> Ambiguous. It does not fire, and the system says it does not know rather than
> guessing.

---

### [3:45] What follows

> No classification triggers an outbound action. Not one.
>
> On a PROGRESS, the system suggests I might want the interview simulation.

**TYPE:**

```
vanguard interview reed:57092035 --phase 1
```

*[let a couple of questions render]*

> Questions generated from the CV I actually submitted. It picks a claim with a
> number in it and asks me to defend it — how it was measured, what the
> baseline was, what broke first.
>
> Graded on five dimensions. The first is CV grounding, and a zero there is
> terminal for that answer regardless of everything else. An unsupported claim
> cannot be rescued by good reasoning, and I would rather find that out here.

---

### [4:30] Decline and silence

> On a DECLINE, it drafts a feedback request. Drafts. I read it and I send it
> myself.

**TYPE:**

```
vanguard dormant
```

> And this is applications that have gone quiet past the silence threshold.
> Twenty-one days normally, thirty for public sector.
>
> Dormant is a **derived** state, not a classification. It never counts as a
> rejection and it never triggers a feedback request.
>
> Silence is an absence of information. Employers go quiet and come back, and
> asking for feedback on a decision nobody has made is worse than saying
> nothing.

---

### [5:00] Close

> Next segment: the weekly review, and what to do when something breaks.

---

## Notes for the editor

**5:00 spoken, roughly 5:45 with pauses.**

**The soft rejection at 2:00 is the segment.** Read the email aloud slowly and
let the beat land before revealing the classification.

**The "recall" example at 3:00 is the second-best moment** — a real bug, a real
consequence, thirty seconds to explain.
