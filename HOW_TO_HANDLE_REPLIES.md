# HOW TO HANDLE REPLIES

Five steps. From an employer's email to an interview, or a rejection.

---

## STEP 1 — Check the mailbox

```powershell
vanguard poll
```

Reads your mailbox and matches each message to an application. Add `--dry-run`
to see what it finds without recording anything. **Nothing is sent, replied to
or deleted.**

`UNREACHABLE` means credentials are missing — see `COMMANDS.md` under
`vanguard poll`. You need an **app password**, not your account password.

---

## STEP 2 — Read what came back

Each message is one of these:

| | Means | Do |
|---|---|---|
| **OFFER** | You got the job | Nothing. Well done |
| **PROGRESS** | Interview or assessment | Step 3 |
| **DECLINE** | Unsuccessful | Step 5 |
| **QUERY** | They asked something | Answer it |
| **ACK** / **ADMIN** | Receipt, or scheduling | Nothing |
| **AMBIGUOUS** | No marker fired | Read it |

**UNCORRELATED** — matched no application, usually a job alert. **"matched 2
applications"** — several matched; the system names both rather than guessing.

---

## STEP 3 — Prepare for the interview

```powershell
vanguard interviews
```

Lists everything currently in progress. Then:

```powershell
vanguard interviews reed:57092035
```

Shows the rounds so far and tells you which phase to rehearse:

```
next:  vanguard interview reed:57092035 --phase 2
```

Run that. It asks questions drawn from the CV you actually submitted —
phase 1 defends your CV claims, 2 is a technical problem, 3 is behavioural.

---

## STEP 4 — Keep polling

Run `vanguard poll` whenever you check your email. Another **PROGRESS** opens
the next round; **ADMIN** and **QUERY** attach to the current one — confirming
a time is part of that interview, not a new stage. **OFFER** or **DECLINE**
closes it.

**Silence closes nothing.** Employers go quiet between rounds and come back.

If you withdraw:

```powershell
vanguard interviews reed:57092035 --withdraw "accepted another role"
```

---

## STEP 5 — After a rejection

```powershell
vanguard responses --status DECLINE          # find it
vanguard feedback <id> --name "Your Name" --contact "you@example.com"
```

Drafts a short message asking what was missing. **Read it, then send it
yourself** — nothing is sent for you.

---

# IF SOMETHING GOES WRONG

**"UNCORRELATED" on a real reply** — nothing identified it. Use
`vanguard mail --file` with the employer name in `--subject`.

**No messages found** — `vanguard poll --since-days 60 --category all`. By
default it reads the Primary tab, last 30 days.

**Nothing in `vanguard interviews`** — a process opens only on a **PROGRESS**
message against a **dispatched** application.

---

# A MESSAGE THE POLL DID NOT FIND

A forward, or a reply to a different address, can be entered by hand with
`vanguard mail --file`. Everything after that is identical — see
`COMMANDS.md`.

---

# COPY-PASTE VERSION

```powershell
vanguard poll
vanguard responses
vanguard funnel                  # where applications stop, and why
vanguard interview <id> --phase 1
```

*Full reference: `COMMANDS.md`. Day-to-day routine: `SOP.md`.*
