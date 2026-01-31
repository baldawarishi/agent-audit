"""Tests for session analyzer module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_code_audit.analyzer.session_analyzer import (
    SessionAnalyzer,
    build_session_analysis_prompt,
    load_session_analysis_template,
    build_global_synthesis_prompt,
    load_global_synthesis_template,
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
        # Basic project info
        assert "{project}" in template
        assert "{session_count}" in template
        assert "{input_tokens" in template  # May have formatting
        assert "{output_tokens" in template
        assert "{tool_call_count}" in template
        assert "{toml_dir}" in template
        # Global percentiles (P50 has tokens, P75/P90 just messages for brevity)
        assert "{global_p50_msgs}" in template
        assert "{global_p75_msgs}" in template
        assert "{global_p90_msgs}" in template
        assert "{global_p50_tokens" in template
        # Project stats
        assert "{project_avg_msgs}" in template
        assert "{project_min_msgs}" in template
        assert "{project_max_msgs}" in template
        assert "{project_avg_tokens" in template

    def test_template_has_critical_framing(self):
        """Template uses critical/skeptical framing, not positive."""
        template = load_session_analysis_template()
        assert "skeptical auditor" in template.lower()
        assert "find problems" in template.lower()
        # Should not have overly positive framing instructions
        assert "excellent" not in template.lower() or "do not use" in template.lower()

    def test_template_requires_evidence(self):
        """Template requires evidence for claims."""
        template = load_session_analysis_template()
        assert "quote" in template.lower()
        assert "evidence" in template.lower()

    def test_template_has_assumption_marking(self):
        """Template instructs to mark assumptions with brackets."""
        template = load_session_analysis_template()
        assert "[SQUARE BRACKETS" in template or "SQUARE BRACKETS" in template


class TestBuildSessionAnalysisPrompt:
    """Tests for building the analysis prompt."""

    def test_builds_prompt_with_metrics(self):
        """Prompt includes project metrics and global percentiles."""
        prompt = build_session_analysis_prompt(
            project="test-project",
            session_count=10,
            turn_count=50,
            input_tokens=1000,
            output_tokens=2000,
            tool_call_count=100,
            toml_dir="/path/to/toml",
            global_p50_msgs=126,
            global_p75_msgs=251,
            global_p90_msgs=346,
            global_p50_tokens=25000,
            project_avg_msgs=150,
            project_min_msgs=10,
            project_max_msgs=300,
            project_avg_tokens=30000,
        )

        # Basic project info
        assert "test-project" in prompt
        assert "10" in prompt  # session_count
        assert "1,000" in prompt  # input_tokens formatted
        assert "2,000" in prompt  # output_tokens formatted
        assert "100" in prompt  # tool_call_count
        assert "/path/to/toml" in prompt

        # Global percentiles
        assert "126" in prompt  # global_p50_msgs
        assert "251" in prompt  # global_p75_msgs
        assert "346" in prompt  # global_p90_msgs
        assert "25,000" in prompt  # global_p50_tokens formatted

        # Project stats
        assert "150" in prompt  # project_avg_msgs
        assert "300" in prompt  # project_max_msgs
        assert "30,000" in prompt  # project_avg_tokens formatted


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
        db.get_global_percentiles = MagicMock(
            return_value={
                "p50_msgs": 126,
                "p75_msgs": 251,
                "p90_msgs": 346,
                "p50_tokens": 25000,
                "p75_tokens": 50000,
                "p90_tokens": 75000,
            }
        )
        db.get_project_session_stats = MagicMock(
            return_value={
                "avg_msgs": 150,
                "min_msgs": 10,
                "max_msgs": 300,
                "avg_tokens": 30000,
                "min_tokens": 1000,
                "max_tokens": 80000,
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

        # Verify database was queried for all metrics
        mock_db.get_project_metrics.assert_called_once_with("my-project")
        mock_db.get_global_percentiles.assert_called_once()
        mock_db.get_project_session_stats.assert_called_once_with("my-project")

        # Verify Claude was invoked
        mock_client.query.assert_called_once()
        prompt_arg = mock_client.query.call_args[0][0]
        assert "my-project" in prompt_arg
        assert "/fake/toml/my-project" in prompt_arg
        # Check that global percentiles appear in prompt
        assert "126" in prompt_arg  # p50_msgs
        assert "251" in prompt_arg  # p75_msgs

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
        mock_db.get_project_session_stats.return_value = {
            "avg_msgs": 0,
            "min_msgs": 0,
            "max_msgs": 0,
            "avg_tokens": 0,
            "min_tokens": 0,
            "max_tokens": 0,
        }

        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=Path("/fake/toml"),
        )

        await analyzer.analyze_project("empty-project")

        # Should still call Claude even with empty project
        mock_client.query.assert_called_once()


class TestLoadGlobalSynthesisTemplate:
    """Tests for loading the global synthesis prompt template."""

    def test_template_loads_successfully(self):
        """Template file exists and loads."""
        template = load_global_synthesis_template()
        assert isinstance(template, str)
        assert len(template) > 100

    def test_template_has_placeholders(self):
        """Template contains required placeholders."""
        template = load_global_synthesis_template()
        assert "{project_count}" in template
        assert "{analysis_files}" in template
        assert "{analysis_dir}" in template

    def test_template_has_critical_framing(self):
        """Template uses critical/skeptical framing, not positive."""
        template = load_global_synthesis_template()
        assert "skeptical analyst" in template.lower()
        # Should not have overly positive framing instructions
        assert "excellent" not in template.lower() or "do not use" in template.lower()

    def test_template_requires_evidence(self):
        """Template requires evidence from multiple projects."""
        template = load_global_synthesis_template()
        assert "evidence" in template.lower()
        assert "quote" in template.lower()

    def test_template_has_assumption_marking(self):
        """Template instructs to mark assumptions with brackets."""
        template = load_global_synthesis_template()
        assert "[SQUARE BRACKETS" in template or "SQUARE BRACKETS" in template


class TestBuildGlobalSynthesisPrompt:
    """Tests for building the global synthesis prompt."""

    def test_builds_prompt_with_file_list(self):
        """Prompt includes analysis file paths."""
        analysis_files = [
            Path("/analysis/run-123/project-a.md"),
            Path("/analysis/run-123/project-b.md"),
        ]
        prompt = build_global_synthesis_prompt(
            analysis_files=analysis_files,
            analysis_dir=Path("/analysis/run-123"),
        )

        assert "2" in prompt  # project_count
        assert "project-a.md" in prompt
        assert "project-b.md" in prompt
        assert "/analysis/run-123" in prompt

    def test_builds_prompt_with_single_file(self):
        """Prompt handles single analysis file."""
        analysis_files = [Path("/analysis/run-123/single-project.md")]
        prompt = build_global_synthesis_prompt(
            analysis_files=analysis_files,
            analysis_dir=Path("/analysis/run-123"),
        )

        assert "1" in prompt  # project_count
        assert "single-project.md" in prompt


class TestSessionAnalyzerGlobalSynthesis:
    """Tests for SessionAnalyzer global synthesis."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Claude client."""
        client = MagicMock()
        client.query = AsyncMock(
            return_value="# Global Synthesis\n\nCross-project patterns"
        )
        return client

    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_synthesize_global(self, mock_client, mock_db, tmp_path):
        """Test global synthesis across multiple project analyses."""
        # Create fake analysis files
        analysis_dir = tmp_path / "analysis" / "run-123"
        analysis_dir.mkdir(parents=True)
        (analysis_dir / "project-a.md").write_text("# Project A Analysis")
        (analysis_dir / "project-b.md").write_text("# Project B Analysis")

        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=tmp_path / "toml",
        )

        result = await analyzer.synthesize_global(analysis_dir)

        # Verify Claude was invoked with synthesis prompt
        mock_client.query.assert_called_once()
        prompt_arg = mock_client.query.call_args[0][0]
        assert "project-a.md" in prompt_arg
        assert "project-b.md" in prompt_arg
        assert str(analysis_dir) in prompt_arg

        # Verify result
        assert result == "# Global Synthesis\n\nCross-project patterns"

    @pytest.mark.asyncio
    async def test_synthesize_global_excludes_non_md_files(
        self, mock_client, mock_db, tmp_path
    ):
        """Global synthesis only includes .md files."""
        analysis_dir = tmp_path / "analysis" / "run-123"
        analysis_dir.mkdir(parents=True)
        (analysis_dir / "project-a.md").write_text("# Project A Analysis")
        (analysis_dir / "project-b.txt").write_text("Not an analysis file")
        (analysis_dir / "global-synthesis.md").write_text("Existing synthesis")

        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=tmp_path / "toml",
        )

        await analyzer.synthesize_global(analysis_dir)

        prompt_arg = mock_client.query.call_args[0][0]
        assert "project-a.md" in prompt_arg
        assert "project-b.txt" not in prompt_arg
        # Should exclude existing global synthesis file
        assert "global-synthesis.md" not in prompt_arg

    @pytest.mark.asyncio
    async def test_synthesize_global_empty_directory(
        self, mock_client, mock_db, tmp_path
    ):
        """Global synthesis raises error on empty directory."""
        analysis_dir = tmp_path / "analysis" / "run-123"
        analysis_dir.mkdir(parents=True)

        analyzer = SessionAnalyzer(
            client=mock_client,
            db=mock_db,
            toml_dir=tmp_path / "toml",
        )

        with pytest.raises(ValueError, match="No analysis files found"):
            await analyzer.synthesize_global(analysis_dir)
