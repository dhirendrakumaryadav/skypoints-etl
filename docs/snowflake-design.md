# How SkyPoints could run on Snowflake

The demo uses SQLite to show what the pipeline should do. The plan below describes how to do the same work in Snowflake at much higher volume. The SQL file defines the Snowflake tables and shows how to join miles transactions to member profiles. [Run the local demo](../README.md) · [View the Snowflake SQL](../sql/snowflake.sql)

## 1. Receive and check the files

- Keep the original files in cloud storage. Each delivery should have a list of its files, expected row counts, date, format version, and file fingerprints. This list is called a manifest. Use several compressed files so Snowflake can load them in parallel. For large partner deliveries, use one JSON object per line.
- Use Snowflake `COPY INTO` to load the files. Keep the original data, file name, and row number so a problem can be traced back to its source. Record which files have arrived, loaded, passed checks, and been published. Use the fingerprints to recognise files that arrive again.
- Use SQL to check many rows at once. Use the same column names, date formats, and country codes across sources. Check that each date matches its expected format and is a real calendar date. Use `LATERAL FLATTEN` to turn each list of miles transactions into separate rows. Keep each item’s position for the rejection report. Report any row whose transactions are missing or have the wrong shape.

## 2. Choose the latest records and update country tables

- Keep one accepted row for each member and delivery date. Do the same for each partner transaction. Check for duplicates in SQL before running `MERGE`, because Snowflake does not enforce primary keys on standard tables. Skip exact copies. If two rows from the same date disagree, use a stable receipt order from the file list and save the other row for review.
- Use `ROW_NUMBER()` to find the newest valid row for each changed ID. Update the current row only if the new delivery date is later. For miles transactions, identify each row by its partner and transaction ID.
- Make a list of changed members with their old and new countries. In one transaction, update the current profiles, remove moved members from their old country tables, add them to the new ones, update the miles transactions, and mark the delivery complete. Create the tables ahead of time. Process deliveries that can change the same members one at a time.
- Refresh age and staleness separately from profile updates. If the values must be stored, track when each member will have their next birthday or reach 91 days since their last flight. Update these dates whenever the profile changes and catch up after missed runs. Reports can also calculate both values when they read the data.

## 3. Check that the system is working

- Compare the file and row counts with the delivery list. Account for accepted rows, duplicates, and rejected rows. Check that each current member appears once in the right country table. Track miles transactions with missing profiles separately, since a profile can arrive later.
- Track how late files arrive, how many rows fail, how long updates take, and what each load costs. Test with realistic file sizes and arrival times before choosing a warehouse size. Limit the data read by each update to the dates and IDs it needs. A load test should confirm whether the design meets the billions-per-day target within the time available.
- Limit access to the original profiles and rejected rows because they can contain names and birth dates. Give report users only the columns they need. Keep original files for as long as needed to retry old deliveries and follow the data retention policy.

Snowflake reference documentation for [table DDL](https://docs.snowflake.com/en/sql-reference/sql/create-table), [constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview), and [FLATTEN](https://docs.snowflake.com/en/sql-reference/functions/flatten).
