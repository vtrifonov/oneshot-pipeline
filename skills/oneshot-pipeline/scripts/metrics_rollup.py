"""Cross-run rollup of oneshot-pipeline metrics, and a text viewer over it.

Used by run-metrics.py as the `rollup` and `show` subcommands.

rollup
  Finds every run: <home>/runs/<folder>/ plus every directory matched by the
  globs in <home>/rollup-sources.local.json ("run_dirs"). A run directory holds
  any of run-summary.json, review-runs.jsonl, review-ledger.jsonl,
  step-metrics.json, either directly or under reviews/. External runs are
  copied into <home>/runs/<run_id>/ (a copy only when the source is newer).
  Then writes three flat tables under <home>/runs/_rollup/:
    runs.json     one row per run, joined from metrics.csv, run-summary,
                  step totals, ledger counts, quality notes and papercuts
    steps.json    step-metrics rows (json per run, else step-metrics.csv)
    reviews.json  one row per review pass with lens, phase, tokens, B/M/m
  Idempotent: a second run rewrites nothing when nothing changed.

show
  Text views over the three tables; see cmd_show.
"""
import collections
import csv
import datetime as dt
import glob
import json
import os
import pathlib
import re
import shutil
import statistics

ARTIFACTS = ("run-summary.json", "review-runs.jsonl", "review-ledger.jsonl", "step-metrics.json")
GENERIC_DIRS = {"reviews", "run", "superpowers", "docs", "runs", "artifacts"}
ROLLUP_DIR = "_rollup"
MAX_TABLE_BYTES = 8 * 1024 * 1024
DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
JIRA_RE = re.compile(r"\b([A-Za-z]{2,}-\d{3,})\b")
DIGITS_RE = re.compile(r"\d{2,}")
CSV_NUMERIC = ("waves", "bot_threads", "threads_fixed", "threads_closed_no_change", "commits", "loc",
               "parked", "defects_90d")
CSV_HOURS = ("h_approved_to_pr", "h_pr_to_ready")
STEP_INT = ("wall_s", "active_s", "human_wait_s", "idle_s", "messages", "input", "cache_write",
            "cache_read", "output", "total_tokens", "depth")
FAILURE_CLASSES = {
    "stopped_agents": re.compile(r"\bstopped\b", re.I),
    "duplicate_writers": re.compile(r"duplicate (writer|author|agent|spec|plan|implementer)|second writer", re.I),
    "stalls": re.compile(r"\bstall", re.I),
    "hook_denials": re.compile(r"hook (denied|denial|blocked)|denied by (the )?\w*-?guard|guard denied", re.I),
    "backfilled_metrics": re.compile(r"backfill", re.I),
}
RETRO_PHASE_FACTOR = 2.0
RETRO_PHASE_FLOOR = {"wall_s": 120, "output": 5000}  # a 20s phase at 2x its 6s median is noise
RETRO_LENS_PASSES = 5
RETRO_TASK_ACTIVE_S = 600
RETRO_HUMAN_WAIT_SHARE = 0.25
SHOW_DEFAULT_RUNS = 15


# ----------------------------------------------------------------- helpers

def sources_path(home):
    override = os.environ.get("ONESHOT_ROLLUP_SOURCES")
    return pathlib.Path(override) if override else home / "rollup-sources.local.json"


def read_sources(home):
    path = sources_path(home)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("run_dirs"), list):
        raise SystemExit(f"{path}: expected {{\"run_dirs\": [glob, ...]}}")
    return [str(g) for g in data["run_dirs"]]


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def read_jsonl(path):
    out = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def to_int(value):
    if value in ("", None, "-", "NA", "n/a"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value in ("", None, "-", "NA", "n/a"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bmm(value):
    """'0/4/6' -> (0, 4, 6); None or malformed -> None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def date_of(*texts):
    for text in texts:
        if not text:
            continue
        match = DATE_RE.search(str(text))
        if match:
            return match.group(1)
    return None


def jira_of(*texts):
    for text in texts:
        if not text:
            continue
        match = JIRA_RE.search(str(text))
        if match:
            return match.group(1).upper()
    return None


def digit_groups(value):
    return set(DIGITS_RE.findall(str(value))) if value not in (None, "") else set()


def write_if_changed(path, payload):
    """Write JSON only when the serialized content differs, so reruns leave mtimes alone."""
    text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    if len(text.encode()) > MAX_TABLE_BYTES:
        raise SystemExit(f"{path.name} would exceed {MAX_TABLE_BYTES} bytes")
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


# ------------------------------------------------------------- discovery

def artifact_files(run_dir):
    """Map artifact name -> path, looking in the dir and its reviews/ and run/ children."""
    found = {}
    for name in ARTIFACTS:
        for candidate in (run_dir / name, run_dir / "reviews" / name, run_dir / "run" / name):
            if candidate.is_file():
                found[name] = candidate
                break
    return found


def external_run_dirs(home):
    matched = []
    for pattern in read_sources(home):
        for match in sorted(glob.glob(os.path.expanduser(pattern))):
            path = pathlib.Path(match).resolve()
            if path.is_dir() and artifact_files(path) and path not in matched:
                matched.append(path)
    # A dir nested under another matched dir is that run's reviews/ or run/ child, already read.
    return [p for p in matched if not any(other != p and other in p.parents for other in matched)]


def fallback_run_id(run_dir):
    """Folder name, skipping generic layout folders such as reviews/ or superpowers/."""
    for part in reversed(run_dir.parts):
        if part.lower() not in GENERIC_DIRS:
            return part
    return run_dir.name


def run_id_for(run_dir, files):
    summary = read_json(files["run-summary.json"]) if "run-summary.json" in files else None
    if isinstance(summary, dict) and summary.get("run_id"):
        return str(summary["run_id"])
    return fallback_run_id(run_dir)


def sync_external(home, notes):
    """Copy newer external artifacts into runs/<run_id>/. Returns the copied count."""
    runs_root = home / "runs"
    copied = 0
    for src_dir in external_run_dirs(home):
        files = artifact_files(src_dir)
        run_id = run_id_for(src_dir, files)
        if run_id == ROLLUP_DIR or "/" in run_id:
            notes.append(f"skipped {src_dir}: unusable run id {run_id!r}")
            continue
        dest_dir = runs_root / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name, src in files.items():
            dest = dest_dir / name
            if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
                continue
            shutil.copy2(src, dest)
            copied += 1
        marker = dest_dir / ".source"
        if not marker.exists() or marker.read_text().strip() != str(src_dir):
            marker.write_text(str(src_dir) + "\n")
    return copied


def local_run_dirs(home):
    runs_root = home / "runs"
    if not runs_root.is_dir():
        return []
    return [p for p in sorted(runs_root.iterdir()) if p.is_dir() and p.name != ROLLUP_DIR]


# --------------------------------------------------------------- loading

def load_metrics_csv(home):
    path = home / "metrics.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def load_step_csv(home):
    path = home / "step-metrics.csv"
    if not path.exists():
        return {}
    by_run = collections.defaultdict(list)
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            by_run[raw["run_id"]].append(coerce_step(raw))
    return by_run


def coerce_step(raw):
    row = dict(raw)
    for key in STEP_INT:
        if key in row:
            row[key] = to_int(row[key])
    return row


def load_papercuts(path):
    """Parse ~/code/papercuts.md new-format lines into (date, class, minutes, project)."""
    out = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = [p.strip() for p in line.split(" · ")]
        if len(parts) < 7 or not DATE_RE.fullmatch(parts[0]):
            continue
        minutes = to_int(parts[2].rstrip("m"))
        out.append({"date": parts[0], "class": parts[1], "minutes": minutes, "project": parts[6]})
    return out


def failure_counts(notes):
    counts = {name: 0 for name in FAILURE_CLASSES}
    for note in notes:
        for name, pattern in FAILURE_CLASSES.items():
            if pattern.search(str(note)):
                counts[name] += 1
    return counts


def ledger_accepted(records):
    """Canonical accepted findings by severity: latest record per id wins."""
    latest = {}
    for rec in records:
        if isinstance(rec, dict) and rec.get("id"):
            latest[rec["id"]] = rec
    counts = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
    for rec in latest.values():
        if rec.get("disposition") == "accepted":
            sev = str(rec.get("severity") or "").upper()
            if sev in counts:
                counts[sev] += 1
    return counts


def step_totals(rows):
    total = next((r for r in rows if r.get("kind") == "total"), None)
    agents = sum(1 for r in rows if r.get("kind") == "agent")
    if not total:
        return None
    return {
        "wall_s": total.get("wall_s"), "human_wait_s": total.get("human_wait_s"),
        "idle_s": total.get("idle_s"), "output": total.get("output"),
        "cache_write": total.get("cache_write"), "total_tokens": total.get("total_tokens"),
        "agents": agents,
    }


# ----------------------------------------------------------------- build

def build_run(run_dir, files, step_csv):
    summary = read_json(files["run-summary.json"]) if "run-summary.json" in files else {}
    summary = summary if isinstance(summary, dict) else {}
    run_id = str(summary.get("run_id") or fallback_run_id(run_dir))
    steps = None
    if "step-metrics.json" in files:
        data = read_json(files["step-metrics.json"])
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            steps = {"rows": [coerce_step(r) for r in data["rows"]], "notes": data.get("notes") or [],
                     "source": "step-metrics.json"}
    if steps is None:
        for key in {run_id, run_dir.name}:
            if key in step_csv:
                steps = {"rows": step_csv[key], "notes": [], "source": "step-metrics.csv"}
                break
    reviews = read_jsonl(files["review-runs.jsonl"]) if "review-runs.jsonl" in files else []
    ledger = read_jsonl(files["review-ledger.jsonl"]) if "review-ledger.jsonl" in files else []
    rows = steps["rows"] if steps else []
    quality_notes = list(summary.get("metrics_quality_notes") or [])
    source_marker = run_dir / ".source"
    pass_dates = sorted(d for d in (date_of(r.get("started_at")) for r in reviews if isinstance(r, dict)) if d)
    file_dates = sorted(dt.datetime.fromtimestamp(p.stat().st_mtime).date().isoformat() for p in files.values())
    source = source_marker.read_text().strip() if source_marker.exists() else "runs/"
    row = {
        "run_id": run_id,
        "folder": run_dir.name,
        "source": source,
        "repository": summary.get("repository") or repository_from_source(source),
        "date": date_of(summary.get("approved_at"), run_id, run_dir.name,
                        rows[0].get("date") if rows else None,
                        pass_dates[0] if pass_dates else None, file_dates[0] if file_dates else None),
        "lane": summary.get("lane") or (rows[0].get("lane") if rows else None),
        "mode": summary.get("mode") or (rows[0].get("mode") if rows else None),
        "impl_mode": summary.get("impl_mode"),
        "status": summary.get("status"),
        "pr": summary.get("pr"),
        "jira": jira_of(run_id, run_dir.name),
        "policy_version": summary.get("policy_version"),
        "has_summary": bool(summary),
        "has_steps": bool(rows),
        "steps_source": steps["source"] if steps else None,
        "review_passes": len(reviews),
        "ledger_accepted": ledger_accepted(ledger) if ledger else None,
        "step_totals": step_totals(rows) if rows else (summary.get("step_metrics_totals") or None),
        "metrics_quality_notes": quality_notes,
        "failures": failure_counts(quality_notes + (steps["notes"] if steps else [])),
        "papercuts": {},
        "csv": None,
    }
    return row, rows, reviews


def repository_from_source(source):
    """'<...>/<repo>/docs/superpowers/reviews/<slug>' -> '<repo>' (checkout folder name)."""
    parts = pathlib.Path(source).parts
    for i, part in enumerate(parts):
        if part == "superpowers" and i >= 1:
            root = i - 2 if parts[i - 1] == "docs" and i >= 2 else i - 1
            if root >= 0 and parts[root].lower() not in GENERIC_DIRS:
                return parts[root]
    return None


def csv_run_row(csv_row):
    key = csv_row.get("jira") if csv_row.get("jira") not in (None, "", "-", "NA") else csv_row.get("pr")
    run_id = f"csv-{csv_row.get('date')}-{re.sub(r'[^A-Za-z0-9#+.-]+', '_', str(key))}"
    return {
        "run_id": run_id, "folder": None, "source": "metrics.csv", "repository": None,
        "date": csv_row.get("date"), "lane": csv_row.get("lane"), "mode": csv_row.get("mode"),
        "impl_mode": csv_row.get("impl_mode"), "status": None, "pr": csv_row.get("pr"),
        "jira": jira_of(csv_row.get("jira")), "policy_version": None, "has_summary": False,
        "has_steps": False, "steps_source": None, "review_passes": 0, "ledger_accepted": None,
        "step_totals": None, "metrics_quality_notes": [], "failures": failure_counts([]),
        "papercuts": {}, "csv": normalise_csv(csv_row),
    }


def normalise_csv(csv_row):
    out = dict(csv_row)
    for key in CSV_NUMERIC:
        out[key] = to_int(csv_row.get(key))
    for key in CSV_HOURS:
        out[key] = to_float(csv_row.get(key))
    for key in ("spec_bmm", "plan_bmm", "review_bmm"):
        out[key + "_parsed"] = parse_bmm(csv_row.get(key))
    return out


def match_csv(run, csv_rows, used):
    """Join a run to one metrics.csv row by PR number, else by Jira key."""
    run_prs = digit_groups(run.get("pr"))
    for i, csv_row in enumerate(csv_rows):
        if i in used:
            continue
        if run_prs and run_prs & digit_groups(csv_row.get("pr")):
            return i
    jira = run.get("jira")
    if jira:
        for i, csv_row in enumerate(csv_rows):
            if i in used:
                continue
            if jira_of(csv_row.get("jira")) == jira:
                return i
    return None


def attach_papercuts(runs, papercuts):
    for run in runs:
        repo_tail = (run.get("repository") or "").split("/")[-1].lower()
        if not repo_tail or not run.get("date"):
            continue
        counts = collections.Counter()
        for cut in papercuts:
            if cut["date"] == run["date"] and cut["project"].lower() == repo_tail:
                counts[cut["class"]] += 1
        run["papercuts"] = dict(counts)


def review_row(rec, run):
    reported = parse_bmm(rec.get("reported_bmm"))
    accepted = parse_bmm(rec.get("unique_accepted_bmm"))
    lens = (rec.get("lens") or rec.get("reviewer_id") or "unknown").strip().lower()
    return {
        "run_id": run["run_id"], "date": run["date"], "lane": run["lane"], "mode": run["mode"],
        "phase": str(rec.get("phase")) if rec.get("phase") is not None else None,
        "reviewer_id": rec.get("reviewer_id"), "lens": lens, "pass_kind": rec.get("pass_kind"),
        "started_at": rec.get("started_at"), "elapsed_seconds": to_int(rec.get("elapsed_seconds")),
        "tokens": to_int(rec.get("tokens")), "output_tokens": to_int(rec.get("output_tokens")),
        "reported": list(reported) if reported else None,
        "accepted": list(accepted) if accepted else None,
        "accepted_bm": (accepted[0] + accepted[1]) if accepted else None,
        "duplicate_count": to_int(rec.get("duplicate_count")),
        "rejected_count": to_int(rec.get("rejected_count")),
        "finding_ids": rec.get("finding_ids") or [],
    }


def cmd_rollup(args):
    home = pathlib.Path(args.home).expanduser() if args.home else SKILL_HOME
    notes = []
    copied = sync_external(home, notes)
    step_csv = load_step_csv(home)
    csv_rows = load_metrics_csv(home)
    runs, steps, reviews = [], [], []
    pending = []  # (run, step rows, review passes): emitted after the metrics.csv join fills lane/mode
    seen_ids = set()
    for run_dir in local_run_dirs(home):
        files = artifact_files(run_dir)
        if not files:
            continue
        run, rows, passes = build_run(run_dir, files, step_csv)
        if run["run_id"] in seen_ids:
            notes.append(f"duplicate run id {run['run_id']!r} at {run_dir}; later folder skipped")
            continue
        seen_ids.add(run["run_id"])
        runs.append(run)
        pending.append((run, rows, passes))
    for run_id, rows in step_csv.items():
        if run_id in seen_ids or not rows:
            continue
        first = rows[0]
        run = {
            "run_id": run_id, "folder": None, "source": "step-metrics.csv", "repository": None,
            "date": first.get("date"), "lane": first.get("lane"), "mode": first.get("mode"),
            "impl_mode": None, "status": None, "pr": None, "jira": jira_of(run_id), "policy_version": None,
            "has_summary": False, "has_steps": True, "steps_source": "step-metrics.csv",
            "review_passes": 0, "ledger_accepted": None, "step_totals": step_totals(rows),
            "metrics_quality_notes": [], "failures": failure_counts([]), "papercuts": {}, "csv": None,
        }
        seen_ids.add(run_id)
        runs.append(run)
        pending.append((run, rows, []))
    used = set()
    for run in runs:
        index = match_csv(run, csv_rows, used)
        if index is not None:
            used.add(index)
            run["csv"] = normalise_csv(csv_rows[index])
            run["date"] = run["date"] or csv_rows[index].get("date")
            run["lane"] = run["lane"] or csv_rows[index].get("lane")
            run["mode"] = run["mode"] or csv_rows[index].get("mode")
            run["impl_mode"] = run["impl_mode"] or csv_rows[index].get("impl_mode")
    for run, rows, passes in pending:
        for row in rows:
            steps.append({**row, "run_id": run["run_id"], "lane": run["lane"], "mode": run["mode"],
                          "date": run["date"]})
        for rec in passes:
            if isinstance(rec, dict):
                reviews.append(review_row(rec, run))
    for i, csv_row in enumerate(csv_rows):
        if i not in used:
            runs.append(csv_run_row(csv_row))
    papercuts_path = pathlib.Path(args.papercuts).expanduser() if args.papercuts else DEFAULT_PAPERCUTS
    attach_papercuts(runs, load_papercuts(papercuts_path))
    runs.sort(key=lambda r: (r.get("date") or "", r["run_id"]))
    out_dir = home / "runs" / ROLLUP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = [
        write_if_changed(out_dir / "runs.json", runs),
        write_if_changed(out_dir / "steps.json", steps),
        write_if_changed(out_dir / "reviews.json", reviews),
    ]
    with_steps = sum(1 for r in runs if r["has_steps"])
    print(f"rollup: {len(runs)} runs ({with_steps} with step metrics, {len(reviews)} review passes, "
          f"{len(steps)} step rows); copied {copied} external files; "
          f"{'wrote' if any(changed) else 'unchanged'} {out_dir}")
    for note in notes:
        print(f"note: {note}")
    return 0


# ------------------------------------------------------------------ show

def load_tables(home):
    out_dir = home / "runs" / ROLLUP_DIR
    tables = {}
    for name in ("runs", "steps", "reviews"):
        data = read_json(out_dir / f"{name}.json")
        if data is None:
            raise SystemExit(f"{out_dir / (name + '.json')} missing; run `rollup` first")
        tables[name] = data
    return tables


def fmt_s(value):
    if value in ("", None):
        return "-"
    value = int(value)
    return f"{value // 3600}h{value % 3600 // 60:02d}" if value >= 3600 else f"{value // 60}m{value % 60:02d}"


def fmt_k(value):
    if value in ("", None):
        return "-"
    value = int(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    return f"{value / 1000:.0f}k" if value >= 1000 else str(value)


def fmt_bmm(parsed):
    return "/".join(str(x) for x in parsed) if parsed else "-"


def accepted_bm_of(run):
    ledger = run.get("ledger_accepted")
    if ledger:
        return ledger["BLOCKER"] + ledger["MAJOR"]
    csv_row = run.get("csv")
    if csv_row:
        total = 0
        found = False
        for key in ("spec_bmm_parsed", "plan_bmm_parsed", "review_bmm_parsed"):
            parsed = csv_row.get(key)
            if parsed:
                found = True
                total += parsed[0] + parsed[1]
        return total if found else None
    return None


def print_table(header, rows):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(header)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line.rstrip())
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())


def show_runs(tables, limit):
    runs = tables["runs"]
    shown = runs if limit is None else runs[-limit:]
    rows = []
    for run in shown:
        totals = run.get("step_totals") or {}
        rows.append([
            run.get("date") or "-", run["run_id"][:40], run.get("lane") or "-", run.get("mode") or "-",
            fmt_s(totals.get("wall_s")), fmt_s(totals.get("human_wait_s")), fmt_k(totals.get("output")),
            fmt_k(totals.get("cache_write")),
            "-" if accepted_bm_of(run) is None else accepted_bm_of(run),
            run.get("review_passes") or "-",
            sum(run["failures"].values()) + sum(run["papercuts"].values()) or "-",
            run.get("steps_source") or ("csv" if run.get("csv") and not run.get("has_summary") else "-"),
        ])
    print_table(["date", "run", "lane", "mode", "wall", "wait", "out", "cache_w", "acc B+M", "passes",
                 "fail", "steps"], rows)
    print(f"\n{len(shown)} of {len(runs)} runs" + ("" if limit is None else " (--all for every run)"))


def show_run(tables, run_id):
    runs = [r for r in tables["runs"] if r["run_id"] == run_id or r.get("folder") == run_id]
    if not runs:
        raise SystemExit(f"no run {run_id!r} in runs.json")
    run = runs[0]
    for key in ("run_id", "folder", "source", "repository", "date", "lane", "mode", "impl_mode", "status",
                "pr", "jira", "policy_version", "steps_source"):
        print(f"{key:<15} {run.get(key)}")
    print(f"{'accepted B/M/m':<15} {run.get('ledger_accepted')}")
    print(f"{'failures':<15} {run.get('failures')}")
    print(f"{'papercuts':<15} {run.get('papercuts')}")
    if run.get("csv"):
        c = run["csv"]
        print(f"{'metrics.csv':<15} spec {c.get('spec_bmm')} plan {c.get('plan_bmm')} review {c.get('review_bmm')}"
              f" waves {c.get('waves')} commits {c.get('commits')} loc {c.get('loc')} parked {c.get('parked')}")
    for note in run.get("metrics_quality_notes") or []:
        print(f"note: {note}")
    steps = [s for s in tables["steps"] if s["run_id"] == run["run_id"]]
    if steps:
        print("\nsteps")
        rows = [[s.get("phase"), s.get("kind"), fmt_s(s.get("wall_s")), fmt_s(s.get("active_s")),
                 fmt_s(s.get("human_wait_s")), fmt_k(s.get("output")), fmt_k(s.get("cache_write")),
                 fmt_k(s.get("total_tokens")), (s.get("step") or "")[:50], s.get("model") or ""]
                for s in steps]
        print_table(["phase", "kind", "wall", "active", "wait", "out", "cache_w", "total", "step", "model"], rows)
    reviews = [r for r in tables["reviews"] if r["run_id"] == run["run_id"]]
    if reviews:
        print("\nreview passes")
        rows = [[r.get("phase"), r.get("pass_kind"), r.get("lens"), fmt_s(r.get("elapsed_seconds")),
                 fmt_k(r.get("output_tokens")), fmt_k(r.get("tokens")), fmt_bmm(r.get("reported")),
                 fmt_bmm(r.get("accepted"))] for r in reviews]
        print_table(["phase", "kind", "lens", "elapsed", "out", "tokens", "reported", "accepted"], rows)


def lens_stats(reviews):
    by_lens = collections.defaultdict(list)
    for rev in reviews:
        by_lens[rev["lens"]].append(rev)
    out = []
    for lens, passes in by_lens.items():
        passes.sort(key=lambda r: (r.get("date") or "", r.get("started_at") or ""))
        tokens = sum(r["tokens"] or 0 for r in passes)
        accepted = sum(r["accepted_bm"] or 0 for r in passes)
        measured = [r for r in passes if r["accepted_bm"] is not None]
        since_last = 0
        for rev in reversed(measured):
            if rev["accepted_bm"]:
                break
            since_last += 1
        out.append({
            "lens": lens, "passes": len(passes), "measured": len(measured), "tokens": tokens,
            "output_tokens": sum(r["output_tokens"] or 0 for r in passes), "accepted_bm": accepted,
            "bm_per_mtok": (accepted / tokens * 1_000_000) if tokens else None,
            "passes_since_accepted": since_last,
            "runs": len({r["run_id"] for r in passes}),
        })
    out.sort(key=lambda s: (-(s["accepted_bm"]), s["lens"]))
    return out


def show_lenses(tables):
    rows = [[s["lens"][:40], s["passes"], s["measured"], s["runs"], fmt_k(s["tokens"]), fmt_k(s["output_tokens"]),
             s["accepted_bm"], "-" if s["bm_per_mtok"] is None else f"{s['bm_per_mtok']:.2f}",
             s["passes_since_accepted"]] for s in lens_stats(tables["reviews"])]
    print_table(["lens", "passes", "measured", "runs", "tokens", "out", "acc B+M", "B+M/Mtok", "dry streak"], rows)
    print("\nmeasured = passes with an accepted B/M/m count; dry streak = measured passes since the last accepted B/M")


def phase_rows(steps):
    return [s for s in steps if s.get("kind") == "phase"]


def phase_medians(steps, key):
    """median of <key> per (lane, phase) over phase rows with a value."""
    groups = collections.defaultdict(list)
    for row in phase_rows(steps):
        value = row.get(key)
        if value not in (None, "") and row.get("lane"):
            groups[(row["lane"], str(row["phase"]))].append(value)
    return {k: statistics.median(v) for k, v in groups.items() if v}


def show_phases(tables):
    steps = tables["steps"]
    for key in ("wall_s", "output", "cache_write"):
        medians = phase_medians(steps, key)
        rows = []
        for (lane, phase), median in sorted(medians.items(), key=lambda kv: (kv[0][0], phase_sort(kv[0][1]))):
            values = [r[key] for r in phase_rows(steps) if r.get("lane") == lane and str(r["phase"]) == phase
                      and r.get(key) not in (None, "")]
            fmt = fmt_s if key.endswith("_s") else fmt_k
            rows.append([lane, phase, len(values), fmt(median), fmt(max(values)), fmt(min(values))])
        print(f"\n{key} per phase (phase rows)")
        print_table(["lane", "phase", "n", "median", "max", "min"], rows)


def phase_sort(phase):
    try:
        return (0, int(phase))
    except (TypeError, ValueError):
        return (1, str(phase))


def retro_candidates(tables):
    """The same rules the dashboard computes: evidence for skill changes."""
    out = []
    steps = tables["steps"]
    for key in ("wall_s", "output"):
        medians = phase_medians(steps, key)
        for row in phase_rows(steps):
            value = row.get(key)
            if value in (None, "") or not row.get("lane"):
                continue
            median = medians.get((row["lane"], str(row["phase"])))
            if median and value > RETRO_PHASE_FACTOR * median and value >= RETRO_PHASE_FLOOR[key]:
                fmt = fmt_s if key.endswith("_s") else fmt_k
                out.append({"rule": f"phase over 2x lane median ({key})", "run_id": row["run_id"],
                            "detail": f"phase {row['phase']} {key} {fmt(value)} vs median {fmt(median)} "
                                      f"for lane {row['lane']}"})
    for stat in lens_stats(tables["reviews"]):
        if stat["measured"] >= RETRO_LENS_PASSES and stat["passes_since_accepted"] >= RETRO_LENS_PASSES:
            out.append({"rule": f"lens dry for {RETRO_LENS_PASSES}+ passes", "run_id": None,
                        "detail": f"{stat['lens']}: {stat['passes_since_accepted']} measured passes without an "
                                  f"accepted B/M ({fmt_k(stat['tokens'])} tokens over {stat['passes']} passes)"})
    for row in steps:
        if row.get("kind") == "task" and (row.get("active_s") or 0) > RETRO_TASK_ACTIVE_S:
            out.append({"rule": "task over 10 min active", "run_id": row["run_id"],
                        "detail": f"{row.get('step')} active {fmt_s(row['active_s'])}, out {fmt_k(row.get('output'))}"
                                  f" [{row.get('model')}]"})
    for run in tables["runs"]:
        totals = run.get("step_totals") or {}
        wall, wait = totals.get("wall_s"), totals.get("human_wait_s")
        if wall and wait and wait > RETRO_HUMAN_WAIT_SHARE * wall:
            out.append({"rule": "human wait over 25% of wall", "run_id": run["run_id"],
                        "detail": f"wait {fmt_s(wait)} of wall {fmt_s(wall)} ({wait / wall:.0%})"})
    return out


def show_retro(tables):
    candidates = retro_candidates(tables)
    if not candidates:
        with_steps = sum(1 for r in tables["runs"] if r["has_steps"])
        measured = sum(1 for r in tables["reviews"] if r["accepted_bm"] is not None)
        print(f"no retro candidates: {with_steps} runs with step metrics, {measured} review passes with accepted "
              f"counts; rules need a lane median (2+ runs per lane), {RETRO_LENS_PASSES}+ measured passes per lens, "
              f"task rows, or run totals")
        return
    rows = [[c["rule"], c["run_id"] or "-", c["detail"]] for c in candidates]
    print_table(["rule", "run", "detail"], rows)


def show_failures(tables):
    rows = []
    for run in tables["runs"]:
        failures = run["failures"]
        if not any(failures.values()) and not run["papercuts"]:
            continue
        rows.append([run.get("date") or "-", run["run_id"][:40], *(failures[k] or "" for k in FAILURE_CLASSES),
                     ", ".join(f"{k}x{v}" for k, v in sorted(run["papercuts"].items()))])
    print_table(["date", "run", *(k.replace("_", " ") for k in FAILURE_CLASSES), "papercuts"], rows)
    if not rows:
        print("no failures or papercuts recorded on any run")


def cmd_show(args):
    home = pathlib.Path(args.home).expanduser() if args.home else SKILL_HOME
    tables = load_tables(home)
    if args.json:
        payload = {"retro": retro_candidates(tables), "lenses": lens_stats(tables["reviews"]),
                   "runs": len(tables["runs"])}
        print(json.dumps(payload, indent=1))
        return 0
    if args.run:
        show_run(tables, args.run)
        return 0
    any_view = False
    if args.lenses:
        show_lenses(tables)
        any_view = True
    if args.phases:
        show_phases(tables)
        any_view = True
    if args.failures:
        show_failures(tables)
        any_view = True
    if args.retro:
        show_retro(tables)
        any_view = True
    if not any_view:
        show_runs(tables, None if args.all else SHOW_DEFAULT_RUNS)
    return 0


def add_subcommands(sub):
    rollup = sub.add_parser("rollup", help="build runs/_rollup/{runs,steps,reviews}.json across runs")
    rollup.add_argument("--home", help="skill directory holding runs/, metrics.csv, step-metrics.csv")
    rollup.add_argument("--papercuts", help="papercuts.md path (default ~/code/papercuts.md)")
    rollup.set_defaults(func=cmd_rollup)
    show = sub.add_parser("show", help="text views over the rollup tables")
    show.add_argument("--home")
    show.add_argument("--run", help="one run id or folder: phases, agents, tasks, review passes")
    show.add_argument("--all", action="store_true", help=f"every run (default: last {SHOW_DEFAULT_RUNS})")
    show.add_argument("--lenses", action="store_true", help="reviewer value per lens")
    show.add_argument("--phases", action="store_true", help="per-phase medians and extremes per lane")
    show.add_argument("--failures", action="store_true", help="failure classes and papercuts per run")
    show.add_argument("--retro", action="store_true", help="retro candidates (same rules as the dashboard)")
    show.add_argument("--json", action="store_true", help="retro candidates and lens stats as JSON")
    show.set_defaults(func=cmd_show)


SKILL_HOME = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PAPERCUTS = pathlib.Path.home() / "code" / "papercuts.md"
