"""Tests for Codex parser."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_audit.codex_parser import (
    parse_codex_session,
    discover_codex_sessions,
    get_session_id_from_filename,
    get_codex_home,
)


def _write_jsonl(lines: list[dict], path: Path):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


class TestUserMessageDeduplication:
    """Duplicate user messages from event_msg and response_item are deduplicated."""

    def test_duplicate_user_message_produces_single_entry(self):
        rollout = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "user_message", "message": "hello world"},
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello world"}],
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        user_msgs = [m for m in session.messages if m.type == "user"]
        assert len(user_msgs) == 1

    def test_different_user_messages_are_not_deduped(self):
        rollout = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "user_message", "message": "first question"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:10Z",
                "payload": {"type": "user_message", "message": "second question"},
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        user_msgs = [m for m in session.messages if m.type == "user"]
        assert len(user_msgs) == 2


class TestRepoExtraction:
    def test_https_url(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "https://github.com/acme/repo.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "acme/repo"
        assert session.repo_platform == "github"

    def test_ssh_url(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "git@github.com:acme/repo.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "acme/repo"
        assert session.repo_platform == "github"

    def test_gitlab_url_produces_repo(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "https://gitlab.com/org/repo.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "org/repo"
        assert session.repo_platform == "gitlab"

    def test_gitlab_nested_groups(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "https://gitlab.com/group/subgroup/project.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "group/subgroup/project"
        assert session.repo_platform == "gitlab"

    def test_bitbucket_url(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "https://bitbucket.org/team/repo.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "team/repo"
        assert session.repo_platform == "bitbucket"

    def test_unknown_host_url(self):
        rollout = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "cwd": "/proj",
                    "git": {"branch": "main", "repository_url": "https://git.corp.example.com/team/repo.git"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()
        assert session.repo == "team/repo"
        assert session.repo_platform is None  # unrecognized host


class TestToolCallArgumentParsing:
    def test_json_string_arguments(self):
        """Tool call with arguments as a JSON string."""
        rollout = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "shell",
                    "arguments": '{"command": "ls -la"}',
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert len(session.tool_calls) == 1
        parsed = json.loads(session.tool_calls[0].input_json)
        assert parsed["command"] == "ls -la"

    def test_dict_arguments(self):
        """Tool call with arguments already as a dict (via 'input' key)."""
        rollout = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "c2",
                    "name": "read_file",
                    "input": {"path": "/foo/bar.txt"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert len(session.tool_calls) == 1
        parsed = json.loads(session.tool_calls[0].input_json)
        assert parsed["path"] == "/foo/bar.txt"

    def test_unparseable_string_arguments(self):
        """Tool call with non-JSON string falls back to wrapping."""
        rollout = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "function_call",
                    "call_id": "c3",
                    "name": "shell",
                    "arguments": "not valid json",
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert len(session.tool_calls) == 1
        # Should be valid JSON (wrapped in some structure), not crash
        parsed = json.loads(session.tool_calls[0].input_json)
        assert isinstance(parsed, dict)


class TestToolResultErrorDetection:
    def test_success_false_is_error(self):
        rollout = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": {"success": False, "error": "permission denied"},
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert len(session.tool_results) == 1
        assert session.tool_results[0].is_error is True

    def test_plain_string_output_is_not_error(self):
        rollout = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": "file1.txt\nfile2.txt",
                },
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        _write_jsonl(rollout, path)

        session = parse_codex_session(path, "proj")
        path.unlink()

        assert len(session.tool_results) == 1
        assert session.tool_results[0].is_error is False


class TestSessionDiscovery:
    def test_valid_rollout_filename_extracts_uuid(self):
        path = Path("rollout-2026-01-01T09-00-00-12345678-1234-1234-1234-123456789abc.jsonl")
        sid = get_session_id_from_filename(path)
        assert sid == "12345678-1234-1234-1234-123456789abc"

    def test_invalid_filename_returns_none(self):
        assert get_session_id_from_filename(Path("random-file.jsonl")) is None
        assert get_session_id_from_filename(Path("session.json")) is None

    def test_discover_scans_sessions_and_archived(self, tmp_path):
        """discover_codex_sessions finds files in both sessions/ and archived_sessions/."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        archived_dir = tmp_path / "archived_sessions"
        archived_dir.mkdir()

        # Write minimal rollout files
        for d, name in [(sessions_dir, "rollout-2026-01-01T00-00-00-11111111-1111-1111-1111-111111111111.jsonl"),
                         (archived_dir, "rollout-2026-01-02T00-00-00-22222222-2222-2222-2222-222222222222.jsonl")]:
            _write_jsonl([{"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z",
                           "payload": {"cwd": "/home/dev/proj"}}], d / name)

        found = list(discover_codex_sessions(codex_home=tmp_path, include_archived=True))
        assert len(found) == 2

    def test_discover_excludes_archived_when_flag_false(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        archived_dir = tmp_path / "archived_sessions"
        archived_dir.mkdir()

        _write_jsonl([{"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z",
                        "payload": {"cwd": "/proj"}}],
                      sessions_dir / "rollout-2026-01-01T00-00-00-11111111-1111-1111-1111-111111111111.jsonl")
        _write_jsonl([{"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z",
                        "payload": {"cwd": "/proj"}}],
                      archived_dir / "rollout-2026-01-02T00-00-00-22222222-2222-2222-2222-222222222222.jsonl")

        found = list(discover_codex_sessions(codex_home=tmp_path, include_archived=False))
        assert len(found) == 1
