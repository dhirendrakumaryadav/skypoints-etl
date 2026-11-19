# SkyPoints member and redemption pipeline

SkyPoints needs one current profile per member, one country table for that profile, and a way to query partner redemptions even when the profile arrives late. This project implements that flow in Python and SQLite and includes Snowflake DDL and a [production design](docs/snowflake-design.md).

## Run the demo

Use Python 3.12 or later from this directory. The demo and tests use the standard library. GitHub Actions runs the test suite on Windows and Linux.

```sh
python -m unittest discover -s tests -v
python -m skypoints --db demo.db --feed-date 2024-01-15 --profile global demo/members-2024-01-15.psv --redemptions demo/redemptions-2024-01-15.jsonl
python -m skypoints --db demo.db --feed-date 2024-01-16 --profile global demo/members-2024-01-16.psv
```

Start with a fresh database name for the walkthrough. The first load publishes four members, three redemptions, and one rejected redemption item. The second moves `global:90001` from the USA to Canada. The profile stays unique, and its two redemptions now show Canada in the current-profile join. The third redemption stays visible with a null country until its profile arrives.

```sh
python -m sqlite3 demo.db "SELECT country, member_key FROM stage_member ORDER BY member_key;"
python -m sqlite3 demo.db "SELECT member_key FROM table_usa UNION ALL SELECT member_key FROM table_canada;"
python -m sqlite3 demo.db "SELECT txn_id, status, country FROM redemption_with_member ORDER BY txn_id;"
python -m sqlite3 demo.db "SELECT f.filename, r.record_number, r.item_number, r.reason FROM rejected_record AS r JOIN landing_file AS f USING (file_id);"
```

Rerun the second load to show that an identical file does not create a new version. To demonstrate an older delivery arriving late, start with a fresh database, run the second load first, then run the first load with `--as-of 2024-01-16`. The member should stay in Canada. To test a new reporting date without new files, run `python -m skypoints --db demo.db --feed-date 2024-01-16 --as-of 2024-01-17`. The CLI reports cumulative counts for the database.

## Input contracts

Pass `--profile SOURCE PATH` once per file. Use `--redemptions PATH` for partner files containing a JSON object, a JSON array of envelopes, or newline-delimited JSON (`.jsonl` or `.ndjson`). All files in an invocation share `--feed-date`; JSON envelopes must carry that date in `YYYYMMDD` form. The input files should be immutable while loading.

| Source | Layout and date rules |
| --- | --- |
| `global` | Pipe-delimited `H` and `D` records. Enrollment and flight dates are `YYYYMMDD`. DOB is assumed to be `MMDDYYYY`. `AU` maps to `AUS` and `PHIL` to `PHL`. A header with `Post_Code` between `Country` and `DOB` is also accepted. |
| `usa` | USA CSV headers. Seven-digit dates are interpreted as `MDDYYYY` and eight-digit dates as `MMDDYYYY`. For example, `1052022` is January 5, 2022. DOB is absent. |
| `ind` | India CSV headers. Dates are `M/D/YYYY`. Member type is optional and accepts `I` or `C`. |
| `aus` | Australia CSV headers. Dates are `YYYY-MM-DD`. A blank DOB is valid. |

With the assessment files in `local-data/`, use:

```sh
python -m skypoints --db assessment.db --feed-date 2024-01-15 --profile usa local-data/USA.csv --profile ind local-data/IND.csv --profile aus local-data/AUS.csv
```

The supplied Australian sample was described as an Excel workbook. This command uses the CSV that was provided. The project copy applies the confirmed correction `2021-13-13` → `2021-12-13`. The tests still exercise the original invalid value to verify the rejection path. `local-data/` is Git-ignored. The tracked demo uses fictional profiles and transactions.

## Decisions worth discussing

- **Identity.** The specification labels member name as the key, but the partner feed joins by member ID and names can recur. The global feed uses `global:<member_id>`. Local IDs recur across the supplied country files, so those files use `usa:`, `ind:`, and `aus:` namespaces. Cross-country moves use the global key. A production crosswalk would link country-local accounts to a global member where the source can confirm the match. IDs stay text, including leading zeros.
- **Ordering.** The supplied profile rows lack an update timestamp. The source delivery date acts as the version. A later valid version wins across country tables, an earlier version remains in history, and identical same-date records collapse. Conflicting same-date payloads go to quarantine after the first accepted version. The pipeline needs a source-owned sequence or update timestamp to order genuine same-day updates reliably.
- **Validation.** Name, ID and enrollment date are required. Missing optional dates yield null derived values. Malformed dates, impossible DOB ordering, future dates relative to the feed, unrouteable countries and invalid redemption items are quarantined. The postcode in the field spec is accepted in the alternate global layout as five digits, stored as text to retain leading zeros. Supplied layouts leave it null. Optional profile whitespace is trimmed. A malformed CSV document, wrong header or unreadable JSON document rolls back the batch. Row-level errors with understood boundaries leave valid records available.
- **Reporting date.** Age counts complete calendar years. A February 29 birthday rolls over on March 1 in non-leap years. `stale_member` is true on day 91 after the last flight. `--as-of` recalculates both values even if no new files arrive. It must be at least the latest loaded delivery date. The country tables represent current membership with a reporting date for the derived values.
- **Redemptions.** Each `(partner, txn_id)` has one current row. A later delivery can update its status. The left join shows the member’s current country and preserves unmatched transactions. An event-time membership report would need a join against profile history and a confirmed effective date.
- **Failure and retry.** Every parsed record keeps a file and record reference. For JSON, a rejected item also has a one-based position in the envelope. The SQLite transaction covers raw data, accepted versions, rejections, staging and country publication. A SHA-256 digest identifies repeat files within the same source and delivery date.

## AI use

An AI coding assistant drafted the implementation, tests, and documentation. The user confirmed the Australian date correction. The assumptions above identify decisions to review against the source contract before submission. The automated tests and demo provide reproducible checks for country moves, replay, ambiguous date handling, quarantine and the exact 90-day boundary.
