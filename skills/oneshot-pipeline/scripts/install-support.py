#!/usr/bin/env python3
"""Link bundled support into Claude config without replacing existing files."""
import argparse
from pathlib import Path


def install(config):
    skill = Path(__file__).resolve().parent.parent
    support = skill / "support"
    if not support.is_dir():
        raise SystemExit("Support missing: share a bundle made by bin/package-oneshot.py, not the raw skill folder.")
    pairs = [(skill, config / "skills/oneshot-pipeline")]
    for group in ("agents", "bin", "hooks"):
        pairs.extend((source, config / group / source.name)
                     for source in sorted((support / group).iterdir()))
    # Check every destination before making changes. Existing unrelated links
    # are conflicts too; never silently redirect someone's config.
    conflicts = [str(dest) for source, dest in pairs
                 if (dest.exists() or dest.is_symlink()) and dest.resolve() != source.resolve()]
    if conflicts:
        raise SystemExit("Existing destinations differ; no changes made:\n" + "\n".join(conflicts))
    for source, dest in pairs:
        if dest.exists() or dest.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(source, target_is_directory=source.is_dir())
        print(f"linked {dest}")
    print("Support installed. Hook registration is optional; see reference/distribution.md. Restart Claude to load pr-shepherd.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path.home() / ".claude")
    install(parser.parse_args().config_dir.expanduser().resolve())
