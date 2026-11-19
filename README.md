# SkyPoints data pipeline

SkyPoints is the airline rewards program in this assessment. The pipeline reads member files and records of miles spent with partner airlines. It keeps one current profile per member and puts that profile in the right country table.

For example, if a member moves from the US to Canada, the pipeline removes their profile from the US table and adds it to the Canada table. Their past miles transactions stay available.

The demo runs on Python and SQLite. The [Snowflake design](docs/snowflake-design.md) explains how the same process could handle billions of records a day.

## Run the demo

Open a terminal in this folder. Use Python 3.12 or later. Python includes everything you need for the demo. GitHub also runs the tests on Windows and Linux.

The first command runs the tests. The next two load the files for January 15 and 16 into `demo.db`. For a fresh run, pick a database name you have not used and use it in both load commands and the queries below.

```sh
python -m unittest discover -s tests -v
python -m skypoints --db demo.db --feed-date 2024-01-15 --profile global demo/members-2024-01-15.psv --redemptions demo/redemptions-2024-01-15.jsonl
python -m skypoints --db demo.db --feed-date 2024-01-16 --profile global demo/members-2024-01-16.psv
```

After each load, the database has four members, three accepted miles transactions, and one rejected transaction. Watch what happens to these records.

| What to inspect | After January 15 | After January 16 |
| --- | --- | --- |
| `global:90001` in the country tables | One row in `table_usa` | One row in `table_canada` |
| Country shown for `DEMO-1` and `DEMO-2` | `USA` | `CAN` |
| Country shown for `DEMO-4` | Blank because its member profile is missing | Still blank, and the transaction is still available |
| Rejected transaction | Line 1, item 3 has negative miles | The same error is still on record |

```sh
python -m sqlite3 demo.db "SELECT country, member_key FROM stage_member ORDER BY member_key;"
python -m sqlite3 demo.db "SELECT 'USA' AS country, member_key FROM table_usa UNION ALL SELECT 'CAN', member_key FROM table_canada;"
python -m sqlite3 demo.db "SELECT txn_id, status, country FROM redemption_with_member ORDER BY txn_id;"
python -m sqlite3 demo.db "SELECT filename, record_number, item_number, reason FROM rejection_report;"
python -m sqlite3 demo.db "SELECT * FROM country_publication_issue;"
```

The last query should return zero rows. It checks whether each profile appears once, in the right country table, with the current delivery date, age, and staleness flag.

### Try a repeat or a late file

- Run the January 16 load again. The totals should stay the same.
- To try a late file, use a fresh database. Load January 16 first, then load January 15 with `--as-of 2024-01-16`. The member should stay in Canada.
- You can refresh age and staleness without loading another file. Run `python -m skypoints --db demo.db --feed-date 2024-01-16 --as-of 2024-01-17`.

The totals printed after a run cover everything loaded into that database so far.

### Recover a failed delivery

- If a file cannot be read, the command names it and exits with code `1`. It saves none of that delivery and keeps earlier deliveries. Fix the file or source name and try the same date again.
- If a few rows fail, the rest of the delivery can still load. `rejection_report` lists the file, row, and reason. A corrected row can use the same date if there is no accepted version for that ID and date. Replacing an accepted version requires a later delivery date.
- When loading an older file, set `--as-of` to the newest delivery date in the database or later. Use a fresh database to see what the data looked like at an earlier date.

## Files the pipeline accepts

Use `--profile SOURCE PATH` for each member file and `--redemptions PATH` for each partner file. A partner file can hold one JSON object, a list of objects, or one object per line (`.jsonl` or `.ndjson`). Each object must use the date passed to `--feed-date`, written as `YYYYMMDD`.

Repeated property names and values such as `NaN` or `Infinity` make the input invalid. In a JSON Lines file, the pipeline rejects the affected line. In a regular JSON file, it stops the whole load. Keep source files unchanged while a load runs.

| Source | Layout and date rules |
| --- | --- |
| `global` | Columns are separated by `\|`. The header starts with `H` and data rows start with `D`. Enrollment and flight dates use `YYYYMMDD`. We read birth dates as `MMDDYYYY`. We map `AU` to `AUS` and `PHIL` to `PHL`. `Post_Code` can appear between `Country` and `DOB`. |
| `usa` | US CSV. Dates use `MDDYYYY` or `MMDDYYYY`. For example, `1052022` means January 5, 2022. This file has no birth date column. |
| `ind` | India CSV. Dates use `M/D/YYYY`. The member type can be blank, `I` for individual, or `C` for corporate. |
| `aus` | Australia CSV. Dates use `YYYY-MM-DD`. Birth dates can be blank. |

If you have the assessment CSVs, put them in `local-data/` and run this command.

```sh
python -m skypoints --db assessment.db --feed-date 2024-01-15 --profile usa local-data/USA.csv --profile ind local-data/IND.csv --profile aus local-data/AUS.csv
```

The local copy of the Australian CSV changes `2021-13-13` to `2021-12-13` as confirmed. A test still checks that the pipeline rejects month `13`. Git ignores `local-data/`. The public demo uses fictional profiles and transactions.

## Why the pipeline works this way

- **Which profile belongs to whom?** Names can repeat, and the partner files use member IDs. The global feed uses `global:<member_id>`. The three country files reuse IDs, so `usa:1` and `ind:1` are treated as separate accounts. A global ID can move countries. The real system would need a list linking local accounts to confirmed global IDs. IDs stay as text to keep leading zeros.
- **Which profile wins?** The files have no update time, so the delivery date decides. A newer valid profile becomes current, and older versions stay in history. On the same date, an exact copy is skipped. If two versions disagree, the first accepted one stays and the other goes to the rejection report. A time or sequence number from the source would let us order same-day updates.
- **Which records pass?** A profile needs a name, ID, and enrollment date. The pipeline rejects invalid dates, dates after delivery, birth dates after enrollment, and countries with no target table. A supplied postcode must have five digits. It stays as text so `02108` keeps its leading zero. Missing optional values, such as a postcode or birth date, stay blank.
- **How are age and staleness calculated?** `--as-of` sets the reporting date. Age counts full years, with February 29 birthdays counted on March 1 in non-leap years. A member becomes stale 91 days after their last flight. If the input date is missing, the result stays blank.
- **How do miles link to members?** Each partner and transaction ID pair has one current row. A later file can update its status. The join shows the member’s current country and keeps transactions visible when the profile is missing. To report the country at the time of the transaction, we would need profile history and a confirmed date for each country move.
- **What happens on retry?** Each raw record keeps its file and row number. A rejected JSON transaction also has an item number within its row. SQLite saves the delivery in one transaction, so a file-level error cannot leave country tables partly updated. A SHA-256 fingerprint detects a repeat file from the same source and delivery date.

## AI use

An AI coding assistant drafted the code, tests, and documentation. The Australian date correction was confirmed by the candidate. The tests and demo show how the code handles country moves, repeat files, bad data, and the 90-day cutoff. The assumptions above should be checked against the real source files before using this design in production.
