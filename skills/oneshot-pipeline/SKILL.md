---
name: oneshot-pipeline
description: Use when the user asks to "execute as one shot", "run the playbook", "quick one shot" / "one shot, quick mode" (the reduced-review quick mode), "one shot without fable" / "no fable" (opus replaces fable everywhere), or wants a feature or fix taken from idea to a merge-ready PR without repeated check-ins.
---

# One-Shot Pipeline (idea → green merge-ready PR)

**New installation or sharing:** read `reference/distribution.md` before Phase 0. Share the repository and run `bash ./link.sh` from its root to install the skill, agent and CLI dependencies. For standalone distribution, export with `bin/package-oneshot.py`; bundled support installs with `scripts/install-support.py`. The raw skill folder alone omits dependencies. Check required external skills/tools before starting.

This file is the contract, the triage rules, and the phase map. The detailed procedure for each phase lives in `reference/` next to this file. **On entering a phase, Read its reference file first**; never run a phase from memory of this summary. Files:

| Phase | Reference |
|---|---|
| Repository/runtime binding | `reference/repository-adapter.md` |
| Risk-based reviewers, findings ledger, per-pass metrics | `reference/review-policy.md` |
| Lane triage — full trigger table with mechanical checks | `reference/lane-triage.md` |
| 0 Setup · 1 Brainstorm · 2 Spec · 3 Panel · 4 Plan · 5 Panel | `reference/phases-0-5-setup-to-plan.md` |
| 6 Implement (SDD, dispatch rules, watchdogs) | `reference/phase-6-implement.md` |
| 7 Code review · 8 Pre-push gates · 9 PR | `reference/phases-7-9-review-gates-pr.md` |
| 10 Shepherd + babysit (10a controller loop, 10b Workflow) | `reference/phase-10-shepherd.md` |
| 11 Done · Retro | `reference/phase-11-done-retro.md` |

## Contract

After the brainstorm approval checkpoint, run fully autonomously. Do not check in with the user except for **critical, non-resolvable** decisions. Every other question gets answered by consulting a relevant expert subagent, the spec, or repo docs. Done = green PR on the repository adapter's base branch, zero unresolved review threads, ready for the user to merge (never merge it yourself).

**Invoking this playbook = pre-approval for pushing the branch and opening the ONE PR it produces.** No further approval asks for that PR. (Blanket approvals never extend to other PRs.) **One exception: the PR size budget.** The pre-approval covers a PR only inside the reviewer's normal tier: ≤ 4,000 changed lines, ≤ 75 files and ≤ 200 KB of diff, counted base-relative and including generated files and lockfiles. Past that the reviewer gets only per-file summaries and the review goes shallow by design. A PR projected or measured over budget needs the user's explicit yes. Send a PushNotification, then AskUserQuestion with the three numbers and a proposed split. Their yes covers that one PR. It is also the explicit opt-in the `Workflow` tool requires (Phase 10b).

## Lane triage — decide at the end of Phase 1, record in the PR body

The lane is a **predicate over the diff**, not a feeling about the task. Evaluate every trigger row; one match = **full lane**, none = **lite lane**. Evaluate three times: **provisional** at the end of Phase 1 (design + expected files), **confirmed** at the end of Phase 2 (written spec), **mechanical** at Phase 8 (base-relative name/status, source-filtered numstat, and changed-content inspection in `reference/lane-triage.md`, the only evaluation that sees the real diff).

Trigger categories: authorization/trust boundaries; persistence shape/queries/transactions; concurrency/state; deployment/infra; public or cross-package contracts; repository deploy-safety rules; more than one package/app or >300 changed source lines. Read `reference/lane-triage.md` and resolve repository-specific evidence through `reference/repository-adapter.md`. Lane is separate from panel size; use `reference/review-policy.md` for reviewer selection.

| Phase | Full | Lite |
|---|---|---|
| 2–5 | Separate spec (`opus`) and plan (`fable`); default **two spec reviewers + one fresh plan reviewer**; expand for named risks per review policy | ONE spec + task document; ONE combined reviewer; no second panel; accepted B/M/m goes in `spec_bmm`. `opus` writes the spec sections, then the `fable` plan agent appends the task list to the SAME file — sequential, never both at once |
| 6 | SDD | Same |
| 7 | `correctness/testing review` AND security/architecture review | `correctness/testing review` only |
| 8–11 | Identical | Identical |

## Quick mode — the user names it, the controller never picks it

**Opt-in only.** Quick mode is on when the invocation says so ("quick one shot", "one shot, quick mode", "run the playbook quick"). It is a cost/latency choice, never a risk call: the controller never selects it, never infers it from "this feels small", and never silently drops it once set. It is **orthogonal to the lane** — a run is `lane=full, mode=quick` or `lane=lite, mode=quick` just as readily.

It overrides exactly three things and nothing else:

| Phase | Standard | **Quick** |
|---|---|---|
| 3 Panel on spec | Reviewer count per `review-policy.md` (1 lite · 2 ordinary full · 3–4 high risk) | **At most TWO reviewers**, whatever lane and risk say. Two scopes: requirements/architecture + the single highest-risk domain. One is fine on lite. Never a third, never a "fifth for a named risk". |
| 5 Panel on plan | Full lane runs it | **Skipped entirely.** Phase 4 is NOT skipped — the `fable` plan agent still writes the plan; it is the task list and the invariant/TDD matrix. It just gets no reviewers. |
| 6 Implement | SDD unless lite AND ≤2 files under ~100 lines | **Inline TDD in the controller session**, regardless of lane and size — `reference/phase-6-implement.md` §6c. |

Everything else is identical: lane triage still runs all three evaluations, Phase 7 still follows the lane (lite = `correctness/testing review`; full = both review scopes), Phases 8–11 unchanged. **Phase 7 still runs in a fresh `opus` subagent** — in quick mode the controller wrote the code, so self-review is worth nothing.

**The one conversation quick mode adds lands at the Phase 1 checkpoint, where the user is already present:** if provisional triage matches a trust-boundary, persistence, concurrency, or deploy-safety trigger, name the trigger in that same round and ask whether to keep quick mode. They may keep it — record it and go. After the checkpoint it never blocks again. A full-lane upgrade confirmed at Phase 2, or mechanically at Phase 8, does **not** retro-add the plan panel (the plan is already implemented by then); it records `mode=quick` + `lane=lite→full` and adds one line to the PR body: "Plan was not panel-reviewed (quick mode)."

Record `mode` (`standard` / `quick`) in the metrics row.

**Upgrade, never downgrade within a run.** A later match runs the missing coverage on affected surfaces, updates the lane and reviewer-risk assessment, and at Phase 8 adds any missing code-review skill. A lite→full upgrade separates spec and plan and completes their distinct review contracts, reusing verified findings rather than repeating unaffected reviews. Record `lane=lite→full` in metrics. A new risk in an already-full run can add a specialist without restarting the panel.

## Finding contract — paste into EVERY reviewer brief (panels, task reviewers, code reviews, shepherd)

A finding has four parts, in this order: **severity**, **claim** (one sentence), **failure scenario** (concrete input or state → wrong output, crash, or violated invariant), **fix sketch**. Severity is derived from the scenario, not asserted:

- **BLOCKER** — security, data loss, deploy-safety rule, or a spec requirement not met.
- **MAJOR** — correctness bug, missing test for a stated invariant, coupled surface left out.
- **MINOR** — anything without a concrete failure scenario: style, naming, hypothetical future need, "consider", "could be cleaner".

Controller disposition: validate premises and deduplicate first; mark accepted/rejected/duplicate/unresolved with evidence. A plausible scenario is not proof. Fix every accepted BLOCKER and MAJOR (fix the class, not the instance). MINOR is **optional by default** — apply only when it is a one-line change in a file already being edited; otherwise list it under "Parked (MINOR)" in the PR body with one line of rationale. On a bot thread, MINOR means a rationale reply and a close with no edit (Phase 10). A finding that arrives without a failure scenario is MINOR regardless of the label the reviewer put on it. A clean review is valid; no finding quota. Check premises before adding guards or tests for impossible states.

## Model matrix

Claude defaults below: pass `model` when that alias is available. Other runtimes use the adapter's available model mapping or inherit; never pass unavailable aliases. **No-fable mode (opt-in, the user names it):** when the invocation says "without fable", "no fable" or "opus only", every `fable` row below runs on `opus` instead — brainstorm, plan author/reviser and wave fixer (10a dispatch `model: opus`; 10b pass `fixModel: 'opus'` in the Workflow args). Nothing else changes: same agents, same sole-writer ownership, same phases. Like quick mode it is orthogonal to lane and mode, never inferred, never dropped mid-run; record it by suffixing the metrics row's `mode` value with `+nofable` (`standard+nofable`, `quick+nofable`) — the 19-column schema stays fixed. Wherever a phase reference says `fable`, read "the plan/design/fixer model". **If `fable` is not available in the runtime, the brainstorm, plan and wave-fixer agents fall back to `opus`** — they stay subagents either way, because the phase structure (design brief file, one sole writer per artifact) is what makes revisions cheap, not the model alias. `fable` goes where judgment beats prose: design exploration, task decomposition, and disputing reviewer claims; it is never used on parallel panels, where tier cost multiplies.

| Work | Model | Why |
|---|---|---|
| Brainstorm design agent (question set, options, trade-offs, agreed design + standing decisions) | `fable` | Design exploration is the highest-judgment step and the only one the user sees; the controller still owns the checkpoint conversation and relays both directions |
| Spec author and reviser (first draft AND post-panel rewrites) | `opus` | Spec prose does not need the top tier; one alias writes and revises so voice and structure stay consistent across revisions |
| Plan author and reviser (first draft AND post-panel rewrites) | `fable` | Task decomposition, ordering and the invariant matrix are the highest-leverage reasoning in the run |
| Controller work (orchestration, findings triage, lane calls, dispositions, gates) | inherit (session model) | Judgment on other agents' output stays on the session model |
| Expert panel — spec & plan reviews | `opus` | Independent reasoning per selected scope; record cost per pass (parallelism reduces latency, not total cost) |
| SDD implementer subagents | `sonnet` | Fast, strong coder for well-scoped plan tasks |
| SDD implementer — task flagged complex/cross-cutting in the plan | `opus` | Escalate when the plan marks risk |
| SDD task reviewer | `opus` | Reviewer must out-reason the implementer |
| Code review (correctness/testing; plus security/architecture on the full lane) | `opus` | Run each review in an opus subagent |
| Phase 10 wave fixer (`pr-shepherd`, both 10a and 10b) | `fable` | Verifies bot claims against code, fixes the class, disputes findings; every burned wave costs 25–100 min, so out-reasoning the reviewer pays for the tier |
| Phase 10 triage (classify a wave under the Finding contract) | `sonnet` | Read-only, bounded, schema-typed |
| Mechanical helpers (transcript digging, `review-wait`, gh queries) | `haiku`, effort low | Cheap, no judgment needed |
| Expert consults answering fixer/mid-run questions | `opus` | Decision quality matters, single-shot |

## Phase map — the one rule per phase you must not forget

0. **Setup** — read repository adapter; resolve base branch, worktree root, domain risks, tools, and CI gates; new worktree + branch off latest resolved base; one implementation writer per worktree; reviewers own separate findings files.
1. **Brainstorm** — the ONLY planned check-in. A **`fable` design agent** drafts questions and options; the controller relays them to the user and their answers back. Collect standing decisions, state the provisional lane, estimate the PR size against the size budget (Contract), and if it is over, propose the split or get the override in this same round. Then write `approved=` to `/tmp/<slug>/timeline.txt`.
2. **Spec** — an **`opus` spec agent** writes the file under `docs/superpowers/specs/`; controller confirms the lane against it.
3. **Panel on spec** — use review policy (**quick: two reviewers max**): intent, boundaries, invariants, failure behavior. Independent findings to files; source-backed disposition in shared ledger; targeted rechecks; scoped reference reads. Controller triages; the **`opus` spec agent applies accepted BLOCKER/MAJOR rewrites**.
4. **Plan** — a **`fable` plan agent** applies `superpowers:writing-plans`; coupled surfaces become explicit tasks, invariant matrix becomes the TDD list; under 2,000 lines or split into parts.
5. **Panel on plan** — **skipped in quick mode**; full lane otherwise: fresh implementation/test reviewer, plus highest-risk execution specialist for high risk; requirement → task → verification coverage. The **`fable` plan agent applies accepted rewrites**. Reopen design only on new failure evidence, and amend the spec before the plan.
6. **Implement** — SDD by default; **quick mode is always inline TDD** (RED test first, per task, §6c); otherwise inline only when the lane is lite AND the diff is one or two files under ~100 lines (then compact after Phase 7). The brief carries the task text, prefixed `(Task N of M)`; implementers never Read the plan or spec. No multi-line bash, no `&&`, no destructive commands in any brief; `verify-diff` once per step; batch task reviews 3–5 at a seam, split past ~400 lines or ~8–10 files; stall watchdog on every dispatch, armed in the same turn; never end a turn on "next up".
7. **Code review** — per lane; fix the class, not the instance.
8. **Pre-push gates** — controller runs adapter CI gates: full local suite/build here, scoped tests during implementation; optional hook override and independently checked packages in Phase 8 reference. Mechanical lane evaluation on committed branch diff. Measure the size budget on the same diff; over budget without an override → ask before push.
9. **PR** — rebase before first push, then merge-in only; every push is a wave; batch the PUSH, never the WORK; never open red; flaky check → `rerun-failed`, never a commit.
10. **Shepherd** — fresh `pr-shepherd` per wave, dispatched at wave 1 never at `gh pr create`; `review-wait` → `pr-threads --reviews` → triage → dispatch → `audit-wait` after any thread close (a close with no push needs a `/ai-review` comment first, or the bot never audits it); heartbeat every ~30 min (10a) with `delaySeconds` + `prompt` + `reason`.
11. **Done** — checks green, zero unresolved threads, `reviewDecision` APPROVED, `audit-wait` none pending, `ready=` in timeline, **metrics row appended** (with `mode`) to `metrics.csv`, review ledger/per-pass metrics and run summary persisted. Retro after ten comparable completed runs.

## Red flags — stop and self-check

| Thought | Reality |
|---|---|
| "Thread replied and closed, the bot will audit it" | Only if a review run starts, and runs start on a push or an `/ai-review` comment. A no-push close stays `pending` forever; post `/ai-review`, then `audit-wait`. |
| "The PR body diagram is fine as ASCII" | GitHub clips wide plain fences. Diagrams are Mermaid, always. |
| "I'll just ask the user quickly" | Blocked AskUserQuestion froze a pipeline overnight. Expert agent first; PushNotification before any ask. |
| "The fable design agent can ask the user itself" | Subagents cannot reach them. The controller relays both directions and sends answers back to the SAME agent. |
| "Faster if I just fix the spec/plan myself" | The spec goes back to its `opus` author, the plan to its `fable` author. Controller triages and verifies; it does not author. |
| "The design agent died, I remember the design" | Reconstructing from memory loses the standing decisions. Seed a fresh agent from `/tmp/<slug>/design-brief.md`. |
| "Shepherd's been quiet, probably fine" | Silent ≠ fine. Read its transcript JSONL now. |
| "My watcher would tell me if it broke" | Only if you gave it a stall arm. Success-only watchers are mute on a dead agent. |
| "Feels simple, go lite" / "Feels risky, add five reviewers" | Evaluate lane triggers, then name the distinct risks and reviewer coverage. Size alone does not require a high-risk panel. |
| "Full lane means the same four agents twice" | Full defaults to two spec reviewers and one fresh plan reviewer. Add only named risk coverage; each phase has a different job. |
| "It's only MINOR but I'll fix it anyway" | Every unforced change is a new surface for the next round. Park it with a rationale line. |
| "Reviewer marked it MAJOR" | Severity comes from the failure scenario. No scenario → MINOR, whatever the label. |
| "Lite lane, so one review pass" | Lite drops security/architecture review, never `correctness/testing review`. Full runs both. |
| "I'll add the metrics row later" | Done includes the row. Later is never; the retro then has nothing to read. |
| "Full local suite before every push" | Scoped tests locally; CI is the gate. |
| "Pre-approval covers this second PR too" | It covers exactly one PR — the one this invocation produces. |
| "It's 4,600 lines, but the playbook pre-approved the push" | Pre-approval stops at 4,000 lines / 75 files / 200 KB. Past that, PushNotification + ask with the numbers and a split. |
| "I'll batch this fix with whatever the review finds next" | Batch the PUSH, never the WORK. Implement, test and commit a triaged fix immediately; hold only `git push`. |
| "Nothing to do but wait for the review" | Ask what the worktree is owed first: a triaged FIX, a parked doc correction, a queued cleanup. Idle-waiting is right only when the answer is genuinely nothing. |
| "This one feels small, I'll run it quick" | Quick mode is the user's word, never the controller's inference. Unasked, run standard. |
| "Quick mode, so skip the spec panel too" | Quick caps the spec panel at two reviewers; it never takes it to zero. The spec is the only artifact still challenged. |
| "Quick mode, so no plan needed" | Phase 5 is skipped, Phase 4 is not. The plan is the task list and the TDD matrix the inline implementation runs off. |
| "Inline TDD — I'll write the code and add the test after" | The failing test first IS the trade for the skipped plan panel. Code-first forfeits it. |
| "I implemented it inline, I can review it myself" | Never self-review. Phase 7 goes to a fresh `opus` subagent in quick mode exactly as in SDD. |
| "Quick mode, so push past the bail-out" | ~400 source lines or ~8–10 files ends inline. Hand the rest to SDD, record `inline-tdd→sdd`, don't ask. |
| "I remember what Phase N says" | You remember this summary. Read `reference/` for the phase before acting. |
