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

``bash_sequences_query`` (``05_bash_sequences``) is a sharper lens on the
same motif: identical consecutive-trigram aggregation, but bash-family
calls are first expanded to their subcommand via the Step-5 primitives
(``first_token``/``_command_text``), so the opaque ``Bash→Bash→Bash``
resolves into a *named* loop (``bash:cargo→bash:cargo→bash:cargo``
failing-build retry vs ``bash:git→bash:git→bash:git``). Bash-expanded
tokens are ``bash:``-prefixed so they never collide with a real tool
literally named like a subcommand (real archive: a ``grep`` tool exists);
an empty command (``input_json == "{}"``) becomes ``bash:?`` so the call
keeps its stream position -- skipping it would splice non-adjacent
neighbours into a false trigram. ``04_tool_sequences`` is left untouched:
it is the verbatim baseline carrying the cross-agent ``Bash`` vs ``bash``
finding; the expansion is enrichment via already-mined Step-5 logic, not
normalization of the baseline.
"""

from __future__ import annotations

from .bash import _BASH_TOOL_NAMES, _command_text, first_token
from .source import SessionSource


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


def tool_sequences_query(db: SessionSource) -> dict:
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
        # Tool name verbatim; ``or ""`` only NULL-guards the later join --
        # an empty name is itself a finding, not something to normalize.
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


def _expand_call(call: dict) -> str:
    """One call -> its stream token: bash-family expanded, else verbatim.

    Bash-family (Step-5 ``_BASH_TOOL_NAMES``, matched on ``tool_name``
    lower-cased) -> ``bash:<subcommand>`` via the Step-5
    ``first_token``/``_command_text`` primitives. An empty/unparseable
    command (real archive: many lowercase-``bash`` rows are ``{}``) ->
    ``bash:?`` so the call keeps its position in the stream -- dropping it
    would splice its non-adjacent neighbours into a false trigram. The
    ``bash:`` prefix keeps an expanded token from colliding with a real
    tool literally named like a subcommand (archive has a ``grep`` tool).
    Non-bash tool names are verbatim (``Bash`` vs ``bash`` discipline);
    ``or ""`` only NULL-guards the later ``→``.join.
    """
    if (call.get("tool_name") or "").lower() in _BASH_TOOL_NAMES:
        return "bash:" + (
            first_token(_command_text(call.get("input_json"))) or "?"
        )
    return call.get("tool_name") or ""


def bash_sequences_query(db: SessionSource) -> dict:
    """Bash-subcommand-expanded tool trigrams; return ``{name, meta, rows}``.

    Identical aggregation to ``tool_sequences_query`` (consecutive
    ``trigrams`` over the timestamp-ordered per-session stream, fleet-wide
    ``count`` + **distinct-session** tally, sorted count-desc then trigram
    asc, **not** truncated) -- the only difference is each call is run
    through ``_expand_call`` first, so ``Bash→Bash→Bash`` resolves into a
    named loop. ``04_tool_sequences`` is intentionally left as the
    untouched verbatim baseline; this is the sharper, actionable lens.
    """
    sessions = db.get_all_sessions()
    agg: dict[tuple[str, str, str], dict] = {}
    sessions_with_3plus = 0

    for session in sessions:
        sid = session["id"]
        stream = [
            _expand_call(c) for c in db.get_tool_calls_for_session(sid)
        ]
        tris = trigrams(stream)
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
        "name": "05_bash_sequences",
        "meta": {
            "sessions_scanned": len(sessions),
            "sessions_with_3plus_calls": sessions_with_3plus,
            "distinct_trigrams": len(agg),
        },
        "rows": rows,
    }
