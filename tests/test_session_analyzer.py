"""Tests for session analyzer module."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_archive.analyzer.session_analyzer import (
    SessionAnalyzer,
    build_session_analysis_prompt,
    load_session_analysis_template,
)


class TestLoadSessionAnalysisTemplate:
    """Tests for loading the prompt template."""

    def test_template_loads_successfully(self):
        """Template file exists and loads."""
        template = load_session_analysis_template()
        assert isinstance(template, str)
        assert len(template) > 100

    def test_template_has_placeholders(self):
        """Template contains required placeholders."""
        template = load_session_analysis_template()
        assert "{project}" in template
        assert "{session_count}" in template
        assert "{turn_count}" in template
        assert "{input_tokens" in template  # May have formatting
        assert "{output_tokens" in template
        assert "{tool_call_count}" in template
        assert "{toml_dir}" in template


class TestBuildSessionAnalysisPrompt:
    """Tests for building the analysis prompt."""

    def test_builds_prompt_with_metrics(self):
        """Prompt includes project metrics."""
        prompt = build_session_analysis_prompt(
            project="test-project",
            session_count=10,
            turn_count=50,
            input_tokens=1000,
            output_tokens=2000,
            tool_call_count=100,
            toml_dir="/path/to/toml",
        )

        assert "test-project" in prompt
        assert "10" in prompt  # session_count
        assert "50" in prompt  # turn_count
        assert "1,000" in prompt  # input_tokens formatted
        assert "2,000" in prompt  # output_tokens formatted
        assert "100" in prompt  # tool_call_count
        assert "/path/to/toml" in prompt


class TestSessionAnalyzer:
    """Tests for SessionAnalyzer class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Claude client."""
        client = MagicMock()
        client.query = AsyncMock(return_value="# Analysis\n\nSome analysis content")
        return client

    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = MagicMock()
        db.get_project_metrics = MagicMock(
            return_value={
                "session_count": 5,
                "turn_count": 20,
                "total_input_tokens": 5000,
                "total_output_tokens": 10000,
                "tool_call_count": 50,
            }
        )
        return db

    @pytest.mark.asyncio
    async def test_analyze_project(self, mock_client, mock_db):
        """Test analyzing a single project."""
        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=Path("/fake/toml"),
        )

        result = await analyzer.analyze_project("my-project")

        # Verify database was queried
        mock_db.get_project_metrics.assert_called_once_with("my-project")

        # Verify Claude was invoked
        mock_client.query.assert_called_once()
        prompt_arg = mock_client.query.call_args[0][0]
        assert "my-project" in prompt_arg
        assert "/fake/toml/my-project" in prompt_arg

        # Verify result
        assert result == "# Analysis\n\nSome analysis content"

    @pytest.mark.asyncio
    async def test_analyze_project_empty_metrics(self, mock_client, mock_db):
        """Test analyzing a project with no sessions."""
        mock_db.get_project_metrics.return_value = {
            "session_count": 0,
            "turn_count": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "tool_call_count": 0,
        }

        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=Path("/fake/toml"),
        )

        result = await analyzer.analyze_project("empty-project")

        # Should still call Claude even with empty project
        mock_client.query.assert_called_once()
