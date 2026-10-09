#!/bin/bash
# PreToolUse hook (Bash): sd silently exits 0 on multi-line patterns and treats
# $name in a replacement as a capture reference. ~47 papercut entries in three
# weeks, one prod escape. Deny the forms that fail silently and point to Edit.
# Subagents get no sd at all: they have the Edit tool and cannot verify a diff.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
[ -z "$CMD" ] && exit 0
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty')

has_sd=0
while IFS= read -r seg; do
    seg=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//; s/^ctx-wire[[:space:]]+run[[:space:]]+//')
    case "$seg" in sd|sd\ *) has_sd=1 ;; esac
done < <(printf '%s\n' "$CMD" | perl -pe 's/&&|\|\||;|\|/\n/g')
[ "$has_sd" = 1 ] || exit 0

deny() { printf '%s\n' "$1" >&2; exit 2; }

[ -n "$AGENT_ID" ] && deny "Subagents do not use sd (silent no-ops, \$name eaten as capture refs). Use the Edit tool."

# shellcheck disable=SC2016  # the literal text '${' is the thing being matched
case "$CMD" in
    *'\n'*|*'${'*|*'\z'*|*'[\s\S]'*|*'(?s'*)
        deny "sd silently no-ops on multi-line patterns and treats \$name/\${...} as capture refs. Use the Edit tool for this replacement. sd is only for single-line literal edits: sd -F -- 'old' 'new' <file>, then rg to confirm." ;;
esac
case "$CMD" in
    *" -F "*|*" --fixed-strings "*) ;;
    *'\{'*|*'\('*)
        deny "Escaped braces/parens in a regex sd pattern have silently no-op'd before. Use sd -F for literals, or the Edit tool." ;;
esac
exit 0
