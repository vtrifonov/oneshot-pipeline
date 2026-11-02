# shellcheck shell=bash
# Sourced by the PR helper scripts. Not executable on its own.
#
# unresolved_summary <repo> <pr>
#   Prints "<count> <authors>" (authors = comma-separated distinct logins of each
#   unresolved thread's first comment, "-" when none), or "? -" when GitHub could
#   not be read. Paginated: GitHub caps reviewThreads at 100 per page and never warns.
# unresolved_count <repo> <pr>
#   Prints only the count ("?" when unreadable).

unresolved_summary() {
    local repo=$1 pr=$2 cursor="" after="" page n=0 authors="" more
    while :; do
        [ -n "$cursor" ] && after=", after: \"$cursor\""
        page=$(gh api graphql -f query="
        query { repository(owner: \"${repo%/*}\", name: \"${repo#*/}\") { pullRequest(number: $pr) {
          reviewThreads(first: 100$after) { pageInfo { hasNextPage endCursor } nodes { isResolved comments(first: 1) { nodes { author { login } } } } } } } }" 2>/dev/null) || { echo "? -"; return; }
        n=$(( n + $(printf '%s' "$page" | jq -r '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false)] | length') ))
        authors="$authors"$'\n'$(printf '%s' "$page" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false) | (.comments.nodes[0].author.login // "unknown")')
        more=$(printf '%s' "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
        [ "$more" = "true" ] || break
        cursor=$(printf '%s' "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')
    done
    authors=$(printf '%s\n' "$authors" | grep -v '^$' | sort -u | paste -sd, -)
    echo "$n ${authors:--}"
}

unresolved_count() {
    local s
    s=$(unresolved_summary "$1" "$2")
    echo "${s%% *}"
}
