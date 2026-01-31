"""SQLite database operations for Claude Code archive."""

import sqlite3
from pathlib import Path
from typing import Optional

from .models import Session

# Tables schema - run first (CREATE TABLE IF NOT EXISTS won't modify existing tables)
SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT,
    cwd TEXT,
    git_branch TEXT,
    slug TEXT,
    summary TEXT,
    title TEXT,
    parent_session_id TEXT,
    started_at TEXT,
    ended_at TEXT,
    claude_version TEXT,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    total_cache_read_tokens INTEGER,
    model TEXT,
    is_warmup BOOLEAN DEFAULT FALSE,
    is_sidechain BOOLEAN DEFAULT FALSE,
    github_repo TEXT,
    session_context TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    parent_uuid TEXT,
    type TEXT,
    timestamp TEXT,
    content TEXT,
    thinking TEXT,
    model TEXT,
    stop_reason TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    is_sidechain BOOLEAN DEFAULT FALSE,
    is_compact_summary BOOLEAN DEFAULT FALSE,
    has_images BOOLEAN DEFAULT FALSE
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

CREATE TABLE IF NOT EXISTS commits (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    commit_hash TEXT,
    message TEXT,
    timestamp TEXT
);
"""

# Indexes - run after migrations so columns exist
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_results_session ON tool_results(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_github_repo ON sessions(github_repo);
CREATE INDEX IF NOT EXISTS idx_commits_session ON commits(session_id);
CREATE INDEX IF NOT EXISTS idx_commits_hash ON commits(commit_hash);
"""

# Migrations for existing databases (columns added in Phase 1)
MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN slug TEXT",
    "ALTER TABLE sessions ADD COLUMN summary TEXT",
    "ALTER TABLE messages ADD COLUMN thinking TEXT",
    "ALTER TABLE messages ADD COLUMN stop_reason TEXT",
    "ALTER TABLE messages ADD COLUMN is_sidechain BOOLEAN DEFAULT FALSE",
    # Phase 2: Agent relationships
    "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT",
    # Phase 3: Warmup/sidechain session detection
    "ALTER TABLE sessions ADD COLUMN is_warmup BOOLEAN DEFAULT FALSE",
    "ALTER TABLE sessions ADD COLUMN is_sidechain BOOLEAN DEFAULT FALSE",
    # Phase 4: Additional fields from claude-code-transcripts
    "ALTER TABLE sessions ADD COLUMN title TEXT",
    "ALTER TABLE sessions ADD COLUMN github_repo TEXT",
    "ALTER TABLE sessions ADD COLUMN session_context TEXT",
    "ALTER TABLE messages ADD COLUMN is_compact_summary BOOLEAN DEFAULT FALSE",
    "ALTER TABLE messages ADD COLUMN has_images BOOLEAN DEFAULT FALSE",
    # Create commits table if it doesn't exist (handled by schema, but migration ensures index)
    """CREATE TABLE IF NOT EXISTS commits (
        id TEXT PRIMARY KEY,
        session_id TEXT REFERENCES sessions(id),
        commit_hash TEXT,
        message TEXT,
        timestamp TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_github_repo ON sessions(github_repo)",
    "CREATE INDEX IF NOT EXISTS idx_commits_session ON commits(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_commits_hash ON commits(commit_hash)",
]


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
            # 1. Create tables first
            self.conn.executescript(SCHEMA_TABLES)
            # 2. Run migrations to add new columns to existing tables
            for migration in MIGRATIONS:
                try:
                    self.conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # Column/table already exists
            # 3. Create indexes after migrations (so new columns exist)
            self.conn.executescript(SCHEMA_INDEXES)
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
            (id, project, cwd, git_branch, slug, summary, title, parent_session_id, started_at, ended_at,
             claude_version, total_input_tokens, total_output_tokens, total_cache_read_tokens, model,
             is_warmup, is_sidechain, github_repo, session_context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.project,
                session.cwd,
                session.git_branch,
                session.slug,
                session.summary,
                session.title,
                session.parent_session_id,
                session.started_at,
                session.ended_at,
                session.claude_version,
                session.total_input_tokens,
                session.total_output_tokens,
                session.total_cache_read_tokens,
                session.model,
                session.is_warmup,
                session.is_sidechain,
                session.github_repo,
                session.session_context,
            ),
        )

        # Insert messages
        for message in session.messages:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (id, session_id, parent_uuid, type, timestamp, content, thinking, model,
                 stop_reason, input_tokens, output_tokens, is_sidechain, is_compact_summary, has_images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.parent_uuid,
                    message.type,
                    message.timestamp,
                    message.content,
                    message.thinking,
                    message.model,
                    message.stop_reason,
                    message.input_tokens,
                    message.output_tokens,
                    message.is_sidechain,
                    message.is_compact_summary,
                    message.has_images,
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

        # Insert commits
        for commit in session.commits:
            conn.execute(
                """
                INSERT OR REPLACE INTO commits
                (id, session_id, commit_hash, message, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    commit.id,
                    commit.session_id,
                    commit.commit_hash,
                    commit.message,
                    commit.timestamp,
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

    def get_commits_for_session(self, session_id: str) -> list[dict]:
        """Get all commits for a session."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM commits WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_sessions_by_github_repo(self, github_repo: str) -> list[dict]:
        """Get all sessions associated with a GitHub repo."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE github_repo = ? ORDER BY started_at DESC",
            (github_repo,),
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

        cursor = conn.execute("SELECT COUNT(*) as count FROM commits")
        stats["total_commits"] = cursor.fetchone()["count"]

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

        cursor = conn.execute("SELECT DISTINCT github_repo FROM sessions WHERE github_repo IS NOT NULL")
        stats["github_repos"] = [row["github_repo"] for row in cursor.fetchall()]

        return stats

    def get_child_sessions(self, parent_session_id: str) -> list[dict]:
        """Get all sessions that have the given session as their parent."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE parent_session_id = ? ORDER BY started_at",
            (parent_session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_session_tree(self, session_id: str) -> dict:
        """Get a session and all its descendants as a tree structure.

        Returns:
            dict with keys: 'session' (the session data) and 'children' (list of child trees)
        """
        conn = self.connect()
        cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session_row = cursor.fetchone()
        if not session_row:
            return {}

        session = dict(session_row)
        children = self.get_child_sessions(session_id)

        return {
            "session": session,
            "children": [self.get_session_tree(child["id"]) for child in children],
        }

    def get_root_sessions(self) -> list[dict]:
        """Get all sessions that have no parent (root sessions)."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE parent_session_id IS NULL ORDER BY started_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_project_metrics(self, project: str) -> dict:
        """Get aggregate metrics for a project.

        Returns dict with:
            - session_count: number of sessions
            - turn_count: number of user+assistant pairs
            - total_input_tokens: sum of input tokens across sessions
            - total_output_tokens: sum of output tokens across sessions
            - tool_call_count: total tool calls
        """
        conn = self.connect()

        # Session count and token totals
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) as session_count,
                COALESCE(SUM(total_input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(total_output_tokens), 0) as total_output_tokens
            FROM sessions WHERE project = ?
            """,
            (project,),
        )
        row = cursor.fetchone()
        session_count = row["session_count"]
        total_input_tokens = row["total_input_tokens"]
        total_output_tokens = row["total_output_tokens"]

        # Turn count: count user messages (each user message pairs with an assistant response)
        cursor = conn.execute(
            """
            SELECT COUNT(*) as turn_count
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE s.project = ? AND m.type = 'user'
            """,
            (project,),
        )
        turn_count = cursor.fetchone()["turn_count"]

        # Tool call count
        cursor = conn.execute(
            """
            SELECT COUNT(*) as tool_call_count
            FROM tool_calls tc
            JOIN sessions s ON tc.session_id = s.id
            WHERE s.project = ?
            """,
            (project,),
        )
        tool_call_count = cursor.fetchone()["tool_call_count"]

        return {
            "session_count": session_count,
            "turn_count": turn_count,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "tool_call_count": tool_call_count,
        }

    def get_warmup_stats(self) -> dict:
        """Get statistics about warmup/sidechain sessions."""
        conn = self.connect()

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM sessions WHERE is_warmup = 1"
        )
        warmup_count = cursor.fetchone()["count"]

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM sessions WHERE is_sidechain = 1"
        )
        sidechain_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM sessions")
        total_count = cursor.fetchone()["count"]

        return {
            "total_sessions": total_count,
            "warmup_sessions": warmup_count,
            "sidechain_sessions": sidechain_count,
            "regular_sessions": total_count - warmup_count,
        }

    def get_global_percentiles(self) -> dict:
        """Get global percentile statistics across all sessions.

        Returns dict with:
            - p50_msgs, p75_msgs, p90_msgs: message count percentiles
            - p50_tokens, p75_tokens, p90_tokens: output token percentiles
        """
        conn = self.connect()

        # Get session stats with message counts
        cursor = conn.execute(
            """
            WITH session_stats AS (
                SELECT
                    s.id,
                    COUNT(m.id) as msg_count,
                    COALESCE(s.total_output_tokens, 0) as output_tokens
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                HAVING msg_count > 0
            ),
            ranked AS (
                SELECT
                    msg_count,
                    output_tokens,
                    ROW_NUMBER() OVER (ORDER BY msg_count) as msg_rank,
                    ROW_NUMBER() OVER (ORDER BY output_tokens) as token_rank,
                    COUNT(*) OVER () as total
                FROM session_stats
            )
            SELECT
                MAX(CASE WHEN msg_rank = CAST(total * 0.50 AS INT) OR
                         (total * 0.50 < 1 AND msg_rank = 1) THEN msg_count END) as p50_msgs,
                MAX(CASE WHEN msg_rank = CAST(total * 0.75 AS INT) OR
                         (total * 0.75 < 1 AND msg_rank = 1) THEN msg_count END) as p75_msgs,
                MAX(CASE WHEN msg_rank = CAST(total * 0.90 AS INT) OR
                         (total * 0.90 < 1 AND msg_rank = 1) THEN msg_count END) as p90_msgs,
                MAX(CASE WHEN token_rank = CAST(total * 0.50 AS INT) OR
                         (total * 0.50 < 1 AND token_rank = 1) THEN output_tokens END) as p50_tokens,
                MAX(CASE WHEN token_rank = CAST(total * 0.75 AS INT) OR
                         (total * 0.75 < 1 AND token_rank = 1) THEN output_tokens END) as p75_tokens,
                MAX(CASE WHEN token_rank = CAST(total * 0.90 AS INT) OR
                         (total * 0.90 < 1 AND token_rank = 1) THEN output_tokens END) as p90_tokens
            FROM ranked
            """
        )
        row = cursor.fetchone()

        return {
            "p50_msgs": row["p50_msgs"] or 0,
            "p75_msgs": row["p75_msgs"] or 0,
            "p90_msgs": row["p90_msgs"] or 0,
            "p50_tokens": row["p50_tokens"] or 0,
            "p75_tokens": row["p75_tokens"] or 0,
            "p90_tokens": row["p90_tokens"] or 0,
        }

    def get_project_session_stats(self, project: str) -> dict:
        """Get session statistics for a specific project.

        Returns dict with:
            - avg_msgs, min_msgs, max_msgs: message count stats
            - avg_tokens, min_tokens, max_tokens: output token stats
        """
        conn = self.connect()

        cursor = conn.execute(
            """
            WITH session_stats AS (
                SELECT
                    s.id,
                    COUNT(m.id) as msg_count,
                    COALESCE(s.total_output_tokens, 0) as output_tokens
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                WHERE s.project = ?
                GROUP BY s.id
                HAVING msg_count > 0
            )
            SELECT
                COALESCE(CAST(ROUND(AVG(msg_count)) AS INT), 0) as avg_msgs,
                COALESCE(MIN(msg_count), 0) as min_msgs,
                COALESCE(MAX(msg_count), 0) as max_msgs,
                COALESCE(CAST(ROUND(AVG(output_tokens)) AS INT), 0) as avg_tokens,
                COALESCE(MIN(output_tokens), 0) as min_tokens,
                COALESCE(MAX(output_tokens), 0) as max_tokens
            FROM session_stats
            """,
            (project,),
        )
        row = cursor.fetchone()

        return {
            "avg_msgs": row["avg_msgs"] or 0,
            "min_msgs": row["min_msgs"] or 0,
            "max_msgs": row["max_msgs"] or 0,
            "avg_tokens": row["avg_tokens"] or 0,
            "min_tokens": row["min_tokens"] or 0,
            "max_tokens": row["max_tokens"] or 0,
        }
