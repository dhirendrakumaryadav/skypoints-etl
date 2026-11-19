PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS landing_file (
    file_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    feed_date TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    UNIQUE (source, feed_date, sha256)
);

CREATE TABLE IF NOT EXISTS landing_record (
    file_id INTEGER NOT NULL REFERENCES landing_file,
    record_number INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (file_id, record_number)
);

CREATE TABLE IF NOT EXISTS rejected_record (
    file_id INTEGER NOT NULL,
    record_number INTEGER NOT NULL,
    item_number INTEGER NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (file_id, record_number, item_number),
    FOREIGN KEY (file_id, record_number) REFERENCES landing_record
);

CREATE TABLE IF NOT EXISTS profile_version (
    member_key TEXT NOT NULL,
    feed_date TEXT NOT NULL,
    payload TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    record_number INTEGER NOT NULL,
    PRIMARY KEY (member_key, feed_date),
    FOREIGN KEY (file_id, record_number) REFERENCES landing_record
);

CREATE TABLE IF NOT EXISTS stage_member (
    member_key TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    member_name TEXT NOT NULL,
    country TEXT NOT NULL CHECK (country IN ('USA', 'IND', 'PHL', 'CAN', 'AUS')),
    enrollment_date TEXT NOT NULL,
    last_flight_date TEXT,
    dob TEXT,
    tier_code TEXT,
    agent_name TEXT,
    state TEXT,
    post_code TEXT,
    active_flag TEXT,
    member_type TEXT,
    feed_date TEXT NOT NULL,
    age INTEGER,
    stale_member INTEGER CHECK (stale_member IN (0, 1)),
    as_of_date TEXT,
    FOREIGN KEY (member_key, feed_date) REFERENCES profile_version
);

CREATE INDEX IF NOT EXISTS stage_member_country ON stage_member (country);

CREATE TABLE IF NOT EXISTS redemption_version (
    partner TEXT NOT NULL,
    txn_id TEXT NOT NULL,
    feed_date TEXT NOT NULL,
    payload TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    record_number INTEGER NOT NULL,
    PRIMARY KEY (partner, txn_id, feed_date),
    FOREIGN KEY (file_id, record_number) REFERENCES landing_record
);

CREATE TABLE IF NOT EXISTS redemption (
    partner TEXT NOT NULL,
    txn_id TEXT NOT NULL,
    member_key TEXT NOT NULL,
    txn_date TEXT NOT NULL,
    miles_redeemed INTEGER NOT NULL CHECK (miles_redeemed > 0),
    status TEXT NOT NULL,
    feed_date TEXT NOT NULL,
    PRIMARY KEY (partner, txn_id),
    FOREIGN KEY (partner, txn_id, feed_date) REFERENCES redemption_version
);

CREATE INDEX IF NOT EXISTS redemption_member ON redemption (member_key);

CREATE VIEW IF NOT EXISTS redemption_with_member AS
SELECT r.*, m.member_name, m.country
FROM redemption AS r
LEFT JOIN stage_member AS m ON m.member_key = r.member_key;

CREATE VIEW IF NOT EXISTS rejection_report AS
SELECT f.file_id, f.source, f.feed_date, f.filename, r.record_number,
       NULLIF(r.item_number, 0) AS item_number, r.reason
FROM rejected_record AS r
JOIN landing_file AS f USING (file_id);

-- A healthy publication returns zero rows.
CREATE VIEW IF NOT EXISTS country_publication_issue AS
WITH published AS (
    SELECT 'USA' AS target_country, * FROM table_usa
    UNION ALL SELECT 'IND', * FROM table_india
    UNION ALL SELECT 'AUS', * FROM table_australia
    UNION ALL SELECT 'CAN', * FROM table_canada
    UNION ALL SELECT 'PHL', * FROM table_philippines
)
SELECT s.member_key, s.country, 'missing_from_target' AS issue
FROM stage_member AS s
WHERE NOT EXISTS (
    SELECT 1 FROM published AS p
    WHERE p.member_key = s.member_key AND p.target_country = s.country
)
UNION ALL
SELECT p.member_key, p.target_country, 'unexpected_in_target'
FROM published AS p
LEFT JOIN stage_member AS s ON s.member_key = p.member_key
WHERE s.country IS NOT p.target_country OR p.country IS NOT p.target_country
UNION ALL
SELECT member_key, NULL, 'published_more_than_once'
FROM published GROUP BY member_key HAVING count(*) > 1
UNION ALL
SELECT p.member_key, p.target_country, 'outdated_snapshot'
FROM published AS p
JOIN stage_member AS s ON s.member_key = p.member_key AND s.country = p.target_country
WHERE p.feed_date IS NOT s.feed_date OR p.as_of_date IS NOT s.as_of_date
   OR p.age IS NOT s.age OR p.stale_member IS NOT s.stale_member;
