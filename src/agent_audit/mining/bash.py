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
"""

from __future__ import annotations

import json
import re
import shlex

from ..database import Database

# Matched against tool_name.lower(). Evidence-backed (real archive:
# Bash / bash / run_shell_command) plus codex_parser's local_shell_call
# fallback (codex_parser.py:217). Deliberately not a generic ``*shell*``
# match -- KillShell / run_experiment are not command runners.
_BASH_TOOL_NAMES = frozenset({"bash", "run_shell_command", "local_shell_call"})

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
    # Truncate to the first stage: each cut removes text at/after the
    # first separator found, so the earliest separator (of any kind)
    # ultimately wins regardless of which we scan for first.
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


def bash_subcommands_query(db: Database) -> dict:
    """Aggregate bash subcommands fleet-wide; return ``{name, meta, rows}``.

    One bash-family ``tool_call`` contributes exactly one to its
    subcommand's ``count`` (per-call tally -- distinct from Step-4's
    per-*result* tally). A call is "failing" if it has *any* ``is_error``
    result, so ``fail_rate`` is failing-calls / calls. ``rows`` is sorted
    count-descending, ties broken by ``subcommand`` ascending, and is
    **not** truncated -- top-N is a CLI presentation concern.
    """
    sessions = db.get_all_sessions()
    agg: dict[str, dict] = {}
    bash_calls = 0

    for session in sessions:
        sid = session["id"]
        call_sub: dict[str, str] = {}
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
        failing = {
            r.get("tool_call_id")
            for r in db.get_tool_results_for_session(sid)
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
            "fail_rate": e["fail"] / e["count"] if e["count"] else 0.0,
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
        },
        "rows": rows,
    }
