---
name: split-large-pr
description: Split a large pull request or branch into smaller, independently testable stacked PRs that fit the configured review budget.
---

# Split a large PR

Resolve repository base branch, worktree conventions, CI commands and review
policy from repository documentation and configuration. Never assume a sibling
shared-tools checkout or a specific build system.

## 1. Measure and choose boundaries

Default review budget is 75 files, 4,000 changed lines and 200 KB of diff;
use a stricter repository limit when configured. Include generated files and
lockfiles. Measure base-relative files, additions/deletions and bytes from git,
not an API result with a file-count cap. Allow headroom for review fixes.

Cut by final file state and dependency layers, not commit ranges. Order shared
contracts/utilities before consumers; keep signature changes with their callers.
Every PR must compile and pass meaningful verification on its own.

## 2. Build in an isolated worktree

Create the worktree where repository conventions permit. Resolve any shared
build tooling from the actual project configuration and check its revision.
One implementation writer owns the worktree.

Create each branch from the preceding part, starting at the resolved base. Copy
only the explicitly assigned files from the source branch's final state; do not
copy whole directories or accidentally replace dependency manifests.
Resolve intermediate compile failures by moving coupled files together.
Only add a minimal compatibility bridge when layering cannot avoid it; document
the bridge in the PR body.

## 3. Verify each part and the final stack

Run relevant local gates per part and the complete required suite on the final
stack. Test changed public behavior against unchanged existing tests where
applicable. Re-measure each part against its own base.
Compare the stack tip with the source branch; investigate every remaining
difference, including manifests and lockfiles. Never exclude them silently.

## 4. Publish and shepherd

User authorization must cover the proposed stack, its branches and PRs.
Push each branch and open the first PR against the resolved base, then each
successive PR against the preceding branch. Link all parts and mark the current
part in each body. If replacing an existing PR, explain the stack before closing
it and keep its branch until the stack is complete.

Review from the bottom up. Verify current-head required checks and reviews;
a small diff is not proof that its findings are complete. Fix accepted material
findings and explain parked items. Follow the actual reviewer's rerun protocol.

## 5. Merge and cleanup

Merge only with separate user authorization. After a squash merge, update
remaining branches to the new base using the repository's approved strategy.
A published-history rewrite requires explicit approval and force-with-lease;
verify PR bases and measured diffs afterwards.

When complete, compare the final base with the source branch, record intentional
differences, and remove temporary worktrees/branches only within authorized scope.
