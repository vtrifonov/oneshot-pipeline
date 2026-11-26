"""effort-guard: pipeline dispatches carry the model-matrix model and effort."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN = Path(__file__).resolve().parents[1]


def run_hook(description, model=None, effort=None, prompt="brief", tool="Agent", extra=None, env=None):
    tool_input = {"description": description, "prompt": prompt}
    if model:
        tool_input["model"] = model
    if effort:
        tool_input["effort"] = effort
    payload = {"tool_name": tool, "tool_input": tool_input, **(extra or {})}
    return subprocess.run(["python3", str(BIN / "effort-guard")], input=json.dumps(payload),
                          text=True, capture_output=True, env=env)


def transcript(path, *entries):
    lines = [{"type": "user", "message": {"role": "user", "content": "go"}}]
    for model, effort, sidechain in entries:
        lines.append({"type": "assistant", "isSidechain": sidechain, "effort": effort,
                      "message": {"model": model, "role": "assistant", "content": []}})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return str(path)


class ControllerCheckTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = {**os.environ, "ONESHOT_CONTROLLER_OK_DIR": str(self.root / "ok")}

    def tearDown(self):
        self.temporary.cleanup()

    def dispatch(self, *entries, description="p3 spec-security review"):
        path = transcript(self.root / "session.jsonl", *entries)
        return run_hook(description, model="opus", effort="medium", env=self.env,
                        extra={"transcript_path": path, "session_id": "s-1"})

    def test_opus_controller_at_medium_or_high_passes(self):
        for effort in ("medium", "high"):
            result = self.dispatch(("claude-opus-5-5", effort, False))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_fable_controller_is_denied_with_the_fix(self):
        result = self.dispatch(("claude-fable-5-2", "medium", False))
        self.assertEqual(result.returncode, 2)
        self.assertIn("model `claude-fable-5-2`", result.stderr)
        self.assertIn("/model opus", result.stderr)
        self.assertIn(str(self.root / "ok" / "s-1"), result.stderr)

    def test_xhigh_controller_is_denied(self):
        result = self.dispatch(("claude-opus-5-5", "xhigh", False))
        self.assertEqual(result.returncode, 2)
        self.assertIn("effort `xhigh`", result.stderr)

    def test_the_latest_main_thread_entry_decides(self):
        # Switched from fable to opus; a later fable subagent entry is not the controller.
        result = self.dispatch(("claude-fable-5-2", "xhigh", False), ("claude-opus-5-5", "medium", False),
                               ("claude-fable-5-2", "high", True))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_user_acceptance_file_lets_the_session_through(self):
        (self.root / "ok").mkdir()
        (self.root / "ok" / "s-1").touch()
        result = self.dispatch(("claude-fable-5-2", "xhigh", False))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_pipeline_dispatch_is_not_checked(self):
        result = self.dispatch(("claude-fable-5-2", "xhigh", False), description="Recon the request forms")
        self.assertEqual(result.returncode, 0, result.stderr)


class EffortGuardTest(unittest.TestCase):
    def allowed(self, *args, **kwargs):
        result = run_hook(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)

    def denied(self, pattern, *args, **kwargs):
        result = run_hook(*args, **kwargs)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr, pattern)

    def test_non_pipeline_dispatch_passes_untouched(self):
        self.allowed("Recon supplier request forms")
        self.allowed("pr triage")
        self.allowed("p6 T1/3 implementer", tool="SendMessage")

    def test_missing_model_is_denied(self):
        self.denied(r"passes no `model`", "p9 PR1 body writer", effort="medium")

    def test_missing_effort_is_denied_and_names_the_value(self):
        self.denied(r"Pass `effort: medium`", "p3 spec-security review", model="opus")
        self.denied(r"Pass `effort: high`", "p7 PR1 correctness review", model="opus")

    def test_matrix_values_pass(self):
        for description, model, effort in [
            ("p1 design agent", "fable", "high"),
            ("p1 brainstorm design agent", "opus", "high"),
            ("p1 code-state research", "sonnet", "medium"),
            ("p2 spec author", "opus", "medium"),
            ("p3 spec-security review", "opus", "medium"),
            ("p3 recheck security", "opus", "medium"),
            ("p3 spec reviser round-1", "opus", "medium"),
            ("p4 plan author", "fable", "high"),
            ("p4 plan author (opus fallback)", "opus", "high"),
            ("p5 plan impl-test review", "opus", "medium"),
            ("p5 plan reviser round-1", "fable", "high"),
            ("p5 spec amend PSTATE", "opus", "medium"),
            ("p6 T4-5/15 implementer", "sonnet", "medium"),
            ("p6 PR1-1 T4-5/52 task review", "sonnet", "medium"),
            ("p7 PR1 correctness review", "opus", "high"),
            ("p7 recheck P7C-1/2", "opus", "high"),
            ("p7 PR1-1 review fixer", "sonnet", "medium"),
            ("p7 PR3 fix verification review", "sonnet", "medium"),
            ("p8 PR1 rebase", "sonnet", "medium"),
            ("p8 PR1 pre-pr-bot review", "opus", "high"),
            ("p8 recheck P8A-1", "opus", "high"),
            ("p8 PR1 fix P8A-1/2", "sonnet", "medium"),
            ("p9 PR1 body writer", "sonnet", "medium"),
            ("p10 wave-2 fixer", "opus", "high"),
            ("p10 PR3a-1 wave 1 shepherd", "opus", "high"),
            ("p10 triage wave 2", "sonnet", "medium"),
            ("p10 review-wait helper", "haiku", "low"),
            ("p11 bookkeeping", "sonnet", "medium"),
        ]:
            with self.subTest(description=description):
                self.allowed(description, model=model, effort=effort)

    def test_wrong_effort_is_denied(self):
        self.denied(r"model matrix says `medium`", "p3 spec-security review", model="opus", effort="high")
        self.denied(r"model matrix says `high`", "p4 plan author", model="fable", effort="xhigh")
        self.denied(r"model matrix says `high`", "p7 PR1 correctness review", model="opus", effort="medium")
        self.denied(r"model matrix says `low`", "p10 review-wait helper", model="haiku", effort="medium")

    def test_override_allows_a_different_effort_but_not_a_missing_one(self):
        brief = "You are the reviewer.\neffort-guard: override trial of high on the security lens\n"
        self.allowed("p3 spec-security review", model="opus", effort="high", prompt=brief)
        self.denied(r"passes no `effort`", "p3 spec-security review", model="opus", prompt=brief)
        self.denied(r"model matrix says", "p3 spec-security review", model="opus", effort="high",
                    prompt="effort-guard: override")

    def test_opus_implementer_needs_a_named_risk(self):
        self.denied(r"no named risk", "p6 T7/52 implementer", model="opus", effort="medium")
        self.denied(r"no named risk", "p6 T7-9 task review", model="opus", effort="medium")
        self.allowed("p6 T7/52 implementer", model="opus", effort="medium",
                     prompt="(Task 7 of 52)\nComplexity risk: cross-package contract consumed by public-api\n")
        self.allowed("p6 T8-9 implementer (retry)", model="opus", effort="medium",
                     prompt="Escalated after: sonnet attempt left verify-diff red on the reducer test\n")
        self.denied(r"no named risk", "p6 T7/52 implementer", model="opus", effort="medium",
                    prompt="Complexity risk:\n")

    def test_opus_phase_7_fix_round_needs_a_named_risk(self):
        self.denied(r"no named risk", "p7 PR4 fix round", model="opus", effort="medium")
        self.allowed("p7 PR4 fix round", model="sonnet", effort="medium")
        self.allowed("p7 PR4 fix round", model="opus", effort="medium",
                     prompt="Complexity risk: the fix changes the idempotency key shape\n")
        self.allowed("p7 PR1 correctness review", model="opus", effort="high")

    def test_phase_8_pre_pr_review_runs_high_and_its_fix_round_needs_a_named_risk(self):
        self.denied(r"model matrix says `high`", "p8 PR1 pre-pr-bot review", model="opus", effort="medium")
        self.denied(r"no named risk", "p8 PR1 fix P8A-1", model="opus", effort="medium")
        self.allowed("p8 PR1 fix P8A-1", model="opus", effort="medium",
                     prompt="Escalated after: sonnet attempt left the reducer test red\n")

    def test_fable_wave_fixer_needs_an_escalation(self):
        self.denied(r"no escalation", "p10 wave-2 fixer", model="fable", effort="high")
        self.denied(r"no escalation", "p10 wave-2 fixer", model="fable", effort="high",
                    prompt="Complexity risk: contract surface\n")
        self.allowed("p10 wave-3 fixer", model="fable", effort="high",
                     prompt="Escalated after: wave 2, thread 101 reopened by the audit\n")
        self.allowed("p10 wave-2 fixer", model="fable", effort="high",
                     prompt="effort-guard: override measuring fable on first waves\n")
        self.allowed("p10 triage wave 2", model="sonnet", effort="medium")

    def test_sonnet_implementer_needs_no_risk_line(self):
        self.allowed("p6 T4-5/15 implementer", model="sonnet", effort="medium")

    def test_garbage_input_passes(self):
        result = subprocess.run(["python3", str(BIN / "effort-guard")], input="not json", text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
