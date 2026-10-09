"""Exercise public defaults without GitHub calls or the real user config."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN = Path(__file__).resolve().parents[1]


class PortabilityTest(unittest.TestCase):
    def test_hook_scope_and_controller_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "arbitrary-project-name"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            def hook(command, agent=False):
                payload = {"cwd": str(repo), "tool_input": {"command": command}}
                if agent:
                    payload["agent_id"] = "test-agent"
                return subprocess.run(["bash", str(BIN / "block-full-suite.sh")],
                                      input=json.dumps(payload), text=True, capture_output=True)

            self.assertEqual(hook("npm test").returncode, 0)
            (repo / ".scoped-verification").touch()
            self.assertEqual(hook("npm test").returncode, 2)
            self.assertEqual(hook("npx vitest run lib/example.test.ts").returncode, 0)
            self.assertEqual(hook("ALLOW_FULL_SUITE=1 npm test").returncode, 0)
            self.assertEqual(hook("ALLOW_FULL_SUITE=1 npm test", agent=True).returncode, 2)

    def test_ci_has_no_implicit_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            stub = Path(temporary) / "gh"
            stub.write_text('''#!/bin/sh
case "$*" in
  "repo view --json nameWithOwner --jq .nameWithOwner") echo example/project ;;
  "pr view 7 --repo example/project --json id --jq .id") echo PR_test ;;
  "pr checks 7 --repo example/project --json name,bucket")
    echo '[{"name":"build","bucket":"pass"},{"name":"Required reviewers","bucket":"pending"}]' ;;
  "pr view 7 --repo example/project --json headRefOid --jq .headRefOid") echo abc ;;
  "pr view 7 --repo example/project --json mergeable --jq .mergeable") echo MERGEABLE ;;
  "api repos/example/project/pulls/7/reviews --paginate") echo "[]" ;;
  *) exit 99 ;;
esac
''')
            stub.chmod(0o755)
            env = dict(os.environ, PATH=f"{temporary}:{os.environ['PATH']}")
            for name in ("CI_EXCLUDE_CHECKS", "CI_REVIEW_CHECK", "AI_REVIEW_BOT"):
                env.pop(name, None)
            command = [str(BIN / "ci-wait"), "7", "--max", "0"]
            self.assertEqual(subprocess.run(command, env=env, capture_output=True).returncode, 2)
            env["CI_EXCLUDE_CHECKS"] = "^Required reviewers$"
            self.assertEqual(subprocess.run(command, env=env, capture_output=True).returncode, 0)
            result = subprocess.run([str(BIN / "review-wait"), "7", "--max", "0"],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("AI_REVIEW_BOT", result.stdout)


if __name__ == "__main__":
    unittest.main()
