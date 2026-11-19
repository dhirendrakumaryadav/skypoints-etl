-- Run inside the database and schema assigned to SkyPoints.
-- Standard-table primary keys document the grain. The load must check uniqueness.

CREATE TABLE IF NOT EXISTS landing_file (
    file_id VARCHAR NOT NULL PRIMARY KEY,
    source VARCHAR NOT NULL,
    feed_date DATE NOT NULL,
    object_uri VARCHAR NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    UNIQUE (source, feed_date, content_sha256)
);

CREATE TABLE IF NOT EXISTS landing_profile (
    file_id VARCHAR NOT NULL,
    record_number NUMBER NOT NULL,
    payload VARIANT NOT NULL,
    PRIMARY KEY (file_id, record_number)
);

CREATE TABLE IF NOT EXISTS landing_redemption (
    file_id VARCHAR NOT NULL,
    record_number NUMBER NOT NULL,
    payload VARIANT NOT NULL,
    PRIMARY KEY (file_id, record_number)
);

CREATE TABLE IF NOT EXISTS rejected_record (
    file_id VARCHAR NOT NULL,
    record_number NUMBER NOT NULL,
    item_number NUMBER NOT NULL,
    reason VARCHAR NOT NULL,
    PRIMARY KEY (file_id, record_number, item_number)
);

CREATE TABLE IF NOT EXISTS stage_profile_version (
    member_key VARCHAR(25) NOT NULL,
    feed_date DATE NOT NULL,
    payload VARIANT NOT NULL,
    file_id VARCHAR NOT NULL,
    record_number NUMBER NOT NULL,
    PRIMARY KEY (member_key, feed_date)
);

CREATE TABLE IF NOT EXISTS stage_member (
    member_key VARCHAR(25) NOT NULL PRIMARY KEY,
    member_id VARCHAR(18) NOT NULL,
    member_name VARCHAR(255) NOT NULL,
    country VARCHAR(3) NOT NULL,
    enrollment_date DATE NOT NULL,
    last_flight_date DATE,
    dob DATE,
    tier_code VARCHAR(5),
    agent_name VARCHAR(255),
    state VARCHAR(5),
    post_code VARCHAR(5),
    active_flag VARCHAR(1),
    member_type VARCHAR(1),
    feed_date DATE NOT NULL,
    age NUMBER(4),
    stale_member BOOLEAN,
    as_of_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS table_usa LIKE stage_member;
CREATE TABLE IF NOT EXISTS table_india LIKE stage_member;
CREATE TABLE IF NOT EXISTS table_australia LIKE stage_member;
CREATE TABLE IF NOT EXISTS table_canada LIKE stage_member;
CREATE TABLE IF NOT EXISTS table_philippines LIKE stage_member;

CREATE TABLE IF NOT EXISTS stage_redemption_version (
    partner VARCHAR(255) NOT NULL,
    txn_id VARCHAR(255) NOT NULL,
    feed_date DATE NOT NULL,
    payload VARIANT NOT NULL,
    file_id VARCHAR NOT NULL,
    record_number NUMBER NOT NULL,
    item_number NUMBER NOT NULL,
    PRIMARY KEY (partner, txn_id, feed_date)
);

CREATE TABLE IF NOT EXISTS redemption (
    partner VARCHAR(255) NOT NULL,
    txn_id VARCHAR(255) NOT NULL,
    member_key VARCHAR(25) NOT NULL,
    txn_date DATE NOT NULL,
    miles_redeemed NUMBER(19, 0) NOT NULL,
    status VARCHAR(40) NOT NULL,
    feed_date DATE NOT NULL,
    PRIMARY KEY (partner, txn_id)
);

CREATE VIEW IF NOT EXISTS redemption_with_member AS
SELECT r.*, m.member_name, m.country
FROM redemption AS r
LEFT JOIN stage_member AS m ON m.member_key = r.member_key;
