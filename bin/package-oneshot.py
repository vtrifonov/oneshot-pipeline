#!/usr/bin/env python3
"""Export the pipeline with its repo-owned runtime dependencies."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def package(output):
    repo = Path(__file__).resolve().parent.parent
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "oneshot-pipeline"
        # Export versionable skill files only. Ignored run logs and backups can
        # contain personal context and must never enter a shared archive.
        paths = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z",
             "--", "skills/oneshot-pipeline"], cwd=repo).decode().split("\0")
        for relative in filter(None, paths):
            source = repo / relative
            if not source.is_file():
                continue
            destination = root / source.relative_to(repo / "skills/oneshot-pipeline")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        support = root / "support"
        (support / "agents").mkdir(parents=True)
        (support / "bin").mkdir()
        shutil.copy2(repo / "agents/pr-shepherd.md", support / "agents/pr-shepherd.md")
        for name in ("verify-diff", "review-wait", "pr-threads", "audit-wait",
                     "rerun-failed", "pr-thread-close", "ci-wait"):
            shutil.copy2(repo / "bin" / name, support / "bin" / name)
        shutil.copytree(repo / "bin/lib", support / "bin/lib")
        (support / "hooks").mkdir()
        shutil.copy2(repo / "bin/block-full-suite.sh", support / "hooks/block-full-suite.sh")
        archive = shutil.make_archive(str(Path(temporary) / "bundle"), "gztar", temporary,
                                      "oneshot-pipeline")
        shutil.copy2(archive, output)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="New .tar.gz bundle path")
    package(parser.parse_args().output)
