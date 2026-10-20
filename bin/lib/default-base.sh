# shellcheck shell=bash
# Sourced by wt-create and derived-check. Not executable on its own.
#
# default_base <repo-dir>
#   Prints the ref new work branches from and diffs against, first match wins:
#     1. git config wt.base           (per-repo override)
#     2. origin/develop, if it exists (git-flow trunk; origin/HEAD is often the
#                                      release branch there, e.g. master)
#     3. origin/HEAD
#     4. the current branch
#   Prints nothing only when <repo-dir> is not a git checkout.

default_base() {
    local repo=$1 base
    base=$(git -C "$repo" config --get wt.base 2>/dev/null)
    if [ -z "$base" ] && git -C "$repo" show-ref --verify -q refs/remotes/origin/develop; then
        base=origin/develop
    fi
    [ -z "$base" ] && base=$(git -C "$repo" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)
    [ -z "$base" ] && base=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)
    printf '%s' "$base"
}
