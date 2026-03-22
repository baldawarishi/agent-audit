"""Tests for Goose parser."""

import json
import sqlite3
import tempfile
from pathlib import Path

from agent_audit.goose_parser import (
    parse_goose_session,
    discover_goose_sessions,
)
from agent_audit.database import Database


def _write_jsonl(lines: list[dict], path: Path):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def _create_goose_sqlite(db_path: Path, sessions: list[dict] | None = None):
    """Create a minimal Goose SQLite database for testing."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content_json TEXT,
            timestamp TEXT,
            created_timestamp INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)

    if sessions is None:
        sessions = [_default_sqlite_session()]

    for s in sessions:
        conn.execute("INSERT INTO sessions (id, name) VALUES (?, ?)", (s["id"], s.get("name")))
        for msg in s.get("messages", []):
            conn.execute(
                "INSERT INTO messages (session_id, role, content_json, timestamp, created_timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (s["id"], msg["role"], msg.get("content_json"), msg.get("timestamp"), msg.get("created_timestamp")),
            )

    conn.commit()
    conn.close()


def _default_sqlite_session() -> dict:
    return {
        "id": "goose-session-001",
        "name": "my-project",
        "messages": [
            {
                "role": "user",
                "content_json": json.dumps([{"type": "text", "text": "help me refactor utils.py"}]),
                "timestamp": "2026-01-01T00:00:00+00:00",
                "created_timestamp": None,
            },
            {
                "role": "assistant",
                "content_json": json.dumps([{"type": "text", "text": "I'll refactor that for you."}]),
                "timestamp": "2026-01-01T00:00:05+00:00",
                "created_timestamp": None,
            },
        ],
    }


def _default_jsonl_session() -> list[dict]:
    return [
        {
            "working_dir": "/Users/dev/projects/my-app",
            "description": "Working on feature X",
            "id": "goose-jsonl-001",
        },
        {
            "role": "user",
            "content": "add a new endpoint",
            "created": 1704067200,
        },
        {
            "role": "assistant",
            "content": "I'll add the endpoint now.",
            "created": 1704067210,
        },
    ]


class TestSqliteParsing:
    def test_session_metadata(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)

        session = parse_goose_session("sqlite:goose-session-001", "my-project", goose_home=tmp_path)

        assert session.id == "goose-session-001"
        assert session.project == "my-project"
        assert session.agent_type == "goose"
        assert session.claude_version == "goose"

    def test_messages_parsed(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)

        session = parse_goose_session("sqlite:goose-session-001", "proj", goose_home=tmp_path)

        user_msgs = [m for m in session.messages if m.type == "user"]
        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert len(user_msgs) == 1
        assert "refactor" in user_msgs[0].content
        assert len(asst_msgs) == 1
        assert "refactor" in asst_msgs[0].content

    def test_timestamps(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)

        session = parse_goose_session("sqlite:goose-session-001", "proj", goose_home=tmp_path)

        assert session.started_at is not None
        assert session.ended_at is not None

    def test_plain_string_content(self, tmp_path):
        """content_json that is just a plain string (not JSON array)."""
        db_path = tmp_path / "sessions.db"
        sess = {
            "id": "plain-str",
            "name": "proj",
            "messages": [
                {"role": "user", "content_json": "just a string", "timestamp": "2026-01-01T00:00:00Z"},
            ],
        }
        _create_goose_sqlite(db_path, [sess])

        session = parse_goose_session("sqlite:plain-str", "proj", goose_home=tmp_path)

        assert len(session.messages) == 1
        assert session.messages[0].content == "just a string"

    def test_epoch_timestamp_fallback(self, tmp_path):
        """When timestamp is null, falls back to created_timestamp."""
        db_path = tmp_path / "sessions.db"
        sess = {
            "id": "epoch-ts",
            "name": "proj",
            "messages": [
                {"role": "user", "content_json": '"hello"', "timestamp": None, "created_timestamp": 1704067200},
            ],
        }
        _create_goose_sqlite(db_path, [sess])

        session = parse_goose_session("sqlite:epoch-ts", "proj", goose_home=tmp_path)

        assert session.started_at is not None
        assert "2024" in session.started_at  # epoch 1704067200 = 2024-01-01


class TestJsonlParsing:
    def test_session_metadata(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_default_jsonl_session(), path)

        session = parse_goose_session(str(path), "my-app")
        path.unlink()

        assert session.id == "goose-jsonl-001"
        # Project name derived from cwd, matching Claude Code convention
        # cwd=/Users/dev/projects/my-app -> "projects" is a skip_dir -> "my-app"
        assert session.project == "my-app"
        assert session.agent_type == "goose"
        assert session.cwd == "/Users/dev/projects/my-app"
        assert session.summary == "Working on feature X"

    def test_messages_parsed(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_default_jsonl_session(), path)

        session = parse_goose_session(str(path), "proj")
        path.unlink()

        user_msgs = [m for m in session.messages if m.type == "user"]
        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert len(user_msgs) == 1
        assert "endpoint" in user_msgs[0].content
        assert len(asst_msgs) == 1

    def test_timestamps_from_epoch(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_default_jsonl_session(), path)

        session = parse_goose_session(str(path), "proj")
        path.unlink()

        assert session.started_at is not None
        assert session.ended_at is not None


class TestDiscovery:
    def test_discover_sqlite_sessions(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)

        found = list(discover_goose_sessions(goose_home=tmp_path))
        assert len(found) == 1
        assert found[0][0] == "sqlite:goose-session-001"
        assert found[0][1] == "my-project"

    def test_discover_jsonl_fallback(self, tmp_path):
        """When no sessions.db exists, discovers JSONL files."""
        _write_jsonl(_default_jsonl_session(), tmp_path / "session1.jsonl")

        found = list(discover_goose_sessions(goose_home=tmp_path))
        assert len(found) == 1

    def test_sqlite_preferred_over_jsonl(self, tmp_path):
        """When both exist, only SQLite sessions are returned."""
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)
        _write_jsonl(_default_jsonl_session(), tmp_path / "extra.jsonl")

        found = list(discover_goose_sessions(goose_home=tmp_path))
        # SQLite should be used, not JSONL
        assert all(sid.startswith("sqlite:") for sid, _ in found)

    def test_discover_empty_dir(self, tmp_path):
        found = list(discover_goose_sessions(goose_home=tmp_path))
        assert len(found) == 0

    def test_discover_nonexistent_dir(self, tmp_path):
        found = list(discover_goose_sessions(goose_home=tmp_path / "nope"))
        assert len(found) == 0


class TestWarmupDetection:
    def test_warmup_sqlite(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        sess = {
            "id": "warmup-1",
            "name": "proj",
            "messages": [
                {"role": "user", "content_json": json.dumps([{"type": "text", "text": "Warmup"}]),
                 "timestamp": "2026-01-01T00:00:00Z"},
            ],
        }
        _create_goose_sqlite(db_path, [sess])

        session = parse_goose_session("sqlite:warmup-1", "proj", goose_home=tmp_path)
        assert session.is_warmup is True

    def test_normal_not_warmup(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        _create_goose_sqlite(db_path)

        session = parse_goose_session("sqlite:goose-session-001", "proj", goose_home=tmp_path)
        assert session.is_warmup is False


class TestDatabaseRoundTrip:
    def test_goose_session_stores_and_reads(self, tmp_path):
        goose_db = tmp_path / "sessions.db"
        _create_goose_sqlite(goose_db)

        session = parse_goose_session("sqlite:goose-session-001", "my-project", goose_home=tmp_path)

        audit_db = Database(tmp_path / "audit.db")
        with audit_db:
            audit_db.insert_session(session)

            assert audit_db.session_exists(session.id)

            sessions = audit_db.get_all_sessions()
            assert len(sessions) == 1
            assert sessions[0]["agent_type"] == "goose"
            assert sessions[0]["project"] == "my-project"

            messages = audit_db.get_messages_for_session(session.id)
            assert len(messages) == 2
