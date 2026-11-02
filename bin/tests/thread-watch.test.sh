#!/bin/bash
# Tests for bin/thread-watch and review-wait exit 4 with a stub gh.
# Stub state in $S: threads.json = the GraphQL reviewThreads page served; mergeable = value served;
# gql.count = number of graphql calls so far; switch_after = once gql.count passes it, serve threads-late.json.
BIN="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d /tmp/tw-XXXXXX); trap 'rm -rf "$TMP"' EXIT
pass=0 fail=0; ok() { pass=$((pass+1)); }; bad() { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }
S="$TMP/state"; mkdir -p "$TMP/bin" "$S"; export S
cat > "$TMP/bin/gh" <<'EOF'
#!/bin/bash
case "$*" in
    "repo view --json nameWithOwner --jq .nameWithOwner") echo "acme/widgets" ;;
    "pr view 7 --repo acme/widgets --json id --jq .id") echo "PR_node7" ;;
    "pr view 7 --repo acme/widgets --json mergeable --jq .mergeable") cat "$S/mergeable" 2>/dev/null || echo MERGEABLE ;;
    "pr view 7 --repo acme/widgets --json headRefOid --jq .headRefOid") echo "feedfacefeedfacefeedfacefeedfacefeedface" ;;
    "pr view 7 --repo acme/widgets --json baseRefName --jq .baseRefName") echo develop ;;
    "pr checks 7 --repo acme/widgets --json name,bucket") echo '[{"name":"build","bucket":"pass"}]' ;;
    "api repos/acme/widgets/pulls/7/reviews --paginate") echo '[]' ;;
    api\ graphql*)
        n=$(cat "$S/gql.count" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$S/gql.count"
        sw=$(cat "$S/switch_after" 2>/dev/null || echo 999999)
        if [ "$n" -gt "$sw" ]; then cat "$S/threads-late.json"; else cat "$S/threads.json"; fi ;;
    *) echo "stub gh: unhandled: $*" >&2; exit 99 ;;
esac
EOF
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"
none='{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
codex='{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"isResolved":false,"comments":{"nodes":[{"author":{"login":"chatgpt-codex-connector"}}]}},{"isResolved":true,"comments":{"nodes":[{"author":{"login":"old"}}]}}]}}}}}'
reset() { rm -f "$S"/*; printf '%s' "$none" > "$S/threads.json"; printf '%s' "$codex" > "$S/threads-late.json"; }
check() { # label expected-rc rc out pattern...
    local label=$1 exp=$2 act=$3 out=$4; shift 4
    [ "$exp" = "$act" ] || { bad "$label" "expected exit $exp, got $act" "$out"; return; }
    for p in "$@"; do printf '%s' "$out" | grep -qE -- "$p" || { bad "$label" "output lacks /$p/" "$out"; return; }; done
    ok
}

reset
out=$("$BIN/thread-watch" --interval 0 --max 0 7 2>&1); rc=$?
check "no threads: gives up at --max" 2 "$rc" "$out" 'TIMEOUT after 0s'

# Zero threads keeps it polling (no --max): the late thread arrives on the 3rd poll and ends it.
reset; echo 2 > "$S/switch_after"
out=$("$BIN/thread-watch" --interval 0 7 2>&1); rc=$?
check "no threads: keeps polling until one appears" 0 "$rc" "$out" 'THREADS pr=7 unresolved=1'
polls=$(cat "$S/gql.count"); if [ "$polls" = 3 ]; then ok; else bad "no threads: polled until the thread appeared (gql calls=$polls, want 3)" "$out"; fi

reset; printf '%s' "$codex" > "$S/threads.json"
out=$("$BIN/thread-watch" --interval 0 --max 5 7 2>&1); rc=$?
check "codex thread: exit 0 naming the author" 0 "$rc" "$out" 'THREADS pr=7 unresolved=1 authors=chatgpt-codex-connector'

reset; echo CONFLICTING > "$S/mergeable"
out=$("$BIN/thread-watch" --interval 0 --max 5 7 2>&1); rc=$?
check "conflicting: exit 3" 3 "$rc" "$out" 'CONFLICTING pr=7'

reset; out=$("$BIN/thread-watch" 2>&1); rc=$?
check "usage without a PR" 64 "$rc" "$out" 'usage:'

# review-wait: baseline 0 (first graphql call), a Codex thread appears on a later poll, no bot verdict yet.
reset; echo 1 > "$S/switch_after"
out=$(env -u AI_REVIEW_BOT "$BIN/review-wait" 7 --max 5 --interval 0 2>&1); rc=$?
check "review-wait: non-bot thread before the verdict exits 4" 4 "$rc" "$out" 'THREADS head=feedfacefeedfacefeedfacefeedfacefeedface unresolved=1 authors=chatgpt-codex-connector'

# review-wait: threads already open at start are the baseline, not news.
reset; printf '%s' "$codex" > "$S/threads.json"
out=$(env -u AI_REVIEW_BOT "$BIN/review-wait" 7 --max 1 --interval 1 2>&1); rc=$?
check "review-wait: pre-existing threads do not trigger exit 4" 2 "$rc" "$out" 'TIMEOUT'

echo "thread-watch passed=$pass failed=$fail"; [ "$fail" = 0 ]
