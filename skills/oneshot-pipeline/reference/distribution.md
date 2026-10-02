# Distribution and dependency preflight

Read before Phase 0 on a new installation. Sharing only SKILL.md or the raw skill directory omits runtime dependencies. The portable bundle includes the phase references, Workflow script, pr-shepherd agent, seven CLI helpers, their shared library, and the optional scoped-verification hook.

## Build and install

Preferred: share access to the repository. Recipient clones it into a permanent
directory and runs `bash ./link.sh` from the repository root, then restarts Claude
Code. This links the skills, pr-shepherd, helpers and shared library into their own
~/.claude directories, plus the optional hook file. No bundle generation or manual
copies are needed. Keep the clone in place; pull updates and rerun link.sh for new
items. External capabilities below remain prerequisites.

For standalone sharing without repository access:

From the claude-config repository:

```sh
python3 bin/package-oneshot.py /tmp/oneshot-pipeline.tar.gz
```

Share that archive. Recipient extracts it into a permanent location, then runs:

```sh
tar -xzf oneshot-pipeline.tar.gz
python3 oneshot-pipeline/scripts/install-support.py
```

The installer links the skill and support into ~/.claude, checks all conflicts before changing anything, and refuses to replace existing files or unrelated links. Keep the extracted folder: links point there. Restart Claude Code to discover pr-shepherd. If the skill is already installed elsewhere, use the same extracted bundle as the canonical installation and resolve the reported conflict explicitly.

The archive is generated from canonical repo sources; do not maintain manual copies under support/. Rebuild after changing a helper or agent.

## Required external capabilities

The bundle does not include credentials or third-party skills. Before starting, resolve these through the repository/runtime adapter:

- Python 3 for installation; bash, git, gh (authenticated to the target repository), jq, and standard Unix utilities for helpers. verify-diff also needs the target repo's Node/npm toolchain and installed test/lint/type tools.
- `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development`, and `superpowers:test-driven-development` where the phase uses them.
- Independent correctness/testing review and, for the full lane, security/architecture review. Use available review skills or brief fresh reviewers directly with the Finding contract. Do not report an unavailable required gate as passed.
- Native agent dispatch/status and user checkpoint tools. Phase 10b additionally requires the Claude Workflow integration; use Phase 10a if unavailable.

For Claude/GitHub runs, confirm pr-shepherd is discovered and the required helpers are executable in ~/.claude/bin. A missing helper is an installation problem: use this bundle or repository sources, never assume only the user can provide it. Other runtimes use the adapter's native equivalents and the bundled agent brief.

## Optional scoped-verification hook

The installer places ~/.claude/hooks/block-full-suite.sh but does not change settings.json. This hook enforces scoped local verification in opted-in repositories; it is not required to execute the pipeline. Without it, obey the same scoped-check rule in the phase instructions.

If wanted, merge this entry into the existing PreToolUse list in ~/.claude/settings.json, preserving all other settings:

```json
{
  "matcher": "Bash",
  "hooks": [
    {"type": "command", "command": "bash \"$HOME/.claude/hooks/block-full-suite.sh\""}
  ]
}
```

The hook requires jq, git and perl. Opt in per repository by creating a .scoped-verification file at its Git root; no directory naming convention is required. Phase 8's main-controller override remains ALLOW_FULL_SUITE=1. Installing the file alone does not register the hook.
