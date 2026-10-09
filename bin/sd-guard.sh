#!/bin/bash
# PreToolUse hook (Bash): sd silently exits 0 on multi-line patterns and treats
# $name in a replacement as a capture reference. ~47 papercut entries in three
# weeks, one prod escape. Deny the forms that fail silently and point to Edit.
# Subagents get no sd at all: they have the Edit tool and cannot verify a diff.
# Only the sd segment(s) of a command are inspected: quoted text elsewhere
# (rg 'x|sd \(') and other segments (… && echo "${HOME}") are not sd's business.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)

deny() { printf '%s\n' "$1" >&2; exit 2; }

# shellcheck disable=SC2016  # the literal text '${' is the thing being matched
check_sd_segment() {
    local seg="$1" fixed=0
    [ -n "$AGENT_ID" ] && deny "Subagents do not use sd (silent no-ops, \$name eaten as capture refs). Use the Edit tool."
    case "$seg" in
        *'\n'*|*'${'*|*'\z'*|*'[\s\S]'*|*'(?s'*)
            deny "sd silently no-ops on multi-line patterns and treats \$name/\${...} as capture refs. Use the Edit tool for this replacement. sd is only for single-line literal edits: sd -F -- 'old' 'new' <file>, then rg to confirm." ;;
    esac
    case " $seg " in *" -F "*|*" --fixed-strings "*|*" -sF "*|*" -Fs "*) fixed=1 ;; esac
    [ "$fixed" = 1 ] && return 0
    case "$seg" in
        *'\{'*|*'\('*)
            deny "Escaped braces/parens in a regex sd pattern have silently no-op'd before. Use sd -F for literals, or the Edit tool." ;;
    esac
    if printf '%s' "$seg" | grep -qE '\$[A-Za-z_]'; then
        deny "In regex mode sd treats \$name in the replacement as a capture reference: an unknown name expands to nothing (silent deletion; one prod escape). Use sd -F for a literal \$name, or the Edit tool."
    fi
}

# Split on ; | & outside quotes, keeping each segment's quoted text intact.
while IFS= read -r seg; do
    seg=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//')
    while printf '%s' "$seg" | grep -qE '^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+'; do
        seg=$(printf '%s' "$seg" | sed -E 's/^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+//')
    done
    seg=$(printf '%s' "$seg" | sed -E 's/^ctx-wire[[:space:]]+run[[:space:]]+//; s/^(time|command|env)[[:space:]]+//')
    case "$seg" in sd|sd\ *) check_sd_segment "$seg" ;; esac
done < <(printf '%s' "$CMD" | perl -ne 'while (/\G((?:"[^"]*"|\x27[^\x27]*\x27|[^;|&"\x27])+|[;|&]+)/gc) { print "$1\n" unless $1 =~ /^[;|&]+$/ }')
exit 0
