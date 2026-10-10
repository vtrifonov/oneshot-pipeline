#!/bin/bash
# Tests for bin/text-guards against a throwaway repo.
BIN="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d /tmp/tg-XXXXXX); trap 'rm -rf "$TMP"' EXIT
pass=0 fail=0; ok() { pass=$((pass+1)); }; bad() { fail=$((fail+1)); echo "FAIL [$1]"; shift; printf '  %s\n' "$@"; }
GIT_C=(-c user.email=t@e.invalid -c user.name=T -c commit.gpgsign=false)
R="$TMP/r"; mkdir -p "$R/app/api/x" "$R/lib/__tests__" "$R/docs"; git -C "$R" init -q -b main
printf 'export const GET = 1;\n' > "$R/app/api/x/route.ts"
printf 'export const y = 1;\n' > "$R/lib/util.ts"
# path leg: names the file literally
printf "import { readFileSync } from 'fs';\nconst s = readFileSync('app/api/x/route.ts', 'utf8');\n" > "$R/lib/__tests__/by-path.test.ts"
# nested-dir scan leg: quotes app/api and shells out
printf "import { execFileSync } from 'child_process';\nexecFileSync('rg', ['-l', 'drive', 'app/api']);\n" > "$R/lib/__tests__/scan-api.test.ts"
# broad leg: quotes only the top-level root
printf "import { readdirSync } from 'fs';\nreaddirSync('app');\n" > "$R/lib/__tests__/scan-root.test.ts"
# quotes app/api but never reads files: must NOT be listed
printf "const label = 'app/api';\ntest('x', () => {});\n" > "$R/lib/__tests__/mentions-only.test.ts"
# imports the changed file: an import-graph suite, not a text guard
printf "import { y } from '../util';\ntest('y', () => {});\n" > "$R/lib/__tests__/util.test.ts"
git -C "$R" add -A; git -C "$R" "${GIT_C[@]}" commit -qm base; git -C "$R" branch base

out=$("$BIN/text-guards" --repo "$R" --base base 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q 'no changed files'; then ok; else bad "clean tree" "rc=$rc $out"; fi

printf '// drives the pill\nexport const GET = 2;\n' > "$R/app/api/x/route.ts"
out=$("$BIN/text-guards" --repo "$R" --base base --cmd 2>&1); rc=$?
direct=$(printf '%s\n' "$out" | sed -n '/^direct/,/^broad/p')
broad=$(printf '%s\n' "$out" | sed -n '/^broad/,$p')
if [ "$rc" = 0 ] && printf '%s' "$direct" | grep -q 'by-path.test.ts' && printf '%s' "$direct" | grep -q 'path app/api/x/route.ts'; then ok; else bad "path leg (direct)" "$out"; fi
if printf '%s' "$direct" | grep -q 'scan-api.test.ts' && printf '%s' "$direct" | grep -q 'scans app/api/'; then ok; else bad "nested-dir scan leg (direct)" "$out"; fi
if printf '%s' "$broad" | grep -q 'scan-root.test.ts'; then ok; else bad "top-level scan listed as broad" "$out"; fi
if printf '%s' "$out" | grep -q 'mentions-only'; then bad "a quoted dir without a file reader is not a guard" "$out"; else ok; fi
if printf '%s' "$out" | grep -q 'util.test.ts'; then bad "an importing suite is not a text guard" "$out"; else ok; fi
if printf '%s' "$out" | grep -q '^npx vitest run .*by-path.test.ts'; then ok; else bad "--cmd prints a vitest line" "$out"; fi

out=$("$BIN/text-guards" --repo "$R" 2>&1); rc=$?
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'needs a ref'; then ok; else bad "no --base is a usage error (origin/HEAD is not always the trunk)" "rc=$rc $out"; fi
out=$("$BIN/text-guards" --repo "$R" --base nope 2>&1); rc=$?
if [ "$rc" = 64 ] && printf '%s' "$out" | grep -q 'not found'; then ok; else bad "unknown base is an error, not a clean" "rc=$rc $out"; fi
echo "text-guards passed=$pass failed=$fail"; [ "$fail" = 0 ]
