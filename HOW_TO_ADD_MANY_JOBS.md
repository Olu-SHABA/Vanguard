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

Leave a row blank and that file is skipped — not lost, just not ingested.

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
vanguard review
```

---

*Single job: `HOW_TO_ADD_A_JOB.md`. Full reference: `COMMANDS.md`.*
