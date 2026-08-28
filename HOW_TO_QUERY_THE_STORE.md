# HOW TO QUERY THE STORE

Everything Vanguard has ever ingested is in one SQLite file. This is how to
look at it, and what writes to it.

---

## WHERE IT IS

```
data\vanguard.db          everything
archive.db                log records past their retention window
```

**SQLite has no server.** Any client opens the file directly — `sqlite3`, DB
Browser for SQLite, DBeaver, Python's built-in `sqlite3` module.

---

## THE EASY WAY

```powershell
vanguard sql --tables
vanguard sql "SELECT status, COUNT(*) FROM queue GROUP BY status"
vanguard sql "SELECT term, COUNT(*) n FROM gaps GROUP BY term" --csv
```

| Option | Effect |
|---|---|
| `--tables` | List the tables, their columns and row counts |
| `--limit` | Cap the rows. `0` for all. Default 50 |
| `--csv` | CSV instead of a table, for pasting into Excel |

**It is read-only, and refuses to write.** See *Why writing is refused* below.

---

## THE `sqlite3` SHELL

`vanguard sql` is read-only by design. For an interactive session, or to
write, use the shell directly.

### Getting it

Windows does not ship it. Download `sqlite-tools-win-x64-*.zip` from
`sqlite.org/download.html`, unzip, and put `sqlite3.exe` on your PATH — or
just run it from where you unzipped it.

You already have a copy of the library through Python, so this works with no
download at all:

```powershell
python -c "import sqlite3, sys; con = sqlite3.connect('data/vanguard.db'); [print(r) for r in con.execute(sys.argv[1])]" "SELECT status, COUNT(*) FROM queue GROUP BY status"
```

### Opening it

```powershell
sqlite3 dataanguard.db
```

You get a `sqlite>` prompt.

### The one thing everybody hits first

**Every SQL statement ends with a semicolon. Dot-commands take none.**

Type `help` without a dot and SQLite reads it as the start of a statement and
waits:

```
sqlite> help
   ...>
   ...>
```

`...>` means *still waiting*. Everything typed after it — including a
dot-command — is swallowed into that unfinished statement.

**To get out:** type `;` and Enter, or press **Ctrl+C**. You will see a syntax
error and then a clean `sqlite>` prompt.

To leave the shell entirely: `.quit`, or Ctrl+C at a clean prompt.

### The dot-commands

These are the shell's own, not SQL, and take no semicolon.

| | |
|---|---|
| `.tables` | List every table |
| `.schema queue` | The CREATE statement for one table |
| `.schema` | All of them |
| `.headers on` | Show column names — **do this first** |
| `.mode column` | Aligned columns rather than pipe-separated |
| `.mode csv` | CSV, for export |
| `.width 20 40 10` | Set column widths |
| `.once out.csv` | Send the NEXT query's output to a file |
| `.output out.txt` | Send everything following to a file |
| `.output stdout` | Back to the screen |
| `.read script.sql` | Run a file of statements |
| `.dump` | The whole database as SQL text |
| `.backup safe.db` | A consistent copy, safe while in use |
| `.quit` | Leave |

### A session that is actually pleasant

```
sqlite> .headers on
sqlite> .mode column
sqlite> SELECT status, COUNT(*) FROM queue GROUP BY status;
```

Put those two settings in `%USERPROFILE%\.sqliterc` and every session starts
that way:

```
.headers on
.mode column
```

### Exporting

```
sqlite> .headers on
sqlite> .mode csv
sqlite> .once gaps.csv
sqlite> SELECT term, COUNT(*) n FROM gaps GROUP BY term ORDER BY n DESC;
```

`gaps.csv` opens in Excel.

### One line, without the prompt

```powershell
sqlite3 -header -column dataanguard.db "SELECT status, COUNT(*) FROM queue GROUP BY status"
sqlite3 -csv dataanguard.db "SELECT * FROM responses" > responses.csv
```

### Read-only, deliberately

The shell will let you write. If you only mean to look:

```powershell
sqlite3 "file:data/vanguard.db?mode=ro" 
```

Worth the habit. `DELETE FROM queue` with a mistyped `WHERE` is not
recoverable, and the reasons in *Why writing is refused* apply to the shell
exactly as they do to `vanguard sql`.

---

## THE TABLES

| Table | Holds | Written by |
|---|---|---|
| `vacancies` | Every advert ingested | `run`, `paste`, `discover`, `adverts ingest` |
| `queue` | One row per vacancy: status, note, timestamps | every state change |
| `scores` | **One row per scoring run** — history, not current state | `run`, `paste`, `rescore` |
| `gaps` | Every unmet requirement, with its type | scoring |
| `transitions` | The audit trail: every status change with its reason | `approve`, `reject`, `dispatch`, `override`, `resolve` |
| `responses` | Classified inbound mail, with bodies | `poll`, `mail`, `reclassify` |
| `interviews` | One process per application | `poll` on a PROGRESS message |
| `interview_rounds` | One row per stage | `poll` |
| `interview_messages` | Every message attached to a process | `poll` |
| `registrations` | Where you hold accounts | `registrations set` |
| `answers` | Recurring application answers | `registrations answer` |
| `diagnostics` | Parse observations per advert | scoring |

### Two that behave unusually

**`scores` holds one row per RUN, not one per vacancy.** That history is the
input to threshold recalibration. Any query joining it must take the latest:

```sql
JOIN scores s ON s.vacancy_id = q.vacancy_id
             AND s.computed_at = (SELECT MAX(computed_at) FROM scores s2
                                  WHERE s2.vacancy_id = q.vacancy_id)
```

Joining naively multiplies every queue record by its number of scoring runs —
two vacancies rendered as twenty rows after ten runs, which is defect B-21.

**`transitions` is append-only.** Nothing updates or deletes a row. It is the
record of what happened, and a record that can be edited is not one.

---

## QUERIES WORTH HAVING

```sql
-- where everything is
SELECT status, COUNT(*) FROM queue GROUP BY status;

-- what is worth applying to, latest score only
SELECT v.employer, v.title, s.coverage, s.terms_total
FROM queue q
JOIN vacancies v ON v.id = q.vacancy_id
JOIN scores s ON s.vacancy_id = q.vacancy_id
             AND s.computed_at = (SELECT MAX(computed_at) FROM scores s2
                                  WHERE s2.vacancy_id = q.vacancy_id)
WHERE q.status = 'PENDING'
ORDER BY s.coverage DESC;

-- the gap, ranked
SELECT term, COUNT(*) n FROM gaps
WHERE outcome = 'GAP' GROUP BY term ORDER BY n DESC LIMIT 20;

-- what came back, and how it correlated
SELECT v.employer, r.state, r.method, r.received_at
FROM responses r LEFT JOIN vacancies v ON v.id = r.vacancy_id
ORDER BY r.received_at DESC;

-- how long an application took to be rejected
SELECT v.employer,
       julianday(r.received_at) - julianday(q.updated_at) AS days
FROM responses r
JOIN queue q ON q.vacancy_id = r.vacancy_id
JOIN vacancies v ON v.id = r.vacancy_id
WHERE r.state = 'DECLINE';
```

That last one is the input to **P-04**, `silence_days`, which is still an
authored guess.

---

## WHY WRITING IS REFUSED

Not caution about SQL. Three things sit between a command and the database,
and a raw `UPDATE` bypasses every one.

**The state machine.** `UPDATE queue SET status='DISPATCHED'` skips the
legality check, so a vacancy could be dispatched without ever being approved.

**The audit trail.** `transitions` is written by the code, not by a database
trigger. A direct write leaves no record of what changed or why — and that
record is the point of having it.

**The conflict rules.** `responses` relies on `ON CONFLICT` to deduplicate
messages and to stop a decided classification being overwritten. A raw
`INSERT` sidesteps both, and re-polling would multiply every row.

**Query freely. Write through the commands.**

If you need something no command offers, that is worth saying — a missing
command is a better answer than a manual edit that leaves the store
inconsistent.

---

## MOVING IT SOMEWHERE ELSE

Two different jobs, and it is worth separating them.

| | |
|---|---|
| **Copy the DATA out** | One command. Minutes |
| **Make Vanguard USE the new database** | A week |

Most reasons for wanting Postgres — reporting, a dashboard, joining against
other data — need only the first.

---

### To PostgreSQL

```bash
pgloader data/vanguard.db postgresql://user:pass@localhost/vanguard
```

That is the whole migration. `pgloader` reads the SQLite file, creates the
tables, maps the types and copies every row. Nothing to configure.

On Windows it runs under WSL or Docker:

```powershell
docker run --rm -v ${PWD}:/w dimitri/pgloader pgloader /w/data/vanguard.db postgresql://user:pass@host/vanguard
```

Verify:

```sql
SELECT COUNT(*) FROM vacancies;
SELECT status, COUNT(*) FROM queue GROUP BY status;
```

Against `vanguard sql "SELECT status, COUNT(*) FROM queue GROUP BY status"`.
The numbers should match exactly.

---

### To MySQL

No equivalent tool, so it is CSV per table.

```powershell
sqlite3 -header -csv data\vanguard.db "SELECT * FROM vacancies" > vacancies.csv
sqlite3 -header -csv data\vanguard.db "SELECT * FROM queue"     > queue.csv
sqlite3 -header -csv data\vanguard.db "SELECT * FROM responses" > responses.csv
```

Create the tables, then:

```sql
LOAD DATA INFILE 'vacancies.csv' INTO TABLE vacancies
  FIELDS TERMINATED BY ',' ENCLOSED BY '"'
  LINES TERMINATED BY '\r\n' IGNORE 1 ROWS;
```

For the `CREATE TABLE` statements:

```powershell
sqlite3 data\vanguard.db .schema > schema.sql
```

Then two edits: `AUTOINCREMENT` becomes `AUTO_INCREMENT`, and SQLite's
`TIMESTAMP` columns hold ISO text, so declare them `VARCHAR(32)` or convert
them to `DATETIME` on load.

---

### To anything else

```powershell
sqlite3 data\vanguard.db .dump > vanguard.sql
```

Portable SQL — schema and data, one file. Drop the `PRAGMA` lines at the top
and adjust `AUTOINCREMENT` for the target.

---

### What would need care in the SCHEMA

**Timestamps are ISO-8601 text**, and every comparison in the code is a string
comparison. That works because ISO sorts correctly. A target with a real
`TIMESTAMP` type should convert them, and then every query touching one wants
checking.

**`scores` holds one row per RUN.** Any reporting built on the copy must take
the latest per vacancy, or it multiplies every vacancy by its scoring history
— see the join above.

**Booleans are integers.** SQLite has no boolean type; `partial` and
`confirmed` are 0 or 1.

---

### Making Vanguard itself use it

`store.py` is roughly 1,500 lines of direct `sqlite3` calls. Repointing it
means an abstraction layer and rewriting every query. Three things need care:

**`ON CONFLICT(message_key) DO UPDATE`** — Postgres shares the syntax; MySQL
spells it `ON DUPLICATE KEY UPDATE`. That clause deduplicates responses and
protects a decided classification, so it has to keep working exactly.

**`INSERT OR IGNORE` and `INSERT OR REPLACE`** are SQLite spellings with no
direct MySQL equivalent.

**Timestamps**, as above.

### Whether it is worth it

Probably not, and for design reasons rather than effort.

Vanguard is a **single-operator system running on your own machine** — which
is why embeddings run locally rather than through an API. The CV holds
personal data and the mail holds more.

A server database earns its place with concurrent writers, remote access, or
data too large for one file. None applies: one writer, one machine, and a
store that will be tens of megabytes after a year.

**What SQLite gives you instead:** the whole thing is one file you can copy,
back up, or hand over. No service, no credentials, no open port.

**When that changes:** several people sharing one pipeline, or a hosted
version. Both are different products, and both want the abstraction layer
built first.

---

## IF YOU DO EDIT IT DIRECTLY

Back it up first. It is one file:

```powershell
Copy-Item data\vanguard.db data\vanguard.backup.db
```

Then verify afterwards:

```powershell
vanguard stats --storage
vanguard review --status PENDING
```

---

*Full command reference: `COMMANDS.md`. What grows and when to act:
`COMMANDS.md`, section "What grows".*
