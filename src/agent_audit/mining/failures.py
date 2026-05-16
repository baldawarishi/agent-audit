"""Failure-classification query (mined finding ``02_failure_classification``).

Deterministically buckets every ``is_error`` tool result so the fleet's
failure surface is measurable. ``classify_error`` is a pure,
ordered-first-match classifier; order is load-bearing (``auth``/``not_found``
must win over the bare ``http_client`` ``400`` rule).
"""

from __future__ import annotations

import re

from ..database import Database

# Ordered: the FIRST rule that matches the lowered content wins. Keep
# auth/not_found before http_client so 401/404 beat 400. HTTP status codes
# use (?<!\.)\b...\b: \b rejects alnum-embedded substrings (e.g. "400"
# inside "0xdd68d8d4000") and the lookbehind rejects decimal fractions
# (e.g. "3.400") while still allowing trailing-period prose ("404.").
# Text phrases stay plain substrings. ``code`` is None when none apply.
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


def failures_query(db: Database, *, examples: int = 1) -> dict:
    """Classify every error result and return the ``{name, meta, rows}`` envelope.

    A session with N error results contributes N to ``total_failures`` (a
    call producing multiple error results counts each). ``rows`` is sorted
    count-descending, ties broken by ``bucket`` ascending for determinism.
    """
    sessions = db.get_all_sessions()
    buckets: dict[str, dict] = {}
    total_failures = 0
    sessions_with_errors = 0

    for session in sessions:
        sid = session["id"]
        session_had_error = False
        for r in db.get_tool_results_for_session(sid):
            if not r.get("is_error"):
                continue
            session_had_error = True
            total_failures += 1
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
        if session_had_error:
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
    return {
        "name": "02_failure_classification",
        "meta": {
            "sessions_scanned": len(sessions),
            "sessions_with_errors": sessions_with_errors,
            "total_failures": total_failures,
        },
        "rows": rows,
    }
