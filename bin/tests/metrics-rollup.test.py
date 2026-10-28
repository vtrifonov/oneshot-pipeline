"""run-metrics.py rollup / show against synthetic runs in a temporary skill home."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "skills/oneshot-pipeline/scripts/run-metrics.py"

METRICS_CSV = (
    "date,pr,jira,lane,mode,impl_mode,h_approved_to_pr,h_pr_to_ready,spec_bmm,plan_bmm,review_bmm,waves,"
    "bot_threads,threads_fixed,threads_closed_no_change,commits,loc,parked,defects_90d\n"
    "2026-10-01,41,AB-1001,full,standard,sdd,2.5,1.0,0/2/3,0/1/1,1/0/4,1,2,2,0,9,300,2,\n"
    "2026-10-02,55,AB-1002,lite,quick,inline-tdd,1.0,0.5,3,-,0/0/2,0,0,0,0,3,40,0,\n"
    "2026-10-03,-,AB-1003,full,standard,sdd,4.0,NA,0/1/1,0/0/0,0/0/0,0,0,0,0,5,120,0,\n"
    "2026-09-01,7,-,full,quick,inline-tdd,1.5,0.2,1,skipped(quick),0/1/1,0,0,0,0,4,80,1,\n"
)
STEP_FIELDS = ("run_id,date,mode,lane,phase,kind,step,agent_type,model,depth,started_at,ended_at,wall_s,"
               "active_s,human_wait_s,idle_s,messages,input,cache_write,cache_read,output,total_tokens,"
               "effort,thinking_tokens,thinking_s,latency_s")


def step_row(run_id, phase, kind, step, wall="", active="", wait="", output=1000, model="sonnet-5-5",
             date="2026-10-03", lane="full", mode="standard", effort="medium", thinking=None, latency=30):
    return {
        "run_id": run_id, "date": date, "mode": mode, "lane": lane, "phase": phase, "kind": kind,
        "step": step, "agent_type": "", "model": model, "depth": "", "started_at": f"{date}T10:00:00Z",
        "ended_at": "", "wall_s": wall, "active_s": active, "human_wait_s": wait, "idle_s": 0,
        "messages": 3, "input": 10, "cache_write": output * 3, "cache_read": output * 50,
        "output": output, "total_tokens": output * 54 + 10,
        "effort": effort, "thinking_tokens": output // 4 if thinking is None else thinking,
        "thinking_s": 5, "latency_s": latency,
    }


def review(run_id, lens, accepted, phase="3", tokens=1_000_000, started="2026-10-01T10:00:00Z"):
    return {
        "schema_version": 1, "policy_version": "2026-09-risk-panels", "run_id": run_id, "phase": phase,
        "reviewer_id": f"p{phase} {lens}", "lens": lens, "pass_kind": "initial", "started_at": started,
        "finished_at": started, "elapsed_seconds": 300, "tokens": tokens, "output_tokens": 20000,
        "reported_bmm": "0/2/2", "unique_accepted_bmm": accepted, "duplicate_count": 0,
        "rejected_count": 0, "unresolved_count": 0, "finding_ids": [],
    }


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


class RollupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.home = root / "skill"
        self.runs = self.home / "runs"
        self.runs.mkdir(parents=True)
        (self.home / "metrics.csv").write_text(METRICS_CSV)
        self.papercuts = root / "papercuts.md"
        self.papercuts.write_text(
            "# Papercuts\n\n2026-10-01 · cwd · 2m · open · ran from main checkout · cd first · widgets\n"
            "2026-10-01 · install · 25m · open · emulator died · pin version · widgets\n"
            "2026-10-01 · cwd · 1m · open · unrelated project · - · other-repo\n")
        self.sources = root / "sources.json"
        self.env = {**os.environ, "ONESHOT_ROLLUP_SOURCES": str(self.sources)}

        # Local run with every artifact: joins metrics.csv row AB-1001 by PR 41.
        local = self.runs / "2026-10-01-ab-1001-widgets"
        local.mkdir()
        (local / "run-summary.json").write_text(json.dumps({
            "schema_version": 1, "run_id": "ab-1001-widgets", "repository": "acme/widgets", "pr": 41,
            "lane": "full", "mode": "standard", "impl_mode": "sdd", "status": "ready",
            "approved_at": "2026-10-01T09:00:00Z",
            "metrics_quality_notes": ["one stopped duplicate spec author billed to phase 2",
                                      "per-task split backfilled from commit times"],
        }))
        write_jsonl(local / "review-runs.jsonl", [
            review("ab-1001-widgets", "requirements/architecture", "0/2/1"),
            review("ab-1001-widgets", "security", "0/0/0"),
        ])
        write_jsonl(local / "review-ledger.jsonl", [
            {"id": "A1", "severity": "MAJOR", "disposition": "accepted", "status": "open"},
            {"id": "A1", "severity": "MAJOR", "disposition": "accepted", "status": "closed"},
            {"id": "A2", "severity": "MAJOR", "disposition": "rejected"},
            {"id": "A3", "severity": "MINOR", "disposition": "accepted"},
            {"id": "S1", "severity": "BLOCKER", "disposition": "duplicate", "duplicate_of": "A1"},
        ])
        rows = [
            step_row("ab-1001-widgets", "3", "phase", "phase 3", wall=600, wait=0, output=50000, date="2026-10-01"),
            step_row("ab-1001-widgets", "6", "phase", "phase 6", wall=1200, wait=0, output=80000, date="2026-10-01"),
            step_row("ab-1001-widgets", "6", "agent", "p6 T1-2 implementer", active=900, output=70000, date="2026-10-01"),
            step_row("ab-1001-widgets", "7", "agent", "p7 correctness/testing review", active=400, output=20000,
                     model="opus-5-5", effort="high", thinking=10000, latency=60, date="2026-10-01"),
            step_row("ab-1001-widgets", "6", "task", "T1 (p6 T1-2 implementer)", active=200, output=30000, date="2026-10-01"),
            step_row("ab-1001-widgets", "6", "task", "T2 (p6 T1-2 implementer)", active=700, output=40000, date="2026-10-01"),
            step_row("ab-1001-widgets", "all", "total", "run", wall=3600, wait=1200, output=130000, date="2026-10-01"),
        ]
        (local / "step-metrics.json").write_text(json.dumps({"schema_version": 1, "run_id": "ab-1001-widgets",
                                                              "notes": ["stall-watch fired once"], "rows": rows}))

        # External run in a target repo, artifacts under reviews/: joins AB-1003 by Jira key in the folder name.
        self.external = root / "checkout" / "gadgets" / "docs" / "superpowers" / "reviews" / "ab-1003-gadgets"
        (self.external / "reviews").mkdir(parents=True)
        write_jsonl(self.external / "reviews" / "review-runs.jsonl", [
            review("ab-1003-gadgets", "security", "0/0/0", started="2026-10-03T10:00:00Z"),
            review("ab-1003-gadgets", "requirements/architecture", "1/0/0", started="2026-10-03T10:00:00Z"),
        ])
        write_jsonl(self.external / "reviews" / "review-ledger.jsonl", [
            {"id": "B1", "severity": "BLOCKER", "disposition": "accepted"}])
        self.sources.write_text(json.dumps({"run_dirs": [str(root / "checkout" / "*" / "docs" / "superpowers"
                                                             / "reviews" / "*")]}))

        # A run known only from step-metrics.csv (two phases, one far over the lane median).
        csv_rows = [
            step_row("ab-1002-step-only", "3", "phase", "phase 3", wall=4000, wait=0, output=400000, lane="full",
                     date="2026-10-02"),
            step_row("ab-1002-step-only", "6", "phase", "phase 6", wall=1100, wait=0, output=75000, lane="full",
                     date="2026-10-02"),
            step_row("ab-1002-step-only", "all", "total", "run", wall=5000, wait=100, output=475000, lane="full",
                     date="2026-10-02"),
            step_row("ab-1004-step-only", "3", "phase", "phase 3", wall=500, wait=0, output=40000, lane="full",
                     date="2026-10-04"),
            step_row("ab-1004-step-only", "all", "total", "run", wall=900, wait=0, output=40000, lane="full",
                     date="2026-10-04"),
        ]
        lines = [STEP_FIELDS] + [",".join(str(r[k]) for k in STEP_FIELDS.split(",")) for r in csv_rows]
        (self.home / "step-metrics.csv").write_text("\n".join(lines) + "\n")

    def tearDown(self):
        self.temporary.cleanup()

    def run_metrics(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args, "--home", str(self.home)],
                              env=self.env, text=True, capture_output=True)

    def rollup(self):
        result = self.run_metrics("rollup", "--papercuts", str(self.papercuts))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def table(self, name):
        return json.loads((self.runs / "_rollup" / f"{name}.json").read_text())

    def test_tables_join_every_source(self):
        out = self.rollup()
        self.assertIn("copied 2 external files", out)
        runs = {r["run_id"]: r for r in self.table("runs")}
        self.assertEqual(set(runs), {"ab-1001-widgets", "ab-1003-gadgets", "ab-1002-step-only",
                                     "ab-1004-step-only", "csv-2026-09-01-7"})
        self.assertIsNone(runs["ab-1004-step-only"]["csv"])
        local = runs["ab-1001-widgets"]
        self.assertEqual(local["csv"]["pr"], "41")
        self.assertEqual(local["csv"]["review_bmm_parsed"], [1, 0, 4])
        self.assertEqual(local["ledger_accepted"], {"BLOCKER": 0, "MAJOR": 1, "MINOR": 1})
        self.assertEqual(local["step_totals"]["wall_s"], 3600)
        self.assertEqual(local["step_totals"]["agents"], 2)
        self.assertEqual(local["step_totals"]["effort"], "medium")
        self.assertEqual(local["failures"]["stopped_agents"], 1)
        self.assertEqual(local["failures"]["duplicate_writers"], 1)
        self.assertEqual(local["failures"]["backfilled_metrics"], 1)
        self.assertEqual(local["failures"]["stalls"], 1)
        self.assertEqual(local["papercuts"], {"cwd": 1, "install": 1})
        external = runs["ab-1003-gadgets"]
        self.assertEqual(external["csv"]["jira"], "AB-1003")
        self.assertEqual(external["repository"], "gadgets")
        self.assertEqual(external["date"], "2026-10-03")
        self.assertEqual(external["source"], str(self.external.resolve()))
        self.assertTrue((self.runs / "ab-1003-gadgets" / "review-runs.jsonl").exists())
        step_only = runs["ab-1002-step-only"]
        self.assertEqual(step_only["steps_source"], "step-metrics.csv")
        self.assertEqual(step_only["csv"]["jira"], "AB-1002")
        self.assertEqual(step_only["step_totals"]["output"], 475000)
        self.assertIsNone(runs["csv-2026-09-01-7"]["csv"]["defects_90d"])
        steps = self.table("steps")
        self.assertEqual({s["run_id"] for s in steps}, {"ab-1001-widgets", "ab-1002-step-only", "ab-1004-step-only"})
        self.assertTrue(all(isinstance(s["output"], int) for s in steps))
        reviews = self.table("reviews")
        self.assertEqual(len(reviews), 4)
        by_lens = {(r["run_id"], r["lens"]): r for r in reviews}
        self.assertEqual(by_lens[("ab-1001-widgets", "requirements/architecture")]["accepted_bm"], 2)
        self.assertEqual(by_lens[("ab-1003-gadgets", "security")]["accepted_bm"], 0)
        self.assertEqual(by_lens[("ab-1003-gadgets", "security")]["lane"], "full")

    def test_rerun_changes_nothing_and_copies_only_newer(self):
        self.rollup()
        before = {p.name: (p.stat().st_mtime_ns, p.read_text()) for p in (self.runs / "_rollup").iterdir()}
        copy = self.runs / "ab-1003-gadgets" / "review-runs.jsonl"
        copy_mtime = copy.stat().st_mtime_ns
        time.sleep(0.02)
        out = self.rollup()
        self.assertIn("copied 0 external files", out)
        self.assertIn("unchanged", out)
        after = {p.name: (p.stat().st_mtime_ns, p.read_text()) for p in (self.runs / "_rollup").iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(copy.stat().st_mtime_ns, copy_mtime)
        # A newer source replaces the copy; an older one is left alone.
        src = self.external / "reviews" / "review-runs.jsonl"
        write_jsonl(src, [review("ab-1003-gadgets", "security", "0/1/0", started="2026-10-03T10:00:00Z")])
        future = time.time() + 5
        os.utime(src, (future, future))
        out = self.rollup()
        self.assertIn("copied 1 external files", out)
        self.assertEqual(len([r for r in self.table("reviews") if r["run_id"] == "ab-1003-gadgets"]), 1)

    def test_show_views(self):
        self.rollup()
        default = self.run_metrics("show")
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertIn("ab-1001-widgets", default.stdout)
        self.assertIn("5 of 5 runs", default.stdout)
        self.assertIn("1h00", default.stdout)
        one = self.run_metrics("show", "--run", "2026-10-01-ab-1001-widgets")
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertIn("acme/widgets", one.stdout)
        self.assertIn("T2 (p6 T1-2 implementer)", one.stdout)
        self.assertIn("requirements/architecture", one.stdout)
        self.assertIn("note: one stopped duplicate", one.stdout)
        lenses = self.run_metrics("show", "--lenses")
        self.assertEqual(lenses.returncode, 0, lenses.stderr)
        self.assertRegex(lenses.stdout, r"requirements/architecture\s+2\s+2\s+2\s+2\.0M")
        self.assertRegex(lenses.stdout, r"security\s+2\s+2\s+2\s+2\.0M\s+40k\s+0\s+0\.00\s+2")
        failures = self.run_metrics("show", "--failures")
        self.assertIn("cwdx1, installx1", failures.stdout)
        effort = self.run_metrics("show", "--effort")
        self.assertEqual(effort.returncode, 0, effort.stderr)
        # reviewer on opus at high: 20k out, 10k thinking (50%), 60s over 3 messages
        self.assertRegex(effort.stdout, r"reviewer\s+opus-5-5\s+high\s+1\s+1\s+20k\s+6667\s+50%\s+20\.0s\s+6m40")
        self.assertRegex(effort.stdout, r"implementer\s+sonnet-5-5\s+medium\s+1\s+1\s+70k")
        self.assertRegex(effort.stdout, r"task\s+sonnet-5-5\s+medium\s+2")
        self.assertIn("p7 correctness/testing review", one.stdout)
        self.assertRegex(one.stdout, r"opus-5-5\s+high")
        missing = subprocess.run(["python3", str(SCRIPT), "show", "--home", str(Path(self.temporary.name) / "nope")],
                                 env=self.env, text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("run `rollup` first", missing.stderr)

    def test_retro_candidates_follow_the_four_rules(self):
        self.rollup()
        retro = self.run_metrics("show", "--retro")
        self.assertEqual(retro.returncode, 0, retro.stderr)
        self.assertIn("phase over 2x lane median (wall_s)", retro.stdout)
        self.assertIn("phase over 2x lane median (output)", retro.stdout)
        self.assertRegex(retro.stdout, r"ab-1002-step-only\s+phase 3 wall_s 1h06 vs median 10m00")
        self.assertIn("task over 10 min active", retro.stdout)
        self.assertIn("T2 (p6 T1-2 implementer)", retro.stdout)
        self.assertIn("human wait over 25% of wall", retro.stdout)
        self.assertNotIn("lens dry", retro.stdout)  # only 2 measured passes per lens
        as_json = json.loads(self.run_metrics("show", "--json").stdout)
        rules = {c["rule"] for c in as_json["retro"]}
        self.assertIn("human wait over 25% of wall", rules)
        self.assertEqual(as_json["runs"], 5)

    def test_retro_explains_an_empty_list(self):
        for path in list(self.runs.rglob("step-metrics.json")) + [self.home / "step-metrics.csv"]:
            path.unlink()
        self.rollup()
        retro = self.run_metrics("show", "--retro")
        self.assertIn("no retro candidates", retro.stdout)
        self.assertIn("0 runs with step metrics", retro.stdout)
        self.assertIn("4 review passes with accepted counts", retro.stdout)

    def test_dry_lens_after_five_measured_passes(self):
        passes = [review("ab-1001-widgets", "devops", "0/0/0", started=f"2026-10-0{i}T10:00:00Z")
                  for i in range(1, 7)]
        write_jsonl(self.runs / "2026-10-01-ab-1001-widgets" / "review-runs.jsonl", passes)
        self.rollup()
        retro = self.run_metrics("show", "--retro")
        self.assertIn("lens dry for 5+ passes", retro.stdout)
        self.assertIn("devops: 6 measured passes", retro.stdout)

    def test_bad_sources_file_is_an_error(self):
        self.sources.write_text(json.dumps(["not", "an", "object"]))
        result = self.run_metrics("rollup", "--papercuts", str(self.papercuts))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run_dirs", result.stderr)


if __name__ == "__main__":
    unittest.main()
