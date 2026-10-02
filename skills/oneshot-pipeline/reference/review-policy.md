# Spec and plan review policy

Read before choosing or briefing reviewers in Phases 3 and 5. Lane controls document separation and code-review gates; reviewer count follows the distinct risks below. This policy is a trial to evaluate after ten comparable completed runs, not a measured optimum.

## Select reviewers

| Scope | Spec | Plan |
|---|---|---|
| Lite: no lane trigger | One reviewer of the combined spec/task document: requirements, architecture, implementation coverage, tests, and applicable security boundaries | Included; no second dispatch |
| Full, ordinary: no high-risk condition below | Two independent reviewers: requirements/architecture and the most relevant domain specialist | One fresh implementation/test reviewer |
| Full, high risk | Three or four reviewers with distinct scopes | Two: implementation/test coverage and the highest-risk execution surface |
| Exceptional breadth | Fifth reviewer only when a named material risk is uncovered by the first four | Additional specialist only for a named uncovered execution risk |
| **Quick mode** — overrides every row above, any lane, any risk | **Two, hard cap:** requirements/architecture + the single highest-risk domain (one on lite) | **None — Phase 5 is skipped** |

Quick mode is the user's explicit opt-in at invocation, never a controller inference (SKILL.md § Quick mode). Under it, high risk no longer buys reviewers — it buys *scope selection*: the two slots go to the risks with the worst failure consequence, and the scopes left uncovered are recorded in the ledger as `not-covered (quick)` for the Phase 7 code review to weight. Reviewer count is the only thing the cap touches; the Finding contract, ledger, dispositions, author-agent rewrites, and rechecks below all apply unchanged.

High risk means the planned change alters an authorization/trust boundary; deletes, migrates, or backfills persisted data; changes concurrency, retry, or idempotency behavior with a concrete duplicate/loss/invariant risk; changes a public compatibility contract; or changes production rollout/recovery behavior. Record the condition and failure consequence. Source size alone selects ordinary full, not high risk. Unknown impact on one of these surfaces requires investigation before claiming ordinary risk.

Choose specialists by changed behavior: security for trust boundaries; data/Firestore for persistence and transaction semantics; DevOps for deployment and recovery; frontend/UX for interaction/accessibility; API/runtime for compatibility; domain correctness for other features. For a high-risk change, use three reviewers when one specialist plus architecture and verification covers the risks; use four when two distinct specialist domains are needed. A fifth needs an explicit uncovered risk. Name each reviewer's scope and why it cannot be covered by an existing brief. Schedule within the runtime's concurrency limit; a five-person panel need not run five agents simultaneously.

## Different jobs

**Spec:** assess user intent, scope boundaries, invariants, failure behavior, compatibility, and applicable operational constraints. Identify coupled surfaces and missing decisions. Use the repository adapter's relevant domain questions; mark non-applicable ones with a reason.

**Plan:** verify every approved requirement and accepted spec finding maps to an implementation task and meaningful verification. Check dependency order, integration seams, migration/rollout/rollback where applicable, and whether an implementer can execute without inventing missing decisions. Require a compact requirement → task → verification matrix. Reopen a settled design only with new evidence of a concrete requirement failure or invalid assumption; record that evidence and affected surfaces.

## Dispatch and converge

1. Freeze the artifact revision for the initial pass. Give reviewers the artifact path/revision, their scope, relevant repository evidence, standing decisions, and the Finding contract. Use fresh minimal context when supported. Reviewers may inspect relevant source to verify claims. First-pass reviewers do not receive peer findings before submitting their own file. A clean review is valid: explicitly return `no findings` with coverage; no quota.
2. Each finding includes the four Finding-contract fields plus a document/source anchor and the premise supporting the failure scenario. Concrete scenarios based on false premises are not accepted automatically. Each reviewer writes a findings file and returns its path/status; include sections for coverage and unknowns.
3. Controller keeps one `review-ledger.jsonl` under the run's durable artifact directory. Give findings stable IDs; validate premises against source, spec, and standing decisions; deduplicate by root cause. Dispositions are `accepted`, `rejected`, `duplicate`, or `unresolved`, with evidence and rationale. Link duplicates to the canonical ID. No majority voting. Track canonical accepted findings only in phase B/M/m totals.
4. Fix accepted BLOCKER/MAJOR findings **by sending the dispositions back to the artifact's author agent** — the `opus` spec agent for a spec, the `fable` plan agent for a plan (continue the live agent, else seed a fresh one from the artifact path plus the accepted-findings list). The controller rules on findings and verifies the rewrite landed; it does not author the artifact. MINOR follows the existing contract. Link accepted IDs to document changes and planned/later verification. Unknowns affecting a material risk remain unresolved until investigated; disagreements resolve through evidence or a targeted expert consult.
5. Original reviewer rechecks the affected delta and finding IDs. Rerun broader review only if revised assumptions affect other reviewers' surfaces. Finish the phase when accepted BLOCKER/MAJOR findings are verified closed and no material unknown remains. After two unsuccessful targeted rechecks, controller identifies the root disagreement and resolves it with evidence or one bounded expert consult; do not restart the whole panel reflexively. A round limit never waives an unresolved material issue.

## Record value

Record one `review-runs.jsonl` entry per reviewer pass, including rechecks: `schema_version` (1), `policy_version` (`2026-09-risk-panels`), `run_id`, `phase`, `reviewer_id`, `lens`, `artifact_revision`, `pass_kind` (`initial`/`recheck`), `started_at`, `finished_at`, `elapsed_seconds`, `tokens`, `cost`, `currency`, `reported_bmm`, `unique_accepted_bmm`, `duplicate_count`, `rejected_count`, `unresolved_count`, `finding_ids`. Unknown token/cost values are null, never zero estimates. Concurrent duplicate discoveries count once; record all discovering reviewers on the ledger entry rather than awarding uniqueness by arrival order.

Ledger entries contain `id`, `phase`, `reviewer_ids`, `severity`, `claim`, `scenario`, `fix_sketch`, `anchor`, `premise_evidence`, `disposition`, `rationale`, `duplicate_of`, `resolution_ref`, `verification_ref`, and `status` (`open`/`closed`). Append updated records for the same ID; latest record is authoritative. Store summaries and source references only, never transcripts, credentials, or customer data.

At Done, record total accepted issues once per canonical ID. If a later phase discovers a missed issue, link its ID to the earlier reviewed surface; distinguish an earlier omission from a new requirement. Evaluate per-lens unique contribution, overlapping discoveries, recheck churn, elapsed time, available cost, and later escapes. Finding volume alone is not value.
