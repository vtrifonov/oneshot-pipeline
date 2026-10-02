# Lane triage

Evaluate every row at Phase 1 (expected behavior/files), Phase 2 (written spec), and Phase 8 (actual committed branch diff). Any confirmed match selects full; none selects lite. Record matching rows and evidence. Lane controls document separation and code-review gates, not specialist count: use `review-policy.md` separately.

| Full trigger | Evidence of changed behavior |
|---|---|
| Authorization, admission, trust boundary, access grants | Changes a gating condition, identity claim, or access path |
| Persistence shape, field/collection, inequality query, transaction | Introduces or changes a stored shape, query, or transactional operation |
| Concurrency or state | Changes lock, cursor, retry, cache, idempotency, upload-session, or scheduled-job behavior |
| Deploy/infra | Changes CI/deploy configuration, permissions, network policy, or runtime infrastructure |
| Public/cross-package contract | Changes SDK, runtime dispatch, public API, or a shared context contract |
| Repository deploy-safety rules | Applicable documented deletion, backfill, route/response, bundle, deployment-literal, or activation rule |
| Size | More than one actual package/app has changed source, or >300 added + deleted source lines |

## Mechanical evaluation

At Phase 8 commit intended changes first; check `git status --short` for uncommitted/untracked work so nothing is silently omitted. Use the same base on every check. Resolve `<base-ref>` from the adapter and record merge-base SHA and HEAD SHA.

```sh
git merge-base <base-ref> HEAD
git diff --name-status --find-renames <base-ref>...HEAD
git diff --numstat --find-renames <base-ref>...HEAD
git diff --unified=0 --find-renames <base-ref>...HEAD
```

Substitute the resolved base ref before execution. Use `-z` name/numstat output when parsing filenames programmatically. Include added, deleted, and both sides of renamed paths; inspect deleted source from the base revision. Use actual workspace/package ownership, including deleted or renamed packages from base configuration. Record changed package names, source line total, and exclusions. Sum numeric additions + deletions only for adapter-defined source files (including source tests); exclude docs, lockfiles, generated/vendor files, and binaries from this size count. Binary/config/deployment effects still undergo the other trigger rows.

Search added and removed content to discover candidates, then inspect relevant context/callers to establish changed behavior. Whole-file identifier matches are navigation hints, not automatic matches: an untouched `cache` or `.update(` cannot alone upgrade the lane. A changed caller can alter a sensitive operation without adding its identifier; negative greps never waive a known affected surface. Record evidence and conclusion for every row. Investigate unresolved relevant risks before confirming lite.

## Lane effects and upgrades

| Phase | Full | Lite |
|---|---|---|
| 2–5 | Separate spec/plan; two spec reviewers and one fresh plan reviewer, expanding for named risks | One combined spec/task document and one reviewer |
| 6 | SDD with batched task review | Same; inline permitted by Phase 6's small-diff rule |
| 7 | Correctness/testing plus security/architecture reviews | Correctness/testing review |
| 8–11 | Adapter CI/review gates and metrics | Identical |

Upgrade, never downgrade within a run. A new match at Phase 2/8 requires missing review coverage on affected surfaces. Lite→full separates spec and plan and fulfills both review contracts; existing verified findings need not be rediscovered. At Phase 8 add any missing code-review gate before push. Record `lane=lite→full`. A new high-risk surface also updates reviewer selection even when lane was already full.
