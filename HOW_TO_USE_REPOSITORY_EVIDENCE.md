# HOW TO USE REPOSITORY EVIDENCE

Five steps. Finds work you have genuinely done that your CV does not mention.

---

## WHAT IT CAN AND CANNOT DO

It finds things you built and forgot to write down. It cannot find things you
did not build — a repository that never touched AWS does not evidence AWS.

So it closes **wording** gaps, not **skills** gaps. If your unmet list is
mostly cloud platforms it will find nothing, and that is the correct answer.

---

## STEP 1 — See what you are missing

```powershell
vanguard stats
```

Look at **most frequently unmet** — the requirements adverts keep asking for
that your CV does not answer.

---

## STEP 2 — Point it at a repository

```powershell
vanguard evidence --repo C:\path\to\your\project --all-gaps
vanguard evidence --repo https://github.com/YourName/your-project --all-gaps
```

A path is read where it sits; a URL is cloned to a temporary folder, read, and
the copy deleted. Repeat `--repo` for several at once. **Private repositories**
work if your normal git access does.

---

## STEP 3 — Read what it found

```
  reporting-engine: 4 competencies, 312 commits, 2024-03 to 2026-08
      data pipelines               11 file(s) of pipeline code

  TYPE 1? ETL
      evidence   reporting-engine: 11 file(s) of pipeline code, 2024-03 to 2026-08
      draft      Built and maintained pipeline code in reporting-engine.
```

**The commit span matters** — two years of work is a different claim from a
weekend, and the dates come from the history rather than anyone's memory.

**Nothing found** is a real answer: those requirements are not in that
repository.

---

## STEP 4 — Decide, one proposal at a time

Ask three questions of each:

- **Did I build this, or did someone else?**
- **Could I answer three follow-up questions on it in an interview, without
  inventing anything?**
- **Which system, what period, what actually happened?**

Hesitate on any of them and **reject it.** It is not a Type 1 gap. It stays
unmet, and that is the system working.

---

## STEP 5 — Add the ones you accept

Nothing is written for you. Open `data\canonical_cv.md` and add the bullet
**in your own words**, under the role it belongs to.

The draft is deliberately plain. Rewrite it with what actually happened —
"Built and maintained pipeline code in reporting-engine" becomes something
like "Designed and maintained the ETL layer of a network reporting engine,
processing 800,000+ rows across daily, weekly and annual cycles."

Then re-score with `vanguard review <id>`. Coverage should rise if the bullet
answered a real requirement.

---

# WHICH REPOSITORIES TO SCAN

**Yes:** anything you built — work projects you own, personal projects, tooling
you wrote and still have.

**No:** forks, tutorials, cloned examples, or anything with many contributors.
Attribution has to be certain, which is why this only reads what you point it
at.

---

# IF SOMETHING GOES WRONG

**"no repository could be read"**
Check the path or URL. For a private repository, confirm `git clone` works
from the same terminal first.

**"nothing evidences the unmet requirements"**
The honest outcome. Try another repository, or accept the gap is real.

**A competency you know is there was not found**
It needs enough files to count — one Dockerfile is a detail, five test files
are a suite. It may still be listed under REPOSITORIES without producing a
proposal.

**Cloning is slow**
`--shallow` fetches recent history only, at the cost of the commit span.

---

# COPY-PASTE VERSION

```powershell
vanguard stats
vanguard evidence --repo https://github.com/YourName/project --all-gaps
# decide each proposal, then edit data\canonical_cv.md by hand
vanguard review <id>
```

*Full reference: `COMMANDS.md`.*
