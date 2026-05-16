"""Read-only churn-score spike (Step 1).

Throwaway standalone script to validate the churn premise on a real
archive/sessions.db before building any mining framework. No writes,
no JSON output, no new dependencies.

    churn = sequences * (1 + fail_count / total_calls)

where a "sequence" is a maximal run of tool calls whose consecutive
timestamps are within --gap seconds of each other (gap logic mirrors
debrief._build_timeline_summary). Run:

    uv run python scripts/01_churn_spike.py [--db PATH] [--gap 120] [--top 20]
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from agent_audit.database import Database

DEFAULT_DB = Path(__file__).resolve().parent.parent / "archive" / "sessions.db"


def parse_ts(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp; return None for missing/unparseable input."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def count_sequences(calls: list[dict], gap_seconds: float) -> int:
    """Count maximal runs of tool calls within ``gap_seconds`` of each other.

    A missing/unparseable timestamp on either side of a pair is treated as
    a gap break (start a new sequence) rather than crashing.
    """
    if not calls:
        return 0
    sequences = 1
    prev_dt = parse_ts(calls[0].get("timestamp"))
    for call in calls[1:]:
        curr_dt = parse_ts(call.get("timestamp"))
        if prev_dt is None or curr_dt is None:
            sequences += 1
        elif (curr_dt - prev_dt).total_seconds() > gap_seconds:
            sequences += 1
        prev_dt = curr_dt
    return sequences


def fail_count(calls: list[dict], results: list[dict]) -> int:
    """Count tool calls in this session whose result is flagged is_error.

    A call with no matching result is not a failure.
    """
    call_ids = {c["id"] for c in calls}
    failing = {
        r.get("tool_call_id")
        for r in results
        if r.get("is_error") and r.get("tool_call_id") in call_ids
    }
    return len(failing)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2


def score_session(session: dict, db: Database, gap_seconds: float) -> dict | None:
    """Compute churn for one session, or None if it has no tool calls."""
    sid = session["id"]
    calls = db.get_tool_calls_for_session(sid)
    total = len(calls)
    if total == 0:
        return None
    results = db.get_tool_results_for_session(sid)
    sequences = count_sequences(calls, gap_seconds)
    fails = fail_count(calls, results)
    fail_ratio = fails / total
    return {
        "session_id": sid,
        "project": session.get("project") or "",
        "total": total,
        "sequences": sequences,
        "fail_count": fails,
        "fail_ratio": fail_ratio,
        "churn": sequences * (1 + fail_ratio),
    }


@click.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB,
              show_default=True, help="Path to sessions.db.")
@click.option("--gap", default=120.0, show_default=True,
              help="Max seconds between calls to stay in the same sequence.")
@click.option("--top", default=20, show_default=True,
              help="How many of the churniest sessions to print.")
def main(db_path: Path, gap: float, top: int) -> None:
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    rows: list[dict] = []
    with Database(db_path) as db:
        sessions = db.get_all_sessions()
        for session in sessions:
            row = score_session(session, db, gap)
            if row is not None:
                rows.append(row)

    scanned = len(sessions)
    with_calls = len(rows)
    if not rows:
        click.echo(f"Scanned {scanned} sessions; none had tool calls.")
        return

    rows.sort(key=lambda r: r["churn"], reverse=True)

    header = (
        f"{'session':8}  {'project':30}  {'total':>5}  {'seqs':>5}  "
        f"{'fails':>5}  {'fail%':>6}  {'churn':>8}"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for r in rows[:top]:
        click.echo(
            f"{r['session_id'][:8]:8}  {r['project'][:30]:30}  "
            f"{r['total']:>5}  {r['sequences']:>5}  {r['fail_count']:>5}  "
            f"{r['fail_ratio'] * 100:>5.1f}%  {r['churn']:>8.2f}"
        )

    click.echo("-" * len(header))
    click.echo(
        f"sessions scanned: {scanned}  |  with tool calls: {with_calls}  |  "
        f"median churn: {median([r['churn'] for r in rows]):.2f}"
    )


if __name__ == "__main__":
    main()
