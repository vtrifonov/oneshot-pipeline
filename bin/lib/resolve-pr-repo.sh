# shellcheck shell=bash
# Sourced by the PR helper scripts. Not executable on its own.
#
# resolve_pr_repo <tool> <pr> [<repo>]
#   Prints owner/name for the repository that holds <pr>. Uses <repo> when given
#   (--repo), else the repository of the current directory, else
#   $PR_HELPER_DEFAULT_REPO (set per project in .claude/settings.local.json `env`,
#   for a session whose shell has drifted to the scratchpad). Fails with exit 64
#   and a message naming the source when that repository has no such PR, so a
#   script started from the wrong checkout stops instead of polling or writing
#   against a PR number that means something else there.

resolve_pr_repo() {
    local tool=$1 pr=$2 repo=${3:-} source="from --repo" node_id
    if [ -z "$repo" ]; then
        source="resolved from the current directory"
        repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)
    fi
    if [ -z "$repo" ] && [ -n "${PR_HELPER_DEFAULT_REPO:-}" ]; then
        source="from PR_HELPER_DEFAULT_REPO"
        repo=$PR_HELPER_DEFAULT_REPO
    fi
    [ -z "$repo" ] && { echo "$tool: cannot resolve repo; pass --repo owner/name" >&2; return 64; }
    # gh answers `--json number` from the argument without calling GitHub, so it
    # "finds" any number in any repository; `id` forces the lookup.
    node_id=$(gh pr view "$pr" --repo "$repo" --json id --jq .id 2>/dev/null)
    if [ -z "$node_id" ]; then
        echo "$tool: PR #$pr not found in $repo ($source); pass --repo owner/name" >&2
        return 64
    fi
    printf '%s\n' "$repo"
}
