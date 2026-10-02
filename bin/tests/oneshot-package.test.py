"""Fresh-machine installation checks; no writes to the real user config."""
import subprocess
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class BundleTest(unittest.TestCase):
    def test_repository_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "claude"
            env = dict(os.environ, CLAUDE_CONFIG_DIR=str(config))
            command = ["bash", str(REPO / "link.sh")]
            subprocess.run(command, env=env, check=True, capture_output=True)
            subprocess.run(command, env=env, check=True, capture_output=True)
            for relative in ("skills/oneshot-pipeline/SKILL.md", "agents/pr-shepherd.md",
                             "bin/review-wait", "bin/lib/resolve-pr-repo.sh",
                             "hooks/block-full-suite.sh"):
                self.assertTrue((config / relative).is_file(), relative)
            self.assertEqual([p.name for p in (config / "agents").iterdir()], ["pr-shepherd.md"])
            self.assertFalse((config / "skills/removed-skill").exists())
            self.assertFalse((config / "settings.json").exists())
            self.assertFalse((config / "commands").exists())

    def test_bundle_install_and_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "pipeline.tar.gz"
            subprocess.run(["python3", str(REPO / "bin/package-oneshot.py"), str(archive)], check=True)
            with tarfile.open(archive) as bundle:
                bundle.extractall(root / "extracted", filter="data")
            skill = root / "extracted/oneshot-pipeline"
            config = root / "config"
            command = ["python3", str(skill / "scripts/install-support.py"),
                       "--config-dir", str(config)]
            subprocess.run(command, check=True)
            subprocess.run(command, check=True)  # Idempotent.
            self.assertTrue((config / "agents/pr-shepherd.md").is_file())
            self.assertTrue((config / "bin/lib/resolve-pr-repo.sh").is_file())
            self.assertTrue((config / "hooks/block-full-suite.sh").is_file())
            self.assertTrue((config / "skills/oneshot-pipeline/reference/phase-10-shepherd.md").is_file())
            self.assertFalse((config / "settings.json").exists())
            # Actually invoke an installed helper that sources its shared lib.
            subprocess.run([str(config / "bin/pr-threads"), "--help"], check=True)
            conflict_config = root / "conflict"
            (conflict_config / "bin").mkdir(parents=True)
            existing = conflict_config / "bin/review-wait"
            existing.write_text("keep me")
            result = subprocess.run(command[:-1] + [str(conflict_config)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(existing.read_text(), "keep me")
            self.assertFalse((conflict_config / "agents").exists())


if __name__ == "__main__":
    unittest.main()
