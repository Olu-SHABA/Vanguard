# HOW TO APPLY

What happens after `vanguard session`. Five steps, from an approved record to
a submitted application.

---

## STEP 1 — See what is waiting

```powershell
vanguard todo
```

```
APPLY TO THESE  ·  2 approved
     0.700  14/20  Sanderson    Machine Learning Engineer  reed:57092035
STILL TO REVIEW  ·  3 pending
```

**APPROVED** is your list — decided, and waiting on you to actually apply.

---

## STEP 2 — Find out what the application needs

```powershell
vanguard apply reed:57092035
```

It reports, in order:

**Eligibility** — right to work, security clearance. A role needing clearance
you do not hold is not worth the next ten minutes, whatever it scored.

**Channel** — `BOARD_DIRECT` (apply on the board, upload a CV),
`BOARD_PROFILE` (the board applies from a built profile), or `EMPLOYER_ATS`
(the link goes to the employer's own system).

**Account** — whether you are registered there, with the sign-in URL if not.

**Pack** — submission type, whether your CV is rendered, and any answers you
have given before.

**The URL.** Then it stops. Vanguard does not submit anything.

---

## STEP 3 — Make sure your CV exists

`vanguard apply` says whether `out\cv.pdf` is there. If not:

```powershell
python -c "from vanguard.render import render; render('data/canonical_cv.md','render/standard.css','out/cv.pdf')"
```

For a role wanting an anonymised CV, it says so under **profile**.

---

## STEP 4 — Apply, on their site

Open the URL. Register if you need to, upload the CV, answer the questions.

**Record an account once, so you are not asked again:**

```powershell
vanguard registrations set board reed.co.uk
vanguard registrations set employer careers.acme.com
```

**Record an answer you will be asked again:**

```powershell
vanguard registrations answer "What is your notice period?" "1 month"
```

Next time `vanguard apply` shows it back to you.

---

## STEP 5 — Record that you did

```powershell
vanguard dispatch reed:57092035
```

This writes the job description, your CV and a manifest into
`Pipeline_Archive\`, and starts the clock on the reply.

**Do this even if you applied days ago.** Without it the vacancy stays
APPROVED, replies will not correlate, and nothing is archived — and six weeks
later the advert is gone with no record of what you sent.

`vanguard archive <id>` confirms it landed.

---

# THEN WHAT

Replies arrive by email:

```powershell
vanguard poll
```

Interviews, rejections and everything after that are in
**`HOW_TO_HANDLE_REPLIES.md`**.

---

# IF SOMETHING GOES WRONG

**"not ready to apply"** — it is not APPROVED. Run `vanguard session` or
`vanguard approve <id>` first.

**"NOT RECORDED" against a portal you have used** — registration is asserted,
never detected. Tell it once with `vanguard registrations set employer <host>`.

**"NO CV" but you have one** — it looks in `out\cv.pdf`. Point elsewhere with
`--cv-pdf`.

**You applied but forgot to dispatch** — run it now. The archive timestamp
will be late; everything else works.

---

# COPY-PASTE VERSION

```powershell
vanguard todo
vanguard apply <id>
# apply on their site
vanguard dispatch <id>
```

*Reviewing first: `HOW_TO_ADD_MANY_JOBS.md`. Replies after:
`HOW_TO_HANDLE_REPLIES.md`. Full reference: `COMMANDS.md`.*
