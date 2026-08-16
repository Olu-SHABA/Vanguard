# HOW TO ADD A JOB BY HAND

Five steps. Works for LinkedIn, NHS Jobs, Civil Service, Indeed, anywhere.

---

## STEP 1 — Open the job in your browser

**On LinkedIn:** scroll down and click **"See more"** under the description.

The description is folded shut by default. If you skip this you copy about
three sentences, and the system will tell you it could not measure anything.

**On NHS Jobs:** scroll to **"Person specification"** and make sure you can see
the Essential and Desirable lists.

**On Civil Service Jobs:** scroll to **"Behaviours"** and the **word limit** for
the personal statement. You need both.

---

## STEP 2 — Select and copy the whole advert

Click just before the job title. Hold **Shift** and click at the very end of
the requirements list.

Press **Ctrl+C**.

You want everything from the title down past the last requirement. Extra text
does not matter — missing requirements does.

---

## STEP 3 — Paste it into a text file

Open Notepad. **Ctrl+V**. Save it into the `pasted` folder in your repo:

```
C:\Users\USER\Desktop\Project_Vanguard_Global\Project_Vanguard_build\vanguard-repo\vanguard\pasted\job.txt
```

If the `pasted` folder does not exist, create it.

**Watch the filename.** Notepad adds `.txt` automatically. If you type
`job.txt` you may get `job.txt.txt`. Choose "All Files" in the Save As type
dropdown to be certain.

---

## STEP 4 — Run the command

In PowerShell, in your repo folder:

```powershell
vanguard paste --file pasted\job.txt --employer "Company Name" --url "https://..."
```

Replace `Company Name` with the employer. Replace the URL with the page you
copied from.

It prints an id like `linkedin:1e7b8c860dc2ff4c`. Copy that.

---

## STEP 5 — Look at it

```powershell
vanguard review linkedin:1e7b8c860dc2ff4c
```

Then decide:

```powershell
vanguard approve linkedin:1e7b8c860dc2ff4c
```

or

```powershell
vanguard reject linkedin:1e7b8c860dc2ff4c --reason "requires clearance"
```

Apply on the employer's website yourself. Then:

```powershell
vanguard dispatch linkedin:1e7b8c860dc2ff4c
```

---

# IF SOMETHING GOES WRONG

**"not measured"**
You missed the requirements. Go back to step 1 — on LinkedIn, click
**"See more"**.

**"could not determine job title"**
Add the title yourself:
```powershell
vanguard paste --file pasted\job.txt --title "Data Scientist" --employer "Acme"
```

**"no advert text supplied"**
Wrong filename. Check with `dir pasted` — you are probably looking at
`job.txt.txt`.

**Employer shows "(not stated)"**
You left out `--employer`. Harmless, but add it next time.

---

# COPY-PASTE VERSION

```powershell
vanguard paste --file pasted\job.txt --employer "Acme" --url "https://..."
vanguard review <id>
vanguard approve <id>
vanguard dispatch <id>
```

---

*Adding fifty at once? See `HOW_TO_ADD_MANY_JOBS.md`.*
*Per-board detail and configuration: `MANUAL_ENTRY.md`.*
