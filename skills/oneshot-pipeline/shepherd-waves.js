export const meta = {
  name: 'shepherd-waves',
  description: 'Drive an open repository PR through AI-review waves: wait for the reviewer decision, classify findings, fix BLOCKER/MAJOR, comment MINOR, one push per wave, until merge-ready',
  whenToUse: 'oneshot-pipeline Phase 10 when the controller opts for the deterministic loop instead of hand-dispatching a fixer per wave',
  phases: [
    { title: 'Wait', detail: 'review-wait until the bot decides on the head or CI fails' },
    { title: 'Classify', detail: 'pr-threads --reviews, verify each claim, assign severity' },
    { title: 'Fix', detail: 'pr-shepherd: fix the wave, one push, close threads, report' },
  ],
}

// args: { pr, worktree, slug, standingDecisions?, maxWaves?, reportDir?, fixModel? }
const a = args || {}
if (!a.pr || !a.worktree) throw new Error('args.pr and args.worktree are required')
const PR = String(a.pr)
const WT = a.worktree
const SLUG = a.slug || `pr-${PR}`
const MAX_WAVES = a.maxWaves || 6
const REPORT_DIR = a.reportDir || `/tmp/${SLUG}`
const FIX_MODEL = a.fixModel || 'fable'
const STANDING = a.standingDecisions || '(none given — park spec conflicts, do not decide them)'

const CONTRACT = `Finding contract. A finding has four parts in this order: severity, claim (one sentence), failure scenario (concrete input or state -> wrong output, crash, or violated invariant), fix sketch. Severity is DERIVED from the scenario: BLOCKER = security, data loss, deploy-safety rule, or spec requirement not met; MAJOR = correctness bug, missing test for a stated invariant, coupled surface left out; MINOR = anything without a concrete failure scenario (style, naming, hypothetical future need, "consider", "could be cleaner"). A finding that arrives without a failure scenario is MINOR regardless of the label the reviewer put on it.`

const CMD_RULES = `Command rules: every Bash call starts with "cd ${WT}; " (that semicolon form is the one allowed compound; do not rely on a persisted cwd). No multi-line Bash, no && chains, no rm or any destructive command (mv -f, git clean, git checkout --, clearing tsconfig.tsbuildinfo) — report the need instead. Explicit timeout on every tsc/vitest/eslint call. Never start a server, emulator, dev process or --watch. Never run npm test, npm run test:*, npm run build, or a path-less vitest (a hook rejects them; scoped verify-diff only). Never poll CI and never call gh pr checks --watch or gh run watch.`

const WAIT_SCHEMA = {
  type: 'object',
  properties: {
    state: { type: 'string', enum: ['review_done', 'ci_failed', 'pending'] },
    head: { type: 'string' },
    decision: { type: 'string' },
    approval: { type: 'string', enum: ['approved', 'withheld', 'unknown'] },
    skipReason: { type: 'string' },
    sizeGate: { type: 'boolean' },
    unresolvedThreads: { type: 'string' },
    reviewDecision: { type: 'string' },
    failedChecks: { type: 'array', items: { type: 'string' } },
    lastLine: { type: 'string' },
  },
  required: ['state', 'head', 'approval', 'sizeGate', 'lastLine'],
}

const RERUN_SCHEMA = {
  type: 'object',
  properties: { rerunRunIds: { type: 'array', items: { type: 'string' } }, note: { type: 'string' } },
  required: ['rerunRunIds'],
}

const CLASSIFY_SCHEMA = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          kind: { type: 'string', enum: ['thread', 'review_body', 'ci_failure'] },
          commentId: { type: 'string' },
          threadId: { type: 'string' },
          path: { type: 'string' },
          line: { type: 'integer' },
          severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
          claim: { type: 'string' },
          scenario: { type: 'string' },
          verified: { type: 'boolean' },
          rationale: { type: 'string' },
        },
        required: ['kind', 'severity', 'claim', 'verified'],
      },
    },
    unresolvedThreads: { type: 'integer' },
    parkedStillOpen: { type: 'integer' },
    reviewBodyFindings: { type: 'integer' },
    waveFile: { type: 'string' },
    headerLine: { type: 'string' },
  },
  required: ['items', 'unresolvedThreads', 'parkedStillOpen', 'waveFile', 'headerLine'],
}

const FIX_SCHEMA = {
  type: 'object',
  properties: {
    pushedSha: { type: 'string' },
    fixed: { type: 'array', items: { type: 'string' } },
    repliedClosed: { type: 'array', items: { type: 'string' } },
    reopenedAfterAudit: { type: 'array', items: { type: 'string' } },
    parked: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, reason: { type: 'string' } }, required: ['id', 'reason'] } },
    closedConfirmed: { type: 'integer' },
    commits: { type: 'integer' },
    newGuards: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'string' },
    reportFile: { type: 'string' },
  },
  required: ['fixed', 'repliedClosed', 'parked', 'closedConfirmed', 'reportFile'],
}

function waitPrompt(w, attempt) {
  return `You are a mechanical helper. First Bash call: mkdir -p ${REPORT_DIR} (this directory receives the wave files). Second Bash call, with a 300000 ms timeout:
cd ${WT}; ~/.claude/bin/review-wait ${PR} --max 240
Then return the result as structured output. The script's LAST line is the verdict line; earlier lines are progress and context and are ignored. Put that last line verbatim in lastLine and map it:
- "REVIEW DONE head=<sha> decision=<X> approval=<approved|withheld> skipReason=<Y> size_gate=<0|1> unresolved_threads=<N> reviewDecision=<Z>" -> state review_done; copy each field (sizeGate true iff size_gate=1; unresolvedThreads is the string after unresolved_threads=).
- "FAILED head=<sha>:" followed by indented check names -> state ci_failed, those names in failedChecks, approval unknown, sizeGate false.
- "TIMEOUT ..." -> state pending, approval unknown, sizeGate false.
- The Bash call was killed, timed out, or its last line is none of the above -> state pending, approval unknown, sizeGate false, lastLine = the last line you saw. Never guess review_done.
Do nothing else. (wave ${w}, attempt ${attempt})`
}

function rerunPrompt(head, failed) {
  return `You are a mechanical helper. Head ${head} has failed checks ${JSON.stringify(failed)}. Run exactly one Bash call with a 300000 ms timeout:
cd ${WT}; ~/.claude/bin/rerun-failed ${PR} ${head}
(The script reruns the failed jobs and waits on its own for GitHub to reset the check state; do not add sleeps or extra polls.) Map its LAST line "RERUN DONE reruns=<ids> reset=<confirmed|stale|nothing-to-rerun>": the comma-separated ids into rerunRunIds (empty list if none) and the reset value into note. Do nothing else; do not diagnose.`
}

function auditWaitPrompt(w, closedIds) {
  return `You are a mechanical helper. The author just resolved the threads with first-comment ids ${JSON.stringify(closedIds)} on PR #${PR}, each with a rationale reply, and no push followed. The reviewer bot audits a resolved thread only inside a review run, and a run starts only on a push or an /ai-review comment. So trigger one first. Run exactly two Bash calls, in order:
1. cd ${WT}; gh pr comment ${PR} --body "/ai-review"
2. With a 300000 ms timeout: cd ${WT}; ~/.claude/bin/audit-wait ${PR} ${closedIds.join(' ')} --max 240
(audit-wait polls on its own and prints only when the state changes. Do not add sleeps or extra polls, and do not post /ai-review again.) Map the LAST line of call 2 "AUDIT DONE audited=<ids> reopened=<ids> pending=<ids>" into the three lists (comma-separated, empty means empty list; an entry like "<id>:not-found" goes in pending as-is). If the call was killed or the last line is not of that form, return all ids as pending. Do nothing else.`
}

const AUDIT_SCHEMA = {
  type: 'object',
  properties: {
    audited: { type: 'array', items: { type: 'string' } },
    reopened: { type: 'array', items: { type: 'string' } },
    pending: { type: 'array', items: { type: 'string' } },
  },
  required: ['audited', 'reopened', 'pending'],
}

function classifyPrompt(w, wait, parkedIds) {
  const ci = wait.state === 'ci_failed'
    ? `CI FAILED on head ${wait.head} AFTER one rerun of the failed jobs, so this is not a flake: checks ${JSON.stringify(wait.failedChecks || [])}. For each failed check run "cd ${WT}; gh run list --commit ${wait.head} --json databaseId,name,conclusion --limit 20" then "cd ${WT}; gh run view <id> --log-failed" (300000 ms timeout) and extract the failing test/file and the first error lines. Each failed check becomes one item of kind ci_failure; derive its severity from the contract like any other finding (a real failing assertion on changed code is MAJOR; an infrastructure error such as a capacity or runner message is MINOR with the log line as rationale).`
    : `Reviewer decided on head ${wait.head}: decision=${wait.decision} approval=${wait.approval} skipReason=${wait.skipReason}.`
  const parked = parkedIds.length ? `First-comment ids already parked or reopened in earlier waves — EXCLUDE them from items entirely, do not re-verify them: ${JSON.stringify(parkedIds)}. Report in parkedStillOpen how many of these ids appear among the UNRESOLVED thread sections of the pr-threads output (their "comment <id>" header numbers).` : 'No ids are parked yet; parkedStillOpen is 0.'
  return `You are a read-only triage agent for PR #${PR} in worktree ${WT}. Do not edit any file, do not commit, do not push.
${ci}
${parked}
1. Run (one Bash call, 300000 ms timeout): cd ${WT}; ~/.claude/bin/pr-threads ${PR} --reviews > ${REPORT_DIR}/wave-${w}.md — then Read that file. Its first line is the header "# PR #${PR} (...): N unresolved of M review threads" — copy it verbatim into headerLine. If the file is missing, empty, or has no such header, return headerLine "MISSING" and an empty items list; never infer zero findings from a missing file.
2. For EVERY unresolved thread and every review-body finding: open the anchored code, decide whether the failure scenario is real in the current code (verified true/false), and assign severity under this contract:
${CONTRACT}
The bot's own <!-- ai-review:sev=... --> marker is a cross-check, not the answer. A review BODY summarises the inline threads: it is an item (kind review_body) only for a defect that NO thread on this head anchors — otherwise it is a duplicate and is not listed. A "Pass" or approval body is never an item. A thread with no line number is still an item (path only).
3. Append to ${REPORT_DIR}/wave-${w}.md a section "## Triage" with one line per item: severity, commentId (or review id / check name), path:line, claim, verified, one-line rationale.
4. Return structured output listing every item, unresolvedThreads (the N from the header), parkedStillOpen, reviewBodyFindings (items of kind review_body only), headerLine, and waveFile = ${REPORT_DIR}/wave-${w}.md.
${CMD_RULES}`
}

function fixPrompt(w, wait, cls, actionable, minors, parkedIds) {
  return `Fix wave ${w} of PR #${PR}. Worktree: ${WT}. Branch head at wave start: ${wait.head}.
Wave file (read it first, fully): ${cls.waveFile}
Standing decisions (pre-authorized, apply directly): ${STANDING}
Already parked / reopened in earlier waves (first-comment ids) — not yours to touch, do not close, do not fix, do not reply: ${JSON.stringify(parkedIds)}
Every id you report (fixed, repliedClosed, parked.id, reopenedAfterAudit) is the thread's FIRST-COMMENT id (the "comment <id>" number in the wave file header), one per thread, never the thread node id.
${CONTRACT}

Items to FIX (BLOCKER/MAJOR — code change at the anchor, fix the class, TDD for behavioural bugs, verify-diff once per item, commit per item):
${JSON.stringify(actionable, null, 1)}

Items to REPLY-CLOSE (MINOR — one-line rationale reply + pr-thread-close, NO source edit; the bot audits the reply once and accepts a sound rationale. A thread that was already replied-closed in an earlier wave and is open again was REOPENED by that audit: do not close it again, list it in reopenedAfterAudit and in the report as parked):
${JSON.stringify(minors, null, 1)}

Then: git fetch origin, fast-forward if origin moved. Before pushing, measure the PR size budget on the base-relative diff: git diff --shortstat for files and lines, git diff | wc -c for bytes. If the PR would exceed 4,000 changed lines, 75 files or 200 KB and the standing decisions record no size_override, do NOT push: set pushedSha to "none" and report "BLOCKED: size <files>/<lines>/<KB>". Otherwise ONE push if any commit was made (with zero FIX items and zero commits there is nothing to push — say so in pushedSha as "none"). After the push, pr-thread-close every FIX thread item with the fixing SHA. Review-body and ci_failure items have no thread: name the commit in the report.
Write the report to ${REPORT_DIR}/wave-${w}-report.md (per item: your severity, disposition fixed/replied-closed/parked/reopened-after-audit, SHA, close confirmed; pushed SHA; standing decisions applied; any new refusal/guard you added and whose request it now denies; anything blocked with the exact question). Return the same as structured output, then STOP. Do not poll CI, do not wait for the reviewer, do not look for new threads.
${CMD_RULES}`
}

const waves = []
const parkedIds = []          // carried across waves: parked or reopened-after-audit thread ids, never re-triaged or re-closed
const rerunHeads = []         // heads whose failed jobs were already rerun once
let head = ''
for (let w = 1; w <= MAX_WAVES; w++) {
  let wait = null
  for (let attempt = 1; attempt <= 6; attempt++) {
    wait = await agent(waitPrompt(w, attempt), { label: `wait:w${w}#${attempt}`, phase: 'Wait', schema: WAIT_SCHEMA, model: 'haiku', effort: 'low' })
    if (wait && wait.state === 'ci_failed' && !rerunHeads.includes(wait.head)) {
      // One rerun per head before a failure becomes a finding: a flake costs a rerun, never a commit.
      rerunHeads.push(wait.head)
      log(`wave ${w}: checks failed on ${wait.head.slice(0, 8)} — rerunning failed jobs once`)
      await agent(rerunPrompt(wait.head, wait.failedChecks || []), { label: `rerun:w${w}`, phase: 'Wait', schema: RERUN_SCHEMA, model: 'haiku', effort: 'low' })
      wait = null
      continue
    }
    if (wait && wait.state !== 'pending') break
    log(`wave ${w}: reviewer not decided yet (attempt ${attempt}/6)`)
  }
  if (!wait || wait.state === 'pending') return { status: 'stalled_waiting', pr: PR, head, waves }
  head = wait.head
  if (wait.state === 'review_done' && wait.sizeGate === true) {
    // Nothing was reviewed. Terminal whether or not old threads linger: the owner decides (deep request or admin merge).
    return { status: 'size_gate_withheld', pr: PR, head, unresolved: wait.unresolvedThreads, waves, note: 'approval withheld with skipReason=pr_too_large: size gate, terminal — ping the owner, do not re-request review' }
  }

  const cls = await agent(classifyPrompt(w, wait, parkedIds), { label: `classify:w${w}`, phase: 'Classify', schema: CLASSIFY_SCHEMA, model: 'sonnet' })
  if (!cls) return { status: 'classify_failed', pr: PR, head, waves }
  // A missing wave file must never read as zero findings (the an earlier review false merge-ready).
  if (!/^# PR #\d+ .*: \d+ unresolved of \d+ review threads/.test(cls.headerLine || '')) {
    return { status: 'classify_failed', pr: PR, head, detail: `pr-threads header not read: ${cls.headerLine}`, waves }
  }
  // parkedIds holds first-comment ids only (one per thread), so its length is a thread count.
  const items = (cls.items || []).filter(i => !parkedIds.includes(String(i.commentId || '')))
  const blockers = items.filter(i => i.severity === 'BLOCKER')
  const majors = items.filter(i => i.severity === 'MAJOR')
  const actionable = items.filter(i => i.severity === 'BLOCKER' || i.severity === 'MAJOR')
  const minors = items.filter(i => i.severity === 'MINOR')
  log(`wave ${w}: ${items.length} items — ${blockers.length} BLOCKER, ${majors.length} MAJOR, ${minors.length} MINOR; review-body ${cls.reviewBodyFindings || 0}; unresolved ${cls.unresolvedThreads}; parked so far ${parkedIds.length}`)

  if (items.length === 0 && wait.state === 'review_done') {
    // Merge-ready needs all three: nothing to fix, GitHub reports zero unresolved threads, and the decision is APPROVED.
    if (cls.unresolvedThreads === 0 && wait.decision === 'APPROVED' && wait.reviewDecision === 'APPROVED') return { status: 'merge_ready', pr: PR, head, decision: wait.decision, waves }
    // Compare against parked threads that are STILL open in this wave's list, not the cumulative array.
    if (parkedIds.length > 0 && cls.parkedStillOpen > 0 && cls.unresolvedThreads <= cls.parkedStillOpen) return { status: 'parked_only', pr: PR, head, parked: parkedIds, decision: wait.decision, waves, note: 'every remaining open thread is parked — owner decision' }
    if (cls.unresolvedThreads > 0) return { status: 'threads_open_but_no_items', pr: PR, head, unresolved: cls.unresolvedThreads, waves }
    return { status: 'no_findings_not_approved', pr: PR, head, decision: wait.decision, reviewDecision: wait.reviewDecision, approval: wait.approval, skipReason: wait.skipReason, waves, note: 'a stale CHANGES_REQUESTED review from an earlier head may need dismissing — controller checks gh pr view --json reviews' }
  }

  const fix = await agent(fixPrompt(w, wait, cls, actionable, minors, parkedIds), { label: `fix:w${w}`, phase: 'Fix', schema: FIX_SCHEMA, model: FIX_MODEL, agentType: 'pr-shepherd' })
  if (fix) {
    for (const p of fix.parked || []) if (p.id && !parkedIds.includes(String(p.id))) parkedIds.push(String(p.id))
    for (const r of fix.reopenedAfterAudit || []) if (r && !parkedIds.includes(String(r))) parkedIds.push(String(r))
  }
  waves.push({
    wave: w, head, ci: wait.state, items: items.length,
    blocker: blockers.length,
    major: majors.length,
    minor: minors.length,
    fixed: fix ? fix.fixed.length : 0, repliedClosed: fix ? fix.repliedClosed.length : 0, parked: fix ? fix.parked.length : 0,
    reopenedAfterAudit: fix && fix.reopenedAfterAudit ? fix.reopenedAfterAudit.length : 0,
    closedConfirmed: fix ? fix.closedConfirmed : 0, pushedSha: fix ? fix.pushedSha : null, newGuards: fix ? fix.newGuards : null,
    reportFile: fix ? fix.reportFile : null,
  })
  if (!fix) return { status: 'fixer_died', pr: PR, head, waves }
  if (fix.blocked) return { status: 'blocked', pr: PR, head, detail: fix.blocked, waves }
  if (fix.reopenedAfterAudit && fix.reopenedAfterAudit.length > 0) return { status: 'reopened_after_audit', pr: PR, head, threads: fix.reopenedAfterAudit, parked: parkedIds, waves }
  if (actionable.length > 0 && (!fix.pushedSha || fix.pushedSha === 'none')) {
    // Every actionable item parked and nothing committed is a decision for the owner, not a fixer fault.
    if (fix.fixed.length === 0 && (fix.parked || []).length >= actionable.length) return { status: 'parked_only', pr: PR, head, parked: parkedIds, waves }
    return { status: 'fixer_no_push', pr: PR, head, waves }
  }
  if (actionable.length === 0) {
    // Only MINOR replies this wave: no push happened, so nothing re-triggers the bot, and it audits an author-resolved
    // thread only inside a review run. The audit helper posts /ai-review, then waits for every replied-closed thread.
    const closed = (fix.repliedClosed || []).map(String)
    if (closed.length > 0) {
      const audit = await agent(auditWaitPrompt(w, closed), { label: `audit:w${w}`, phase: 'Wait', schema: AUDIT_SCHEMA, model: 'haiku', effort: 'low' })
      // Reopened first, and parked unconditionally: a reopened thread must never be re-closed by a later wave (fixer rule 11).
      if (audit && audit.reopened.length > 0) {
        for (const r of audit.reopened) if (!parkedIds.includes(String(r))) parkedIds.push(String(r))
        return { status: 'reopened_after_audit', pr: PR, head, threads: audit.reopened, pending: audit.pending, parked: parkedIds, waves }
      }
      if (!audit || audit.pending.length > 0) return { status: 'audit_pending', pr: PR, head, pending: audit ? audit.pending : closed, parked: parkedIds, waves, note: 'call audit-wait again, or the bot audit is slower than 7 min' }
    }
    const after = await agent(waitPrompt(w, 'post-audit'), { label: `recheck:w${w}`, phase: 'Wait', schema: WAIT_SCHEMA, model: 'haiku', effort: 'low' })
    const ok = after && after.state === 'review_done' && after.decision === 'APPROVED' && after.reviewDecision === 'APPROVED' && after.unresolvedThreads === '0'
    return { status: ok ? 'merge_ready' : 'minor_only_wave_not_approved', pr: PR, head, decision: after ? after.decision : null, reviewDecision: after ? after.reviewDecision : null, unresolved: after ? after.unresolvedThreads : null, parked: parkedIds, waves }
  }
}
return { status: 'max_waves', pr: PR, head, parked: parkedIds, waves }
