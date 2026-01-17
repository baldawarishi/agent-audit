"""SQLite database operations for Claude Code archive."""

import sqlite3
from pathlib import Path
from typing import Optional

from .models import Message, Session, ToolCall, ToolResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT,
    cwd TEXT,
    git_branch TEXT,
    started_at TEXT,
    ended_at TEXT,
    claude_version TEXT,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    total_cache_read_tokens INTEGER,
    model TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    parent_uuid TEXT,
    type TEXT,
    timestamp TEXT,
    content TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    message_id TEXT REFERENCES messages(id),
    session_id TEXT REFERENCES sessions(id),
    tool_name TEXT,
    input_json TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS tool_results (
    id TEXT PRIMARY KEY,
    tool_call_id TEXT REFERENCES tool_calls(id),
    session_id TEXT REFERENCES sessions(id),
    content TEXT,
    is_error BOOLEAN,
    timestamp TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_results_session ON tool_results(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
"""


class Database:
    """SQLite database for storing archived sessions."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Connect to the database and ensure schema exists."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        return self.conn

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def session_exists(self, session_id: str) -> bool:
        """Check if a session already exists in the database."""
        conn = self.connect()
        cursor = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        return cursor.fetchone() is not None

    def insert_session(self, session: Session):
        """Insert a session and all its related data."""
        conn = self.connect()

        # Insert session
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (id, project, cwd, git_branch, started_at, ended_at, claude_version,
             total_input_tokens, total_output_tokens, total_cache_read_tokens, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.project,
                session.cwd,
                session.git_branch,
                session.started_at,
                session.ended_at,
                session.claude_version,
                session.total_input_tokens,
                session.total_output_tokens,
                session.total_cache_read_tokens,
                session.model,
            ),
        )

        # Insert messages
        for message in session.messages:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (id, session_id, parent_uuid, type, timestamp, content, model, input_tokens, output_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.parent_uuid,
                    message.type,
                    message.timestamp,
                    message.content,
                    message.model,
                    message.input_tokens,
                    message.output_tokens,
                ),
            )

        # Insert tool calls
        for tool_call in session.tool_calls:
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_calls
                (id, message_id, session_id, tool_name, input_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_call.id,
                    tool_call.message_id,
                    tool_call.session_id,
                    tool_call.tool_name,
                    tool_call.input_json,
                    tool_call.timestamp,
                ),
            )

        # Insert tool results
        for tool_result in session.tool_results:
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_results
                (id, tool_call_id, session_id, content, is_error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_result.id,
                    tool_result.tool_call_id,
                    tool_result.session_id,
                    tool_result.content,
                    tool_result.is_error,
                    tool_result.timestamp,
                ),
            )

        conn.commit()

    def get_session_ids(self) -> list[str]:
        """Get all session IDs in the database."""
        conn = self.connect()
        cursor = conn.execute("SELECT id FROM sessions")
        return [row["id"] for row in cursor.fetchall()]

    def get_sessions_by_project(self, project: str) -> list[dict]:
        """Get all sessions for a project."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE project = ? ORDER BY started_at DESC",
            (project,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_sessions_by_date_range(self, start_date: str, end_date: str) -> list[dict]:
        """Get sessions within a date range."""
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT * FROM sessions
            WHERE started_at >= ? AND started_at < ?
            ORDER BY started_at DESC
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_all_sessions(self) -> list[dict]:
        """Get all sessions."""
        conn = self.connect()
        cursor = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def get_messages_for_session(self, session_id: str) -> list[dict]:
        """Get all messages for a session ordered by timestamp."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_tool_calls_for_session(self, session_id: str) -> list[dict]:
        """Get all tool calls for a session."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_tool_results_for_session(self, session_id: str) -> list[dict]:
        """Get all tool results for a session."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM tool_results WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get overall archive statistics."""
        conn = self.connect()

        stats = {}

        cursor = conn.execute("SELECT COUNT(*) as count FROM sessions")
        stats["total_sessions"] = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM messages")
        stats["total_messages"] = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM tool_calls")
        stats["total_tool_calls"] = cursor.fetchone()["count"]

        cursor = conn.execute(
            "SELECT SUM(total_input_tokens) as total FROM sessions"
        )
        row = cursor.fetchone()
        stats["total_input_tokens"] = row["total"] or 0

        cursor = conn.execute(
            "SELECT SUM(total_output_tokens) as total FROM sessions"
        )
        row = cursor.fetchone()
        stats["total_output_tokens"] = row["total"] or 0

        cursor = conn.execute("SELECT DISTINCT project FROM sessions")
        stats["projects"] = [row["project"] for row in cursor.fetchall()]

        return stats
