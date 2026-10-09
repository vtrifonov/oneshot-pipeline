"""stall-watch: synthetic subagent transcripts, no real sessions touched."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

BIN = Path(__file__).resolve().parents[1]


def write_jsonl(path, lines):
    with open(path, "w") as f:
        for ts, kind, block in lines:
            iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".000Z"
            f.write(json.dumps({"type": kind, "timestamp": iso, "message": {"content": [block]}}) + "\n")


def watch(session, *args):
    return subprocess.run([str(BIN / "stall-watch"), "--session", str(session), "--interval", "0", "--max", "1", *args],
                          capture_output=True, text=True)


class StallWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = Path(self.tmp.name) / "s"; (self.session / "subagents").mkdir(parents=True)
        self.jsonl = self.session / "subagents" / "agent-a1.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_unanswered_tool_call_past_threshold(self):
        old = time.time() - 900
        write_jsonl(self.jsonl, [(old, "assistant", {"type": "tool_use", "id": "t1", "name": "Bash"})])
        os.utime(self.jsonl, (old, old))
        r = watch(self.session, "--threshold", "420")
        self.assertEqual(r.returncode, 3)
        self.assertIn("STALL agent=a1 reason=unanswered-tool-call tool=Bash", r.stdout)

    def test_answered_tool_call_is_not_pending(self):
        old = time.time() - 900
        write_jsonl(self.jsonl, [(old, "assistant", {"type": "tool_use", "id": "t1", "name": "Bash"}),
                                 (old + 1, "user", {"type": "tool_result", "tool_use_id": "t1"})])
        os.utime(self.jsonl, (old, old))
        r = watch(self.session, "--threshold", "420")
        self.assertEqual(r.returncode, 3)
        self.assertIn("reason=idle", r.stdout)

    def test_fresh_agent_not_stalled(self):
        old = time.time() - 900
        write_jsonl(self.jsonl, [(old, "assistant", {"type": "tool_use", "id": "t1", "name": "Bash"})])
        os.utime(self.jsonl, (old, old))
        r = watch(self.session, "--threshold", "3000")
        self.assertEqual(r.returncode, 2)
        self.assertIn("TIMEOUT", r.stdout)

    def test_commit_event(self):
        repo = Path(self.tmp.name) / "wt"; repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / "a").write_text("1"); subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
        git_c = ["-c", "user.email=t@e.invalid", "-c", "user.name=T", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "-C", str(repo), *git_c, "commit", "-qm", "x"], check=True)
        write_jsonl(self.jsonl, [(time.time(), "assistant", {"type": "text", "text": "hi"})])
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        (repo / "a").write_text("2"); subprocess.run(["git", "-C", str(repo), *git_c, "commit", "-qam", "y"], check=True)
        r = watch(self.session, "--worktree", str(repo), "--base", base)
        self.assertEqual(r.returncode, 0)
        self.assertIn("COMMIT", r.stdout)

    def test_missing_session_dir_is_usage_error(self):
        r = watch(Path(self.tmp.name) / "nope")
        self.assertEqual(r.returncode, 64)
        self.assertIn("subagents", r.stderr)

    def test_agent_prefix_stripped(self):
        old = time.time() - 900
        write_jsonl(self.jsonl, [(old, "assistant", {"type": "tool_use", "id": "t1", "name": "Bash"})])
        os.utime(self.jsonl, (old, old))
        r = watch(self.session, "--agent", "agent-a1", "--threshold", "420")
        self.assertEqual(r.returncode, 3)
        self.assertIn("agent=a1", r.stdout)

    def test_no_transcript_yet(self):
        r = watch(self.session, "--agent", "zz", "--threshold", "3000")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("TIMEOUT", r.stdout)
        r = watch(self.session, "--agent", "zz", "--threshold", "0")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("reason=no-transcript", r.stdout)

    def test_named_agent_only(self):
        other = self.session / "subagents" / "agent-b2.jsonl"
        write_jsonl(other, [(time.time(), "assistant", {"type": "text", "text": "busy"})])
        old = time.time() - 900
        write_jsonl(self.jsonl, [(old, "assistant", {"type": "tool_use", "id": "t1", "name": "Edit"})])
        os.utime(self.jsonl, (old, old))
        r = watch(self.session, "--agent", "a1", "--threshold", "420")
        self.assertEqual(r.returncode, 3)
        self.assertIn("agent=a1", r.stdout)


if __name__ == "__main__":
    unittest.main()
