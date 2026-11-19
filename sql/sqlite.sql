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
