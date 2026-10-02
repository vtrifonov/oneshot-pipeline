# claude-config

Portable Claude Code skills, a PR wave-fixer agent and helper scripts.

## Install from the shared repository

Install Claude Code, git and bash. Copy this repository's clone URL from GitHub,
replace the placeholder below, then run:

```sh
git clone 'REPLACE_WITH_REPOSITORY_CLONE_URL' ~/work/claude-config
bash ~/work/claude-config/link.sh
```

Keep the clone in place: installation uses symlinks. Restart Claude Code so it
discovers the skills and pr-shepherd agent. Then ask it to use oneshot-pipeline
for your task. From an existing checkout, the installation command is:

```sh
bash ./link.sh
```

The command installs both skills, pr-shepherd, CLI helpers, their shared library,
and the optional scoped-verification hook file into your own ~/.claude
directories. It preserves real files/directories and reports conflicts as SKIP.
Existing symlinks at matching destinations are redirected to this clone; inspect
them first if you use another configuration repository.

Before running the pipeline:
- Install GitHub CLI and jq; authenticate with gh auth login and verify with
  gh auth status.
- Install the Superpowers skills brainstorming, writing-plans,
  subagent-driven-development and test-driven-development, or map equivalent
  available capabilities in the repository adapter.
- Install the target project's development dependencies and test tools.
- Resolve the target repository's base branch, worktree location, CI gates and
  required review policy. The pipeline does not assume a checkout layout.
- Independent correctness/testing review is required; the full lane also needs
  security/architecture review. Available review skills or freshly briefed
  reviewer agents can satisfy those scopes.

The repository includes no credentials or private review skills. Missing required
capabilities must be resolved before claiming completion.

## Update

```sh
git -C ~/work/claude-config pull --ff-only
bash ~/work/claude-config/link.sh
```

Edits to existing linked files appear automatically; rerun installation for new
items. Restart Claude Code after agent or skill registration changes.
Installation does not delete old unrelated user files or edit settings.json.

## Optional integrations

The PR helpers resolve owner/name from your current checkout or --repo.
ci-wait checks all CI checks by default. A repository may explicitly configure
CI_EXCLUDE_CHECKS (regex) for non-gating checks and CI_REVIEW_CHECK (regex) to
return early when a review check passes. Early return is not final approval.

review-wait and audit-wait support a specific optional bot protocol:
approval reviews contain ai-review:approval reviewed=<sha>, and post-close
audit replies contain ai-review:author-resolve-audit. Configure AI_REVIEW_BOT
with the actual bot login and, if needed, AI_REVIEW_JOB with its job-name regex.
No bot identity or company workflow is built in. For other reviewers, the
pipeline uses native GitHub review/check APIs instead.

The optional block-full-suite.sh hook applies only to repositories containing
a .scoped-verification file at the Git root. Hook registration and the
controller-only ALLOW_FULL_SUITE=1 override are described in
skills/oneshot-pipeline/reference/distribution.md. Installing the hook file
does not activate it.

## What lives here

```text
skills/     oneshot-pipeline and split-large-pr, with supporting references
agents/     pr-shepherd: fixes one prepared review wave, then stops
bin/        CLI helpers and tests
link.sh     links the resources into the current user's Claude configuration
```

Machine-local logs, metrics, credentials, backups and repository-adapter.local.md
are gitignored. The repository adapter derives project rules from the target
repository; private details belong in local configuration, not shared skills.

## Optional standalone bundle

Repository installation is the normal sharing path. To distribute just the
pipeline and its support files without repository access:

```sh
python3 bin/package-oneshot.py /tmp/oneshot-pipeline.tar.gz
```

Recipient extracts the archive into a permanent directory, then runs:

```sh
tar -xzf oneshot-pipeline.tar.gz
python3 oneshot-pipeline/scripts/install-support.py
```

Restart Claude Code. The bundle installer checks all conflicts before linking
and refuses to replace unrelated destinations. External tools and capabilities
above remain prerequisites. See reference/distribution.md inside the skill.

## Verify installation helpers

```sh
python3 bin/tests/oneshot-package.test.py
python3 bin/tests/public-portability.test.py
bash bin/tests/run.sh
```

Tests use temporary configs and stub GitHub responses; they do not modify your
real Claude configuration or contact GitHub.
