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
# Run from inside a worktree without --repo: the new worktree must still land beside the main checkout.
out=$(cd "$WT" && "$BIN/wt-create" feat/z 2>&1); rc=$?
if [ "$rc" = 0 ] && [ -e "$TMP/work/svc-worktrees/feat-z" ] && [ ! -e "$WT-worktrees" ]; then ok; else bad "from inside a worktree, resolves the main checkout" "rc=$rc $out"; fi
# A branch that exists only on origin (the PR case) must be checked out tracking origin, not recreated off base.
git clone -q --bare "$TMP/work/svc" "$TMP/work/origin.git"
git -C "$TMP/work/svc" remote add origin "$TMP/work/origin.git"
git -C "$TMP/work/svc" switch -q -c pr/remote-only
echo remote > "$TMP/work/svc/remote.txt"; git -C "$TMP/work/svc" add remote.txt; git -C "$TMP/work/svc" -c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false commit -qm remote
git -C "$TMP/work/svc" push -q origin pr/remote-only
git -C "$TMP/work/svc" switch -q master; git -C "$TMP/work/svc" branch -q -D pr/remote-only
REMOTE_SHA=$(git -C "$TMP/work/svc" rev-parse origin/pr/remote-only)
out=$("$BIN/wt-create" pr/remote-only --repo "$TMP/work/svc" --base master --dir other 2>&1); rc=$?
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'exists on origin'; then ok; else bad "refuses --base for a remote-only branch" "rc=$rc $out"; fi
out=$("$BIN/wt-create" pr/remote-only --repo "$TMP/work/svc" 2>&1); rc=$?
WT2="$TMP/work/svc-worktrees/pr-remote-only"
if [ "$rc" = 0 ] && [ "$(git -C "$WT2" rev-parse HEAD 2>/dev/null)" = "$REMOTE_SHA" ] && [ "$(git -C "$WT2" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)" = "origin/pr/remote-only" ]; then ok; else bad "remote-only branch tracks origin" "rc=$rc $out"; fi
# Default base is the integration branch: origin/develop when it exists, not origin/HEAD (master).
git -C "$TMP/work/svc" remote set-head origin master >/dev/null 2>&1 || git -C "$TMP/work/svc" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/master
git -C "$TMP/work/svc" fetch -q origin
git -C "$TMP/work/svc" switch -q -c develop
echo dev > "$TMP/work/svc/dev.txt"; git -C "$TMP/work/svc" add dev.txt; git -C "$TMP/work/svc" -c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false commit -qm dev
git -C "$TMP/work/svc" push -q origin develop; git -C "$TMP/work/svc" switch -q master
DEV_SHA=$(git -C "$TMP/work/svc" rev-parse origin/develop)
out=$("$BIN/wt-create" feat/on-develop --repo "$TMP/work/svc" 2>&1); rc=$?
if [ "$rc" = 0 ] && [ "$(git -C "$TMP/work/svc-worktrees/feat-on-develop" rev-parse HEAD 2>/dev/null)" = "$DEV_SHA" ]; then ok; else bad "defaults to origin/develop over origin/HEAD" "rc=$rc $out"; fi
git -C "$TMP/work/svc" config wt.base master
out=$("$BIN/wt-create" feat/on-config --repo "$TMP/work/svc" 2>&1); rc=$?
if [ "$rc" = 0 ] && [ "$(git -C "$TMP/work/svc-worktrees/feat-on-config" rev-parse HEAD 2>/dev/null)" = "$(git -C "$TMP/work/svc" rev-parse master)" ]; then ok; else bad "git config wt.base overrides the default" "rc=$rc $out"; fi
git -C "$TMP/work/svc" config --unset wt.base
# git config wt.setup runs inside the new worktree, after the env copy and the repo hook.
git -C "$TMP/work/svc" config wt.setup 'pwd -P > .wt-setup-cwd; test -f .env.local && echo env-ok >> .wt-setup-cwd'
out=$("$BIN/wt-create" feat/setup --repo "$TMP/work/svc" 2>&1); rc=$?
WT3="$TMP/work/svc-worktrees/feat-setup"
if [ "$rc" = 0 ] && [ "$(head -1 "$WT3/.wt-setup-cwd" 2>/dev/null)" = "$(cd "$WT3" 2>/dev/null && pwd -P)" ] && grep -q env-ok "$WT3/.wt-setup-cwd" 2>/dev/null; then ok; else bad "wt.setup runs in the worktree after the env copy" "rc=$rc $out"; fi
if printf '%s' "$out" | tail -1 | grep -q "^WORKTREE $WT3$"; then ok; else bad "WORKTREE stays the last line after wt.setup" "$out"; fi
out=$("$BIN/wt-create" feat/no-setup --repo "$TMP/work/svc" --no-setup 2>&1); rc=$?
if [ "$rc" = 0 ] && [ ! -e "$TMP/work/svc-worktrees/feat-no-setup/.wt-setup-cwd" ] && printf '%s' "$out" | grep -q 'skipped wt.setup'; then ok; else bad "--no-setup skips wt.setup and says so" "rc=$rc $out"; fi
git -C "$TMP/work/svc" config wt.setup 'exit 7'
out=$("$BIN/wt-create" feat/setup-fails --repo "$TMP/work/svc" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q 'wt.setup exited 7' && printf '%s' "$out" | tail -1 | grep -q '^WORKTREE '; then ok; else bad "a failing wt.setup warns, keeps the worktree and still prints WORKTREE" "rc=$rc $out"; fi
git -C "$TMP/work/svc" config --unset wt.setup
# A Node repo: the worktree reuses the main checkout's node_modules when the lockfile matches.
mkdir -p "$TMP/work/web/node_modules"
git -C "$TMP/work/web" init -q -b master
printf '{"lockfileVersion":3}\n' > "$TMP/work/web/package-lock.json"
printf 'node_modules\n.setup-ran\n' > "$TMP/work/web/.gitignore"
git -C "$TMP/work/web" add -A; git -C "$TMP/work/web" -c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false commit -qm init
out=$("$BIN/wt-create" feat/deps --repo "$TMP/work/web" --base master 2>&1); rc=$?
if [ "$rc" = 0 ] && [ "$(readlink "$TMP/work/web-worktrees/feat-deps/node_modules")" = "$TMP/work/web/node_modules" ]; then ok; else bad "links node_modules when the lockfile matches" "rc=$rc $out"; fi
out=$("$BIN/wt-create" feat/no-setup --repo "$TMP/work/web" --base master --no-setup 2>&1); rc=$?
if [ "$rc" = 0 ] && [ ! -e "$TMP/work/web-worktrees/feat-no-setup/node_modules" ]; then ok; else bad "--no-setup skips the node_modules link" "rc=$rc $out"; fi
printf '{"lockfileVersion":3,"changed":true}\n' > "$TMP/work/web/package-lock.json"
out=$("$BIN/wt-create" feat/drift --repo "$TMP/work/web" --base master 2>&1); rc=$?
if [ "$rc" = 0 ] && [ ! -e "$TMP/work/web-worktrees/feat-drift/node_modules" ] && printf '%s' "$out" | grep -q 'differs'; then ok; else bad "does not link node_modules when the lockfile differs" "rc=$rc $out"; fi
git -C "$TMP/work/web" checkout -q -- package-lock.json
git -C "$TMP/work/web" config wt.setup 'touch .setup-ran'
out=$("$BIN/wt-create" feat/setup --repo "$TMP/work/web" --base master 2>&1); rc=$?
if [ "$rc" = 0 ] && [ -f "$TMP/work/web-worktrees/feat-setup/.setup-ran" ] && [ ! -e "$TMP/work/web-worktrees/feat-setup/node_modules" ]; then ok; else bad "wt.setup runs and replaces the node_modules link" "rc=$rc $out"; fi
cp -R "$TMP/work/svc" "/tmp/wtc-svc-$$"
out=$("$BIN/wt-create" feat/y --repo "/tmp/wtc-svc-$$" 2>&1); rc=$?
rm -rf "/tmp/wtc-svc-$$"
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'never under /tmp'; then ok; else bad "refuses tmp" "rc=$rc $out"; fi
echo "wt-create passed=$pass failed=$fail"; [ "$fail" = 0 ]
