"""papercut CLI against a temp log file."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN = Path(__file__).resolve().parents[1]


def pc(log, *args):
    env = dict(os.environ, PAPERCUTS_FILE=str(log))
    return subprocess.run([str(BIN / "papercut"), *args], env=env, capture_output=True, text=True)


class PapercutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.log = Path(self.tmp.name) / "p.md"
        self.log.write_text("# Papercuts\n\n---\n\n2026-09-21 · sd silently matched nothing · use Edit · portal\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_appends_and_counts(self):
        r = pc(self.log, "add", "--class", "sd", "--min", "10", "--project", "demo", "sym", "fix")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("class sd: 0 prior entries", r.stdout)
        self.assertTrue(self.log.read_text().rstrip().endswith("· sd · 10m · open · sym · fix · demo"))
        pc(self.log, "add", "--class", "sd", "--min", "5", "--project", "demo", "s2", "f2")
        r = pc(self.log, "add", "--class", "sd", "--min", "5", "--project", "demo", "s3", "f3")
        self.assertIn("class sd: 2 prior entries", r.stdout)
        self.assertIn("THIRD STRIKE", r.stdout)

    def test_rejects_unknown_class_and_separator(self):
        self.assertEqual(pc(self.log, "add", "--class", "nope", "--min", "1", "--project", "p", "s", "f").returncode, 64)
        self.assertEqual(pc(self.log, "add", "--class", "sd", "--min", "1", "--project", "p", "a · b", "f").returncode, 64)

    def test_report_groups_by_class(self):
        pc(self.log, "add", "--class", "ctx-wire", "--min", "30", "--project", "p", "s", "f")
        pc(self.log, "add", "--class", "sd", "--min", "5", "--project", "p", "s", "f")
        r = pc(self.log, "report")
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.splitlines() if l and not l.startswith("class")]
        self.assertTrue(lines[0].startswith("ctx-wire"), r.stdout)
        self.assertIn("legacy", r.stdout)

    def test_classes(self):
        self.assertIn("prompt-stall", pc(self.log, "classes").stdout)


if __name__ == "__main__":
    unittest.main()
