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
        self.assertEqual(run_hook(self.S, "rm -f /tmp/probe.txt", agent="a1").returncode, 0)

    def test_quoted_scratch_operand_allowed(self):
        self.assertEqual(run_hook(self.S, 'rm "/private/tmp/claude-1/s/scratchpad/p q.txt"', agent="a1").returncode, 0)
        self.assertEqual(run_hook(self.S, "rm '/tmp/probe.txt'", agent="a1").returncode, 0)

    def test_recursive_rm_denied_even_in_scratch(self):
        for c in ("rm -r /tmp/probe", "rm -rf /tmp/probe", "rm -fr /tmp/probe", "rm -Rf /tmp/probe", "rm --recursive /tmp/probe"):
            r = run_hook(self.S, c, agent="a1")
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("prompt even in scratch", r.stderr)

    def test_find_delete_denied(self):
        self.assertEqual(run_hook(self.S, "find . -name '*.bak' -delete", agent="a1").returncode, 2)
        self.assertEqual(run_hook(self.S, "find -L . -type f -delete", agent="a1").returncode, 2)
        self.assertEqual(run_hook(self.S, "find . -name '*.bak' -exec rm {} \\;", agent="a1").returncode, 2)

    def test_mixed_quotes_do_not_hide_a_command(self):
        self.assertEqual(run_hook(self.S, "echo \"it's\" && rm -rf 'x'", agent="a1").returncode, 2)
        self.assertEqual(run_hook(self.S, "echo 'say \"hi\"' && rm -rf x", agent="a1").returncode, 2)
        self.assertEqual(run_hook(self.S, "echo \"it's\" && rg 'rm -rf' src", agent="a1").returncode, 0)

    def test_other_delete_spellings_denied(self):
        for c in ("ls | xargs rm -f", "echo $(rm -rf src)", "if true; then rm -rf src; fi", "command rm src/x",
                  "/bin/rm src/x", "\\rm src/x", "bash -c 'rm -rf src'", "timeout 300 rm -f src/x", "nohup rm src/x"):
            self.assertEqual(run_hook(self.S, c, agent="a1").returncode, 2, c)

    def test_git_global_options_normalized(self):
        for c in ("git -C /wt checkout -- src/x.ts", "git -C /wt stash", "git -C /wt reset --hard HEAD",
                  "git -C /wt worktree add ../x feat", "git -c core.pager=cat -C /wt restore f",
                  "git checkout HEAD -- f", "git checkout main -- .", "git reset HEAD~1 --hard",
                  "git switch --discard-changes", "timeout 300 git checkout -- ."):
            self.assertEqual(run_hook(self.S, c, agent="a1").returncode, 2, c)
        for c in ("git -C /wt stash list", "git stash show", "git -C /wt checkout -b feat", "git -C /wt status", "git -C /wt switch feat"):
            self.assertEqual(run_hook(self.S, c, agent="a1").returncode, 0, c)

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

    def test_bare_dollar_name_replacement_denied(self):
        r = run_hook(self.S, "sd 'oldName' '$newName' f")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Edit tool", r.stderr)
        self.assertEqual(run_hook(self.S, "sd -F 'oldName' '$newName' f").returncode, 0)

    def test_subagent_sd_always_denied(self):
        r = run_hook(self.S, "sd -F -- 'old' 'new' f", agent="a1")
        self.assertEqual(r.returncode, 2)

    def test_non_sd_passes(self):
        self.assertEqual(run_hook(self.S, "echo 'sd is \\n fine in text'").returncode, 0)

    def test_only_the_sd_segment_is_checked(self):
        self.assertEqual(run_hook(self.S, "sd -F 'a' 'b' f && echo \"${HOME}\"").returncode, 0)
        self.assertEqual(run_hook(self.S, "rg 'x|sd \\(' f").returncode, 0)
        self.assertEqual(run_hook(self.S, "printf '%s\\n' 'M5 sd-guard: rg x|sd \\(' >> log; echo \"${HOME}\"").returncode, 0)
        self.assertEqual(run_hook(self.S, r"sd 'a\{' 'b' f -F").returncode, 0)
        self.assertEqual(run_hook(self.S, r"grep -F x f | sd 'a\(' 'b' f").returncode, 2)
        self.assertEqual(run_hook(self.S, "FOO=1 sd -F 'a' 'b' f", agent="a1").returncode, 2)


if __name__ == "__main__":
    unittest.main()
