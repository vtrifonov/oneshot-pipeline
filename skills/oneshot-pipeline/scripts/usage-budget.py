#!/usr/bin/env python3
"""Weekly usage budget for the Phase 0 run-options recommendation.

Reads the seven-day window from the claude-session-hub usage snapshot
(~/.local/state/claude-session-hub/usage/<account>.json, written by the
statusline) and prints one JSON object:

  used_pct, resets_at, working_days_left, per_day_pct, pace, source

pace is "ample" (>= 20% of the weekly limit per remaining working day),
"tight" (10-20%) or "low" (< 10%). Working days are Mon-Fri from today
(always counted) up to the reset; a later day counts only if the reset
falls after 09:00 local on it. Minimum 1.

Override or supply data by hand with --used PCT --resets ISO8601.
Exits 0 with source="unavailable" when nothing can be read.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys

DAILY_TARGET = 20.0
LOW_FLOOR = 10.0


def account_id():
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    name = pathlib.Path(config).name if config else ""
    return name.removeprefix(".claude-") if name.startswith(".claude-") else None


def read_snapshot(account):
    if not account:
        return None
    path = pathlib.Path.home() / ".local/state/claude-session-hub/usage" / f"{account}.json"
    try:
        window = json.loads(path.read_text())["windows"]["seven_day"]
        return float(window["utilization"]), window["resetsAt"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def working_days(now, resets):
    days = 0
    day = now.date()
    while day <= resets.date():
        workday_start = dt.datetime.combine(day, dt.time(9), now.tzinfo)
        if day.weekday() < 5 and (day == now.date() or workday_start < resets):
            days += 1
        day += dt.timedelta(days=1)
    return max(days, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--used", type=float)
    parser.add_argument("--resets")
    args = parser.parse_args()

    source = "manual"
    used, resets_raw = args.used, args.resets
    if used is None or resets_raw is None:
        snapshot = read_snapshot(account_id())
        if snapshot is None:
            print(json.dumps({"source": "unavailable"}))
            return 0
        source = "snapshot"
        used = snapshot[0] if used is None else used
        resets_raw = snapshot[1] if resets_raw is None else resets_raw

    now = dt.datetime.now().astimezone()
    resets = dt.datetime.fromisoformat(resets_raw.replace("Z", "+00:00")).astimezone()
    days = working_days(now, resets)
    per_day = max(0.0, 100.0 - used) / days
    pace = "ample" if per_day >= DAILY_TARGET else "tight" if per_day >= LOW_FLOOR else "low"
    print(json.dumps({
        "used_pct": used,
        "resets_at": resets.isoformat(timespec="minutes"),
        "working_days_left": days,
        "per_day_pct": round(per_day, 1),
        "pace": pace,
        "source": source,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
