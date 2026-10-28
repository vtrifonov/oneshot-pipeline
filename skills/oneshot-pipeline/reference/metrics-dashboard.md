# Cross-run metrics: rollup tables and the dashboard

Read at Phase 11 after `report` and the `metrics.csv` row, or when the user asks how runs compare.
The retro section of `phase-11-done-retro.md` says how to judge the numbers;
this file says how they are produced and shown.

## Tables

`python3 <skill-dir>/scripts/run-metrics.py rollup` writes three flat JSON arrays under
`<skill-dir>/runs/_rollup/` (gitignored, rebuilt from scratch each time, unchanged files keep their
mtime):

| File | One row per | Joined from |
|---|---|---|
| `runs.json` | run | `runs/<folder>/run-summary.json`, the `metrics.csv` row (by PR number, else by Jira key in the run id), step totals, the ledger's accepted B/M/m, `metrics_quality_notes` failure classes, papercuts on the same date and project |
| `steps.json` | step-metrics row (phase, controller, inline, agent, task, total) | `runs/<folder>/step-metrics.json`, else that run's rows in `step-metrics.csv`; plus `run_id`, `lane`, `mode`, `date`. Rows reported since 2026-10-28 also carry `effort`, `thinking_tokens`, `thinking_s` and `latency_s` |
| `reviews.json` | reviewer pass | `review-runs.jsonl`, with `reported`/`accepted` parsed to `[B, M, m]` and `accepted_bm`; `effort` and `thinking_tokens` when the skeleton carried them |

A run with artifacts in a target repository is copied into `runs/<run_id>/` first (the four
artifact files only, and only when the source is newer; `.source` records where it came from). The
places to look are globs in `<skill-dir>/rollup-sources.local.json`, per machine and gitignored:

```json
{"run_dirs": ["~/projects/<repo>/docs/superpowers/reviews/*", "~/work/superpowers-docs/*"]}
```

Each glob names run directories; artifacts may sit in the directory itself or under its `reviews/`
or `run/` child. A directory nested under another matched one is skipped. Rows of `metrics.csv`
that match no run become `csv-<date>-<pr|jira>` rows, so the per-run trend still covers them.

`run-metrics.py show` prints the last 15 runs (`--all` for every one); `--run <id>` one run's phases,
agents, tasks and passes; `--lenses` reviewer value; `--phases` per-lane medians; `--failures`
failure classes and papercuts; `--retro` the retro candidates below; `--effort` output, thinking share
and API latency per role, model and reasoning effort; `--json` the retro list and lens stats for a
script.

## Effort, thinking and latency

Every assistant entry in a transcript records the reasoning effort it ran at (`effort`,
`perTurnEffort`), its thinking time (`thinkingDurationMs`) and, in `usage.output_tokens_details`,
the thinking tokens inside `output_tokens`; the matching `api-request` entry gives the send time.
`report` folds these into each row: `effort` is the dominant level with any others joined by `+`
(`medium`, `high+medium`); `thinking_tokens` is deduplicated per API message like the other usage
fields; `thinking_s` adds up per content block; `latency_s` is the api-request time to the last
assistant entry of that request, summed over the row's messages (model time plus queueing, so it
is a floor on agent wall time, not a measure of model speed).

Reading them: output per message is not an effort signal (authors write long artifacts, tool-only
turns are tiny); the thinking share of output and latency per message are. Baseline measured on the
runs to 2026-10-26: `opus` and `sonnet` agents at `medium`, `fable` at `high`, thinking share
roughly 30–45% for reviewers on opus; the 2026-10-27 run ran at `high` throughout, so
`show --effort` already holds both arms for quick-mode runs. A change to the model matrix is evaluated one role at a
time, against escaped defects (Phase 10 accepted findings on the same PR) and reviewer yield, not
against dry rate alone: with four to eight passes per arm a dry-rate difference is noise. The
decisive design when a change matters is a paired replay: the same frozen artifact or diff reviewed
by the same prompt and model at both efforts, scored against the ledger's confirmed findings.

## Retro candidates

Computed identically by `show --retro` and the dashboard's `dash.calc`:

- a phase row over 2x the median for the same lane and phase (wall or output tokens), ignoring
  phases under 2 minutes or 5k output tokens;
- a lens with five or more measured passes whose last five accepted no BLOCKER/MAJOR;
- a `task` row over 10 minutes active;
- a run whose human wait exceeds 25% of wall time.

An empty list prints why (how many runs have step metrics, how many passes carry accepted counts).

## Dashboard refresh (Phase 11)

The dashboard is a Claude Dashboard artifact fed by the three files as attached files. Its URL and
the three dataset ids live in `rollup-sources.local.json`:

```json
{"run_dirs": ["..."], "dashboard": {"url": "https://claude.ai/artifact/<id>",
  "datasets": {"runs": "runs", "steps": "steps", "reviews": "reviews"}}}
```

After `rollup`, for each of the three files:

1. Upload it as an asset of that artifact (Artifact tool: `publish` with `url`, `asset: true`,
   `file_path` = the rollup file; one call per file, JSON is text). The result gives the new
   `/_blob/<id>` url.
2. `ArtifactData update` (`url`, `collection: "datasets"`, `doc_id` = the dataset id, `if_version`
   from a prior `get`) with `source: {kind: "file", url: "<blob url>", name: "<file>.json"}` and
   `updated: {at: "<ISO now>", by: "oneshot-pipeline Phase 11 (<run_id>)"}`.

Nothing else changes. The page re-reads the files on its next load. Skip the refresh, and say so in
the final report, when `rollup-sources.local.json` has no `dashboard` entry or the artifact tools are
unavailable in the session; the tables are still rebuilt locally.

## Reading the numbers

- `total_tokens` is dominated by cache reads; compare `output` and `cache_write` first.
- `effort` is `?`/empty on rows reported before 2026-10-28; `show --effort` groups them separately.
- Step rows before 2026-10-26 have no `task` rows; batched implementers before then are one row each.
- Some per-task splits were backfilled from commit times (`metrics_quality_notes` says so).
- `metrics.csv` B/M/m before policy `2026-09-risk-panels` are not comparable to later rows.
- Lens names are free text from the ledger; the same scope can appear under two spellings until the
  review-runs writer normalises them.
