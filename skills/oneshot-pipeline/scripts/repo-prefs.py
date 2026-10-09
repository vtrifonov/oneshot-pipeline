#!/usr/bin/env python3
"""Per-repository run preferences that outlive a single pipeline run.

Stores user choices such as "never use frontend-design in this repository"
in repo-prefs.local.json next to this skill (gitignored, per machine), keyed
by the target repository's owner/name.

  repo-prefs.py get   <owner/name> <key>          prints the value, or "unset"
  repo-prefs.py set   <owner/name> <key> <value>
  repo-prefs.py clear <owner/name> <key>

ONESHOT_REPO_PREFS overrides the file path (tests).
"""
import argparse
import json
import os
import pathlib
import sys
import tempfile

KNOWN = {"frontend_design": {"always", "never"}}


def prefs_path():
    override = os.environ.get("ONESHOT_REPO_PREFS")
    if override:
        return pathlib.Path(override)
    return pathlib.Path(__file__).resolve().parent.parent / "repo-prefs.local.json"


def load(path):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash never leaves a half-written file.
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(handle.name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["get", "set", "clear"])
    parser.add_argument("repo", help="owner/name of the target repository")
    parser.add_argument("key", choices=sorted(KNOWN))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()

    if args.action == "set":
        if args.value not in KNOWN[args.key]:
            parser.error(f"{args.key} accepts: {', '.join(sorted(KNOWN[args.key]))}")
    elif args.value is not None:
        parser.error(f"{args.action} takes no value")

    path = prefs_path()
    data = load(path)
    repo = data.get(args.repo, {})

    if args.action == "get":
        print(repo.get(args.key, "unset"))
        return 0
    if args.action == "set":
        repo[args.key] = args.value
    else:
        repo.pop(args.key, None)
    if repo:
        data[args.repo] = repo
    else:
        data.pop(args.repo, None)
    save(path, data)
    print(f"{args.repo} {args.key}={repo.get(args.key, 'unset')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
