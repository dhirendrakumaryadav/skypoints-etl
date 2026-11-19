"""Load, validate, and publish one batch in a SQLite transaction."""

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from itertools import chain
from pathlib import Path

from .feeds import (
    COUNTRIES, InvalidRecord, normalize_profile, normalize_redemption,
    profile_rows, redemption_envelope, redemption_rows,
)

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "sqlite.sql"
PROFILE_KEYS = ("member_key",)
REDEMPTION_KEYS = ("partner", "txn_id")


def run(database, feed_date, as_of, profiles, redemptions):
    with closing(sqlite3.connect(database, timeout=30)) as db:
        db.executescript(SCHEMA.read_text(encoding="utf-8"))
        with db:
            db.execute("BEGIN IMMEDIATE")
            partner_inputs = (("redemptions", path) for path in redemptions)
            for source, path in chain(profiles, partner_inputs):
                path = Path(path)
                try:
                    load_file(db, source, path, feed_date)
                except (OSError, ValueError, csv.Error) as error:
                    raise ValueError(f"{source} input {path.name}: {error}") from error
            latest_feed = db.execute("SELECT max(feed_date) FROM landing_file").fetchone()[0]
            if latest_feed and as_of < latest_feed:
                raise ValueError(f"reporting date precedes a loaded feed ({latest_feed}); set --as-of")
            publish(db, as_of)
            return {
                "files": count(db, "landing_file"),
                "members": count(db, "stage_member"),
                "redemptions": count(db, "redemption"),
                "rejections": count(db, "rejected_record"),
                "by_country": {country: count(db, table) for country, table in COUNTRIES.items()},
                "as_of": as_of,
            }


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def load_file(db, source, path, feed_date):
    with path.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
        binary.seek(0)
        result = db.execute(
            "INSERT INTO landing_file (source, feed_date, filename, sha256) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (source, feed_date, sha256) DO NOTHING",
            (source, feed_date, path.name, digest),
        )
        if result.rowcount == 0:
            return

        file_id = result.lastrowid
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            is_redemption = source == "redemptions"
            if is_redemption:
                rows = ((number, raw, None) for number, raw in redemption_rows(stream, path.suffix))
            else:
                rows = profile_rows(stream, source)
            for number, raw, fields in rows:
                origin = (file_id, number)
                payload = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                db.execute("INSERT INTO landing_record VALUES (?, ?, ?)", (*origin, payload))
                try:
                    if is_redemption:
                        load_redemptions(db, origin, raw, feed_date)
                    else:
                        values = normalize_profile(raw, source, feed_date, fields)
                        record_version(db, origin, feed_date, values, PROFILE_KEYS, "profile_version", "stage_member")
                except InvalidRecord as error:
                    reject(db, origin, 0, error)


def load_redemptions(db, origin, raw, feed_date):
    member_key, items = redemption_envelope(raw, feed_date)
    for number, item in enumerate(items, 1):
        try:
            values = normalize_redemption(item, member_key, feed_date)
            record_version(db, origin, feed_date, values, REDEMPTION_KEYS, "redemption_version", "redemption")
        except InvalidRecord as error:
            reject(db, origin, number, error)


def reject(db, origin, item, error):
    db.execute("INSERT INTO rejected_record VALUES (?, ?, ?, ?)", (*origin, item, str(error)))


def record_version(db, origin, feed_date, values, keys, history, current):
    version_key = (*(values[key] for key in keys), feed_date)
    payload = json.dumps(values, sort_keys=True)
    where = " AND ".join(f"{key} = ?" for key in (*keys, "feed_date"))
    existing = db.execute(f"SELECT payload FROM {history} WHERE {where}", version_key).fetchone()
    if existing:
        if existing[0] != payload:
            raise InvalidRecord("conflicting records for the same key and feed_date")
        return

    db.execute(
        f"INSERT INTO {history} ({', '.join(keys)}, feed_date, payload, file_id, record_number) "
        f"VALUES ({', '.join('?' for _ in keys)}, ?, ?, ?, ?)",
        (*version_key, payload, *origin),
    )
    values = {**values, "feed_date": feed_date}
    updates = [f"{name} = excluded.{name}" for name in values if name not in keys]
    if current == "stage_member":
        updates.append("as_of_date = NULL")
    db.execute(
        f"INSERT INTO {current} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {', '.join(updates)} "
        f"WHERE excluded.feed_date > {current}.feed_date",
        tuple(values.values()),
    )


def publish(db, as_of):
    # Capture the keys before assigning the reporting date to staging.
    db.execute("CREATE TEMP TABLE publish_key (member_key TEXT PRIMARY KEY) WITHOUT ROWID")
    db.execute(
        "INSERT INTO publish_key SELECT member_key FROM stage_member WHERE as_of_date IS NOT ?",
        (as_of,),
    )
    db.execute(
        """
        UPDATE stage_member
        SET age = CAST(substr(:as_of, 1, 4) AS INTEGER) - CAST(substr(dob, 1, 4) AS INTEGER)
                  - (substr(:as_of, 6) < substr(dob, 6)),
            stale_member = (julianday(:as_of) - julianday(last_flight_date)) > 90,
            as_of_date = :as_of
        WHERE member_key IN (SELECT member_key FROM publish_key)
        """,
        {"as_of": as_of},
    )
    for country, table in COUNTRIES.items():
        db.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM stage_member WHERE 0")
        db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {table}_member_key ON {table} (member_key)")
        db.execute(f"DELETE FROM {table} WHERE member_key IN (SELECT member_key FROM publish_key)")
        db.execute(
            f"INSERT INTO {table} SELECT m.* FROM publish_key AS k "
            "JOIN stage_member AS m USING (member_key) WHERE m.country = ?",
            (country,),
        )
