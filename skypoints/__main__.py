"""Command-line entry point. Run with python -m skypoints."""

import argparse
import csv
import json
import sqlite3
from datetime import date

from .feeds import PROFILE_SOURCES
from .pipeline import run


def iso_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format")


def main():
    parser = argparse.ArgumentParser(description="Load a SkyPoints batch and refresh its country tables.")
    parser.add_argument("--db", default="skypoints.db", help="SQLite output path")
    parser.add_argument("--feed-date", required=True, type=iso_date, help="source delivery date")
    parser.add_argument("--as-of", type=iso_date, help="reporting date, defaults to feed date")
    parser.add_argument("--profile", action="append", nargs=2, default=[], metavar=("SOURCE", "PATH"),
                        help=f"profile input, repeatable. Sources: {', '.join(PROFILE_SOURCES)}")
    parser.add_argument("--redemptions", action="append", default=[], metavar="PATH",
                        help="JSON or newline-delimited JSON input, repeatable")
    args = parser.parse_args()
    for source, _ in args.profile:
        if source not in PROFILE_SOURCES:
            parser.error(f"unknown profile source: {source}")
    as_of = args.as_of or args.feed_date
    if as_of < args.feed_date:
        parser.error("--as-of must be at least --feed-date")
    try:
        summary = run(args.db, args.feed_date, as_of, args.profile, args.redemptions)
    except (OSError, ValueError, csv.Error, sqlite3.Error) as error:
        parser.exit(1, f"Load failed: {error}\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
