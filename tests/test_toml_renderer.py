"""Tests for TOML renderer."""

import tempfile
from pathlib import Path

import pytest

from claude_code_audit.models import Message, Session, ToolCall, ToolResult
from claude_code_audit.toml_renderer import (
    escape_toml_string,
    format_timestamp,
    render_session_toml,
    render_session_to_file,
)


class TestFormatTimestamp:
    def test_formats_z_suffix(self):
        result = format_timestamp("2026-01-01T10:00:00Z")
        assert result == "2026-01-01T10:00:00+00:00"

    def test_handles_none(self):
        assert format_timestamp(None) == ""

    def test_handles_empty(self):
        assert format_timestamp("") == ""


class TestEscapeTomlString:
    def test_escapes_quotes(self):
        assert escape_toml_string('hello "world"') == 'hello \\"world\\"'

    def test_escapes_newlines(self):
        assert escape_toml_string("hello\nworld") == "hello\\nworld"

    def test_escapes_backslashes(self):
        assert escape_toml_string("path\\to\\file") == "path\\\\to\\\\file"


@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        id="test-session-123",
        project="test-project",
        cwd="/test/path",
        slug="dapper-questing-pascal",
        summary="A test session summary",
        started_at="2026-01-01T10:00:00Z",
        ended_at="2026-01-01T11:00:00Z",
        model="claude-opus-4-5-20251101",
        claude_version="2.1.9",
        total_input_tokens=100,
        total_output_tokens=50,
        total_cache_read_tokens=200,
        messages=[
            Message(
                id="msg-1",
                session_id="test-session-123",
                type="user",
                timestamp="2026-01-01T10:00:00Z",
                content="What files are here?",
            ),
            Message(
                id="msg-2",
                session_id="test-session-123",
                type="assistant",
                timestamp="2026-01-01T10:00:01Z",
                content="Let me check.",
                thinking="I should list the files in this directory.",
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        message_id="msg-2",
                        session_id="test-session-123",
                        tool_name="Bash",
                        input_json='{"command": "ls -la"}',
                        timestamp="2026-01-01T10:00:01Z",
                    ),
                ],
            ),
        ],
        tool_calls=[
            ToolCall(
                id="tool-1",
                message_id="msg-2",
                session_id="test-session-123",
                tool_name="Bash",
                input_json='{"command": "ls -la"}',
                timestamp="2026-01-01T10:00:01Z",
            ),
        ],
        tool_results=[
            ToolResult(
                id="result-1",
                tool_call_id="tool-1",
                session_id="test-session-123",
                content="file1.txt\nfile2.txt",
                is_error=False,
                timestamp="2026-01-01T10:00:02Z",
            ),
        ],
    )


class TestRenderSessionToml:
    def test_renders_session_header(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "[session]" in toml
        assert 'id = "test-session-123"' in toml
        assert 'project = "test-project"' in toml
        assert 'model = "claude-opus-4-5-20251101"' in toml
        assert "input_tokens = 100" in toml
        assert "output_tokens = 50" in toml

    def test_renders_slug(self, sample_session):
        toml = render_session_toml(sample_session)
        assert 'slug = "dapper-questing-pascal"' in toml

    def test_renders_summary(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "A test session summary" in toml

    def test_renders_thinking(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "thinking = '''" in toml
        assert "I should list the files in this directory." in toml

    def test_renders_turns(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "[[turns]]" in toml
        assert "number = 1" in toml
        assert "[turns.user]" in toml
        assert "What files are here?" in toml

    def test_renders_assistant_content(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "[turns.assistant]" in toml
        assert "Let me check." in toml

    def test_renders_tool_calls(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "[[turns.assistant.tool_calls]]" in toml
        assert 'tool = "Bash"' in toml
        assert "ls -la" in toml

    def test_renders_tool_results(self, sample_session):
        toml = render_session_toml(sample_session)
        assert "[turns.assistant.tool_calls.result]" in toml
        assert "file1.txt" in toml

    def test_handles_multiline_content(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="msg-1",
                    session_id="test",
                    type="user",
                    timestamp="2026-01-01T10:00:00Z",
                    content="Line 1\nLine 2\nLine 3",
                ),
            ],
        )
        toml = render_session_toml(session)
        # Should use literal string with triple quotes
        assert "'''" in toml
        assert "Line 1\nLine 2\nLine 3" in toml


class TestRenderSessionToFile:
    def test_creates_file(self, sample_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            result = render_session_to_file(sample_session, output_dir)

            assert result.exists()
            assert result.suffix == ".toml"
            assert "test-project" in str(result)
            assert "test-ses" in str(result)  # Short ID (8 chars)

            content = result.read_text()
            assert "[session]" in content

    def test_creates_project_subdirectory(self, sample_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            result = render_session_to_file(sample_session, output_dir)

            assert result.parent.name == "test-project"
