"""The seam every mining query reads through, and its AgentsView side.

``SessionSource`` names the three methods the whole miner layer touches;
``Database`` (database.py:331/346/355) already satisfies it structurally, so
``AgentsViewSource`` is a drop-in over the DuckDB mirror
(``agentsview duckdb push`` -> ``~/.agentsview/sessions.duckdb``) and no query
function changes. Mirror facts this relies on were measured in Step 1: the
only per-call clock is ``messages.timestamp`` (joins 11058/11058 calls),
``tool_calls.id`` is always NULL, and ``(session_id, message_id, call_index)``
is unique while ``(session_id, tool_use_id)`` is not.
"""

from __future__ import annotations

from collections.abc import Container
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .failures import looks_like_error

DEFAULT_MIRROR_PATH = Path.home() / ".agentsview" / "sessions.duckdb"


@runtime_checkable
class SessionSource(Protocol):
    """The read surface a mining query is allowed to use."""

    def get_all_sessions(self) -> list[dict]:
        ...

    def get_tool_calls_for_session(self, session_id: str) -> list[dict]:
        ...

    def get_tool_results_for_session(self, session_id: str) -> list[dict]:
        ...


def _iso(value: Any) -> Any:
    """DuckDB hands back ``datetime``; ``churn.parse_ts`` wants ISO text."""
    return value.isoformat() if hasattr(value, "isoformat") else value


def error_flag(content: str | None) -> bool | None:
    """The mirror's per-call fail signal: read the text, or admit ignorance.

    No result text means **unknown**, never ``False`` -- opencode and
    antigravity carry none at all (Step 1: 0/281, 0/1359 calls).
    """
    return looks_like_error(content) if (content or "").strip() else None


def fail_signal(
    results: list[dict], call_ids: Container[Any]
) -> tuple[set[Any], set[Any]]:
    """Split result rows into (calls this source judged, calls that failed).

    ``is_error`` is tri-state across the seam: True/False are measurements,
    ``None`` is "cannot tell" and counts as neither.
    """
    measured: set[Any] = set()
    failing: set[Any] = set()
    for result in results:
        cid = result.get("tool_call_id")
        if cid not in call_ids or result.get("is_error") is None:
            continue
        measured.add(cid)
        if result.get("is_error"):
            failing.add(cid)
    return measured, failing


def call_id(session_id: str, message_id: Any, call_index: Any) -> str:
    """Synthesize the call id the mirror does not store.

    ``tool_calls.id`` is NULL for every row, and ``tool_use_id`` collides
    (5 antigravity rows), so the unique triple is the key (Step 1).
    """
    return f"{session_id}:{message_id}:{call_index}"


class AgentsViewSource:
    """Read-only, bulk-loaded view of the AgentsView DuckDB mirror.

    Three queries at construction, then dict lookups -- never one query per
    session; the per-session fan-out is exactly what leaving the ``session``
    API was meant to avoid.
    """

    def __init__(self, path: Path | str = DEFAULT_MIRROR_PATH) -> None:
        import duckdb  # imported here so archive-only commands never pay for it

        self.path = Path(path)
        conn = duckdb.connect(str(self.path), read_only=True)
        try:
            self._sessions = self._load_sessions(conn)
            self._calls = self._load_calls(conn, self._message_clock(conn))
        finally:
            conn.close()

    def __enter__(self) -> AgentsViewSource:
        """Context-manager parity with ``Database``; the load already happened."""
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    @staticmethod
    def _load_sessions(conn: Any) -> list[dict]:
        """Ordered by ``id`` -- ``started_at`` is NULL on real rows (Step 2)."""
        rows = conn.execute(
            "select id, project, agent, started_at from sessions order by id"
        ).fetchall()
        return [
            {"id": sid, "project": project, "agent": agent,
             "started_at": _iso(started_at)}
            for sid, project, agent, started_at in rows
        ]

    @staticmethod
    def _message_clock(conn: Any) -> dict[Any, Any]:
        return {
            mid: _iso(ts)
            for mid, ts in conn.execute(
                "select id, timestamp from messages"
            ).fetchall()
        }

    @staticmethod
    def _load_calls(conn: Any, clock: dict[Any, Any]) -> dict[str, list[dict]]:
        """Index calls by session, ordered by ``(timestamp, call_index)``.

        Calls sharing one message share its timestamp, so ``call_index`` is
        what keeps their within-message order stable.
        """
        rows = conn.execute(
            "select session_id, message_id, call_index, tool_use_id, "
            "tool_name, input_json, result_content from tool_calls"
        ).fetchall()
        calls: dict[str, list[dict]] = {}
        for sid, message_id, call_index, tool_use_id, name, inp, result in rows:
            calls.setdefault(sid, []).append({
                "id": call_id(sid, message_id, call_index),
                "session_id": sid,
                "message_id": message_id,
                "call_index": call_index,
                "tool_use_id": tool_use_id,
                "tool_name": name,
                "input_json": inp,
                "timestamp": clock.get(message_id),
                "result_content": result,
            })
        for session_calls in calls.values():
            session_calls.sort(
                key=lambda c: (c["timestamp"] or "", c["call_index"])
            )
        return calls

    def get_all_sessions(self) -> list[dict]:
        """Every mirrored session, including agents we never parsed ourselves."""
        return list(self._sessions)

    def get_tool_calls_for_session(self, session_id: str) -> list[dict]:
        """Timestamp-ordered calls, matching the archive's contract."""
        return list(self._calls.get(session_id, ()))

    def get_tool_results_for_session(self, session_id: str) -> list[dict]:
        """Result text per call, with ``is_error`` read out of that text.

        The mirror has no error flag, so the text detector is the signal
        (Step 4) and ``None`` survives wherever there is no text to read.
        """
        return [
            {
                "tool_call_id": call["id"],
                "tool_use_id": call["tool_use_id"],
                "session_id": session_id,
                "is_error": error_flag(call["result_content"]),
                "content": call["result_content"],
                "timestamp": call["timestamp"],
            }
            for call in self._calls.get(session_id, ())
        ]
