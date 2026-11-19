import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from skypoints.pipeline import run


HEADER = "|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.database = self.folder / "test.db"

    def write(self, name, text):
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def global_feed(self, name, *rows):
        return self.write(name, HEADER + "\n".join(rows) + "\n")

    def query(self, sql):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(sql).fetchall()

    def load(self, profiles=(), redemptions=(), feed_date="2024-01-15", as_of="2024-01-16"):
        return run(self.database, feed_date, as_of, profiles, redemptions)

    def test_country_csv_contracts_and_id_namespaces(self):
        usa = self.write("usa.csv", "ID,Name,TierCode,EnrollmentDate,FlightDate\n001,Alex,GLD,1052022,1152022\n")
        ind = self.write("ind.csv", "ID,Name,DOB,TierCode,EnrollmentDate,Individual or Corporate,Flight Date\n"
                                    "001,Casey,1/4/2000,GLD,1/5/2022,C,1/15/2022\n")
        aus = self.write("aus.csv", "Unique ID,Member Name,Tier Type,Date of Birth,Date of Enrollment,Date of Flight\n"
                                    "001,Jordan,GLD,,2021-12-13,2022-01-15\n"
                                    "002,Taylor,GLD,,2021-13-13,2022-01-15\n")
        summary = self.load(profiles=[("usa", usa), ("ind", ind), ("aus", aus)])
        self.assertEqual(summary["members"], 3)
        self.assertEqual(summary["rejections"], 1)
        self.assertEqual(self.query("SELECT member_key, enrollment_date, age FROM table_usa"),
                         [("usa:001", "2022-01-05", None)])
        self.assertEqual(self.query("SELECT member_key, member_type, age FROM table_india"), [("ind:001", "C", 24)])
        self.assertEqual(self.query("SELECT member_key, enrollment_date, age FROM table_australia"),
                         [("aus:001", "2021-12-13", None)])
        self.assertEqual(self.query("SELECT reason FROM rejected_record"), [("enrollment_date has an invalid date",)])

    def test_newer_profile_moves_country_and_older_delivery_cannot_move_it_back(self):
        new = self.global_feed("new.psv", "|D|Alex|42|20190101||GLD||VIC|AU|01161990|A")
        old = self.global_feed("old.psv", "|D|Alex|42|20190101|20231017|GLD||WA|USA|01161990|A")
        self.load(profiles=[("global", old)])
        self.assertEqual(self.query("SELECT age, stale_member FROM table_usa"), [(34, 1)])
        self.load(profiles=[("global", new)], feed_date="2024-01-16")
        self.assertEqual(self.query("SELECT member_key FROM table_usa"), [])
        self.assertEqual(self.query("SELECT member_key, age, stale_member FROM table_australia"), [("global:42", 34, None)])
        late = self.global_feed("late.psv", "|D|Alex|42|20190101||GLD||ON|CAN|01161990|A")
        self.load(profiles=[("global", late)], feed_date="2024-01-14")
        self.assertEqual(self.query("SELECT country FROM stage_member"), [("AUS",)])
        self.assertEqual(self.query("SELECT count(*) FROM profile_version"), [(3,)])

    def test_staleness_boundary_and_birthday_refresh_without_new_input(self):
        source = self.global_feed("first.psv", "|D|Alex|42|20190101|20231017|GLD||NCR|PHIL|01161990|A")
        self.load(profiles=[("global", source)], as_of="2024-01-15")
        self.assertEqual(self.query("SELECT age, stale_member FROM table_philippines"), [(33, 0)])
        self.load()
        self.assertEqual(self.query("SELECT age, stale_member FROM table_philippines"), [(34, 1)])

    def test_duplicate_file_and_identical_versions_are_noops_but_conflict_is_rejected(self):
        row = "|D|Alex|42|20190101||GLD||WA|USA||A"
        first = self.global_feed("first.psv", row, row)
        self.assertEqual(self.load(profiles=[("global", first)]), self.load(profiles=[("global", first)]))
        conflict = self.global_feed("conflict.psv", "|D|Alex|42|20190101||GLD||WA|CAN||A")
        self.assertEqual(self.load(profiles=[("global", conflict)])["rejections"], 1)
        self.assertEqual(self.query("SELECT country FROM stage_member"), [("USA",)])
        self.assertEqual(self.query("SELECT count(*) FROM profile_version"), [(1,)])

    def test_missing_mandatory_fields_and_unknown_country_are_rejected(self):
        source = self.global_feed("invalid.psv",
                                  "|D||41|20190101||GLD||WA|USA||A",
                                  "|D|Alex||20190101||GLD||WA|USA||A",
                                  "|D|Casey|43|||GLD||WA|USA||A",
                                  "|D|Taylor|44|20190101||GLD||WA|XXX||A",
                                  "|D|Jordan|45|20190101||GLD||WA|USA||A")
        summary = self.load(profiles=[("global", source)])
        self.assertEqual(summary["rejections"], 4)
        self.assertEqual(summary["members"], 1)

    def test_each_redemption_is_validated_and_unmatched_members_are_retained(self):
        source = self.global_feed("members.psv", "|D|Alex|42|20190101||GLD||WA|USA||A")
        item = {"txn_id": "R1", "txn_date": "20240110", "partner": "Demo", "miles_redeemed": 100, "status": "PENDING"}
        envelope = {"member_id": "42", "feed_date": "20240115", "redemptions": [item, {**item, "miles_redeemed": True}]}
        orphan = {**envelope, "member_id": "99", "redemptions": [{**item, "txn_id": "R2"}]}
        feed = self.write("redemptions.jsonl", "\n".join((json.dumps(envelope), "{", json.dumps(orphan))))
        summary = self.load(profiles=[("global", source)], redemptions=[feed])
        self.assertEqual(summary["rejections"], 2)
        self.assertEqual(self.query("SELECT txn_id, country FROM redemption_with_member ORDER BY txn_id"),
                         [("R1", "USA"), ("R2", None)])
        updated = {**envelope, "feed_date": "20240116", "redemptions": [{**item, "status": "COMPLETED"}]}
        next_feed = self.write("next.json", json.dumps(updated, indent=2))
        self.load(redemptions=[next_feed], feed_date="2024-01-16")
        self.assertEqual(self.query("SELECT status FROM redemption WHERE txn_id = 'R1'"), [("COMPLETED",)])

    def test_malformed_file_rolls_back_other_writes_in_same_run(self):
        existing = self.global_feed("existing.psv", "|D|Alex|42|20190101||GLD||WA|USA||A")
        original = self.load(profiles=[("global", existing)])
        pending = self.global_feed("pending.psv", "|D|Casey|43|20190101||GLD||WA|USA||A")
        broken = self.write("broken.csv", 'ID,Name,TierCode,EnrollmentDate,FlightDate\n1,"open\n')
        with self.assertRaises(csv.Error):
            self.load(profiles=[("global", pending), ("usa", broken)])
        self.assertEqual(self.load(), original)
        self.assertEqual(self.load(profiles=[("global", pending)])["members"], 2)


if __name__ == "__main__":
    unittest.main()
