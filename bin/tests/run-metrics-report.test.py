"""run-metrics.py report against a synthetic controller transcript and one subagent transcript.

Checks the effort, thinking and latency columns: thinking tokens are deduplicated per API
message (every content block of one message repeats the same usage), thinking time adds up per
block, latency is the api-request entry to the last assistant entry of that request, and the
effort column names the level the entries ran at.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

SCRIPT = Path(__file__).resolve().parents[2] / "skills/oneshot-pipeline/scripts/run-metrics.py"
T0 = "2026-10-20T10:00:"


def assistant(ts, msg_id, model, output, thinking, effort, request, block, think_ms=0, sidechain=False):
    return {
        "type": "assistant", "timestamp": ts, "isSidechain": sidechain, "requestRef": request,
        "apiBlockIndex": block, "effort": effort, "perTurnEffort": effort,
        "thinkingDurationMs": think_ms,
        "message": {"id": msg_id, "model": model, "role": "assistant",
                    "content": [{"type": "text", "text": "x"}],
                    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000,
                              "output_tokens": output, "output_tokens_details": {"thinking_tokens": thinking}}},
    }


def user(ts, text):
    return {"type": "user", "timestamp": ts, "isSidechain": False, "message": {"role": "user", "content": text}}


def request(ts, rid):
    return {"type": "api-request", "id": rid, "timestamp": ts, "params": {"output_config": {"effort": "medium"}}}


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = root / "config"
        self.slug = f"rm-test-{uuid.uuid4().hex[:8]}"
        self.marks = Path("/tmp") / self.slug
        self.marks.mkdir()
        (self.marks / "marks.tsv").write_text(
            f"{T0}00Z\tphase\t0\n{T0}20Z\tphase\t6\n2026-10-20T10:01:50Z\tdone\n")
        session = self.config / "projects" / "-proj" / "session-1.jsonl"
        write_jsonl(session, [
            user(f"{T0}01Z", f"python3 run-metrics.py mark {self.slug} phase 0"),
            request(f"{T0}02Z", "req-1"),
            # One API message logged as two blocks with identical usage: 500 output / 200 thinking once.
            assistant(f"{T0}05Z", "msg-1", "claude-opus-5-5", 500, 200, "medium", "req-1", 0, think_ms=1500),
            assistant(f"{T0}08Z", "msg-1", "claude-opus-5-5", 500, 200, "medium", "req-1", 1, think_ms=500),
            user(f"{T0}09Z", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
            request(f"{T0}10Z", "req-2"),
            assistant(f"{T0}14Z", "msg-2", "claude-opus-5-5", 300, 0, "high", "req-2", 0),
            user(f"{T0}25Z", f"python3 run-metrics.py mark {self.slug} phase 6"),
            request(f"{T0}25Z", "req-orphan"),  # retried request with no assistant entry: ignored
            request(f"{T0}26Z", "req-3"),
            assistant(f"{T0}28Z", "msg-3", "claude-opus-5-5", 100, 10, "high", "req-3", 0, think_ms=100),
            # 40s gap ended by an agent notification: idle (agent work), not human wait.
            user("2026-10-20T10:01:08Z", "Another Claude session sent a message:\n<teammate-message>done</teammate-message>"),
            # 35s gap ended by a typed message: human wait.
            user("2026-10-20T10:01:43Z", "continue"),
        ])
        agent_dir = session.parent / "session-1" / "subagents"
        write_jsonl(agent_dir / "agent-a1.jsonl", [
            user(f"{T0}30Z", "(Task 1 of 1) You are the implementer"),
            request(f"{T0}31Z", "req-a1"),
            assistant(f"{T0}33Z", "msg-a1", "claude-sonnet-5-5", 400, 40, "medium", "req-a1", 0, think_ms=700,
                      sidechain=True),
            request(f"{T0}34Z", "req-a2"),
            assistant(f"{T0}40Z", "msg-a2", "claude-sonnet-5-5", 600, 60, "medium", "req-a2", 0, think_ms=1300,
                      sidechain=True),
        ])
        (agent_dir / "agent-a1.meta.json").write_text(json.dumps(
            {"description": "p6 T1 implementer", "name": "general-purpose", "spawnDepth": 1}))
        write_jsonl(agent_dir / "agent-r1.jsonl", [
            user(f"{T0}41Z", "You are the correctness/testing review"),
            request(f"{T0}42Z", "req-r1"),
            assistant(f"{T0}45Z", "msg-r1", "claude-opus-5-5", 800, 300, "high", "req-r1", 0, think_ms=2000,
                      sidechain=True),
        ])
        (agent_dir / "agent-r1.meta.json").write_text(json.dumps(
            {"description": "p7 correctness/testing review", "name": "general-purpose", "spawnDepth": 1}))
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config)}

    def tearDown(self):
        shutil.rmtree(self.marks, ignore_errors=True)
        self.temporary.cleanup()

    def report(self):
        result = subprocess.run(["python3", str(SCRIPT), "report", self.slug, "--no-csv", "--run-id", "rm-test"],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, json.loads((self.marks / "step-metrics.json").read_text())["rows"]

    def test_effort_thinking_and_latency_columns(self):
        out, all_rows = self.report()
        rows = {(r["kind"], r["step"]): r for r in all_rows if r["kind"] != "controller"}
        by_phase = {(r["kind"], r["phase"]): r for r in all_rows if r["kind"] == "controller"}
        p0 = by_phase[("controller", "0")]
        self.assertEqual(p0["messages"], 2)
        self.assertEqual(p0["output"], 800)             # 500 once (two blocks deduplicated) + 300
        self.assertEqual(p0["thinking_tokens"], 200)    # not 400: the second block repeats the usage
        self.assertEqual(p0["thinking_s"], 2)           # 1500 + 500 ms, per block
        self.assertEqual(p0["latency_s"], 10)           # req-1: 02 -> 08 (last block) = 6; req-2: 10 -> 14 = 4
        self.assertEqual(p0["effort"], "medium+high")   # one message each, first seen first
        p6 = by_phase[("controller", "6")]
        self.assertEqual(p6["effort"], "high")
        self.assertEqual(p6["latency_s"], 2)
        self.assertEqual(p6["human_wait_s"], 35)   # only the gap before the typed "continue"
        self.assertEqual(p6["idle_s"], 0)          # the 40s gap before the agent message is under IDLE_GAP_S
        agent = rows[("agent", "p6 T1 implementer")]
        self.assertEqual(agent["effort"], "medium")
        self.assertEqual(agent["thinking_tokens"], 100)
        self.assertEqual(agent["thinking_s"], 2)
        self.assertEqual(agent["latency_s"], 8)         # 31 -> 33 and 34 -> 40
        self.assertEqual(agent["model"], "sonnet-5-5")
        total = next(r for r in rows.values() if r["kind"] == "total")
        self.assertEqual(total["thinking_tokens"], 200 + 10 + 100 + 300)
        self.assertEqual(total["effort"], "medium+high")  # 3 messages each: ties keep first-seen order
        self.assertIn("think", out)
        self.assertIn("[sonnet-5-5 medium]", out)
        skeleton = [json.loads(line) for line in (self.marks / "review-runs.skeleton.jsonl").read_text().splitlines()]
        self.assertEqual(len(skeleton), 1)
        self.assertEqual(skeleton[0]["effort"], "high")
        self.assertEqual(skeleton[0]["thinking_tokens"], 300)

    def test_csv_carries_the_new_columns(self):
        csv_path = Path(self.temporary.name) / "step-metrics.csv"
        result = subprocess.run(["python3", str(SCRIPT), "report", self.slug, "--csv", str(csv_path),
                                 "--run-id", "rm-test"], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        header = csv_path.read_text().splitlines()[0].split(",")
        for column in ("effort", "thinking_tokens", "thinking_s", "latency_s"):
            self.assertIn(column, header)


if __name__ == "__main__":
    unittest.main()
