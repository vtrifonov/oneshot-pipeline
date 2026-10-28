#!/usr/bin/env python3
"""Per-phase and per-step time and token metrics for a one-shot run.

Four subcommands (rollup and show live in metrics_rollup.py):

  mark <slug> phase <N>        phase N starts now (0..11; the previous phase ends)
  mark <slug> start <step>     an inline controller step starts (e.g. p6-task-3, p8-gates)
  mark <slug> end <step>       that step ends
  mark <slug> done             the run is over; report counts nothing after this
  mark <slug> task <label> --agent "<dispatch description>"
                               a subagent starts plan task <label> (e.g. T7); run BY the
                               agent as the first command of each task it implements
  any mark takes --at <ISO>    to backfill a boundary (e.g. from a commit time)

  report <slug> [--run-id ID] [--mode M] [--lane L] [--csv PATH] [--no-csv]
                [--artifacts DIR]
  rollup [--home DIR] [--papercuts PATH]
                               cross-run tables in <skill-dir>/runs/_rollup/ (runs, steps,
                               reviews); copies newer artifacts from the run directories
                               listed in rollup-sources.local.json into runs/<run_id>/
  show [--run ID | --lenses | --phases | --failures | --retro | --json] [--all]
                               text views over the rollup; default: the last 15 runs

Marks go to /tmp/<slug>/marks.tsv (ISO time, kind, label[, agent]). report reads the
Claude Code transcripts, so nothing has to be logged by hand per agent:

- Controller sessions: every top-level <projects>/*/<session>.jsonl, modified
  since the first mark, whose text contains "run-metrics.py mark <slug> ".
  Several match after a resume or a /clear; all count.
- Agents: <session>/subagents/agent-*.jsonl (+ .meta.json for description,
  agent type, spawn depth). An agent belongs to the phase active at its first
  message.

Only messages between the first mark and the done mark (or now) count. Usage
is deduplicated per API message id. Tokens are split into input (uncached),
cache_write, cache_read and output, per model. Each row also carries the
reasoning `effort` the entries ran at (dominant level first: `medium`,
`high+medium`), `thinking_tokens` (a part of output), `thinking_s` (summed
thinkingDurationMs) and `latency_s` (api-request entry to the last assistant
entry of that request: model time plus queueing, summed over messages).

- Tasks: an agent that implements several plan tasks is split at its task
  marks into one `task` row per task (its messages before the first mark go
  to the first task). The agent row still carries the whole agent.

Writes /tmp/<slug>/step-metrics.json and, unless --no-csv, replaces this
run's rows in <skill-dir>/step-metrics.csv (one row per agent, task, inline
step, controller-per-phase, phase and total). Prints a compact table.

Also writes /tmp/<slug>/review-runs.skeleton.jsonl: one review-policy record
per agent whose description names a review or recheck, with time and tokens
filled and the finding fields null for the controller to fill from the
ledger. With --artifacts DIR, a missing DIR/review-runs.jsonl is a note.
"""
import re
import argparse
import collections
import csv
import datetime as dt
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import metrics_rollup  # noqa: E402

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
CSV_FIELDS = [
    "run_id", "date", "mode", "lane", "phase", "kind", "step", "agent_type", "model", "depth",
    "started_at", "ended_at", "wall_s", "active_s", "human_wait_s", "idle_s", "messages",
    "input", "cache_write", "cache_read", "output", "total_tokens",
    "effort", "thinking_tokens", "thinking_s", "latency_s",
]
TOKEN_KEYS = ["input", "cache_write", "cache_read", "output"]
# Per-message extras summed like tokens: thinking tokens (already inside output), thinking
# wall time, and API latency (api-request entry to the last assistant entry of that request).
EXTRA_KEYS = ["thinking_tokens", "thinking_s", "latency_s"]
HUMAN_GAP_S = 30
IDLE_GAP_S = 120
REVIEW_STEP = re.compile(r"review|recheck", re.IGNORECASE)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(raw):
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def run_dir(slug):
    return pathlib.Path("/tmp") / slug


def projects_root():
    config = os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")
    return pathlib.Path(config) / "projects"


def cmd_mark(args):
    if args.kind in ("start", "end") and not args.label:
        sys.exit(f"mark {args.kind} needs a step label")
    if args.kind == "phase" and not args.label:
        sys.exit("mark phase needs a phase number")
    if args.kind == "task" and not (args.label and args.agent):
        sys.exit('mark task needs a task label and --agent "<dispatch description>"')
    when = now_iso()
    if args.at:
        when = parse_ts(args.at).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    agent = (args.agent or "").replace("\t", " ")
    path = run_dir(args.slug) / "marks.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(f"{when}\t{args.kind}\t{args.label or ''}" + (f"\t{agent}" if agent else "") + "\n")
    return 0


def read_marks(slug):
    path = run_dir(slug) / "marks.tsv"
    if not path.exists():
        sys.exit(f"no marks at {path}; run `mark {slug} phase 0` at the start of a run")
    marks = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            marks.append((parse_ts(parts[0]), parts[1], parts[2] if len(parts) > 2 else "",
                          parts[3] if len(parts) > 3 else ""))
    return sorted(marks, key=lambda m: m[0])


def task_rows(base, phase, step, agent_marks, messages):
    """Split one agent's messages at its task marks; earlier messages go to the first task."""
    out = []
    for i, (mark_ts, label) in enumerate(agent_marks):
        nxt = agent_marks[i + 1][0] if i + 1 < len(agent_marks) else None
        inside = [m for m in messages
                  if (i == 0 or m["ts"] >= mark_ts) and (nxt is None or m["ts"] < nxt)]
        if not inside:
            continue
        tokens, models = summarize(inside)
        first, last = inside[0]["ts"], inside[-1]["ts"]
        out.append(row(base, phase=phase, kind="task", step=f"{label} ({step})", agent_type="",
                       model=fmt_model(models), depth="", started_at=iso(first), ended_at=iso(last),
                       wall_s="", active_s=round((last - first).total_seconds()), human_wait_s="",
                       idle_s="", messages=len(inside), tokens=tokens))
    return out


def review_skeleton(run_id, phase, step, agent_id, first, last, tokens):
    return {
        "schema_version": 1, "policy_version": "2026-09-risk-panels", "run_id": run_id,
        "phase": phase, "reviewer_id": step, "agent_id": agent_id, "lens": None,
        "artifact_revision": None, "pass_kind": "recheck" if "recheck" in step.lower() else "initial",
        "started_at": iso(first), "finished_at": iso(last),
        "elapsed_seconds": round((last - first).total_seconds()),
        "tokens": sum(tokens[k] for k in TOKEN_KEYS), "output_tokens": tokens["output"],
        "effort": fmt_effort(tokens["effort"]), "thinking_tokens": tokens["thinking_tokens"],
        "cost": None, "currency": None, "reported_bmm": None, "unique_accepted_bmm": None,
        "duplicate_count": None, "rejected_count": None, "unresolved_count": None, "finding_ids": None,
    }


def empty_tokens():
    out = {key: 0 for key in TOKEN_KEYS + EXTRA_KEYS}
    out["effort"] = collections.Counter()
    return out


def usage_tokens(usage):
    details = usage.get("output_tokens_details") or {}
    return {
        "input": usage.get("input_tokens") or 0,
        "cache_write": usage.get("cache_creation_input_tokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "thinking_tokens": details.get("thinking_tokens") or 0,
    }


def fmt_effort(counter):
    """Dominant effort first, others joined with '+': 'medium', 'high+medium'."""
    return "+".join(level for level, _ in counter.most_common()) if counter else ""


# User entries the harness writes on the user's behalf: a gap before one of these is the
# controller waiting on an agent, a compaction or a timer, not on the human.
NOT_TYPED_PREFIXES = (
    "<",
    "Another Claude session sent a message",
    "This session is being continued from a previous conversation",
    "Heartbeat for ",
    "[SYSTEM NOTIFICATION",
)


def typed_by_human(text):
    return not text.lstrip().startswith(NOT_TYPED_PREFIXES)


def read_transcript(path, start, end, skip_sidechain):
    """Return (messages, events). messages: one per API message id, in time order.
    events: (ts, role, is_human) for every entry, used for wait/idle gaps."""
    by_id = {}
    events = []
    ask_ids = set()
    requests = {}      # api-request id -> sent timestamp
    request_last = {}  # api-request id -> (last assistant entry ts, message id)
    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            raw_ts = entry.get("timestamp")
            if raw_ts and entry.get("type") == "api-request" and entry.get("id"):
                requests[entry["id"]] = parse_ts(raw_ts)
                continue
            if not raw_ts or entry.get("type") not in ("assistant", "user"):
                continue
            if skip_sidechain and entry.get("isSidechain"):
                continue
            ts = parse_ts(raw_ts)
            if ts < start or ts > end:
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            if entry["type"] == "assistant":
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                        ask_ids.add(block.get("id"))
                events.append((ts, "assistant", False))
                msg_id = message.get("id")
                model = message.get("model") or "unknown"
                usage = message.get("usage")
                if not msg_id or not usage or model == "<synthetic>":
                    continue
                tokens = usage_tokens(usage)
                tokens["thinking_s"] = (entry.get("thinkingDurationMs") or 0) / 1000
                tokens["latency_s"] = 0
                tokens["effort"] = collections.Counter()
                seen = by_id.get(msg_id)
                if seen:
                    # One API message is logged once per content block with the same usage: keep
                    # the max per token key, but thinking time is per block and adds up.
                    for key in TOKEN_KEYS + ["thinking_tokens"]:
                        seen["tokens"][key] = max(seen["tokens"][key], tokens[key])
                    seen["tokens"]["thinking_s"] += tokens["thinking_s"]
                else:
                    seen = by_id[msg_id] = {"ts": ts, "model": model, "tokens": tokens}
                    level = entry.get("effort") or entry.get("perTurnEffort")
                    if level:
                        seen["tokens"]["effort"][level] += 1
                ref = entry.get("requestRef")
                if ref:
                    request_last[ref] = (max(ts, request_last.get(ref, (ts, None))[0]), msg_id)
            else:
                is_human = False
                if isinstance(content, str):
                    is_human = not entry.get("isMeta") and typed_by_human(content)
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text" and not entry.get("isMeta"):
                            is_human = typed_by_human(block.get("text", ""))
                        elif block.get("type") == "tool_result" and block.get("tool_use_id") in ask_ids:
                            is_human = True
                events.append((ts, "user", is_human))
    for ref, (last_ts, msg_id) in request_last.items():
        sent = requests.get(ref)
        if sent is not None and msg_id in by_id:
            by_id[msg_id]["tokens"]["latency_s"] = max(0.0, (last_ts - sent).total_seconds())
    messages = sorted(by_id.values(), key=lambda m: m["ts"])
    return messages, sorted(events, key=lambda e: e[0])


def find_sessions(slug, start):
    needle = f"run-metrics.py mark {slug} "
    floor = start.timestamp() - 60
    sessions = []
    root = projects_root()
    for path in root.glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime < floor:
                continue
            with path.open(errors="replace") as fh:
                if any(needle in line for line in fh):
                    sessions.append(path)
        except OSError:
            continue
    return sessions


def phase_at(phase_marks, ts):
    current = phase_marks[0][1] if phase_marks else "?"
    for mark_ts, phase in phase_marks:
        if mark_ts <= ts:
            current = phase
        else:
            break
    return current


def add_tokens(target, tokens):
    for key in TOKEN_KEYS + EXTRA_KEYS:
        target[key] += tokens.get(key) or 0
    target["effort"].update(tokens.get("effort") or {})


def summarize(messages):
    tokens = empty_tokens()
    models = collections.Counter()
    for message in messages:
        add_tokens(tokens, message["tokens"])
        models[message["model"]] += 1
    return tokens, models


def gaps(events, phase_marks):
    """Per-phase human-wait and idle seconds from gaps between controller entries."""
    human = collections.Counter()
    idle = collections.Counter()
    for prev, cur in zip(events, events[1:]):
        gap = (cur[0] - prev[0]).total_seconds()
        phase = phase_at(phase_marks, prev[0])
        if cur[2] and gap >= HUMAN_GAP_S:
            human[phase] += gap
        elif gap >= IDLE_GAP_S:
            idle[phase] += gap
    return human, idle


def row(base, **fields):
    out = dict(base)
    out.update(fields)
    tokens = fields.get("tokens") or empty_tokens()
    out.pop("tokens", None)
    for key in TOKEN_KEYS:
        out[key] = tokens[key]
    out["total_tokens"] = sum(tokens[k] for k in TOKEN_KEYS)
    out["effort"] = fmt_effort(tokens["effort"])
    out["thinking_tokens"] = tokens["thinking_tokens"]
    out["thinking_s"] = round(tokens["thinking_s"])
    out["latency_s"] = round(tokens["latency_s"])
    return out


def fmt_model(models):
    return "+".join(name.removeprefix("claude-") for name, _ in models.most_common())


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""


def cmd_report(args):
    marks = read_marks(args.slug)
    start = marks[0][0]
    done = [m[0] for m in marks if m[1] == "done"]
    end = done[-1] if done else dt.datetime.now(dt.timezone.utc)
    phase_marks = [(ts, label) for ts, kind, label, _ in marks if kind == "phase"]
    task_marks = collections.defaultdict(list)
    for ts, kind, label, agent in marks:
        if kind == "task":
            task_marks[agent].append((ts, label))
    step_windows = []
    open_steps = {}
    for ts, kind, label, _ in marks:
        if kind == "start":
            open_steps[label] = ts
        elif kind == "end" and label in open_steps:
            step_windows.append((label, open_steps.pop(label), ts))
    for label, ts in open_steps.items():
        step_windows.append((label, ts, end))

    sessions = find_sessions(args.slug, start)
    base = {
        "run_id": args.run_id or args.slug,
        "date": start.date().isoformat(),
        "mode": args.mode or "",
        "lane": args.lane or "",
    }
    rows = []
    notes = []
    if not sessions:
        notes.append(f"no controller transcript under {projects_root()} contains 'run-metrics.py mark {args.slug} '")

    controller_msgs = []
    controller_events = []
    agents = []
    reviews = []
    for session in sessions:
        messages, events = read_transcript(session, start, end, skip_sidechain=True)
        controller_msgs.extend(messages)
        controller_events.extend(events)
        for agent_path in sorted((session.parent / session.stem / "subagents").glob("agent-*.jsonl")):
            agent_msgs, _ = read_transcript(agent_path, start, end, skip_sidechain=False)
            if not agent_msgs:
                continue
            meta_path = agent_path.with_name(agent_path.stem + ".meta.json")
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, ValueError):
                meta = {}
            agents.append((agent_path.stem, meta, agent_msgs))
    controller_msgs.sort(key=lambda m: m["ts"])
    controller_events.sort(key=lambda e: e[0])

    phase_tokens = collections.defaultdict(empty_tokens)
    phase_msgs = collections.Counter()

    # Inline steps take the controller messages inside their window.
    claimed = set()
    for label, step_start, step_end in step_windows:
        inside = [m for m in controller_msgs if step_start <= m["ts"] <= step_end]
        claimed.update(id(m) for m in inside)
        tokens, models = summarize(inside)
        phase = phase_at(phase_marks, step_start)
        rows.append(row(base, phase=phase, kind="inline", step=label, agent_type="controller",
                        model=fmt_model(models), depth=0, started_at=iso(step_start),
                        ended_at=iso(step_end), wall_s=round((step_end - step_start).total_seconds()),
                        active_s="", human_wait_s="", idle_s="", messages=len(inside), tokens=tokens))

    controller_by_phase = collections.defaultdict(list)
    for message in controller_msgs:
        if id(message) not in claimed:
            controller_by_phase[phase_at(phase_marks, message["ts"])].append(message)
    for message in controller_msgs:
        phase = phase_at(phase_marks, message["ts"])
        add_tokens(phase_tokens[phase], message["tokens"])
        phase_msgs[phase] += 1

    human, idle = gaps(controller_events, phase_marks)
    for phase, messages in controller_by_phase.items():
        tokens, models = summarize(messages)
        rows.append(row(base, phase=phase, kind="controller", step="controller", agent_type="controller",
                        model=fmt_model(models), depth=0, started_at=iso(messages[0]["ts"]),
                        ended_at=iso(messages[-1]["ts"]), wall_s="", active_s="",
                        human_wait_s=round(human[phase]), idle_s=round(idle[phase]),
                        messages=len(messages), tokens=tokens))

    for agent_id, meta, messages in agents:
        tokens, models = summarize(messages)
        first, last = messages[0]["ts"], messages[-1]["ts"]
        phase = phase_at(phase_marks, first)
        add_tokens(phase_tokens[phase], tokens)
        phase_msgs[phase] += len(messages)
        step = meta.get("description") or meta.get("name") or agent_id
        rows.append(row(base, phase=phase, kind="agent", step=step,
                        agent_type=meta.get("name") or meta.get("agentType") or "",
                        model=fmt_model(models), depth=meta.get("spawnDepth", 1),
                        started_at=iso(first), ended_at=iso(last), wall_s="",
                        active_s=round((last - first).total_seconds()), human_wait_s="", idle_s="",
                        messages=len(messages), tokens=tokens))
        if task_marks.get(step):
            rows.extend(task_rows(base, phase, step, task_marks.pop(step), messages))
        if REVIEW_STEP.search(step):
            reviews.append(review_skeleton(base["run_id"], phase, step, agent_id, first, last, tokens))
    for agent in task_marks:
        notes.append(f"task marks for agent {agent!r} match no dispatch description")

    bounds = phase_marks + [(end, None)]
    seen_phases = []
    for phase_start, phase in phase_marks:
        if phase not in seen_phases:
            seen_phases.append(phase)
    for phase in seen_phases:
        wall = sum(
            (b_end - b_start).total_seconds()
            for (b_start, p), (b_end, _) in zip(bounds, bounds[1:]) if p == phase
        )
        starts = [ts for ts, p in phase_marks if p == phase]
        rows.append(row(base, phase=phase, kind="phase", step=f"phase {phase}", agent_type="", model="",
                        depth="", started_at=iso(starts[0]), ended_at="", wall_s=round(wall), active_s="",
                        human_wait_s=round(human[phase]), idle_s=round(idle[phase]),
                        messages=phase_msgs[phase], tokens=phase_tokens[phase]))
    unphased = [p for p in phase_tokens if p not in seen_phases]
    if unphased:
        notes.append(f"tokens outside any phase mark: {unphased}")
    grand = empty_tokens()
    for tokens in phase_tokens.values():
        add_tokens(grand, tokens)
    rows.append(row(base, phase="all", kind="total", step="run", agent_type="", model="", depth="",
                    started_at=iso(start), ended_at=iso(end), wall_s=round((end - start).total_seconds()),
                    active_s="", human_wait_s=round(sum(human.values())), idle_s=round(sum(idle.values())),
                    messages=sum(phase_msgs.values()), tokens=grand))

    reviews.sort(key=lambda r: r["started_at"])
    (run_dir(args.slug) / "review-runs.skeleton.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in reviews))
    if args.artifacts and not (pathlib.Path(args.artifacts) / "review-runs.jsonl").exists():
        notes.append(f"{args.artifacts}/review-runs.jsonl missing: fill /tmp/{args.slug}/"
                     f"review-runs.skeleton.jsonl ({len(reviews)} passes) from the ledger and save it there")

    order = {"phase": 0, "controller": 1, "inline": 2, "agent": 3, "task": 4, "total": 9}
    phase_key = {p: i for i, p in enumerate(seen_phases)}
    rows.sort(key=lambda r: (r["kind"] == "total", phase_key.get(r["phase"], 99), order[r["kind"]], r["started_at"]))

    out = {
        "schema_version": 1,
        "run_id": base["run_id"],
        "sessions": [str(s) for s in sessions],
        "window": [iso(start), iso(end)],
        "agents": len(agents),
        "notes": notes,
        "rows": rows,
    }
    (run_dir(args.slug) / "step-metrics.json").write_text(json.dumps(out, indent=2) + "\n")

    if not args.no_csv:
        csv_path = pathlib.Path(args.csv) if args.csv else SKILL_DIR / "step-metrics.csv"
        kept = []
        if csv_path.exists():
            with csv_path.open(newline="") as fh:
                kept = [r for r in csv.DictReader(fh) if r.get("run_id") != base["run_id"]]
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(kept)
            writer.writerows(rows)

    print(f"{'phase':<6}{'kind':<11}{'wall':>7}{'active':>7}{'wait':>6}{'idle':>6}{'tokens':>11}{'out':>9}"
          f"{'think':>7}{'lat':>7}  step")
    for r in rows:
        tag = " ".join(x for x in (r["model"], r["effort"]) if x)
        print(f"{r['phase']:<6}{r['kind']:<11}{fmt_s(r['wall_s']):>7}{fmt_s(r['active_s']):>7}"
              f"{fmt_s(r['human_wait_s']):>6}{fmt_s(r['idle_s']):>6}{fmt_k(r['total_tokens']):>11}"
              f"{fmt_k(r['output']):>9}{fmt_k(r['thinking_tokens']):>7}{fmt_s(r['latency_s']):>7}"
              f"  {r['step'][:48]} {('[' + tag + ']') if tag else ''}")
    for note in notes:
        print(f"note: {note}")
    return 0


def fmt_s(value):
    if value in ("", None):
        return ""
    value = int(value)
    return f"{value // 3600}h{value % 3600 // 60:02d}" if value >= 3600 else f"{value // 60}m{value % 60:02d}"


def fmt_k(value):
    return f"{value / 1_000_000:.2f}M" if value >= 1_000_000 else f"{value / 1000:.1f}k"


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    mark = sub.add_parser("mark")
    mark.add_argument("slug")
    mark.add_argument("kind", choices=["phase", "start", "end", "done", "task"])
    mark.add_argument("label", nargs="?")
    mark.add_argument("--agent")
    mark.add_argument("--at")
    report = sub.add_parser("report")
    report.add_argument("slug")
    report.add_argument("--run-id")
    report.add_argument("--mode")
    report.add_argument("--lane")
    report.add_argument("--csv")
    report.add_argument("--no-csv", action="store_true")
    report.add_argument("--artifacts")
    metrics_rollup.add_subcommands(sub)
    args = parser.parse_args()
    if args.cmd == "mark":
        return cmd_mark(args)
    if args.cmd == "report":
        return cmd_report(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
