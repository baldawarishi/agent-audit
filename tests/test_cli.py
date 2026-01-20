"""Tests for CLI commands."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from claude_code_archive.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_archive_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestCli:
    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Archive Claude Code transcripts" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_config_show(self, runner):
        result = runner.invoke(main, ["config", "--show"])
        assert result.exit_code == 0
        assert "Archive dir:" in result.output
        assert "Projects dir:" in result.output

    def test_stats_no_db(self, runner, temp_archive_dir):
        result = runner.invoke(main, ["stats", "--archive-dir", str(temp_archive_dir)])
        assert result.exit_code == 0
        assert "No archive database found" in result.output

    def test_render_no_db(self, runner, temp_archive_dir):
        result = runner.invoke(main, ["render", "--archive-dir", str(temp_archive_dir)])
        assert result.exit_code == 0
        assert "No archive database found" in result.output

    def test_sync_missing_projects_dir(self, runner):
        result = runner.invoke(main, ["sync", "--projects-dir", "/nonexistent/path"])
        assert result.exit_code != 0  # Should fail because path doesn't exist

    def test_analyze_no_db(self, runner, temp_archive_dir):
        """Analyze command should error without database."""
        result = runner.invoke(main, ["analyze", "--archive-dir", str(temp_archive_dir)])
        assert result.exit_code == 0
        assert "No archive database found" in result.output

    def test_analyze_legacy_flag_exists(self, runner):
        """Analyze command should accept --legacy flag."""
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--legacy" in result.output
