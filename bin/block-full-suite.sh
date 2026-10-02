#!/bin/bash
# PreToolUse hook (Bash): in an opted-in repository, block full local test suites
# and full builds. CI runs them authoritatively on every push; locally they cost
# 2-10 minutes each and agents were running them per finding despite the prose
# rule (five agents, ~70 min of suites and sleep-polling in one afternoon).
#
# Scope: the hook cwd must be in a Git repository with a .scoped-verification
# marker at its root. Other repositories are unaffected.
#
# Blocked:  npm test | npm run test[:*] | npm run build | next build |
#           vitest [run] with no positional file/dir argument
# Allowed:  npm run build:* (runtime-packages, sdk, ...), vitest with a path,
#           vitest --changed / --related, tsc, lint, everything else.
#
# Known limit: segments are split on ; && || | without quote awareness, so a
# quoted string that itself reads `...; npm test ...` (a prompt written via
# printf, say) is also rejected. Write such text with the Write tool instead.
#
# Escape hatch: a command prefixed with ALLOW_FULL_SUITE=1 passes in the MAIN
# thread only (the once-at-the-end pre-PR run). Subagents are blocked without
# exception. A subagent's hook input carries `agent_id` and `agent_type`
# (verified 2026-09-07 with a logging hook); its transcript_path is the PARENT
# session's, so the /subagents/ check below is a fallback, not the signal.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[ -z "$CMD" ] && exit 0

HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty')
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // .agent_type // empty')

# Opt in at the repository root; no personal checkout path is assumed.
REPO_ROOT=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -f "$REPO_ROOT/.scoped-verification" ] || exit 0

is_subagent() {
    case "$TRANSCRIPT" in */subagents/*) return 0 ;; esac
    [ -n "$AGENT_ID" ] && return 0
    return 1
}

# Split on command separators so `cd x; CI=true npm test 2>&1 | tail` is seen
# as its own segment. Then strip wrappers that precede the real command.
normalize_segment() {
    local seg="$1"
    seg=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
    # Leading env assignments (CI=true, ALLOW_FULL_SUITE=1, FOO="bar baz").
    while printf '%s' "$seg" | grep -qE '^[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:]]*)[[:space:]]+'; do
        seg=$(printf '%s' "$seg" | sed -E 's/^[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:]]*)[[:space:]]+//')
    done
    # Wrappers: ctx-wire run [flags], time, nice [-n N], npx [--yes|-y].
    while :; do
        local before="$seg"
        seg=$(printf '%s' "$seg" | sed -E 's/^ctx-wire[[:space:]]+run([[:space:]]+--[a-z-]+([[:space:]]+[^-][^[:space:]]*)?)*[[:space:]]+//')
        seg=$(printf '%s' "$seg" | sed -E 's/^time[[:space:]]+//; s/^nice([[:space:]]+-n[[:space:]]*[0-9]+)?[[:space:]]+//; s/^npx[[:space:]]+(--yes[[:space:]]+|-y[[:space:]]+)?//')
        [ "$seg" = "$before" ] && break
    done
    printf '%s' "$seg"
}

# vitest with no positional target is a full run. Drop flags and the values of
# flags that take one; --changed/--related scope the run by themselves.
vitest_is_scoped() {
    local rest="$1" tok skip=0
    for tok in $rest; do
        if [ "$skip" = 1 ]; then skip=0; continue; fi
        case "$tok" in
            run) ;;
            --changed|--changed=*|--related|--related=*) return 0 ;;
            --version|-v|--help|-h|list|related|init|bench) return 0 ;;
            --config|-c|--reporter|-r|--root|--dir|--project|-t|--testNamePattern|--outputFile|--coverage.reporter|--pool|--shard|--environment|--bail|--retry|--maxWorkers|--minWorkers)
                skip=1 ;;
            -*) ;;
            *) return 0 ;;
        esac
    done
    return 1
}

check_segment() {
    local seg
    seg=$(normalize_segment "$1")
    case "$seg" in
        "npm test"|"npm test "*|"npm t"|"npm t "*|"npm run test"|"npm run test "*|"npm run test:"*|"npm run-script test"*)
            echo "full test suite ($(printf '%s' "$seg" | cut -d' ' -f1-3))"; return 0 ;;
        "npm run build"|"npm run build "*|"next build"|"next build "*)
            echo "full build ($(printf '%s' "$seg" | cut -d' ' -f1-3))"; return 0 ;;
        "vitest"|"vitest "*)
            if ! vitest_is_scoped "${seg#vitest}"; then
                echo "vitest with no file or directory argument (runs every suite)"; return 0
            fi ;;
    esac
    return 1
}

REASON=""
while IFS= read -r segment; do
    [ -z "$segment" ] && continue
    if r=$(check_segment "$segment"); then REASON="$r"; break; fi
done < <(printf '%s\n' "$CMD" | perl -pe 's/&&|\|\||;|\|/\n/g')

[ -z "$REASON" ] && exit 0

if ! is_subagent && printf '%s' "$CMD" | grep -qE '(^|[[:space:];&|])ALLOW_FULL_SUITE=1[[:space:]]'; then
    exit 0
fi

cat >&2 <<EOF
Blocked in opted-in repository: $REASON.
CI runs the full unit, browser, type, integration and build gates on every push and is the
authoritative gate; locally they cost 2-10 minutes each and hold the worktree for other agents.
Verify the change you just made, not the repo:
  CI=true npx vitest run <path/to/affected.test.ts> [more paths]
  npx tsc --noEmit -p <owning-package>/tsconfig.json
  npx eslint <changed files>
To reproduce a specific failing CI check, run only the failing file(s).
EOF
if is_subagent; then
    echo "Subagents cannot override this. If a full run is truly required, report it to the controller." >&2
else
    echo "Main thread only: prefix with ALLOW_FULL_SUITE=1 for the single pre-PR full run, and run it in the background." >&2
fi
exit 2
