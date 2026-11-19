# Running SkyPoints at production volume

The [SQLite implementation](../README.md) is a reproducible reference for semantics. [Snowflake DDL](../sql/snowflake.sql) defines the warehouse tables and join. The local pipeline publishes changed profiles and refreshes reporting dates in a single transaction. In the warehouse, publish changed profiles and refresh time-based fields separately so a reporting day change need not rewrite each profile.

## Land and reconcile each delivery

1. Put daily source files in immutable object storage with a manifest giving the feed type, version, object digests, record counts and delivery date. Prefer multiple compressed files for parallel loads. Require newline-delimited JSON for high-volume partner deliveries so a single large JSON document does not become the unit of work.
2. Use external stages and Snowflake `COPY INTO` to land files in parallel. Keep raw profile and JSON payloads, source file identity and record position. Use the manifest and a processing ledger to track discovered, loaded, validated and published objects. A committed load may resume by replaying the immutable input and matching its content identity.
3. Use set-based transformations for each source layout. Normalize field names, date formats and countries, and add validation reasons before writing typed rows. Enforce date formats by checking shape and round-tripping parsed values where needed. Flatten the redemption array with `LATERAL FLATTEN`, retaining the item index for quarantine. Count non-array envelopes separately so the flatten step cannot silently drop them.

## Select winners and publish

- Stage one normalized candidate per member and delivery date, and one candidate per partner transaction and delivery date. Check uniqueness in SQL before `MERGE` because standard Snowflake table primary keys are informational. Compare normalized payloads for same-date duplicates. When initial same-date conflicts appear together, the production design should give the first accepted version a stable receipt sequence from the manifest and retain the conflicting payloads for investigation.
- Select the newest valid candidate for each changed member with `ROW_NUMBER() OVER (PARTITION BY member_key ORDER BY feed_date DESC)`. The candidate set must already be unique per key and date. Compare it to the current row and exclude dates that are equal or older. Apply the equivalent rule to redemptions using `(partner, txn_id)`.
- Materialize the changed profile keys, old country, new country and accepted profile snapshot for the batch. In one DML transaction, merge current staging, remove moved keys from their old country tables, upsert each destination, merge the redemptions and mark the batch published. Precreate tables outside the transaction. Serialize overlapping publication batches so different deliveries cannot each decide they own the same current key.
- Store the next birthday and staleness transition date as operational scheduling fields if materialized metrics are needed at this scale. Refresh members whose thresholds the reporting date crossed. Recalculate those thresholds whenever a profile changes, and catch up any missed refresh dates after a failed run. Where consumers can use a view, calculating these columns for the queried slice avoids time-based writes entirely.

## Operate the pipeline

- Reconcile file and record counts against the manifest, including duplicates and rejects. Reconcile the staged current count against the sum across country tables and alert on duplicates across those tables. Track unmatched redemptions separately from rejects, since a valid profile can arrive later.
- Monitor load lag, quarantine rate, input volumes, merge runtimes and warehouse credits by feed. Parallelize landing and validation, then size the publish warehouse using scan and spill measurements from a representative load. Prune by feed date and touched keys before tuning clustering. Treat the billions-per-day requirement as a workload to benchmark against a measured arrival window and service-level target.
- Keep raw profiles and reject payloads in a restricted schema because they contain names and dates of birth. Grant downstream roles access to only the fields they need. Archive raw deliveries based on the required replay window and data-retention policy.

Snowflake reference documentation for [table DDL](https://docs.snowflake.com/en/sql-reference/sql/create-table), [constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview), and [FLATTEN](https://docs.snowflake.com/en/sql-reference/functions/flatten).
