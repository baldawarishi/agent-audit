"""Bash-subcommand distribution query (mined finding ``03_bash_subcommands``).

The article's core technique: pull the command out of every bash-family
tool call, take its first real token (the subcommand), and aggregate
fleet-wide so the failing-bash mass behind churn (Step-4: 78.6% of
failures are bash ``Exit code 1``) is named by *which* subcommands
dominate it.

``first_token`` reports the first real token **verbatim** (case kept,
no smart-rewrite) -- ``cd``/subshells/heredocs are findings to interpret
downstream, not a license to normalize here (mirrors the churn-formula
discipline).

``exec_command`` (codex) joined the bash family in Step 3: it carries
``cmd``, which ``_command_text`` already reads (``first_token`` recovered
400/400 in the Step-1 probe). Its sibling ``exec`` stays **out** -- that
tool's ``input_json`` is raw JavaScript, not JSON, so it is not a shell
runner (``first_token`` 0/400).
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

from .source import SessionSource

# Matched against tool_name.lower(); evidence-backed, deliberately not a
# generic ``*shell*`` match (KillShell / run_experiment are not runners).
_BASH_TOOL_NAMES = frozenset(
    {"bash", "run_shell_command", "local_shell_call", "exec_command"}
)

# Printed and stored verbatim wherever ``fail_rate`` comes back ``None``.
NO_FAIL_SIGNAL = "fail_rate unknown: source carries no is_error flag (Step 4 backfills)"

# Wrapper words: the real subcommand is the next token after these.
_WRAPPERS = frozenset({"sudo", "env", "time", "exec", "nohup", "command"})

# A leading ``NAME=value`` shell env assignment (NAME is a shell ident).
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Earliest of these ends the first pipeline / sequence stage.
_STAGE_SEPS = ("|", "&&", ";", "\n")


def _command_text(input_json: str | None) -> str:
    """Best-effort pull the command string out of a tool_call input_json.

    Real archive shape is top-level ``command``; codex's non-JSON
    arguments fall back to ``{"arguments": "..."}``. Malformed / missing
    -> "" so the caller skips it (never crashes, never miscounts).
    """
    if not input_json:
        return ""
    try:
        obj = json.loads(input_json)
    except (ValueError, TypeError):
        return ""
    if not isinstance(obj, dict):
        return ""
    for key in ("command", "cmd"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v
    args = obj.get("arguments")
    if isinstance(args, dict):
        v = args.get("command")
        if isinstance(v, str) and v.strip():
            return v
    elif isinstance(args, str) and args.strip():
        return args
    return ""


def first_token(command: str | None) -> str:
    """First real subcommand token, verbatim. Empty/None/unparseable -> "".

    Strips leading ``VAR=val`` env assignments and wrapper words
    (sudo/env/time/exec/nohup/command), then returns the first token of
    the first pipeline / ``&&`` / ``;`` stage with surrounding quotes
    removed. Case is preserved (shell commands are case-sensitive).
    ``cd``, subshells and heredocs are returned as-is -- those are
    findings to interpret downstream, not normalized away here.
    """
    if not command:
        return ""
    text = command.strip()
    if not text:
        return ""
    # Cut at the earliest separator: each cut drops everything after the
    # first hit, so scan order does not matter.
    for sep in _STAGE_SEPS:
        idx = text.find(sep)
        if idx != -1:
            text = text[:idx]
    text = text.strip()
    if not text:
        return ""
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for tok in tokens:
        if _ENV_ASSIGN.match(tok) or tok in _WRAPPERS:
            continue
        return tok
    return ""


def _fail_rate(entry: dict, known: bool) -> float | None:
    """Failing-calls / calls, or ``None`` when the source has no fail signal.

    Unknown must stay ``None``: a computed-looking ``0.0`` would read as
    "measured, nothing failed" (see ``NO_FAIL_SIGNAL``).
    """
    if not known:
        return None
    return entry["fail"] / entry["count"] if entry["count"] else 0.0


def bash_subcommands_query(db: SessionSource) -> dict:
    """Aggregate bash subcommands fleet-wide; return ``{name, meta, rows}``.

    One bash-family ``tool_call`` contributes exactly one to its
    subcommand's ``count`` (per-call tally -- distinct from Step-4's
    per-*result* tally). A call is "failing" if it has *any* ``is_error``
    result, so ``fail_rate`` is failing-calls / calls -- unless the source
    never reports ``is_error`` at all (the AgentsView mirror), in which case
    every ``fail_rate`` is ``None`` and ``meta`` says why. ``rows`` is sorted
    count-descending, ties broken by ``subcommand`` ascending, and is
    **not** truncated -- top-N is a CLI presentation concern.
    """
    sessions = db.get_all_sessions()
    agg: dict[str, dict] = {}
    bash_calls = 0
    fail_signal = False

    for session in sessions:
        sid = session["id"]
        # Keys are untyped row ids; ``Any`` spares the lookup below a cast.
        call_sub: dict[Any, str] = {}
        for c in db.get_tool_calls_for_session(sid):
            if (c.get("tool_name") or "").lower() not in _BASH_TOOL_NAMES:
                continue
            sub = first_token(_command_text(c.get("input_json")))
            if not sub:
                continue
            bash_calls += 1
            call_sub[c["id"]] = sub
            entry = agg.setdefault(
                sub, {"count": 0, "sessions": set(), "fail": 0}
            )
            entry["count"] += 1
            entry["sessions"].add(sid)
        if not call_sub:
            continue
        results = db.get_tool_results_for_session(sid)
        # One non-None ``is_error`` anywhere means the source can measure
        # fail_rate; all-None (the mirror) means it cannot.
        fail_signal = fail_signal or any(
            r.get("is_error") is not None for r in results
        )
        failing = {
            r.get("tool_call_id")
            for r in results
            if r.get("is_error") and r.get("tool_call_id") in call_sub
        }
        for cid in failing:
            agg[call_sub[cid]]["fail"] += 1

    rows = [
        {
            "subcommand": sub,
            "count": e["count"],
            "sessions": len(e["sessions"]),
            "calls_per_session": (
                e["count"] / len(e["sessions"]) if e["sessions"] else 0.0
            ),
            "fail_rate": _fail_rate(e, fail_signal),
        }
        for sub, e in agg.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["subcommand"]))
    return {
        "name": "03_bash_subcommands",
        "meta": {
            "sessions_scanned": len(sessions),
            "bash_calls": bash_calls,
            "distinct_subcommands": len(agg),
            "fail_rate_known": fail_signal,
            "fail_rate_note": None if fail_signal else NO_FAIL_SIGNAL,
        },
        "rows": rows,
    }
