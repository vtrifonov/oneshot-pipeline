"""writer-guard: one writer per claimed file, against synthetic session transcripts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

BIN = Path(__file__).resolve().parents[1]
SPEC = "/w/docs/spec.md"


def row(role, content, stop=None):
    msg = {"role": role, "content": content}
    if stop:
        msg["stop_reason"] = stop
    return {"type": role, "timestamp": "2026-10-26T13:00:00.000Z", "message": msg}


def tool_result():
    return [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]


class WriterGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = os.path.join(self.tmp.name, "sess")
        os.makedirs(os.path.join(self.session, "subagents"))
        self.transcript = self.session + ".jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, agent_id, name, rows, age=0):
        path = os.path.join(self.session, "subagents", f"agent-{agent_id}.jsonl")
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        with open(path[: -len(".jsonl")] + ".meta.json", "w") as f:
            json.dump({"name": name, "description": f"p2 {name}"}, f)
        if age:
            t = time.time() - age
            os.utime(path, (t, t))

    def run_hook(self, tool, tool_input):
        payload = {"tool_name": tool, "transcript_path": self.transcript, "tool_input": tool_input}
        return subprocess.run(["python3", str(BIN / "writer-guard")], input=json.dumps(payload),
                              text=True, capture_output=True)

    def brief(self, extra=""):
        return f"You are the spec reviser.\nSole writer: {SPEC}\n{extra}"

    def running_owner(self, age=0):
        self.agent("a1", "spec-1", [row("user", self.brief()), row("assistant", [{"type": "tool_use"}], "tool_use"),
                                    row("user", tool_result())], age=age)

    def finished_owner(self, then=()):
        self.agent("a1", "spec-1", [row("user", self.brief()), row("assistant", [{"type": "text"}], "end_turn"), *then])

    def test_second_writer_denied_while_owner_runs(self):
        self.running_owner()
        r = self.run_hook("Agent", {"prompt": self.brief()})
        self.assertEqual(r.returncode, 2)
        self.assertIn("spec-1 is still running", r.stderr)

    def test_backtick_and_bullet_claims_match(self):
        self.running_owner()
        r = self.run_hook("Agent", {"prompt": f"- Sole writer: `{SPEC}`"})
        self.assertEqual(r.returncode, 2)

    def test_takeover_overrides(self):
        self.running_owner()
        self.assertEqual(self.run_hook("Agent", {"prompt": self.brief("writer-guard: takeover")}).returncode, 0)

    def test_dispatch_after_owner_finished_allowed(self):
        self.finished_owner()
        self.assertEqual(self.run_hook("Agent", {"prompt": self.brief()}).returncode, 0)

    def test_owner_resumed_by_message_counts_as_running(self):
        self.finished_owner(then=[row("user", "<teammate-message>add the burn-rate section</teammate-message>")])
        self.assertEqual(self.run_hook("Agent", {"prompt": self.brief()}).returncode, 2)

    def test_stale_owner_released(self):
        self.running_owner(age=3600)
        self.assertEqual(self.run_hook("Agent", {"prompt": self.brief()}).returncode, 0)

    def test_other_file_and_unclaimed_briefs_pass(self):
        self.running_owner()
        self.assertEqual(self.run_hook("Agent", {"prompt": "Sole writer: /w/docs/plan.md"}).returncode, 0)
        self.assertEqual(self.run_hook("Agent", {"prompt": f"Review {SPEC} and report."}).returncode, 0)

    def test_message_to_finished_owner_denied(self):
        self.finished_owner()
        r = self.run_hook("SendMessage", {"to": "spec-1", "message": "also add the burn-rate copy"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("Dispatch a fresh agent", r.stderr)

    def test_message_resume_override_and_running_owner_allowed(self):
        self.finished_owner()
        self.assertEqual(self.run_hook("SendMessage", {"to": "spec-1", "message": "writer-guard: resume"}).returncode, 0)
        self.running_owner()
        self.assertEqual(self.run_hook("SendMessage", {"to": "spec-1", "message": "also add X"}).returncode, 0)

    def test_message_to_non_owner_allowed(self):
        self.agent("r1", "reviewer", [row("user", "Review it."), row("assistant", [{"type": "text"}], "end_turn")])
        self.assertEqual(self.run_hook("SendMessage", {"to": "reviewer", "message": "thanks"}).returncode, 0)

    def test_no_session_dir_is_a_no_op(self):
        payload = {"tool_name": "Agent", "transcript_path": "/nonexistent/x.jsonl", "tool_input": {"prompt": self.brief()}}
        r = subprocess.run(["python3", str(BIN / "writer-guard")], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
