#!/bin/bash
# PreToolUse hook (Bash), subagents only: deny the command classes that have
# stalled unattended runs on a permission prompt nobody answers, or that have
# destroyed work. Each denial names the allowed alternative. The main session
# is untouched: it can answer its own prompts.
#
# Classes (see docs/superpowers/plans/2026-10-09-papercuts-enforcement.md):
#   delete outside scratch, any recursive delete (the ask rule prompts even in
#   scratch), multi-line/heredoc, inline interpreter code (python -c, bash -c),
#   git revert/stash/clean/reset --hard, raw git worktree add.
# git global options (-C, -c, --git-dir, ...) and wrappers (ctx-wire run,
# timeout, env, command, nohup, xargs, ...) are stripped before matching.
# Fails open: no command, no agent_id, or unparsable input → exit 0.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
[ -z "$AGENT_ID" ] && exit 0

set -f  # never glob-expand operands in the hook's own cwd

deny() { printf '%s\n' "$1" >&2; exit 2; }

case "$CMD" in
    *$'\n'*|*'<<'*)
        deny "No multi-line bash or heredocs in subagents: it prompts and nobody answers. Write file content with the Write tool; run one command per Bash call." ;;
esac

# Inside quoted strings, replace separators and shell metacharacters with '_'
# so `rg "rm -rf"` is text, not a command, while quoted operands keep their path.
# One left-to-right pass over both quote styles, so an apostrophe inside "…" (or a
# double quote inside '…') cannot unpair the other style and hide a later command.
STRIPPED=$(printf '%s' "$CMD" | perl -pe 's/"([^"]*)"|\x27([^\x27]*)\x27/ defined $1 ? "\"" . ($1 =~ s{[;|&\s\$()`{}\x27]}{_}gr) . "\"" : "\x27" . ($2 =~ s{[;|&\s\$()`{}"]}{_}gr) . "\x27" /ge')

scratch_path() { # 0 when the operand is under a scratch root
    case "$1" in
        /tmp/*|/private/tmp/*|*/scratchpad/*|"\$TMPDIR"*|"\${TMPDIR}"*) return 0 ;;
    esac
    if [ -n "$TMPDIR" ]; then
        case "$1" in "$TMPDIR"*) return 0 ;; esac
    fi
    return 1
}

unquote() { printf '%s' "$1" | tr -d "'\""; }

strip_wrappers() { # env assignments, ctx-wire run, timeout N, command, exec, env, nohup, time, nice, sudo, xargs, leading { or !
    local seg="$1" prev=""
    while [ "$seg" != "$prev" ]; do
        prev="$seg"
        seg=$(printf '%s' "$seg" | sed -E '
            s/^[[:space:]]+//
            s/^[{!][[:space:]]+//
            s/^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+//
            s/^ctx-wire[[:space:]]+run[[:space:]]+//
            s/^(time|nice|sudo|command|exec|nohup|env)[[:space:]]+//
            s/^timeout([[:space:]]+-[^[:space:]]+)*[[:space:]]+[0-9]+[smhd]?[[:space:]]+//
            s/^xargs([[:space:]]+-[^[:space:]]+)*[[:space:]]+/xargs /
            s#^(\\|/[^[:space:]]*/)(rm|rmdir|unlink|find|git|python[0-9.]*|node|perl|bash|sh|zsh)([[:space:]]|$)#\2\3#
        ')
    done
    printf '%s' "$seg"
}

strip_git_globals() { # drop -C <p>, -c <k=v>, --git-dir=…, --work-tree=…, --no-pager, -P after "git"
    local seg="$1" prev=""
    while [ "$seg" != "$prev" ]; do
        prev="$seg"
        seg=$(printf '%s' "$seg" | sed -E '
            s/^git[[:space:]]+(-C|-c)[[:space:]]+[^[:space:]]+[[:space:]]+/git /
            s/^git[[:space:]]+(--git-dir=[^[:space:]]+|--work-tree=[^[:space:]]+|--no-pager|-P)[[:space:]]+/git /
        ')
    done
    printf '%s' "$seg"
}

check_segment() {
    local seg tok rest
    seg=$(strip_wrappers "$1")
    case "$seg" in
        xargs\ rm|xargs\ rm\ *|xargs\ rmdir\ *|xargs\ unlink\ *)
            deny "Subagents cannot pipe into rm (operands unknown). Report the paths to the controller; it deletes." ;;
        rm|rm\ *|rmdir|rmdir\ *|unlink\ *)
            for tok in $seg; do
                case "$tok" in
                    rm|rmdir|unlink|--) continue ;;
                    --recursive|-r*|-R*|-[!-]*r*|-[!-]*R*)
                        deny "Recursive deletes prompt even in scratch (the rm -r ask rule), and nobody answers a subagent's prompt. Leave the directory (scratch is disposable) or report it to the controller. Offending: $tok" ;;
                    -*) continue ;;
                esac
                tok=$(unquote "$tok")
                scratch_path "$tok" || deny "Subagents cannot delete outside scratch paths (/tmp, /private/tmp, scratchpad). Report the path to the controller; it deletes. Single-file scratch deletes are allowed. Offending: $tok"
            done ;;
        find\ *)
            case "$seg" in
                *" -delete"*|*" -exec rm"*|*" -execdir rm"*|*" -ok rm"*)
                    deny "Subagents cannot delete (find -delete / -exec rm). Report the paths to the controller; it deletes." ;;
            esac ;;
        git\ *)
            seg=$(strip_git_globals "$seg")
            rest=${seg#git }
            case "$rest" in
                checkout\ *)
                    case " $rest " in
                        *" -- "*|*" . "*) deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
                    esac ;;
                restore|restore\ *|clean|clean\ *)
                    deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
                stash|stash\ *)
                    case "$rest" in stash\ list*|stash\ show*) ;; *)
                        deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
                    esac ;;
                reset\ *)
                    case " $rest " in *" --hard "*)
                        deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
                    esac ;;
                switch\ *)
                    case " $rest " in *" --discard-changes "*|*" -f "*|*" --force "*)
                        deny "Subagents never revert with git (checkout --, restore, stash, clean, reset --hard). Undo with the Edit tool, or report to the controller." ;;
                    esac ;;
                worktree\ add*)
                    deny "Create worktrees with ~/.claude/bin/wt-create <branch> [--base <ref>] so the location and setup are right (never under /tmp)." ;;
            esac ;;
    esac
    if printf '%s' "$seg" | grep -qE '^(python[0-9.]*([[:space:]]+-[A-Za-z]+)*[[:space:]]+-c|node[[:space:]]+-[ep]|perl[[:space:]]+-[a-zA-Z]*e|(bash|sh|zsh)([[:space:]]+-[A-Za-z]+)*[[:space:]]+-c)([[:space:]]|$)'; then
        deny "No inline interpreter code (python -c, node -e, perl -e, bash -c): shell quoting corrupts it. Write a script into the scratchpad with Write and run \`python3 -I <path>\` (or node <path>, bash <path>)."
    fi
}

# Split on command separators, substitutions and compound keywords, then check each piece.
while IFS= read -r segment; do
    [ -z "$segment" ] && continue
    check_segment "$segment"
done < <(printf '%s\n' "$STRIPPED" | perl -pe 's/&&|\|\||;|\||\$\(|`|\(|\)|(^|\s)(then|do|else|elif|fi|done)(\s|$)/\n/g')
exit 0
