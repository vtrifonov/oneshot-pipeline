### 10. Shepherd + babysit

The controller owns the loop. A fresh pr-shepherd handles one prepared wave and stops; it never polls CI or waits for more findings. Use native APIs unless the adapter confirms the optional helper protocol.

#### 10a. Controller-driven (default)
1. Wait for current-head CI/review evidence using native APIs. For a configured marker-compatible bot, run review-wait with AI_REVIEW_BOT and a bounded timeout. ci-wait alone proves check status, not a reviewer's approval.
2. Run pr-threads <pr> --reviews from the worktree into the wave file. Include review-body findings and relevant failed-check evidence. Missing/empty reports are failures, not zero findings.
3. Triage each item under the Finding contract against anchored code. Append dispositions and evidence to the ledger. Size skips/refusals block completion even with zero findings.
4. Dispatch fresh pr-shepherd with worktree, PR, standing decisions, Finding contract, wave file and FIX/REPLY-CLOSE lists. FIX means accepted BLOCKER/MAJOR: scoped verification and commits. MINOR gets a rationale reply and close where the review policy allows it.
5. Verify its report, pushed head and confirmed thread states. If the adapter requires post-close audits, trigger the configured review when no push did so, then use audit-wait. Do not assume a close starts an audit.
6. Reopened/parked threads need owner resolution; never repeat the same close disposition. Regenerate handover state from GitHub. Repeat only for new actionable findings.

Done requires all required checks/approvals for the current head, zero unresolved required threads or material findings, and no pending required audit. No broad exclusion of human review gates.

#### 10b. Optional Workflow loop
Use shepherd-waves.js only with a compatible Workflow runtime and the configured marker-compatible bot. Confirm explicit opt-in required by the runtime. It applies the same triage, wave and audit contracts with a bounded wave limit.
Before resuming, verify no live writer owns the worktree and inspect worktree state; the script cannot establish this itself. Restart the runtime after installing a new agent definition.

#### Liveness and limits
- Dispatch the first fixer after the first actionable wave exists. The controller owns waiting before that point.
- Confirm any prior fixer is stopped before dispatch; never test/build concurrently with a writer in the same worktree.
- Use native status/results and bounded watchdogs. Quiet output alone does not establish liveness.
- Keep blocking operations within 300 seconds; longer work uses bounded asynchronous continuation.
- Before each push remeasure the size budget. An unapproved over-budget wave commits locally, reports BLOCKED: size, and waits for the controller to obtain user approval.
- Resolve routine questions through standing decisions or expert consultation; only critical non-resolvable decisions go to the user.
