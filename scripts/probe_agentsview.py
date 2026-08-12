#!/usr/bin/env python3
"""Step-1 probe: answer the five mirror questions before any adapter exists.

Throwaway diagnostic. Run it with ``uv run --with duckdb python
scripts/probe_agentsview.py`` so the package gains no runtime dependency;
`duckdb` lands for real in Step 2 with ``AgentsViewSource``.
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
from pathlib import Path

import duckdb

from agent_audit.mining.bash import _command_text, first_token
from agent_audit.mining.churn import count_sequences
from agent_audit.mining.failures import classify_error

REPO = Path(__file__).resolve().parents[1]
MIRROR = Path.home() / ".agentsview" / "sessions.duckdb"
ARCHIVE = REPO / "archive" / "sessions.db"
GAP = 120.0

# Candidate error markers over ``tool_calls.result_content``; the mirror has no
# is_error flag, so text is the only signal (Step 0: status is unusable).
_EXIT = re.compile(r"^exit code:? (\d+)", re.I)
_MARKERS = (
    "<tool_use_error>",
    "api error:",
    "the user doesn't want to proceed",
    "socket hang up",
    "timeout of ",
)


def looks_like_error(content: str | None) -> bool:
    """Candidate replacement for ``tool_results.is_error``, text-only."""
    head = (content or "").strip().lower()[:400]
    if not head:
        return False
    exit_code = _EXIT.match(head)
    if exit_code:
        return exit_code.group(1) != "0"
    return any(marker in head for marker in _MARKERS)


def native_id(their_id: str) -> str:
    """Their ids are ``<agent>:<native>`` for every agent except Claude."""
    return their_id.split(":", 1)[1] if ":" in their_id else their_id


def q1_session_join(duck, lite) -> list[tuple[str, str, str]]:
    print("\n=== Q1 — do session ids join? ===")
    ours = {r[0] for r in lite.execute("select id from sessions")}
    theirs = duck.execute("select id, agent from sessions").fetchall()
    joined = [(tid, native_id(tid), ag) for tid, ag in theirs if native_id(tid) in ours]
    by_agent = collections.Counter(ag for _, _, ag in joined)
    verbatim = sum(1 for tid, _, _ in joined if ":" not in tid)
    for agent, total in sorted(collections.Counter(a for _, a in theirs).items()):
        theirs_only = [t for t, a in theirs if a == agent and native_id(t) not in ours]
        sample = theirs_only[0] if theirs_only else "-"
        print(f"  {agent:16} theirs={total:4} joined={by_agent[agent]:4} "
              f"theirs-only={len(theirs_only):3}  e.g. {sample}")
    print(f"  joined {len(joined)}/{len(theirs)} sessions "
          f"({verbatim} verbatim, {len(joined) - verbatim} after stripping 'agent:')")
    return joined


def _their_calls(duck, their_ids: list[str]) -> list[tuple]:
    return duck.execute(
        "select session_id, tool_use_id, tool_name, result_content "
        "from tool_calls where session_id = any(?)", [their_ids]
    ).fetchall()


def _our_results(lite, our_ids: list[str]) -> dict[str, tuple[bool, str]]:
    """``tool_call_id -> (is_error, error text)``, error rows preferred."""
    marks = ",".join("?" * len(our_ids))
    rows = lite.execute(
        f"select tool_call_id, max(is_error), min(content), "
        f"min(case when is_error then content end) from tool_results "
        f"where session_id in ({marks}) group by 1", our_ids
    )
    return {cid: (bool(err), (err_text if err else text) or "") for cid, err, text, err_text in rows}


def q2_error_signal(duck, lite, joined) -> None:
    print("\n=== Q2 — is the error signal recoverable from result_content? ===")
    for agent in sorted({a for _, _, a in joined}):
        their_ids = [t for t, _, a in joined if a == agent]
        truth = _our_results(lite, [o for _, o, a in joined if a == agent])
        theirs = {r[1]: r[3] or "" for r in _their_calls(duck, their_ids) if r[1] in truth}
        tp = fp = fn = agree = has_text = identical = textless = 0
        for cid, (is_err, our_text) in truth.items():
            if cid not in theirs:
                continue
            their_text = theirs[cid]
            predicted = looks_like_error(their_text)
            if is_err and their_text.strip():
                has_text += 1
                identical += their_text == our_text
            elif is_err:
                textless += not our_text.strip()
            if predicted and is_err:
                tp += 1
                agree += classify_error(their_text) == classify_error(our_text)
            elif predicted:
                fp += 1
            elif is_err:
                fn += 1
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        print(f"  {agent:9} calls={len(theirs):5}  our_errors={tp + fn:4}  "
              f"text_in_mirror={has_text:4}  identical_to_ours={identical:4}  "
              f"textless_in_both={textless:4}")
        print(f"            detector tp={tp:3} fp={fp:3} fn={fn:3}  precision={prec:5.3f} "
              f"recall={rec:5.3f}  bucket_agree={agree}/{tp or '-'}")
    print("  result_content presence / detector hit-rate, whole mirror:")
    totals: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for agent, text in duck.execute(
        "select s.agent, tc.result_content from tool_calls tc "
        "join sessions s on s.id = tc.session_id"
    ).fetchall():
        row = totals[agent]
        row[0] += 1
        row[1] += bool(text)
        row[2] += looks_like_error(text)
    for agent, (total, have, flagged) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        print(f"    {agent:16} text {have:5}/{total:5} ({have / total * 100:5.1f}%)  "
              f"flagged-as-error {flagged}")


def q3_per_call_clock(duck, lite, joined) -> None:
    print("\n=== Q3 — per-call clock (messages.timestamp vs our per-call one) ===")
    hist = duck.execute(
        "select n, count(*) from (select message_id, count(*) n from tool_calls "
        "group by 1) group by 1 order by 1"
    ).fetchall()
    calls = sum(n * c for n, c in hist)
    shared = sum(n * c for n, c in hist if n > 1)
    print(f"  calls per message: {dict(hist)}")
    print(f"  {shared}/{calls} calls ({shared / calls * 100:.1f}%) share a message clock")
    pairs = [(t, o) for t, o, a in joined if a == "claude"]
    by_session: dict[str, list[dict]] = collections.defaultdict(list)
    for sid, stamp in duck.execute(
        "select tc.session_id, m.timestamp from tool_calls tc join messages m "
        "on m.id = tc.message_id where tc.session_id = any(?) "
        "order by tc.session_id, m.timestamp, tc.call_index", [[t for t, _ in pairs]]
    ).fetchall():
        by_session[sid].append({"timestamp": stamp.isoformat()})
    same = ours_total = theirs_total = 0
    worst: list[tuple[int, str, int, int]] = []
    for their_id, our_id in pairs:
        our_calls = [
            {"timestamp": ts} for (ts,) in lite.execute(
                "select timestamp from tool_calls where session_id = ? order by timestamp",
                (our_id,),
            )
        ]
        mine = count_sequences(our_calls, GAP)
        theirs = count_sequences(by_session.get(their_id, []), GAP)
        ours_total += mine
        theirs_total += theirs
        same += mine == theirs
        worst.append((abs(mine - theirs), our_id, mine, theirs))
    worst.sort(reverse=True)
    print(f"  120s sequence A/B on {len(pairs)} joined Claude sessions: "
          f"{same} identical ({same / len(pairs) * 100:.0f}%), "
          f"totals ours={ours_total} message-clock={theirs_total}")
    print(f"  worst drift: {worst[:3]}")


def q4_input_shape(duck) -> None:
    print("\n=== Q4 — input_json shape by tool family ===")
    tools = duck.execute(
        "select tool_name, count(*) n from tool_calls group by 1 order by n desc limit 12"
    ).fetchall()
    for tool, total in tools:
        rows = duck.execute(
            "select input_json from tool_calls where tool_name = ? limit 400", [tool]
        ).fetchall()
        keys: collections.Counter = collections.Counter()
        recovered = 0
        for (raw,) in rows:
            try:
                obj = json.loads(raw or "")
            except ValueError:
                obj = None
            keys[",".join(sorted(obj)) if isinstance(obj, dict) else "<not-json>"] += 1
            if first_token(_command_text(raw)):
                recovered += 1
        shape = keys.most_common(1)[0][0] if keys else "-"
        print(f"  {tool:18} n={total:5}  keys={shape[:44]:46} "
              f"first_token ok {recovered}/{len(rows)}")


def q5_coverage(duck, lite, joined) -> None:
    print("\n=== Q5 — coverage / deletion verdict ===")
    alias = {"claude": "claude-code", "gemini": "gemini-cli"}
    ours = dict(lite.execute(
        "select agent_type, count(*) from sessions group by 1").fetchall())
    theirs = dict(duck.execute(
        "select agent, count(*) from sessions group by 1").fetchall())
    joined_by_agent = collections.Counter(a for _, _, a in joined)
    print("  agent            theirs   ours  ours-only  theirs-only")
    for agent, count in sorted(theirs.items(), key=lambda kv: -kv[1]):
        mine = ours.get(alias.get(agent, agent), 0)
        print(f"  {agent:16} {count:5} {mine:6} {mine - joined_by_agent[agent]:10} "
              f"{count - joined_by_agent[agent]:12}")
    print(f"  sessions only we hold: {sum(ours.values()) - len(joined)} "
          f"— unreconstructable if the archive is deleted")


def main() -> None:
    duck = duckdb.connect(str(MIRROR), read_only=True)
    lite = sqlite3.connect(f"file:{ARCHIVE}?mode=ro", uri=True)
    print(f"mirror={MIRROR}\narchive={ARCHIVE}")
    joined = q1_session_join(duck, lite)
    q2_error_signal(duck, lite, joined)
    q3_per_call_clock(duck, lite, joined)
    q4_input_shape(duck)
    q5_coverage(duck, lite, joined)


if __name__ == "__main__":
    main()
