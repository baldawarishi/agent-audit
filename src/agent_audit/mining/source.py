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

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
        """Result text per call, with ``is_error`` deliberately left unknown.

        The mirror has no error flag; choosing the text signal is Step 4's
        call, and a ``False`` here would silently zero ``01_churn``'s fail term.
        """
        return [
            {
                "tool_call_id": call["id"],
                "tool_use_id": call["tool_use_id"],
                "session_id": session_id,
                "is_error": None,
                "content": call["result_content"],
                "timestamp": call["timestamp"],
            }
            for call in self._calls.get(session_id, ())
        ]
