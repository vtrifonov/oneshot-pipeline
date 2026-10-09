#!/bin/bash
# Tests for bin/derived-check against a throwaway repo.
BIN="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d /tmp/dc-XXXXXX); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0; ok() { pass=$((pass+1)); }; bad() { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }
GIT_C=(-c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false)
R="$TMP/r"; mkdir -p "$R/supabase/migrations" "$R/node_modules"; git -C "$R" init -q -b main
echo '{}' > "$R/package-lock.json"; touch "$R/supabase/migrations/001_a.sql"
git -C "$R" add -A; git -C "$R" "${GIT_C[@]}" commit -qm base; git -C "$R" branch base
out=$(cd "$R" && "$BIN/derived-check" --base base 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q 'clean'; then ok; else bad "clean tree" "$out"; fi
touch "$R/node_modules/.package-lock.json"; sleep 1
echo '{"v":2}' > "$R/package-lock.json"; touch "$R/supabase/migrations/001_b.sql"
git -C "$R" add -A; git -C "$R" "${GIT_C[@]}" commit -qm change
out=$(cd "$R" && "$BIN/derived-check" --base base 2>&1); rc=$?
if [ "$rc" = 1 ] && printf '%s' "$out" | grep -q 'lockfile package-lock.json changed' && printf '%s' "$out" | grep -q 'migration timestamp 001 is duplicated'; then ok; else bad "lockfile + duplicate migration" "rc=$rc $out"; fi
echo "derived-check passed=$pass failed=$fail"; [ "$fail" = 0 ]
