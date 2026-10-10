### 7. Code review
- Lite: fresh independent correctness/testing reviewer. Full: that reviewer plus a separate security/architecture reviewer for the named risks. Apply available review skills or brief agents directly; use the Finding contract and separate findings files.
- **Frontend design on:** the correctness/testing reviewer also checks the UI tasks against the spec's UI design section and its quality floor. When a browser tool is available, it renders the changed screens and attaches screenshots to its findings. A taste disagreement without a concrete broken state, flow or accessibility failure is MINOR.
- Validate premises and deduplicate. Fix accepted BLOCKER/MAJOR findings, with meaningful regression tests for behavioral bugs. MINOR follows the contract.
- Fix sibling call sites and coupled surfaces sharing the same defect; centralize a shared invariant where appropriate.

### 8. Pre-push gates (mirror CI)
- Run the repository adapter's actual CI gates from the controller. Inspect CI configuration for every owning package and independent type/build/browser-test scope; do not assume a root command covers them.
- Scoped checks during implementation; full suite/build here. Run each gate once initially, rerunning only after relevant changes, failures or unresolved evidence.
- Run `~/.claude/bin/derived-check --base <base>` before the gates: lockfiles changed since base need an install, duplicate migration timestamps need a rename and a cold test stack, tracked generated files need regeneration. Then run `~/.claude/bin/text-guards --base <base> --cmd` and run every suite it lists: guards that read changed files as text (by path, or by scanning an enclosing directory) are invisible to import-graph sweeps and otherwise fail only in CI. Run its `direct` suites after every fix round too; a comment-only edit can trip them. Run cspell (and any per-package lint) from inside each package that has its own config, not only from the root.
- If the optional scoped-verification hook is registered and the repository opted in, the controller may prefix the pre-PR full run with ALLOW_FULL_SUITE=1. Subagents use scoped checks. Keep each blocking operation within 300 seconds and use bounded background continuation for longer gates.
- Re-evaluate all lane triggers mechanically against the committed base-relative diff. New matches upgrade the lane and add missing review coverage before push.
- Sweep applicable repository rules: source-size limits, UI accessibility, deployment path filters, access-control invariants, documentation and rollout requirements. Resolve exact rules from the target repository.
- Measure PR size on the same committed diff, including generated files and lockfiles: git diff --shortstat <base>...HEAD and git diff <base>...HEAD | wc -c. Over 4,000 changed lines, 75 files or 200 KB without a recorded override requires user approval of the measured size and proposed split before push. Record size and any override in timeline.txt.
- Fix required gate failures before pushing.

### 9. PR
- Sync with the adapter's latest remote base. Rebase before first push; after publication merge the base in when needed, never amend or force-push.
- Push and create the one authorized PR against the resolved base. Body includes spec/plan links, lane and matching triggers, mode, impl_mode, validation and Parked (MINOR) rationale. Record pr_open in timeline.txt.
- Diagrams use Mermaid fences. Check the actual PR body before create/edit.
- Batch pushes, never delay triaged work: implement, test and commit each accepted fix immediately, then push one coherent wave.
- A flaky check gets a bounded rerun through rerun-failed, never a source commit to retrigger CI. Do not treat a failed rerun as success.
- Opening the PR is not completion. Verify required CI and current-head reviews before claiming merge readiness.
- A review refusal or size skip is not a clean review. Follow the configured reviewer protocol and size-override contract; do not invent a deep-review command for an unknown bot.
