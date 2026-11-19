"""Decode each source using its own column and date contract."""

import csv
import json
import re
from datetime import datetime


class InvalidRecord(ValueError):
    """A data error that can be quarantined while the load continues."""


GLOBAL_COLUMNS = (
    "Member_Name", "Member_Id", "Enrollment_Date", "Last_Flight_Date", "Tier_Code",
    "Agent_Name", "State", "Country", "DOB", "Is_Active",
)
GLOBAL_FIELDS = (
    "member_name", "member_id", "enrollment_date", "last_flight_date", "tier_code",
    "agent_name", "state", "country", "dob", "active_flag",
)
GLOBAL_LAYOUTS = {
    GLOBAL_COLUMNS: GLOBAL_FIELDS,
    (*GLOBAL_COLUMNS[:8], "Post_Code", *GLOBAL_COLUMNS[8:]):
        (*GLOBAL_FIELDS[:8], "post_code", *GLOBAL_FIELDS[8:]),
}
CSV_LAYOUTS = {
    "usa": (
        ("ID", "Name", "TierCode", "EnrollmentDate", "FlightDate"),
        ("member_id", "member_name", "tier_code", "enrollment_date", "last_flight_date"),
    ),
    "ind": (
        ("ID", "Name", "DOB", "TierCode", "EnrollmentDate", "Individual or Corporate", "Flight Date"),
        ("member_id", "member_name", "dob", "tier_code", "enrollment_date", "member_type", "last_flight_date"),
    ),
    "aus": (
        ("Unique ID", "Member Name", "Tier Type", "Date of Birth", "Date of Enrollment", "Date of Flight"),
        ("member_id", "member_name", "tier_code", "dob", "enrollment_date", "last_flight_date"),
    ),
}
PROFILE_SOURCES = ("global", *CSV_LAYOUTS)
COUNTRIES = {
    "USA": "table_usa", "IND": "table_india", "AUS": "table_australia",
    "CAN": "table_canada", "PHL": "table_philippines",
}
COUNTRY_ALIASES = {"AU": "AUS", "PHIL": "PHL"}


def profile_rows(stream, source):
    if source == "global":
        lines = enumerate(stream, 1)
        _, header = next(lines, (0, ""))
        parts = header.rstrip("\r\n").split("|")
        fields = GLOBAL_LAYOUTS.get(tuple(parts[2:]))
        if parts[:2] != ["", "H"] or fields is None:
            raise ValueError("unexpected global profile header")
        for line_number, line in lines:
            line = line.rstrip("\r\n")
            if line:
                yield line_number, line, fields
        return

    columns, fields = CSV_LAYOUTS[source]
    reader = csv.reader(stream, strict=True)
    if tuple(next(reader, [])) != columns:
        raise ValueError(f"unexpected {source} profile header")
    for row in reader:
        if row:
            yield reader.line_num, row, fields


def clean_text(value, field, limit, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise InvalidRecord(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise InvalidRecord(f"{field} must be text")
    value = value.strip()
    if len(value) > limit:
        raise InvalidRecord(f"{field} exceeds {limit} characters")
    return value


def parse_date(value, field, pattern, required=False):
    if value is None or value == "":
        if required:
            raise InvalidRecord(f"{field} is required")
        return None
    try:
        if not isinstance(value, str):
            raise ValueError
        if pattern == "usa":
            if not re.fullmatch(r"[0-9]{7,8}", value):
                raise ValueError
            value, pattern = value.zfill(8), "%m%d%Y"
        parsed = datetime.strptime(value, pattern).date()
        if pattern == "%m/%d/%Y":
            if not re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", value):
                raise ValueError
        elif format_date(parsed, pattern) != value:
            raise ValueError
        return parsed.isoformat()
    except ValueError:
        raise InvalidRecord(f"{field} has an invalid date") from None


def format_date(value, pattern):
    # Explicit padding also works for years below 1000 on every OS.
    if pattern == "%Y-%m-%d":
        return value.isoformat()
    if pattern == "%Y%m%d":
        return value.isoformat().replace("-", "")
    return f"{value.month:02}{value.day:02}{value.year:04}"


def member_key(source, member_id):
    return f"{source}:{member_id}"


def normalize_profile(raw, source, feed_date, fields):
    if source == "global":
        parts = raw.split("|")
        if parts[:2] != ["", "D"]:
            raise InvalidRecord("expected a global detail record")
        values = parts[2:]
    else:
        values = raw
    if len(values) != len(fields):
        raise InvalidRecord("wrong number of profile fields")
    data = dict(zip(fields, (value.strip() for value in values)))
    date_format = {"global": "%Y%m%d", "usa": "usa", "ind": "%m/%d/%Y", "aus": "%Y-%m-%d"}[source]
    profile = {
        "member_id": clean_text(data.get("member_id"), "member_id", 18, required=True),
        "member_name": clean_text(data.get("member_name"), "member_name", 255, required=True),
        "enrollment_date": parse_date(data.get("enrollment_date"), "enrollment_date", date_format, required=True),
        "last_flight_date": parse_date(data.get("last_flight_date"), "last_flight_date", date_format),
        "dob": parse_date(data.get("dob"), "dob", "%m%d%Y" if source == "global" else date_format),
        "post_code": clean_text(data.get("post_code"), "post_code", 5),
    }
    if profile["post_code"] and not re.fullmatch(r"[0-9]{5}", profile["post_code"]):
        raise InvalidRecord("post_code must contain five digits")
    country = (data.get("country") or (source if source != "global" else "")).upper()
    profile["country"] = COUNTRY_ALIASES.get(country, country)
    if profile["country"] not in COUNTRIES:
        raise InvalidRecord("country cannot be routed")
    for field, limit in (("tier_code", 5), ("agent_name", 255), ("state", 5), ("active_flag", 1), ("member_type", 1)):
        profile[field] = clean_text(data.get(field), field, limit)
    if profile["member_type"] not in (None, "I", "C"):
        raise InvalidRecord("member_type must be I or C")
    if any(profile[field] and profile[field] > feed_date for field in ("enrollment_date", "last_flight_date", "dob")):
        raise InvalidRecord("profile date is after feed_date")
    if profile["dob"] and profile["dob"] > profile["enrollment_date"]:
        raise InvalidRecord("dob is after enrollment_date")
    profile["member_key"] = member_key(source, profile["member_id"])
    return profile


def redemption_rows(stream, suffix):
    if suffix.lower() in (".jsonl", ".ndjson"):
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                yield line_number, line.rstrip("\r\n")
        return
    document = json.load(stream)
    envelopes = document if isinstance(document, list) else [document]
    for index, envelope in enumerate(envelopes, 1):
        yield index, json.dumps(envelope, ensure_ascii=False)


def redemption_envelope(raw, feed_date):
    try:
        envelope = json.loads(raw)
    except (ValueError, RecursionError):
        raise InvalidRecord("invalid JSON envelope") from None
    if not isinstance(envelope, dict) or not isinstance(envelope.get("redemptions"), list):
        raise InvalidRecord("expected a JSON object with a redemptions array")
    effective_date = parse_date(envelope.get("feed_date"), "feed_date", "%Y%m%d", required=True)
    if effective_date != feed_date:
        raise InvalidRecord("envelope feed_date differs from batch feed_date")
    member_id = clean_text(envelope.get("member_id"), "member_id", 18, required=True)
    return member_key("global", member_id), envelope["redemptions"]


def normalize_redemption(item, key, feed_date):
    if not isinstance(item, dict):
        raise InvalidRecord("redemption must be a JSON object")
    miles = item.get("miles_redeemed")
    if type(miles) is not int or not 0 < miles <= 2**63 - 1:
        raise InvalidRecord("miles_redeemed must be a positive 64-bit integer")
    txn_date = parse_date(item.get("txn_date"), "txn_date", "%Y%m%d", required=True)
    if txn_date > feed_date:
        raise InvalidRecord("txn_date is after feed_date")
    return {
        "partner": clean_text(item.get("partner"), "partner", 255, required=True),
        "txn_id": clean_text(item.get("txn_id"), "txn_id", 255, required=True),
        "member_key": key,
        "txn_date": txn_date,
        "miles_redeemed": miles,
        "status": clean_text(item.get("status"), "status", 40, required=True).upper(),
    }
