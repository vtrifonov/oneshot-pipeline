# gh_rate_sleep <interval-seconds>
# Sleep between polls of the GitHub REST API without draining the 5,000/h quota.
# `gh api rate_limit` is free (it does not count). When core.remaining is below
# GH_RATE_FLOOR (default 300) the sleep runs until the window resets instead of
# for the interval, and one line says so. Four pipeline waiters on two PRs drained
# the whole quota three times in one run before this guard existed.
gh_rate_sleep() {
    local interval="$1" floor="${GH_RATE_FLOOR:-300}" remaining reset now wait
    remaining=$(gh api rate_limit --jq .resources.core.remaining 2>/dev/null)
    case "$remaining" in
        ''|*[!0-9]*) sleep "$interval"; return ;;
    esac
    if [ "$remaining" -lt "$floor" ]; then
        reset=$(gh api rate_limit --jq .resources.core.reset 2>/dev/null)
        now=$(date +%s)
        case "$reset" in
            ''|*[!0-9]*) wait="$interval" ;;
            *) wait=$(( reset - now + 5 )); [ "$wait" -lt "$interval" ] && wait="$interval" ;;
        esac
        echo "[$(date +%H:%M:%S)] gh quota remaining=$remaining < $floor: sleeping ${wait}s until the window resets"
        sleep "$wait"
        return
    fi
    sleep "$interval"
}
