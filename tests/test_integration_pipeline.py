"""Tests for the full parse → store → retrieve → render pipeline."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.models import Session, Message, ToolCall, ToolResult, Commit
from agent_audit.parser import parse_session
from agent_audit.codex_parser import parse_codex_session, get_session_id_from_filename
from agent_audit.toml_renderer import render_session_toml


CLAUDE_SESSION_JSONL = [
    # First entry: user message with session metadata
    {
        "type": "user",
        "uuid": "msg-user-001",
        "sessionId": "parent-session-abc",
        "timestamp": "2026-01-15T10:00:00Z",
        "cwd": "/home/dev/myproject",
        "gitBranch": "feature/login",
        "version": "2.3.1",
        "slug": "bright-coding-fox",
        "title": "Implement login flow",
        "session_context": {
            "outcomes": [
                {
                    "type": "git_repository",
                    "git_info": {"repo": "acme/myproject"},
                }
            ]
        },
        "message": {
            "role": "user",
            "content": "Add a login page with email and password",
        },
    },
    # Assistant message with thinking + tool call
    {
        "type": "assistant",
        "uuid": "msg-asst-001",
        "parentUuid": "msg-user-001",
        "timestamp": "2026-01-15T10:00:05Z",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-5-20251101",
            "content": [
                {"type": "thinking", "thinking": "I need to create a login component"},
                {"type": "text", "text": "I'll create the login page now."},
                {
                    "type": "tool_use",
                    "id": "toolu-write-001",
                    "name": "Write",
                    "input": {"file_path": "/home/dev/myproject/login.tsx", "content": "<Login />"},
                },
            ],
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_input_tokens": 100,
            },
            "stop_reason": "tool_use",
        },
    },
    # Tool result (comes as a "user" type entry with tool_result content)
    {
        "type": "user",
        "uuid": "msg-toolresult-001",
        "parentUuid": "msg-asst-001",
        "timestamp": "2026-01-15T10:00:06Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu-write-001",
                    "content": "[main abc1234] Add login page\nremote: https://github.com/acme/myproject/pull/new/feature/login",
                }
            ],
        },
    },
    # Final assistant response
    {
        "type": "assistant",
        "uuid": "msg-asst-002",
        "parentUuid": "msg-toolresult-001",
        "timestamp": "2026-01-15T10:00:10Z",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-5-20251101",
            "content": "The login page has been created.",
            "usage": {"input_tokens": 600, "output_tokens": 50, "cache_read_input_tokens": 0},
            "stop_reason": "end_turn",
        },
    },
]

CODEX_ROLLOUT_JSONL = [
    {
        "type": "session_meta",
        "timestamp": "2026-02-01T09:00:00Z",
        "payload": {
            "cwd": "/home/dev/codex-project",
            "cli_version": "0.5.2",
            "git": {
                "branch": "main",
                "repository_url": "https://github.com/acme/codex-project.git",
            },
        },
    },
    {
        "type": "turn_context",
        "timestamp": "2026-02-01T09:00:01Z",
        "payload": {"model": "o3-mini"},
    },
    # User message via event_msg
    {
        "type": "event_msg",
        "timestamp": "2026-02-01T09:00:02Z",
        "payload": {"type": "user_message", "message": "Fix the tests"},
    },
    # Same user message appears via response_item (should be deduped)
    {
        "type": "response_item",
        "timestamp": "2026-02-01T09:00:02Z",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Fix the tests"}],
        },
    },
    # Agent reasoning
    {
        "type": "event_msg",
        "timestamp": "2026-02-01T09:00:03Z",
        "payload": {"type": "agent_reasoning", "text": "Let me check the test failures"},
    },
    # Tool call
    {
        "type": "response_item",
        "timestamp": "2026-02-01T09:00:04Z",
        "payload": {
            "type": "function_call",
            "call_id": "call-001",
            "name": "shell",
            "arguments": '{"command": "pytest tests/"}',
        },
    },
    # Tool result with commit output
    {
        "type": "response_item",
        "timestamp": "2026-02-01T09:00:05Z",
        "payload": {
            "type": "function_call_output",
            "call_id": "call-001",
            "output": "[main def5678] Fix failing test assertions",
        },
    },
    # Token count
    {
        "type": "event_msg",
        "timestamp": "2026-02-01T09:00:06Z",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 150,
                    "cached_input_tokens": 50,
                }
            },
        },
    },
    # Agent message
    {
        "type": "event_msg",
        "timestamp": "2026-02-01T09:00:07Z",
        "payload": {"type": "agent_message", "message": "Tests are now passing."},
    },
]


def _write_jsonl(lines: list[dict], path: Path):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.connect()
    yield db
    db.close()
    db_path.unlink()


class TestClaudeCodePipeline:
    """End-to-end: JSONL → parse → store → retrieve → render."""

    def test_full_roundtrip_preserves_all_fields(self, db):
        """Every field survives the parse → store → retrieve round-trip."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            jsonl_path = Path(f.name)
        _write_jsonl(CLAUDE_SESSION_JSONL, jsonl_path)

        # Parse
        session = parse_session(jsonl_path, "myproject")
        jsonl_path.unlink()

        # Verify parse produced expected structure
        assert session.project == "myproject"
        assert session.cwd == "/home/dev/myproject"
        assert session.git_branch == "feature/login"
        assert session.slug == "bright-coding-fox"
        assert session.title == "Implement login flow"
        assert session.github_repo == "acme/myproject"
        assert session.parent_session_id == "parent-session-abc"
        assert session.model == "claude-opus-4-5-20251101"
        assert session.total_input_tokens == 1100  # 500 + 600
        assert session.total_output_tokens == 250  # 200 + 50
        assert session.total_cache_read_tokens == 100
        assert len(session.messages) == 4
        assert len(session.tool_calls) == 1
        assert len(session.tool_results) == 1
        assert len(session.commits) == 1
        assert session.commits[0].commit_hash == "abc1234"

        # Store
        db.insert_session(session)

        # Retrieve session
        rows = db.get_all_sessions()
        assert len(rows) == 1
        retrieved = rows[0]

        # Verify every session field survives storage
        assert retrieved["id"] == session.id
        assert retrieved["project"] == "myproject"
        assert retrieved["cwd"] == "/home/dev/myproject"
        assert retrieved["git_branch"] == "feature/login"
        assert retrieved["slug"] == "bright-coding-fox"
        assert retrieved["title"] == "Implement login flow"
        assert retrieved["github_repo"] == "acme/myproject"
        assert retrieved["parent_session_id"] == "parent-session-abc"
        assert retrieved["model"] == "claude-opus-4-5-20251101"
        assert retrieved["total_input_tokens"] == 1100
        assert retrieved["total_output_tokens"] == 250

        # Retrieve messages and verify field integrity
        messages = db.get_messages_for_session(session.id)
        assert len(messages) == 4
        # First message is user
        assert messages[0]["type"] == "user"
        assert messages[0]["content"] == "Add a login page with email and password"
        # Second is assistant with thinking
        assert messages[1]["type"] == "assistant"
        assert messages[1]["thinking"] == "I need to create a login component"
        assert messages[1]["stop_reason"] == "tool_use"
        assert messages[1]["model"] == "claude-opus-4-5-20251101"

        # Retrieve tool calls
        tool_calls = db.get_tool_calls_for_session(session.id)
        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "Write"
        assert json.loads(tool_calls[0]["input_json"])["file_path"] == "/home/dev/myproject/login.tsx"

        # Retrieve commits
        commits = db.get_commits_for_session(session.id)
        assert len(commits) == 1
        assert commits[0]["commit_hash"] == "abc1234"
        assert "login page" in commits[0]["message"].lower()

    def test_rendered_toml_contains_key_content(self, db):
        """After round-trip, TOML rendering includes all critical content."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            jsonl_path = Path(f.name)
        _write_jsonl(CLAUDE_SESSION_JSONL, jsonl_path)

        session = parse_session(jsonl_path, "myproject")
        jsonl_path.unlink()

        toml = render_session_toml(session)

        # Verify key content appears in rendered output (behavior, not format)
        assert 'project = "myproject"' in toml
        assert "login page" in toml.lower()
        assert "I need to create a login component" in toml
        assert "Write" in toml
        assert 'parent_session_id = "parent-session-abc"' in toml


class TestCodexPipeline:
    """End-to-end: Codex rollout JSONL → parse → store → retrieve."""

    def test_full_roundtrip_preserves_all_fields(self, db):
        """Parse a Codex rollout, store it, retrieve it, verify integrity."""
        with tempfile.NamedTemporaryFile(
            prefix="rollout-2026-02-01T09-00-00-",
            suffix="-12345678-1234-1234-1234-123456789abc.jsonl",
            delete=False,
        ) as f:
            rollout_path = Path(f.name)
        _write_jsonl(CODEX_ROLLOUT_JSONL, rollout_path)

        session = parse_codex_session(rollout_path, "codex-project")
        rollout_path.unlink()

        # Verify parse
        assert session.agent_type == "codex"
        assert session.project == "codex-project"
        assert session.cwd == "/home/dev/codex-project"
        assert session.git_branch == "main"
        assert session.github_repo == "acme/codex-project"
        assert session.claude_version == "codex-0.5.2"
        assert session.model == "o3-mini"
        assert session.total_input_tokens == 300
        assert session.total_output_tokens == 150
        assert session.total_cache_read_tokens == 50
        assert session.started_at == "2026-02-01T09:00:00Z"
        assert session.ended_at == "2026-02-01T09:00:07Z"

        # Deduplication: "Fix the tests" appears in both event_msg and response_item
        user_messages = [m for m in session.messages if m.type == "user"]
        assert len(user_messages) == 1, "Duplicate user messages should be deduplicated"
        assert user_messages[0].content == "Fix the tests"

        # Tool calls and results
        assert len(session.tool_calls) == 1
        assert session.tool_calls[0].tool_name == "shell"
        assert len(session.tool_results) == 1

        # Commits extracted from tool output
        assert len(session.commits) == 1
        assert session.commits[0].commit_hash == "def5678"

        # Warmup detection: this session is NOT a warmup
        assert session.is_warmup is False

        # Store and retrieve
        db.insert_session(session)
        rows = db.get_all_sessions()
        assert len(rows) == 1
        retrieved = rows[0]
        assert retrieved["agent_type"] == "codex"
        assert retrieved["github_repo"] == "acme/codex-project"
        assert retrieved["model"] == "o3-mini"
        assert retrieved["total_input_tokens"] == 300

    def test_codex_warmup_session_detected(self):
        """A Codex session whose first user message is 'warmup' is flagged."""
        warmup_rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-02-01T09:00:00Z",
                "payload": {"cwd": "/home/dev/proj"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-02-01T09:00:01Z",
                "payload": {"type": "user_message", "message": "warmup"},
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(warmup_rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert session.is_warmup is True

    def test_codex_empty_rollout_does_not_crash(self):
        """An empty or metadata-only rollout produces a session with no messages."""
        empty_rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-02-01T09:00:00Z",
                "payload": {"cwd": "/home/dev/proj"},
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(empty_rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert session.messages == []
        assert session.tool_calls == []
        assert session.is_warmup is False


class TestRegressionBugs:
    """Tests derived from real bugs found in git history."""

    def test_migration_on_old_schema_adds_new_columns(self):
        """Regression for 250521c: migrations must apply to Phase 1 schema."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        # Create a database with only the original (minimal) schema
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE sessions (
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
            CREATE TABLE messages (
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
            CREATE TABLE tool_calls (
                id TEXT PRIMARY KEY,
                message_id TEXT REFERENCES messages(id),
                session_id TEXT REFERENCES sessions(id),
                tool_name TEXT,
                input_json TEXT,
                timestamp TEXT
            );
            CREATE TABLE tool_results (
                id TEXT PRIMARY KEY,
                tool_call_id TEXT REFERENCES tool_calls(id),
                session_id TEXT REFERENCES sessions(id),
                content TEXT,
                is_error BOOLEAN,
                timestamp TEXT
            );
        """)
        # Insert a session with the old schema
        conn.execute(
            "INSERT INTO sessions (id, project, cwd) VALUES (?, ?, ?)",
            ("old-session", "old-project", "/old/path"),
        )
        conn.commit()
        conn.close()

        # Now open with current Database class — migrations must run
        db = Database(db_path)
        db.connect()

        # The old session must be readable
        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "old-session"

        # New columns must exist and accept data
        full_session = Session(
            id="new-session",
            project="new-project",
            github_repo="acme/repo",
            parent_session_id="parent-123",
            title="Test title",
            agent_type="codex",
            is_warmup=True,
            session_context='{"key": "value"}',
            messages=[
                Message(
                    id="m1",
                    session_id="new-session",
                    type="assistant",
                    timestamp="2026-01-01T00:00:00Z",
                    content="hello",
                    thinking="deep thought",
                    stop_reason="end_turn",
                    is_sidechain=True,
                    is_compact_summary=True,
                    has_images=True,
                )
            ],
        )
        # This would fail with "no such column" if migrations didn't run
        db.insert_session(full_session)

        retrieved = db.get_sessions_by_project("new-project")
        assert len(retrieved) == 1
        assert retrieved[0]["github_repo"] == "acme/repo"
        assert retrieved[0]["agent_type"] == "codex"
        assert retrieved[0]["title"] == "Test title"

        db.close()
        db_path.unlink()

    def test_render_reconstruction_includes_all_session_fields(self, db):
        """Regression for 57e69d6: all fields survive store → retrieve cycle."""
        session = Session(
            id="roundtrip-test",
            project="test-proj",
            agent_type="claude-code",
            cwd="/test/cwd",
            git_branch="main",
            slug="test-slug",
            summary="A test summary",
            title="Test Title",
            parent_session_id="parent-999",
            started_at="2026-01-01T10:00:00Z",
            ended_at="2026-01-01T11:00:00Z",
            claude_version="2.3.1",
            total_input_tokens=1000,
            total_output_tokens=500,
            total_cache_read_tokens=200,
            model="claude-opus-4-5-20251101",
            is_warmup=False,
            is_sidechain=True,
            github_repo="acme/test",
            session_context='{"foo": "bar"}',
            messages=[
                Message(
                    id="msg-1",
                    session_id="roundtrip-test",
                    type="user",
                    timestamp="2026-01-01T10:00:00Z",
                    content="Hello",
                ),
                Message(
                    id="msg-2",
                    session_id="roundtrip-test",
                    type="assistant",
                    timestamp="2026-01-01T10:00:01Z",
                    content="Hi there",
                    thinking="Let me think",
                    model="claude-opus-4-5-20251101",
                    input_tokens=100,
                    output_tokens=50,
                    stop_reason="end_turn",
                    parent_uuid="msg-1",
                    is_sidechain=True,
                    is_compact_summary=True,
                    has_images=True,
                ),
            ],
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    message_id="msg-2",
                    session_id="roundtrip-test",
                    tool_name="Bash",
                    input_json='{"command": "ls"}',
                    timestamp="2026-01-01T10:00:01Z",
                ),
            ],
            tool_results=[
                ToolResult(
                    id="tr-1",
                    tool_call_id="tc-1",
                    session_id="roundtrip-test",
                    content="file1.txt",
                    is_error=False,
                    timestamp="2026-01-01T10:00:02Z",
                ),
            ],
            commits=[
                Commit(
                    id="c-1",
                    session_id="roundtrip-test",
                    commit_hash="abc1234",
                    message="Test commit",
                    timestamp="2026-01-01T10:00:02Z",
                ),
            ],
        )

        db.insert_session(session)

        # Reconstruct exactly as the render command does (cli.py:360-434)
        session_dict = db.get_all_sessions()[0]

        # Session-level fields (the parent_session_id bug was here)
        assert session_dict["parent_session_id"] == "parent-999"
        assert session_dict["slug"] == "test-slug"
        assert session_dict["summary"] == "A test summary"
        assert session_dict["title"] == "Test Title"
        assert session_dict["github_repo"] == "acme/test"
        assert session_dict["session_context"] == '{"foo": "bar"}'
        assert session_dict["agent_type"] == "claude-code"
        assert session_dict["is_warmup"] == 0  # SQLite stores as int
        assert session_dict["is_sidechain"] == 1

        # Message-level fields
        messages = db.get_messages_for_session("roundtrip-test")
        asst_msg = [m for m in messages if m["type"] == "assistant"][0]
        assert asst_msg["thinking"] == "Let me think"
        assert asst_msg["stop_reason"] == "end_turn"
        assert asst_msg["parent_uuid"] == "msg-1"
        assert asst_msg["is_sidechain"] == 1
        assert asst_msg["is_compact_summary"] == 1
        assert asst_msg["has_images"] == 1

        # Tool calls and results
        tc = db.get_tool_calls_for_session("roundtrip-test")
        assert len(tc) == 1
        assert tc[0]["tool_name"] == "Bash"

        tr = db.get_tool_results_for_session("roundtrip-test")
        assert len(tr) == 1
        assert tr[0]["content"] == "file1.txt"

        commits = db.get_commits_for_session("roundtrip-test")
        assert len(commits) == 1
        assert commits[0]["commit_hash"] == "abc1234"
