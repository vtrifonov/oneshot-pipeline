# Repository and runtime adapter

Read at Phase 0. Resolve settings from explicit user instructions, repository AGENTS.md/CLAUDE.md, and actual repository configuration. Record them in a run-context file before dispatch. Never assume another repository's layout or policies.

| Setting | Resolution |
|---|---|
| Repository, base branch, worktree root | Inspect target repository and remote HEAD. Follow documented conventions; otherwise use a sibling worktree named for the task. |
| Source/package roots and exclusions | Inspect tracked paths and workspace configuration, including generated/vendor exclusions. |
| Domain risks | Read applicable security, persistence, compatibility and deployment rules. |
| Verification gates | Derive exact commands from CI. Include independent packages, type checks, browser tests and build gates where applicable. |
| Review completion | Required checks, reviewers and approvals for the current head. Never silently exclude a required gate. |
| Review scopes | Lite: one independent correctness/testing review. Full: that review plus an independent security/architecture review focused on named risks. Use available review skills or brief fresh agents directly with the Finding contract. |
| Runtime tools/models | Use available tools and model mappings; otherwise inherit. Use native agent status/results rather than assuming transcript locations. |
| Durable artifacts | Default: docs/superpowers/reviews/<slug>/ in the worktree; ledger and per-pass metrics contain summaries and source references, never private transcripts or customer data. |
| Scoped verification | verify-diff supports TypeScript/JavaScript projects using tsc, eslint and vitest. Other toolchains use equivalent scoped commands from CI. |
| GitHub integration | Resolve owner/name from the current checkout or --repo. ci-wait, pr-threads and pr-thread-close work through authenticated gh. |
| Optional bot protocol | review-wait requires AI_REVIEW_BOT and a bot that emits ai-review:approval reviewed=<sha>. audit-wait requires ai-review:author-resolve-audit replies. Use native review APIs when these protocols are absent. |
| Optional hook | block-full-suite.sh applies only to repositories opting in with a .scoped-verification marker at their root. Registration is per user. |

Standing questions, where applicable:
1. Does every access-granting write revalidate its gating conditions in the appropriate transaction?
2. Which callers, public interfaces, documentation, infrastructure and workflows are coupled to the change?
3. Do meaningful tests cover stateful/concurrent invariants and adversarial inputs?
4. Are scope boundaries and follow-up work explicit?

Phase 10b's Workflow script needs a compatible runtime and the optional bot protocol. Otherwise use controller-driven Phase 10 with native CI/review APIs. Tool availability never grants authority to send messages or merge.

## Shared contract

Invocation authorizes the one branch push/PR described by this pipeline. Never merge without separate authorization. Setup does not imply deploy authority. Keep blocking command/wait calls at most 300 seconds; use bounded asynchronous continuation for longer work. Record unavailable required gates as blocked, never as passed.
