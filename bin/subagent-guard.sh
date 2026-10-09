#!/bin/bash
# PreToolUse hook (Bash), subagents only: deny the command classes that have
# stalled unattended runs on a permission prompt nobody answers, or that have
# destroyed work. Each denial names the allowed alternative. The main session
# is untouched: it can answer its own prompts.
#
# Classes (see docs/superpowers/plans/2026-10-09-papercuts-enforcement.md):
#   delete outside scratch, multi-line/heredoc, inline interpreter code,
#   git revert/stash/clean/reset --hard, raw git worktree add.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[ -z "$CMD" ] && exit 0
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty')
[ -z "$AGENT_ID" ] && exit 0

deny() { printf '%s\n' "$1" >&2; exit 2; }

case "$CMD" in
    *$'\n'*|*'<<'*)
        deny "No multi-line bash or heredocs in subagents: it prompts and nobody answers. Write file content with the Write tool; run one command per Bash call." ;;
esac

# Blank quoted strings so text that merely mentions a command is not matched.
STRIPPED=$(printf '%s' "$CMD" | perl -pe "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")

scratch_path() { # 0 when the operand is under a scratch root
    case "$1" in
        /tmp/*|/private/tmp/*|*/scratchpad/*|"\$TMPDIR"*|"\${TMPDIR}"*) return 0 ;;
    esac
    if [ -n "$TMPDIR" ]; then
        case "$1" in "$TMPDIR"*) return 0 ;; esac
    fi
    return 1
}

check_segment() {
    local seg="$1" tok
    seg=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
    while printf '%s' "$seg" | grep -qE '^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+'; do
        seg=$(printf '%s' "$seg" | sed -E 's/^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+//')
    done
    seg=$(printf '%s' "$seg" | sed -E 's/^ctx-wire[[:space:]]+run[[:space:]]+//; s/^(time|nice|sudo)[[:space:]]+//')
    case "$seg" in
        rm|rm\ *|rmdir\ *|unlink\ *)
            for tok in $seg; do
                case "$tok" in rm|rmdir|unlink|-*) continue ;; esac
                scratch_path "$tok" || deny "Subagents cannot delete outside scratch paths (/tmp, /private/tmp, scratchpad). Report the path to the controller; it deletes. Scratch deletes are allowed. Offending: $tok"
            done ;;
        find\ *)
            case "$seg" in *" -delete"*) deny "Subagents cannot delete (find -delete). Report the paths to the controller; it deletes." ;; esac ;;
        python\ -c*|python3\ -c*|node\ -e*|perl\ -e*)
            deny "No inline interpreter code: shell quoting corrupts it. Write a script into the scratchpad with Write and run \`python3 -I <path>\` (or node <path>)." ;;
        "git checkout --"*|"git checkout ."*|"git restore"*|"git stash"*|"git clean"*|"git reset --hard"*)
            deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
        "git worktree add"*)
            deny "Create worktrees with ~/.claude/bin/wt-create <branch> [--base <ref>] so the location and setup are right (never under /tmp)." ;;
    esac
}

while IFS= read -r segment; do
    [ -z "$segment" ] && continue
    check_segment "$segment"
done < <(printf '%s\n' "$STRIPPED" | perl -pe 's/&&|\|\||;|\|/\n/g')
exit 0
