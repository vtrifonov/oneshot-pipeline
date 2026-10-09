#!/bin/bash
# Tests for bin/wt-create against throwaway repos.
BIN="$(cd "$(dirname "$0")/.." && pwd)"
# Not under /tmp: wt-create refuses /tmp and /private/tmp main checkouts by design.
mkdir -p "$HOME/.cache"
TMP=$(mktemp -d "$HOME/.cache/wtc-XXXXXX"); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }

mkdir -p "$TMP/work/solution" "$TMP/work/svc"
git -C "$TMP/work/svc" init -q -b master
printf 'include ../solution/shared/x.mk\n' > "$TMP/work/svc/Makefile"
printf 'A=1\n' > "$TMP/work/svc/.env.local"
mkdir -p "$TMP/work/svc/.claude"; printf '#!/bin/bash\necho "setup ran in $1 from $2" > "$1/.setup-ran"\n' > "$TMP/work/svc/.claude/worktree-setup.sh"
printf '.env*\n.setup-ran\n' > "$TMP/work/svc/.gitignore"
git -C "$TMP/work/svc" add -A; git -C "$TMP/work/svc" -c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false commit -qm init
mkdir -p "$TMP/work/svc/node_modules"

out=$("$BIN/wt-create" feat/x-1 --repo "$TMP/work/svc" 2>&1); rc=$?
WT="$TMP/work/svc-worktrees/feat-x-1"
if [ "$rc" = 0 ] && { [ -d "$WT/.git" ] || [ -f "$WT/.git" ]; }; then ok; else bad "creates sibling worktree" "$out"; fi
if printf '%s' "$out" | tail -1 | grep -q "^WORKTREE $WT$"; then ok; else bad "last line WORKTREE path" "$out"; fi
if [ "$(git -C "$WT" branch --show-current 2>/dev/null)" = "feat/x-1" ]; then ok; else bad "branch checked out" "$(git -C "$WT" branch 2>&1)"; fi
if [ -L "$TMP/work/svc-worktrees/solution" ] && [ -L "$TMP/work/svc-worktrees/node_modules" ]; then ok; else bad "solution + node_modules symlinks next to worktrees" "$(ls -la "$TMP/work/svc-worktrees" 2>&1)"; fi
if [ -f "$WT/.env.local" ]; then ok; else bad "env file copied" "$out"; fi
if [ -f "$WT/.setup-ran" ]; then ok; else bad "repo-owned worktree-setup.sh ran" "$out"; fi
out=$("$BIN/wt-create" feat/x-1 --repo "$TMP/work/svc" 2>&1); rc=$?
if [ "$rc" != 0 ] && printf '%s' "$out" | grep -q 'already exists'; then ok; else bad "refuses existing" "$out"; fi
cp -R "$TMP/work/svc" "/tmp/wtc-svc-$$"
out=$("$BIN/wt-create" feat/y --repo "/tmp/wtc-svc-$$" 2>&1); rc=$?
rm -rf "/tmp/wtc-svc-$$"
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'never under /tmp'; then ok; else bad "refuses tmp" "rc=$rc $out"; fi
echo "wt-create passed=$pass failed=$fail"; [ "$fail" = 0 ]
