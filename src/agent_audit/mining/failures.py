"""Failure-classification query (mined finding ``02_failure_classification``).

Deterministically buckets every ``is_error`` tool result so the fleet's
failure surface is measurable. ``classify_error`` is a pure,
ordered-first-match classifier; order is load-bearing (``auth``/``not_found``
must win over the bare ``http_client`` ``400`` rule). ``looks_like_error``
answers the prior question -- *is* this result a failure -- for sources that
carry result text but no error flag (the AgentsView mirror).

Step 5 widened ``looks_like_error`` past its Claude-shaped head anchor to the
trailing exit-code line gemini and pi print. That changes what "fail" counts,
so it is a recorded deviation (it moves ``01``'s fail term too), never a
silent reweight. codex needs no needle: its 120 result heads all read
``Exit code: 0``, so its zero failures is a measurement.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # source.py imports looks_like_error, so the seam is type-only
    from .source import SessionSource

# Ported verbatim from the Step-1 probe, where it scored precision 1.000 /
# recall 0.989 against our archive's is_error on the joined Claude sessions.
_EXIT_CODE = re.compile(r"^exit code:? (\d+)", re.I)

# claude and codex *lead* with the code; gemini and pi print it as a trailing
# status line below the output, where the head anchor above cannot see it.
_TRAILING_EXIT = re.compile(
    r"^(?:exit code|command exited with code):?[ \t]*(\d+)[ \t]*$", re.I | re.M
)

# The last three are Step-5 per-agent needles: pi rejects malformed tool
# arguments and directory reads, gemini reports an aborted web search.
_ERROR_MARKERS = (
    "<tool_use_error>",
    "api error:",
    "the user doesn't want to proceed",
    "socket hang up",
    "timeout of ",
    "validation failed for tool",
    "eisdir",
    "error: error during web search",
)


def looks_like_error(content: str | None) -> bool:
    """Does this result text report a failure?

    Only ever asked of calls that *have* result text: textless calls are
    unknown (``is_error=None``), and answering False for them would be a
    silent claim that nothing failed.
    """
    head = (content or "").strip().lower()[:400]
    if not head:
        return False
    exit_code = _EXIT_CODE.match(head)
    if exit_code:
        return exit_code.group(1) != "0"
    if any(marker in head for marker in _ERROR_MARKERS):
        return True
    return _trailing_exit_failed(content or "")


def _trailing_exit_failed(content: str) -> bool:
    """Did the *last* trailing exit-code line report a nonzero code?

    Scans the whole text, not the head: gemini's line sits below arbitrarily
    long output (measured as far as 40 KB in), and the last one is the call's.
    """
    codes = _TRAILING_EXIT.findall(content)
    return bool(codes) and codes[-1] != "0"


# First match wins, so auth/not_found precede http_client (401/404 beat 400).
# Codes use (?<!\.)\b...\b to reject "0xdd68d8d4000" and "3.400", keeping "404.".
_ERROR_RULES: list[tuple[str, tuple[str, ...], re.Pattern | None]] = [
    ("auth",
     ("unauthorized", "forbidden", "permission denied"),
     re.compile(r"(?<!\.)\b(?:401|403)\b")),
    ("not_found",
     ("not found", "no such file"),
     re.compile(r"(?<!\.)\b404\b")),
    ("http_client",
     ("bad request",),
     re.compile(r"(?<!\.)\b400\b")),
    ("timeout",
     ("timeout", "timed out", "deadline exceeded"),
     None),
    ("pdf",
     ("pandoc", "xelatex", "latex"),
     None),
]


def _rule_hits(text: str, needles: tuple[str, ...], code: re.Pattern | None) -> bool:
    return any(n in text for n in needles) or bool(code and code.search(text))


def classify_error(content: str | None) -> str:
    """Bucket one error result's content; ``other`` is the fallback."""
    text = (content or "").lower()
    for bucket, needles, code in _ERROR_RULES:
        if _rule_hits(text, needles, code):
            return bucket
    if text.strip().startswith("error:") or (
        "traceback (most recent call last)" in text
    ):
        return "runtime"
    return "other"


def _example(content: str | None, bucket: str) -> str:
    """First line that *evidences* ``bucket``, stripped, capped at 120 chars.

    Bash results lead with a generic ``Exit code 1`` line; the line proving
    the bucket is below it. Return the first line containing the matched
    substring (or the runtime trigger). ``other`` and unmatched fall back
    to the first non-empty line.
    """
    lines = [s for s in (ln.strip() for ln in (content or "").splitlines()) if s]
    if not lines:
        return ""
    rule = next(((n, c) for b, n, c in _ERROR_RULES if b == bucket), None)
    if rule is not None:
        needles, code = rule
        for ln in lines:
            if _rule_hits(ln.lower(), needles, code):
                return ln[:120]
    elif bucket == "runtime":
        for ln in lines:
            low = ln.lower()
            if low.startswith("error:") or (
                "traceback (most recent call last)" in low
            ):
                return ln[:120]
    return lines[0][:120]


def agent_of(session: dict) -> str:
    """The session's agent under either store's column name."""
    return session.get("agent") or session.get("agent_type") or "unknown"


def counting_note(results: int, calls: int) -> str | None:
    """Say so when a store repeats one call's result across several rows.

    ``02`` tallies per *result*, and the archive stores a call's result once
    per message it survives (37 rows for one pi call), so the two stores'
    ``total_failures`` are not comparable -- ``failing_calls`` is.
    """
    if results <= calls:
        return None
    return (
        f"counted per result row: {results} results over {calls} calls, so "
        f"total_failures repeats a call's error -- failing_calls is per call"
    )


def signal_note(judged: int, scanned: int) -> str | None:
    """Name the fail-signal coverage; ``None`` when every result was judged."""
    if judged >= scanned:
        return None
    return (
        f"error signal on {judged}/{scanned} results; the other "
        f"{scanned - judged} carry no result text and count as non-failing"
    )


def coverage_note(agents: list[dict]) -> str | None:
    """Name every agent this source reports zero failures for, and why.

    Two different blind spots, both a ceiling rather than a finding: nothing
    readable to judge (mirror opencode/antigravity) versus judged and never
    flagged (archive codex/opencode).
    """
    parts = [
        f"{a['agent']} (0 of {a['judged']} judged)" if a["judged"]
        else f"{a['agent']} (0 of {a['results']} results readable)"
        for a in agents if not a["failures"]
    ]
    return "no failures reported for: " + ", ".join(parts) if parts else None


def failures_query(db: SessionSource, *, examples: int = 1) -> dict:
    """Classify every error result and return the ``{name, meta, rows}`` envelope.

    A session with N error results contributes N to ``total_failures`` (a
    call producing multiple error results counts each), so ``failing_calls``
    is the number that compares across stores. ``rows`` is sorted
    count-descending, ties broken by ``bucket`` ascending for determinism.
    """
    sessions = db.get_all_sessions()
    buckets: dict[str, dict] = {}
    total_failures = 0
    sessions_with_errors = 0
    seen = {"results": 0, "judged": 0, "calls": 0, "failing_calls": 0}
    per_agent: dict[str, dict] = {}

    for session in sessions:
        sid = session["id"]
        agent = per_agent.setdefault(
            agent_of(session),
            {"agent": agent_of(session), "results": 0, "judged": 0, "failures": 0},
        )
        calls: set = set()
        failing: set = set()
        for r in db.get_tool_results_for_session(sid):
            seen["results"] += 1
            agent["results"] += 1
            calls.add(r.get("tool_call_id"))
            if r.get("is_error") is not None:
                seen["judged"] += 1
                agent["judged"] += 1
            if not r.get("is_error"):
                continue
            total_failures += 1
            agent["failures"] += 1
            failing.add(r.get("tool_call_id"))
            content = r.get("content")
            bucket = classify_error(content)
            b = buckets.setdefault(
                bucket,
                {"count": 0, "sessions": set(), "examples": []},
            )
            b["count"] += 1
            b["sessions"].add(sid)
            if len(b["examples"]) < examples:
                ex = _example(content, bucket)
                if ex:
                    b["examples"].append(ex)
        seen["calls"] += len(calls)
        seen["failing_calls"] += len(failing)
        if failing:
            sessions_with_errors += 1

    rows = [
        {
            "bucket": name,
            "count": b["count"],
            "pct_of_failures": (
                b["count"] / total_failures * 100 if total_failures else 0.0
            ),
            "sessions_affected": len(b["sessions"]),
            "examples": b["examples"],
        }
        for name, b in buckets.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["bucket"]))
    agents = sorted(per_agent.values(), key=lambda a: a["agent"])
    return {
        "name": "02_failure_classification",
        "meta": {
            "sessions_scanned": len(sessions),
            "sessions_with_errors": sessions_with_errors,
            "total_failures": total_failures,
            "failing_calls": seen["failing_calls"],
            "results_scanned": seen["results"],
            "results_judged": seen["judged"],
            "calls_with_results": seen["calls"],
            "agents": agents,
            "counting_note": counting_note(seen["results"], seen["calls"]),
            "signal_note": signal_note(seen["judged"], seen["results"]),
            "coverage_note": coverage_note(agents),
        },
        "rows": rows,
    }
