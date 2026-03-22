"""Tests for OpenCode parser."""

import json
import sqlite3
from pathlib import Path

from agent_audit.opencode_parser import (
    parse_opencode_session,
    discover_opencode_sessions,
)
from agent_audit.database import Database


def _create_opencode_db(db_path: Path, sessions: list[dict] | None = None):
    """Create a minimal OpenCode SQLite database for testing."""
    conn = sqlite3.connect(db_path)

    conn.executescript("""
        CREATE TABLE project (
            id TEXT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            parent_id TEXT,
            slug TEXT NOT NULL,
            directory TEXT NOT NULL,
            title TEXT NOT NULL,
            version TEXT NOT NULL,
            share_url TEXT,
            summary_additions INTEGER,
            summary_deletions INTEGER,
            summary_files INTEGER,
            summary_diffs TEXT,
            revert TEXT,
            permission TEXT,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            time_compacting INTEGER,
            time_archived INTEGER,
            workspace_id TEXT,
            FOREIGN KEY (project_id) REFERENCES project(id)
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES session(id)
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL,
            FOREIGN KEY (message_id) REFERENCES message(id)
        );
    """)

    # Insert a default project
    conn.execute("INSERT INTO project (id, name) VALUES ('proj1', 'test-project')")

    if sessions is None:
        sessions = [_default_session()]

    for s in sessions:
        conn.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (s["id"], "proj1", s.get("slug", "default"), s["directory"],
             s["title"], "1.0", s["time_created"], s["time_updated"]),
        )
        for msg in s.get("messages", []):
            conn.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
                (msg["id"], s["id"], msg["time_created"], msg["time_created"], json.dumps(msg["data"])),
            )
            for part in msg.get("parts", []):
                conn.execute(
                    "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (part["id"], msg["id"], s["id"], msg["time_created"], msg["time_created"],
                     json.dumps(part["data"])),
                )

    conn.commit()
    conn.close()


def _default_session() -> dict:
    return {
        "id": "ses_test001",
        "directory": "/Users/dev/workspaces/my-project",
        "title": "Fix bug in parser",
        "slug": "fix-bug",
        "time_created": 1704067200000,  # 2024-01-01T00:00:00Z
        "time_updated": 1704067260000,  # +60 seconds
        "messages": [
            {
                "id": "msg_user1",
                "time_created": 1704067200000,
                "data": {
                    "role": "user",
                    "time": {"created": 1704067200000},
                    "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4-5"},
                },
                "parts": [
                    {
                        "id": "prt_1",
                        "data": {"type": "text", "text": "Fix the bug in parser.py"},
                    },
                ],
            },
            {
                "id": "msg_asst1",
                "time_created": 1704067210000,
                "data": {
                    "role": "assistant",
                    "time": {"created": 1704067210000},
                    "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4-5"},
                    "usage": {"input": 200, "output": 150},
                },
                "parts": [
                    {
                        "id": "prt_2",
                        "data": {"type": "reasoning", "text": "Let me analyze the parser code..."},
                    },
                    {
                        "id": "prt_3",
                        "data": {"type": "text", "text": "I found and fixed the bug."},
                    },
                    {
                        "id": "prt_4",
                        "data": {
                            "type": "tool-invocation",
                            "toolName": "readFile",
                            "toolInvocationId": "tool_1",
                            "input": {"path": "parser.py"},
                            "result": {"content": "def parse(): pass"},
                            "state": "success",
                        },
                    },
                ],
            },
        ],
    }


class TestBasicParsing:
    def test_session_metadata(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "workspaces-my-project", db_path=db_path)

        assert session.id == "ses_test001"
        assert session.project == "workspaces-my-project"
        assert session.agent_type == "opencode"
        assert session.cwd == "/Users/dev/workspaces/my-project"
        assert session.title == "Fix bug in parser"
        assert session.model == "claude-sonnet-4-5"
        assert session.claude_version == "opencode-anthropic"

    def test_messages_parsed(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        user_msgs = [m for m in session.messages if m.type == "user"]
        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert len(user_msgs) == 1
        assert "Fix the bug" in user_msgs[0].content
        assert len(asst_msgs) == 1
        assert "found and fixed" in asst_msgs[0].content

    def test_thinking_from_reasoning_parts(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert asst_msgs[0].thinking == "Let me analyze the parser code..."

    def test_tool_calls_extracted(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        assert len(session.tool_calls) == 1
        assert session.tool_calls[0].tool_name == "readFile"
        parsed = json.loads(session.tool_calls[0].input_json)
        assert parsed["path"] == "parser.py"

    def test_tool_results_extracted(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        assert len(session.tool_results) == 1
        assert "def parse()" in session.tool_results[0].content

    def test_token_counts(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        assert session.total_input_tokens == 200
        assert session.total_output_tokens == 150

    def test_timestamps_set(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        assert session.started_at is not None
        assert session.ended_at is not None


class TestDiscovery:
    def test_discover_finds_sessions(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        found = list(discover_opencode_sessions(db_path=db_path))
        assert len(found) == 1
        sid, proj = found[0]
        assert sid == "ses_test001"
        # Project name derived from cwd using Claude Code convention
        assert proj == "workspaces-my-project"

    def test_discover_multiple_sessions(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        sessions = [
            {
                "id": "ses_a",
                "directory": "/code/alpha",
                "title": "Session A",
                "time_created": 1704067200000,
                "time_updated": 1704067260000,
                "messages": [],
            },
            {
                "id": "ses_b",
                "directory": "/code/beta",
                "title": "Session B",
                "time_created": 1704067300000,
                "time_updated": 1704067360000,
                "messages": [],
            },
        ]
        _create_opencode_db(db_path, sessions)

        found = list(discover_opencode_sessions(db_path=db_path))
        assert len(found) == 2

    def test_discover_missing_db_returns_empty(self, tmp_path):
        found = list(discover_opencode_sessions(db_path=tmp_path / "nonexistent.db"))
        assert len(found) == 0


class TestErrorSession:
    def test_tool_error_state(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        session_data = _default_session()
        # Replace tool part with error state
        session_data["messages"][1]["parts"][2] = {
            "id": "prt_err",
            "data": {
                "type": "tool-invocation",
                "toolName": "writeFile",
                "toolInvocationId": "tool_err",
                "input": {"path": "bad.py"},
                "result": {"error": "permission denied"},
                "state": "error",
            },
        }
        _create_opencode_db(db_path, [session_data])

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)

        assert len(session.tool_results) == 1
        assert session.tool_results[0].is_error is True


class TestWarmupDetection:
    def test_warmup_detected(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        session_data = {
            "id": "ses_warmup",
            "directory": "/tmp",
            "title": "Warmup",
            "time_created": 1704067200000,
            "time_updated": 1704067200000,
            "messages": [
                {
                    "id": "msg_w",
                    "time_created": 1704067200000,
                    "data": {"role": "user"},
                    "parts": [{"id": "prt_w", "data": {"type": "text", "text": "Warmup"}}],
                },
            ],
        }
        _create_opencode_db(db_path, [session_data])

        session = parse_opencode_session("ses_warmup", "proj", db_path=db_path)
        assert session.is_warmup is True

    def test_normal_not_warmup(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        _create_opencode_db(db_path)

        session = parse_opencode_session("ses_test001", "proj", db_path=db_path)
        assert session.is_warmup is False


class TestDatabaseRoundTrip:
    def test_opencode_session_stores_and_reads(self, tmp_path):
        oc_db = tmp_path / "opencode.db"
        _create_opencode_db(oc_db)

        session = parse_opencode_session("ses_test001", "my-project", db_path=oc_db)

        audit_db = Database(tmp_path / "audit.db")
        with audit_db:
            audit_db.insert_session(session)

            assert audit_db.session_exists(session.id)

            sessions = audit_db.get_all_sessions()
            assert len(sessions) == 1
            assert sessions[0]["agent_type"] == "opencode"
            assert sessions[0]["title"] == "Fix bug in parser"

            messages = audit_db.get_messages_for_session(session.id)
            assert len(messages) == 2

            tool_calls = audit_db.get_tool_calls_for_session(session.id)
            assert len(tool_calls) == 1
