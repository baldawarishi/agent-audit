"""Cross-session tool-sequence trigrams (mined finding ``04_tool_sequences``).

The *motif* behind the churn: per session take the timestamp-ordered
tool-name stream, slice it into consecutive 3-grams, and aggregate
fleet-wide so the Step-1 fragmentation finding + the Step-5 failing
build/test mass surface as a concrete repeated loop (e.g.
``Read→Edit→Bash``).

Trigram definition is a verbatim port of ``debrief._analyze_tool_patterns``
(debrief.py:403-404): a *consecutive* window of 3 over the ordered stream
-- no skip-gram, no dedup (repeats are signal). Tool names are taken
**verbatim** -- ``Bash`` vs ``bash`` is NOT normalized; cross-agent name
variance is a finding to interpret downstream, not normalized away here
(mirrors the Step-5 verbatim discipline). No time-gap segmentation and no
fail attribution: both are deliberately deferred (see plan Step 6/7).
"""

from __future__ import annotations

from ..database import Database


def trigrams(tool_names: list[str]) -> list[tuple[str, str, str]]:
    """Consecutive 3-grams over the ordered stream; ``len < 3`` -> ``[]``.

    Pure and deterministic. No skip-gram and no dedup -- a tool repeated
    back-to-back yields a repeated trigram on purpose (that *is* the
    retry-loop signal we are mining).
    """
    return [
        (tool_names[i], tool_names[i + 1], tool_names[i + 2])
        for i in range(len(tool_names) - 2)
    ]


def tool_sequences_query(db: Database) -> dict:
    """Aggregate tool trigrams fleet-wide; return ``{name, meta, rows}``.

    Per session: the timestamp-ordered tool-name stream
    (``get_tool_calls_for_session`` is already ``ORDER BY timestamp``) ->
    ``trigrams`` -> tally a fleet-wide ``count`` (every occurrence) and a
    **distinct-session** tally (a trigram seen N times in one session is
    ``count`` +N but ``sessions`` +1 -- distinct from naive per-occurrence
    session counting). ``rows`` is sorted count-descending, ties broken by
    ``trigram`` ascending, and is **not** truncated -- top-N is a CLI
    presentation concern (Step-5 resolution).
    """
    sessions = db.get_all_sessions()
    agg: dict[tuple[str, str, str], dict] = {}
    sessions_with_3plus = 0

    for session in sessions:
        sid = session["id"]
        # Tool name verbatim; ``or ""`` only guards a NULL row from
        # crashing the later ``→``.join -- an empty name is itself a
        # finding, not normalized (mirrors bash.py's defensive tally).
        names = [
            (c.get("tool_name") or "")
            for c in db.get_tool_calls_for_session(sid)
        ]
        tris = trigrams(names)
        if not tris:
            continue
        sessions_with_3plus += 1
        for tri in tris:
            entry = agg.setdefault(tri, {"count": 0, "sessions": set()})
            entry["count"] += 1
            entry["sessions"].add(sid)

    rows = [
        {
            "trigram": "→".join(tri),
            "count": e["count"],
            "sessions": len(e["sessions"]),
        }
        for tri, e in agg.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["trigram"]))
    return {
        "name": "04_tool_sequences",
        "meta": {
            "sessions_scanned": len(sessions),
            "sessions_with_3plus_calls": sessions_with_3plus,
            "distinct_trigrams": len(agg),
        },
        "rows": rows,
    }
