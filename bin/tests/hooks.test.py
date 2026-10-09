"""PreToolUse guard hooks: run each with a synthetic payload, no real config touched."""
import json
import os
from pathlib import Path
import subprocess
import unittest

BIN = Path(__file__).resolve().parents[1]


def run_hook(script, command, agent=None, cwd="/Users/x/work/repo"):
    payload = {"cwd": cwd, "tool_input": {"command": command}}
    if agent:
        payload["agent_id"] = agent
    return subprocess.run(["bash", str(BIN / script)], input=json.dumps(payload),
                          text=True, capture_output=True)


class SubagentGuardTest(unittest.TestCase):
    S = "subagent-guard.sh"

    def test_main_session_untouched(self):
        self.assertEqual(run_hook(self.S, "rm -rf build").returncode, 0)
        self.assertEqual(run_hook(self.S, "cat <<EOF\nx\nEOF").returncode, 0)

    def test_rm_outside_scratch_denied(self):
        r = run_hook(self.S, "rm -f src/x.ts", agent="a1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Report the path to the controller", r.stderr)

    def test_rm_in_scratch_allowed(self):
        self.assertEqual(run_hook(self.S, "rm /private/tmp/claude-1/s/scratchpad/p.txt", agent="a1").returncode, 0)
        self.assertEqual(run_hook(self.S, "rm -r /tmp/probe", agent="a1").returncode, 0)

    def test_find_delete_denied(self):
        self.assertEqual(run_hook(self.S, "find . -name '*.bak' -delete", agent="a1").returncode, 2)

    def test_rm_inside_quoted_string_passes(self):
        self.assertEqual(run_hook(self.S, 'rg "rm -rf" src', agent="a1").returncode, 0)

    def test_heredoc_and_newline_denied(self):
        self.assertEqual(run_hook(self.S, "cat <<EOF > f\nx\nEOF", agent="a1").returncode, 2)
        r = run_hook(self.S, "echo a\necho b", agent="a1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Write tool", r.stderr)

    def test_inline_interpreter_denied(self):
        r = run_hook(self.S, "python3 -c 'print(1)'", agent="a1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("python3 -I", r.stderr)
        self.assertEqual(run_hook(self.S, "python3 -I /tmp/s.py", agent="a1").returncode, 0)

    def test_git_revert_denied(self):
        for c in ("git checkout -- src/x.ts", "git restore src/x.ts", "git stash", "git clean -fd", "git reset --hard HEAD"):
            self.assertEqual(run_hook(self.S, c, agent="a1").returncode, 2, c)
        self.assertEqual(run_hook(self.S, "git checkout -b feat", agent="a1").returncode, 0)

    def test_worktree_add_denied(self):
        r = run_hook(self.S, "git worktree add ../x feat", agent="a1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("wt-create", r.stderr)

    def test_segments_and_wrappers(self):
        self.assertEqual(run_hook(self.S, "cd /tmp; CI=1 ctx-wire run rm -f src/x", agent="a1").returncode, 2)
        self.assertEqual(run_hook(self.S, "ls | rm -f src/x", agent="a1").returncode, 2)


class SdGuardTest(unittest.TestCase):
    S = "sd-guard.sh"

    def test_single_line_literal_main_allowed(self):
        self.assertEqual(run_hook(self.S, "sd -F -- 'old' 'new' src/x.ts").returncode, 0)

    def test_multiline_pattern_denied(self):
        r = run_hook(self.S, r"sd 'a,\nb' '' src/x.ts")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Edit tool", r.stderr)

    def test_template_literal_replacement_denied(self):
        self.assertEqual(run_hook(self.S, "sd 'x' '${id}' src/x.ts").returncode, 2)
        self.assertEqual(run_hook(self.S, r"sd '\z' 'tail' f").returncode, 2)
        self.assertEqual(run_hook(self.S, r"sd '[\s\S]*?x' 'y' f").returncode, 2)

    def test_regex_brace_without_fixed_denied(self):
        self.assertEqual(run_hook(self.S, r"sd 'a\{' 'b' f").returncode, 2)
        self.assertEqual(run_hook(self.S, r"sd -F 'a\{' 'b' f").returncode, 0)

    def test_subagent_sd_always_denied(self):
        r = run_hook(self.S, "sd -F -- 'old' 'new' f", agent="a1")
        self.assertEqual(r.returncode, 2)

    def test_non_sd_passes(self):
        self.assertEqual(run_hook(self.S, "echo 'sd is \\n fine in text'").returncode, 0)


if __name__ == "__main__":
    unittest.main()
