"""Churn-score query (mined finding ``01_churn``).

The pure functions below are ported **verbatim** from the Step-1 spike
(commit ``3a3051a``); their logic is unchanged. The churn
formula is kept exactly as the reference article defines it — the
fragmentation / ``quamin`` skew is a finding to interpret downstream,
not a license to reweight here.

    churn = sequences * (1 + fail_count / total_calls)

A "sequence" is a maximal run of tool calls whose consecutive
timestamps are within ``gap`` seconds of each other in one session.
"""

from __future__ import annotations

from datetime import datetime

from ..database import Database


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


def churn_query(db: Database, *, gap: float = 120.0) -> dict:
    """Score every session and return the ``{name, meta, rows}`` envelope.

    ``rows`` is every session that had tool calls, sorted churn-descending
    and **not** truncated — top-N is a presentation concern for the CLI.
    """
    sessions = db.get_all_sessions()
    rows: list[dict] = []
    for session in sessions:
        row = score_session(session, db, gap)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["churn"], reverse=True)
    return {
        "name": "01_churn",
        "meta": {
            "gap": gap,
            "sessions_scanned": len(sessions),
            "sessions_with_calls": len(rows),
            "median_churn": median([r["churn"] for r in rows]),
        },
        "rows": rows,
    }
