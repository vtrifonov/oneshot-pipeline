#!/bin/bash
# Tests for bin/lib/resolve-pr-repo.sh with a stub gh: FAKE_CWD_REPO is what `gh repo view` reports for
# the current directory (unset = not a repo), FAKE_PR_REPO is the only repository that holds a PR.
BIN="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d /tmp/rpr-XXXXXX); trap 'rm -rf "$TMP"' EXIT
pass=0 fail=0; ok() { pass=$((pass+1)); }; bad() { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }
mkdir -p "$TMP/bin"
cat > "$TMP/bin/gh" <<'EOF'
#!/bin/bash
if [ "$1 $2" = "repo view" ]; then [ -n "${FAKE_CWD_REPO:-}" ] && { echo "$FAKE_CWD_REPO"; exit 0; }; exit 1; fi
if [ "$1 $2" = "pr view" ]; then
    while [ $# -gt 0 ]; do [ "$1" = "--repo" ] && repo=$2; shift; done
    [ "$repo" = "${FAKE_PR_REPO:-}" ] && { echo "PR_node"; exit 0; }; exit 1
fi
exit 2
EOF
chmod +x "$TMP/bin/gh"
# shellcheck source=SCRIPTDIR/../lib/resolve-pr-repo.sh
run() { (PATH="$TMP/bin:$PATH"; . "$BIN/lib/resolve-pr-repo.sh"; resolve_pr_repo t 7 "$@") 2>&1; }

out=$(unset FAKE_CWD_REPO PR_HELPER_DEFAULT_REPO; FAKE_PR_REPO=o/r run); rc=$?
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'cannot resolve repo'; then ok; else bad "outside a repo with no default fails" "rc=$rc $out"; fi

out=$(unset FAKE_CWD_REPO; FAKE_PR_REPO=o/r PR_HELPER_DEFAULT_REPO=o/r run); rc=$?
if [ "$rc" = 0 ] && [ "$out" = "o/r" ]; then ok; else bad "outside a repo the default repo is used" "rc=$rc $out"; fi

out=$(unset FAKE_CWD_REPO; FAKE_PR_REPO=o/other PR_HELPER_DEFAULT_REPO=o/r run); rc=$?
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'not found in o/r (from PR_HELPER_DEFAULT_REPO)'; then ok; else bad "the default still has to hold the PR" "rc=$rc $out"; fi

out=$(FAKE_CWD_REPO=o/cwd FAKE_PR_REPO=o/cwd PR_HELPER_DEFAULT_REPO=o/r run); rc=$?
if [ "$rc" = 0 ] && [ "$out" = "o/cwd" ]; then ok; else bad "the current directory's repo beats the default" "rc=$rc $out"; fi

out=$(FAKE_CWD_REPO=o/cwd FAKE_PR_REPO=o/flag PR_HELPER_DEFAULT_REPO=o/r run o/flag); rc=$?
if [ "$rc" = 0 ] && [ "$out" = "o/flag" ]; then ok; else bad "--repo beats both" "rc=$rc $out"; fi

echo "resolve-pr-repo passed=$pass failed=$fail"; [ "$fail" = 0 ]
