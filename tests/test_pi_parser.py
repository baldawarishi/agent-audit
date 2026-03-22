"""Tests for Pi parser."""

import json
import tempfile
from pathlib import Path

from agent_audit.pi_parser import (
    parse_pi_session,
    discover_pi_sessions,
    _decode_pi_project_name,
)
from agent_audit.database import Database


def _write_jsonl(lines: list[dict], path: Path):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def _make_pi_session(extra_lines: list[dict] | None = None) -> list[dict]:
    """Build a minimal Pi session JSONL."""
    lines = [
        {
            "type": "session",
            "version": 3,
            "id": "aaaa1111-0000-0000-0000-000000000000",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "cwd": "/Users/dev/workspaces/my-project",
        },
        {
            "type": "model_change",
            "id": "mc1",
            "parentId": None,
            "timestamp": "2026-01-01T00:00:00.001Z",
            "provider": "anthropic",
            "modelId": "claude-sonnet-4-5",
        },
        {
            "type": "message",
            "id": "msg1",
            "parentId": "mc1",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "fix the bug in main.py"}],
            },
        },
        {
            "type": "message",
            "id": "msg2",
            "parentId": "msg1",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Let me look at the code...",
                    },
                    {"type": "text", "text": "I'll fix that for you."},
                    {
                        "type": "toolCall",
                        "id": "tc1",
                        "name": "readFile",
                        "arguments": {"path": "main.py"},
                    },
                ],
                "usage": {"input": 100, "output": 50, "cacheRead": 10, "cacheWrite": 0, "totalTokens": 150, "cost": {"input": 0, "output": 0}},
            },
        },
    ]
    if extra_lines:
        lines.extend(extra_lines)
    return lines


class TestBasicParsing:
    def test_session_metadata(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "my-project")
        path.unlink()

        assert session.id == "aaaa1111-0000-0000-0000-000000000000"
        # Project name is derived from cwd, matching Claude Code convention
        assert session.project == "workspaces-my-project"
        assert session.agent_type == "pi"
        assert session.cwd == "/Users/dev/workspaces/my-project"
        assert session.model == "claude-sonnet-4-5"
        assert session.claude_version == "pi-anthropic"

    def test_messages_parsed(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        user_msgs = [m for m in session.messages if m.type == "user"]
        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert len(user_msgs) == 1
        assert "fix the bug" in user_msgs[0].content
        assert len(asst_msgs) == 1
        assert "fix that for you" in asst_msgs[0].content

    def test_thinking_extracted(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        asst_msgs = [m for m in session.messages if m.type == "assistant"]
        assert asst_msgs[0].thinking == "Let me look at the code..."

    def test_tool_calls_extracted(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert len(session.tool_calls) == 1
        assert session.tool_calls[0].tool_name == "readFile"
        assert session.tool_calls[0].id == "tc1"
        parsed_input = json.loads(session.tool_calls[0].input_json)
        assert parsed_input["path"] == "main.py"

    def test_token_counts(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert session.total_input_tokens == 100
        assert session.total_output_tokens == 50

    def test_timestamps(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert session.started_at == "2026-01-01T00:00:01.000Z"
        assert session.ended_at == "2026-01-01T00:00:02.000Z"


class TestToolResults:
    def test_tool_result_extraction(self):
        extra = [
            {
                "type": "message",
                "id": "msg3",
                "parentId": "msg2",
                "timestamp": "2026-01-01T00:00:03.000Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc1",
                    "toolName": "readFile",
                    "content": [
                        {"type": "text", "text": "def main():\n    print('hello')"}
                    ],
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(extra), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert len(session.tool_results) == 1
        assert "def main()" in session.tool_results[0].content
        assert session.tool_results[0].tool_call_id == "tc1"
        assert session.tool_results[0].is_error is False

    def test_tool_result_error(self):
        extra = [
            {
                "type": "message",
                "id": "msg3",
                "parentId": "msg2",
                "timestamp": "2026-01-01T00:00:03.000Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc1",
                    "toolName": "readFile",
                    "isError": True,
                    "content": [
                        {"type": "text", "text": "file not found"}
                    ],
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(extra), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert session.tool_results[0].is_error is True


class TestProjectNameDecoding:
    def test_standard_path(self):
        # Should match Claude Code naming convention
        assert _decode_pi_project_name("--Users-rishibaldawa-workspaces-quamina-rs--") == "rishibaldawa-workspaces-quamina-rs"

    def test_short_path(self):
        assert _decode_pi_project_name("--Users-dev-myproject--") == "myproject"

    def test_empty_dashes(self):
        result = _decode_pi_project_name("----")
        assert isinstance(result, str)


class TestDiscovery:
    def test_discover_finds_sessions_in_project_dirs(self, tmp_path):
        proj_dir = tmp_path / "--Users-dev-workspaces-myproj--"
        proj_dir.mkdir()
        _write_jsonl(_make_pi_session(), proj_dir / "session1.jsonl")
        _write_jsonl(_make_pi_session(), proj_dir / "session2.jsonl")

        found = list(discover_pi_sessions(pi_home=tmp_path))
        assert len(found) == 2
        assert all(p.endswith("myproj") or p == "myproj" for _, p in found)

    def test_discover_skips_non_directories(self, tmp_path):
        (tmp_path / "stray-file.txt").write_text("not a dir")
        found = list(discover_pi_sessions(pi_home=tmp_path))
        assert len(found) == 0


class TestWarmupDetection:
    def test_warmup_session_detected(self):
        lines = [
            {
                "type": "session",
                "version": 3,
                "id": "warm-0000",
                "timestamp": "2026-01-01T00:00:00.000Z",
                "cwd": "/tmp",
            },
            {
                "type": "message",
                "id": "m1",
                "parentId": None,
                "timestamp": "2026-01-01T00:00:01.000Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Warmup"}]},
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(lines, path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert session.is_warmup is True

    def test_normal_session_not_warmup(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "proj")
        path.unlink()

        assert session.is_warmup is False


class TestDatabaseRoundTrip:
    def test_pi_session_inserts_and_reads_back(self, tmp_path):
        """Pi session stores to DB and reads back with correct agent_type."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(_make_pi_session(), path)

        session = parse_pi_session(path, "my-project")
        path.unlink()

        db = Database(tmp_path / "test.db")
        with db:
            db.insert_session(session)

            # Verify it exists
            assert db.session_exists(session.id)

            # Verify agent_type
            sessions = db.get_all_sessions()
            assert len(sessions) == 1
            assert sessions[0]["agent_type"] == "pi"
            assert sessions[0]["project"] == "workspaces-my-project"
            assert sessions[0]["model"] == "claude-sonnet-4-5"

            # Verify messages
            messages = db.get_messages_for_session(session.id)
            assert len(messages) == 2

            # Verify tool calls
            tool_calls = db.get_tool_calls_for_session(session.id)
            assert len(tool_calls) == 1
            assert tool_calls[0]["tool_name"] == "readFile"
