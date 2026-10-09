"""Per-repository preference store, against a temporary file only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "skills/oneshot-pipeline/scripts/repo-prefs.py"


class RepoPrefsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "prefs.json"
        self.env = {**os.environ, "ONESHOT_REPO_PREFS": str(self.path)}

    def tearDown(self):
        self.temporary.cleanup()

    def run_prefs(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args], env=self.env,
                              text=True, capture_output=True)

    def test_round_trip_is_scoped_per_repository(self):
        self.assertEqual(self.run_prefs("get", "acme/web", "frontend_design").stdout.strip(), "unset")
        self.assertEqual(self.run_prefs("set", "acme/web", "frontend_design", "never").returncode, 0)
        self.assertEqual(self.run_prefs("get", "acme/web", "frontend_design").stdout.strip(), "never")
        self.assertEqual(self.run_prefs("get", "acme/api", "frontend_design").stdout.strip(), "unset")
        self.run_prefs("set", "acme/web", "frontend_design", "always")
        self.assertEqual(self.run_prefs("get", "acme/web", "frontend_design").stdout.strip(), "always")

    def test_clear_removes_empty_repository_entry(self):
        self.run_prefs("set", "acme/web", "frontend_design", "never")
        self.assertEqual(self.run_prefs("clear", "acme/web", "frontend_design").returncode, 0)
        self.assertEqual(json.loads(self.path.read_text()), {})

    def test_rejects_unknown_values_and_keys(self):
        self.assertNotEqual(self.run_prefs("set", "acme/web", "frontend_design", "maybe").returncode, 0)
        self.assertNotEqual(self.run_prefs("get", "acme/web", "colour").returncode, 0)
        self.assertNotEqual(self.run_prefs("get", "acme/web", "frontend_design", "never").returncode, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
