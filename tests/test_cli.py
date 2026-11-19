import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "skypoints", "--db", str(self.folder / "demo.db"), *arguments],
            cwd=PROJECT, capture_output=True, text=True, timeout=20,
        )

    def test_demo_command_replays_with_the_same_summary(self):
        arguments = ("--feed-date", "2024-01-15", "--profile", "global", "demo/members-2024-01-15.psv",
                     "--redemptions", "demo/redemptions-2024-01-15.jsonl")
        first = self.invoke(*arguments)
        replay = self.invoke(*arguments)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        summary = json.loads(first.stdout)
        self.assertEqual(summary, json.loads(replay.stdout))
        self.assertEqual((summary["files"], summary["members"], summary["redemptions"], summary["rejections"]),
                         (2, 4, 3, 1))

    def test_file_error_exits_nonzero_and_leaves_no_partial_delivery(self):
        bad_feed = self.folder / "unexpected.csv"
        bad_feed.write_text("wrong,header\n", encoding="utf-8")
        arguments = ("--feed-date", "2024-01-15", "--profile", "global", "demo/members-2024-01-15.psv")
        failed = self.invoke(*arguments, "--profile", "usa", str(bad_feed))
        self.assertEqual(failed.returncode, 1)
        self.assertIn("usa input unexpected.csv: unexpected usa profile header", failed.stderr)
        self.assertEqual(failed.stdout, "")
        empty = self.invoke("--feed-date", "2024-01-15")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout)["files"], 0)
        retry = self.invoke(*arguments)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads(retry.stdout)["members"], 4)
