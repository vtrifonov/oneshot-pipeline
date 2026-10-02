### 7. Code review
- Lite: fresh independent correctness/testing reviewer. Full: that reviewer plus a separate security/architecture reviewer for the named risks. Apply available review skills or brief agents directly; use the Finding contract and separate findings files.
- Validate premises and deduplicate. Fix accepted BLOCKER/MAJOR findings, with meaningful regression tests for behavioral bugs. MINOR follows the contract.
- Fix sibling call sites and coupled surfaces sharing the same defect; centralize a shared invariant where appropriate.

### 8. Pre-push gates (mirror CI)
- Run the repository adapter's actual CI gates from the controller. Inspect CI configuration for every owning package and independent type/build/browser-test scope; do not assume a root command covers them.
- Scoped checks during implementation; full suite/build here. Run each gate once initially, rerunning only after relevant changes, failures or unresolved evidence.
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
