# HOW TO ADD MANY JOBS AT ONCE

Five steps. Five jobs a day is fine one at a time; fifty is not.

*For a single job, see `HOW_TO_ADD_A_JOB.md`.*

---

## STEP 1 — Save the adverts

Save every advert into the `adverts` folder, one file each.

---

## STEP 2 — Build a list


```powershell
vanguard adverts register --template
```

That writes `adverts\to_register.csv` with a row per file.

---

## STEP 3 — Fill in the details

Open it in Excel or Notepad. Fill in the **employer** and **url** columns for each row.

Leave employer or url blank and that file is skipped — not lost, just not
ingested.

---

## STEP 4 — Register them all


```powershell
vanguard adverts register --from-csv adverts\to_register.csv
```

---

## STEP 5 — Ingest


```powershell
vanguard adverts ingest
```

Anything without an employer and url is skipped and named. One bad advert
never stops the rest.

To keep the folder tidy, move files out as they are ingested:

```powershell
vanguard adverts ingest --move-to done\
```

---

---

## STEP 6 — Work through what came back

Fifty adverts might produce 15 PENDING, 20 FLAGGED and 15 UNREACHABLE. Do not
open them one at a time.

**Clear what you will never apply to** — one judgement, one command:

```powershell
vanguard reject --status UNREACHABLE --dry-run
vanguard reject --status UNREACHABLE --reason "ceiling below gate" --yes
```

Dry-run first; it shows exactly what would change.

**Then work the rest in one sitting:**

```powershell
vanguard session                     # PENDING
vanguard session --status FLAGGED    # later, when you have time
```

Each record shows its coverage, ceiling and any eligibility gate, then asks
`a` approve, `r` reject, `s` skip, `o` show gaps, `q` quit.

Fifteen decisions, one command, no ids typed. `q` stops and leaves everything
after it untouched.

---

# IF SOMETHING GOES WRONG

**"N skipped — no valid entry"**
Those files have no employer or url. Run `vanguard adverts check` to see which.

**"2 rejected" after registering**
Some rows failed validation. The reason is printed beside each filename —
usually a missing employer, or a url that is not a real web address.

**A file you deleted still appears**
```powershell
vanguard adverts check --fix
```
Drops entries whose file has gone. It never deletes an advert.

---

# COPY-PASTE VERSION

```powershell
vanguard adverts register --template
# fill in the CSV
vanguard adverts register --from-csv adverts\to_register.csv
vanguard adverts ingest --move-to done\
vanguard reject --status UNREACHABLE --reason "ceiling below gate" --yes
vanguard session
```

---

*Single job: `HOW_TO_ADD_A_JOB.md`. Full reference: `COMMANDS.md`.*

Fifty records one at a time is a poor use of an evening — every acting command
takes a filter and a `--dry-run`. See `COMMANDS.md`, *Acting on many records*.
