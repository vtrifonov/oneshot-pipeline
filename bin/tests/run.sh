#!/bin/bash
# Tests for ~/.claude/bin/{pr-threads,pr-thread-close,ci-wait,verify-diff}.
# Run: bash ~/.claude/bin/tests/run.sh
#
# GitHub-touching scripts run against a stub `gh` placed first on PATH that
# serves canned responses and records every call, so nothing reaches GitHub.
# verify-diff is exercised in --dry-run mode against a throwaway git repo.

BIN="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d /tmp/binstub-XXXXXX); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }
check() { # check <label> <expected-exit> <actual-exit> <output> [grep-must-match ...]
    local label="$1" exp="$2" act="$3" out="$4"; shift 4
    if [ "$exp" != "$act" ]; then bad "$label" "expected exit $exp, got $act" "$out"; return; fi
    for pat in "$@"; do
        if ! printf '%s' "$out" | grep -qE -- "$pat"; then bad "$label" "output lacks /$pat/" "$out"; return; fi
    done
    ok
}

# ---------------------------------------------------------------- gh stub
mkdir -p "$TMP/stubbin"; : > "$TMP/gh.log"
cat > "$TMP/stubbin/gh" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
case "$*" in
    "repo view --json nameWithOwner --jq .nameWithOwner") echo "acme/widgets" ;;
    "pr view 7 --repo acme/widgets --json id --jq .id") echo "PR_node7" ;;
    "pr view 8 --repo acme/widgets --json id --jq .id") echo "GraphQL: Could not resolve to a PullRequest with the number of 8." >&2; exit 1 ;;
    "pr view 8 --repo acme/widgets --json number --jq .number") echo "8" ;;
    api\ graphql*)
        q="$*"
        if printf '%s' "$q" | grep -q 'resolveReviewThread'; then
            echo '{"data":{"resolveReviewThread":{"thread":{"isResolved":true}}}}'; touch "$GH_STATE/resolved"
        elif printf '%s' "$q" | grep -q 'after: "CUR1"'; then
            cat "$GH_FIXTURES/threads-page2.json"
        else
            if [ -f "$GH_STATE/resolved" ]; then cat "$GH_FIXTURES/threads-page1-resolved.json"; else cat "$GH_FIXTURES/threads-page1.json"; fi
        fi ;;
    api\ repos/*/pulls/*/comments/*/replies*) echo "999" ;;
    "pr checks 7 --json name,bucket"|"pr checks 7 --repo acme/widgets --json name,bucket")
        n=$(cat "$GH_STATE/tick" 2>/dev/null || echo 0); echo $((n+1)) > "$GH_STATE/tick"
        f="$GH_FIXTURES/checks-$n.json"; [ -f "$f" ] || f="$GH_FIXTURES/checks-last.json"; cat "$f" ;;
    *) echo "stub gh: unhandled: $*" >&2; exit 99 ;;
esac
STUB
chmod +x "$TMP/stubbin/gh"
export GH_LOG="$TMP/gh.log" GH_FIXTURES="$TMP/fx" GH_STATE="$TMP/state"; mkdir -p "$GH_FIXTURES" "$GH_STATE"
export CI_EXCLUDE_CHECKS='CODEOWNERS|Required reviewers|Required-reviewers'
export CI_REVIEW_CHECK='automated-review'
export AI_REVIEW_BOT='example-reviewer[bot]'
export PATH="$TMP/stubbin:$PATH"

# Fixture repo with one file the anchored excerpt can read.
REPO="$TMP/repo"; mkdir -p "$REPO/lib/__tests__" "$REPO/apps/web/src" "$REPO/packages/core/src"
git -C "$REPO" init -q;
for i in $(seq 1 60); do echo "line $i of util" >> "$REPO/lib/util.ts"; done
printf "import { x } from '../util';\ntest('x', () => {});\n" > "$REPO/lib/__tests__/util.test.ts"
printf "export const y = 1;\n" > "$REPO/apps/web/src/page.tsx"
printf "export const z = 1;\n" > "$REPO/packages/core/src/index.ts"
printf "test('p', () => {});\n" > "$REPO/apps/web/src/page.test.tsx"
echo '{}' > "$REPO/tsconfig.json"; echo '{}' > "$REPO/apps/web/tsconfig.json"; echo '{}' > "$REPO/packages/core/tsconfig.json"
echo 'export default {}' > "$REPO/vitest.config.browser.ts"
git -C "$REPO" add -A >/dev/null; git -C "$REPO" -c commit.gpgsign=false -c user.email=test@example.invalid -c user.name=Test commit -qm init

# Two pages of threads: page 1 has hasNextPage=true → the 100-cap trap.
cat > "$GH_FIXTURES/threads-page1.json" <<'J'
{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":true,"endCursor":"CUR1"},"nodes":[
 {"id":"T1","isResolved":false,"isOutdated":false,"path":"lib/util.ts","line":30,"originalLine":30,"comments":{"totalCount":1,"nodes":[{"databaseId":101,"author":{"login":"codex"},"createdAt":"2026-09-07T10:00:00Z","body":"**P1** Fence the claim on attemptId."}]}},
 {"id":"T2","isResolved":true,"isOutdated":true,"path":"lib/old.ts","line":5,"originalLine":5,"comments":{"totalCount":2,"nodes":[{"databaseId":102,"author":{"login":"codex"},"createdAt":"2026-09-07T10:00:00Z","body":"already done"}]}}
]}}}}}
J
cat > "$GH_FIXTURES/threads-page2.json" <<'J'
{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[
 {"id":"T3","isResolved":false,"isOutdated":false,"path":"lib/missing.ts","line":9,"originalLine":9,"comments":{"totalCount":1,"nodes":[{"databaseId":103,"author":{"login":"example-reviewer"},"createdAt":"2026-09-07T10:01:00Z","body":"Second-page finding — a 100-cap reader never sees this."}]}}
]}}}}}
J
sed 's/"id":"T1","isResolved":false/"id":"T1","isResolved":true/' "$GH_FIXTURES/threads-page1.json" > "$GH_FIXTURES/threads-page1-resolved.json"

# ---------------------------------------------------------------- pr-threads
out=$(cd "$REPO" && "$BIN/pr-threads" 7 --context 2 2>&1); rc=$?
check "pr-threads: unresolved only, paginated" 0 "$rc" "$out" \
    '2 unresolved of 3 review threads' 'lib/util.ts:30' 'comment 101' 'thread T1' 'Fence the claim' \
    'lines 28-32' '>   30  line 30 of util' 'covering tests' 'lib/__tests__/util.test.ts' \
    'Second-page finding' 'lib/missing.ts: not present' 'pr-thread-close 7 101 <sha>'
if printf '%s' "$out" | grep -q 'already done'; then bad "pr-threads hides resolved by default" "$out"; else ok; fi
out=$(cd "$REPO" && "$BIN/pr-threads" 7 --all --no-tests 2>&1); rc=$?
check "pr-threads --all includes resolved, flags it" 0 "$rc" "$out" 'all 3 review threads' 'already done' 'RESOLVED OUTDATED'
if printf '%s' "$out" | grep -q 'covering tests'; then bad "pr-threads --no-tests" "$out"; else ok; fi
out=$("$BIN/pr-threads" 2>&1); rc=$?
check "pr-threads usage" 64 "$rc" "$out" 'usage:'

# ---------------------------------------------------------------- pr-thread-close
: > "$GH_LOG"; rm -f "$GH_STATE/resolved"
out=$("$BIN/pr-thread-close" 7 101 abc1234 "Fenced the claim on attemptId." 2>&1); rc=$?
check "pr-thread-close: reply + resolve + confirm" 0 "$rc" "$out" 'replied to 101' 'thread T1 isResolved=true'
if grep -q 'pulls/7/comments/101/replies' "$GH_LOG" && grep -q 'body=Fenced the claim on attemptId.' "$GH_LOG" && grep -q 'Fixed in abc1234' "$GH_LOG"; then ok; else bad "pr-thread-close posts reply with sha" "$(cat "$GH_LOG")"; fi
if grep -q 'resolveReviewThread(input:{threadId:"T1"})' "$GH_LOG"; then ok; else bad "pr-thread-close resolves T1" "$(cat "$GH_LOG")"; fi
: > "$GH_LOG"; rm -f "$GH_STATE/resolved"
out=$("$BIN/pr-thread-close" 7 103 abc1234 "second page" 2>&1); rc=$?
# T3 lives on page 2 and never gets marked resolved by the stub → confirm fails honestly.
check "pr-thread-close: finds a page-2 thread, reports unresolved honestly" 1 "$rc" "$out" 'thread T3 isResolved=false'
out=$("$BIN/pr-thread-close" 7 555 abc1234 "nope" 2>&1); rc=$?
check "pr-thread-close: unknown comment id" 3 "$rc" "$out" 'no thread starts with comment 555'
out=$("$BIN/pr-thread-close" 7 101 2>&1); rc=$?
check "pr-thread-close: usage without sha/message" 64 "$rc" "$out" 'usage:'
: > "$GH_LOG"; rm -f "$GH_STATE/resolved"
out=$("$BIN/pr-thread-close" 7 101 --no-reply 2>&1); rc=$?
check "pr-thread-close --no-reply resolves only" 0 "$rc" "$out" 'isResolved=true'
if grep -q 'replies' "$GH_LOG"; then bad "pr-thread-close --no-reply must not reply" "$(cat "$GH_LOG")"; else ok; fi

# ---------------------------------------------------------------- ci-wait
mkchecks() { # mkchecks <file> "bucket name" ...
    local f="$1"; shift; { echo '['; local first=1; for e in "$@"; do [ $first = 1 ] || echo ','; first=0; printf '{"name":"%s","bucket":"%s"}' "${e#* }" "${e%% *}"; done; echo ']'; } > "$f"
}
# Scenario A: pending → review passes while integration still pending → exit 0 immediately.
rm -f "$GH_STATE/tick" "$GH_FIXTURES"/checks-*.json
mkchecks "$GH_FIXTURES/checks-0.json" "pending build" "pending review / automated-review" "pending integration-tests" "pending CODEOWNERS / Required reviewers"
mkchecks "$GH_FIXTURES/checks-1.json" "pass build" "pass review / automated-review" "pending integration-tests" "pending CODEOWNERS / Required reviewers"
cp "$GH_FIXTURES/checks-1.json" "$GH_FIXTURES/checks-last.json"
out=$("$BIN/ci-wait" 7 --interval 0 --max 30 2>&1); rc=$?
check "ci-wait: returns when review check passes" 0 "$rc" "$out" 'REVIEW CHECK PASSED: review / automated-review' 'pr-threads 7'
if printf '%s' "$out" | grep -q 'CODEOWNERS'; then bad "ci-wait excludes CODEOWNERS from output" "$out"; else ok; fi
# Scenario B: a failure → exit 1 naming it.
rm -f "$GH_STATE/tick" "$GH_FIXTURES"/checks-*.json
mkchecks "$GH_FIXTURES/checks-0.json" "pending build" "fail unit-tests" "pending review / automated-review"
cp "$GH_FIXTURES/checks-0.json" "$GH_FIXTURES/checks-last.json"
out=$("$BIN/ci-wait" 7 --interval 0 --max 30 2>&1); rc=$?
check "ci-wait: failed check exits 1" 1 "$rc" "$out" 'FAILED:' 'unit-tests'
# Scenario C: everything settled except CODEOWNERS → exit 0.
rm -f "$GH_STATE/tick" "$GH_FIXTURES"/checks-*.json
mkchecks "$GH_FIXTURES/checks-0.json" "pass build" "skipping review / automated-review" "pass unit-tests" "pending CODEOWNERS / Required reviewers"
cp "$GH_FIXTURES/checks-0.json" "$GH_FIXTURES/checks-last.json"
out=$("$BIN/ci-wait" 7 --interval 0 --max 30 2>&1); rc=$?
check "ci-wait: all settled ignoring CODEOWNERS" 0 "$rc" "$out" 'ALL CHECKS SETTLED'
# Scenario D: stays pending → timeout exit 2, transitions printed once.
rm -f "$GH_STATE/tick" "$GH_FIXTURES"/checks-*.json
mkchecks "$GH_FIXTURES/checks-0.json" "pending build"
cp "$GH_FIXTURES/checks-0.json" "$GH_FIXTURES/checks-last.json"
out=$("$BIN/ci-wait" 7 --interval 1 --max 2 2>&1); rc=$?
check "ci-wait: timeout exits 2" 2 "$rc" "$out" 'TIMEOUT after 2s'
n=$(printf '%s\n' "$out" | grep -c 'pending build')
if [ "$n" = 1 ]; then ok; else bad "ci-wait prints transitions once (got $n)" "$out"; fi

# ---------------------------------------------------------------- repo resolution
# PR 8 does not exist in acme/widgets, the repo the current directory resolves to:
# every script must refuse instead of watching or editing the wrong repository.
out=$("$BIN/review-wait" 8 --max 1 --interval 0 2>&1); rc=$?
check "review-wait: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets \(resolved from the current directory\)' 'pass --repo'
out=$("$BIN/review-wait" 8 --repo acme/widgets --max 1 --interval 0 2>&1); rc=$?
check "review-wait: PR missing in --repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets \(from --repo\)'
out=$("$BIN/ci-wait" 8 --max 1 --interval 0 2>&1); rc=$?
check "ci-wait: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets'
out=$("$BIN/audit-wait" 8 101 --max 1 --interval 0 2>&1); rc=$?
check "audit-wait: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets'
out=$("$BIN/rerun-failed" 8 abc1234 --max 1 --interval 0 2>&1); rc=$?
check "rerun-failed: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets'
out=$(cd "$REPO" && "$BIN/pr-threads" 8 --no-tests 2>&1); rc=$?
check "pr-threads: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets'
: > "$GH_LOG"
out=$("$BIN/pr-thread-close" 8 101 abc1234 "msg" 2>&1); rc=$?
check "pr-thread-close: PR missing in cwd repo" 64 "$rc" "$out" 'PR #8 not found in acme/widgets'
if grep -qE 'replies|resolveReviewThread' "$GH_LOG"; then bad "pr-thread-close must not write when the PR is missing" "$(cat "$GH_LOG")"; else ok; fi

# ---------------------------------------------------------------- verify-diff (dry-run)
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --files lib/util.ts lib/__tests__/util.test.ts apps/web/src/page.tsx packages/core/src/index.ts 2>&1); rc=$?
check "verify-diff: one tsc per owning tsconfig" 0 "$rc" "$out" \
    'tsc: npx tsc --noEmit -p \./tsconfig\.json' 'tsc: npx tsc --noEmit -p apps/web/tsconfig\.json' 'tsc: npx tsc --noEmit -p packages/core/tsconfig\.json' \
    'eslint: npx eslint --quiet lib/util\.ts lib/__tests__/util\.test\.ts apps/web/src/page\.tsx packages/core/src/index\.ts' \
    'vitest\(unit\): env CI=true npx vitest run lib/__tests__/util\.test\.ts --passWithNoTests' \
    'vitest\(browser\): env CI=true npx vitest run apps/web/src/page\.test\.tsx --passWithNoTests --reporter=dot --config vitest\.config\.browser\.ts'
n=$(printf '%s\n' "$out" | grep -c 'tsc: npx tsc'); if [ "$n" = 3 ]; then ok; else bad "verify-diff dedupes tsconfigs (got $n)" "$out"; fi
n=$(printf '%s\n' "$out" | grep -o 'util\.test\.ts' | wc -l | tr -d ' '); if [ "$n" = 2 ]; then ok; else bad "verify-diff lists a test once even when changed AND co-located (eslint + vitest = 2 mentions, got $n)" "$out"; fi
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --files lib/util.ts 2>&1); rc=$?
check "verify-diff: source change selects co-located/importing test, no browser run" 0 "$rc" "$out" 'vitest\(unit\): .* lib/__tests__/util\.test\.ts'
if printf '%s' "$out" | grep -q 'vitest(browser)'; then bad "verify-diff: no browser run for .ts-only" "$out"; else ok; fi
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --files apps/web/src/page.test.tsx 2>&1); rc=$?
check "verify-diff: .test.tsx runs under browser config" 0 "$rc" "$out" 'vitest\(browser\): .*apps/web/src/page\.test\.tsx'
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --files packages/core/src/index.ts 2>&1); rc=$?
check "verify-diff: source with no test says so" 0 "$rc" "$out" 'no test selected for the changed files'
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --related --files lib/util.ts apps/web/src/page.tsx 2>&1); rc=$?
check "verify-diff --related uses vitest related" 0 "$rc" "$out" 'vitest\(unit\): env CI=true npx vitest related lib/util\.ts apps/web/src/page\.tsx --run' 'vitest\(browser\): env CI=true npx vitest related lib/util\.ts apps/web/src/page\.tsx --run .*--config vitest\.config\.browser\.ts'
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --files README.md docs/x.md 2>&1); rc=$?
check "verify-diff: no source change is a clean no-op" 0 "$rc" "$out" 'no changed source or test files'
echo "// changed" >> "$REPO/lib/util.ts"; echo "export const n = 2;" > "$REPO/lib/new.ts"
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run 2>&1); rc=$?
check "verify-diff: default set = working tree incl. untracked" 0 "$rc" "$out" '2 source, 0 test' 'lib/new\.ts' 'lib/util\.ts'
out=$(cd "$REPO" && "$BIN/verify-diff" --dry-run --no-tests --no-lint --files lib/util.ts 2>&1); rc=$?
check "verify-diff: --no-tests --no-lint leaves tsc only" 0 "$rc" "$out" 'tsc:'
if printf '%s' "$out" | grep -qE 'eslint|vitest'; then bad "verify-diff --no-tests --no-lint" "$out"; else ok; fi

# ---------------------------------------------------------------- hooks
if python3 "$BIN/tests/hooks.test.py" >"$TMP/hooks.out" 2>&1; then ok; else bad "hooks.test.py" "$(cat "$TMP/hooks.out")"; fi

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
