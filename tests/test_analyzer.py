"""Tests for analyzer pattern detection."""

import tempfile
from pathlib import Path

import pytest

from claude_code_archive.analyzer.patterns import (
    PatternDetector,
    RawPattern,
    detect_patterns,
    extract_phrase_ngrams,
    extract_prompt_prefix,
    extract_tool_sequences,
    merge_overlapping_sequences,
    normalize_bash_command,
    normalize_file_path,
    normalize_prompt,
    normalize_tool_name,
)
from claude_code_archive.database import Database

from tests.fixtures.analyzer_fixtures import (
    create_minimal_sessions,
    create_realistic_sessions,
)


class TestNormalizeBashCommand:
    """Tests for Bash command normalization."""

    def test_simple_command(self):
        assert normalize_bash_command('{"command": "ls"}') == "ls"
        assert normalize_bash_command('{"command": "pwd"}') == "pwd"
        assert normalize_bash_command('{"command": "echo hello"}') == "echo"

    def test_git_subcommands(self):
        assert normalize_bash_command('{"command": "git status"}') == "git-status"
        assert normalize_bash_command('{"command": "git diff HEAD"}') == "git-diff"
        assert normalize_bash_command('{"command": "git add ."}') == "git-add"
        assert normalize_bash_command('{"command": "git commit -m \\"msg\\""}') == "git-commit"

    def test_npm_subcommands(self):
        assert normalize_bash_command('{"command": "npm install"}') == "npm-install"
        assert normalize_bash_command('{"command": "npm test"}') == "npm-test"
        assert normalize_bash_command('{"command": "npm run build"}') == "npm-run"

    def test_docker_subcommands(self):
        assert normalize_bash_command('{"command": "docker build ."}') == "docker-build"
        assert normalize_bash_command('{"command": "docker run image"}') == "docker-run"
        assert normalize_bash_command('{"command": "docker compose up"}') == "docker-compose"

    def test_flags_not_subcommands(self):
        # Flags should not be treated as subcommands
        assert normalize_bash_command('{"command": "git --version"}') == "git"
        assert normalize_bash_command('{"command": "npm -v"}') == "npm"

    def test_paths_not_subcommands(self):
        # Paths should not be treated as subcommands
        assert normalize_bash_command('{"command": "git /path/to/repo"}') == "git"

    def test_invalid_json(self):
        assert normalize_bash_command("not json") == "unknown"
        assert normalize_bash_command('{"other": "field"}') == "unknown"
        assert normalize_bash_command('{"command": ""}') == "unknown"

    def test_complex_commands(self):
        # Commands with quotes and special chars
        cmd = '{"command": "git commit -m \\"fix: bug\\""}'
        assert normalize_bash_command(cmd) == "git-commit"

    def test_other_tools_with_subcommands(self):
        assert normalize_bash_command('{"command": "kubectl get pods"}') == "kubectl-get"
        assert normalize_bash_command('{"command": "cargo build"}') == "cargo-build"
        assert normalize_bash_command('{"command": "terraform plan"}') == "terraform-plan"


class TestNormalizeToolName:
    """Tests for tool name normalization."""

    def test_non_bash_tools(self):
        assert normalize_tool_name({"tool_name": "Read"}) == "Read"
        assert normalize_tool_name({"tool_name": "Edit"}) == "Edit"
        assert normalize_tool_name({"tool_name": "Write"}) == "Write"
        assert normalize_tool_name({"tool_name": "Grep"}) == "Grep"

    def test_bash_tool(self):
        tc = {"tool_name": "Bash", "input_json": '{"command": "git status"}'}
        assert normalize_tool_name(tc) == "Bash:git-status"

        tc = {"tool_name": "Bash", "input_json": '{"command": "ls -la"}'}
        assert normalize_tool_name(tc) == "Bash:ls"


class TestExtractToolSequences:
    """Tests for tool sequence extraction."""

    def test_extract_3grams(self):
        tool_calls = [
            {"tool_name": "Read", "timestamp": "2025-01-01T10:00:00Z"},
            {"tool_name": "Edit", "timestamp": "2025-01-01T10:00:01Z"},
            {"tool_name": "Write", "timestamp": "2025-01-01T10:00:02Z"},
            {"tool_name": "Bash", "input_json": '{"command": "git status"}', "timestamp": "2025-01-01T10:00:03Z"},
        ]
        sequences = extract_tool_sequences(tool_calls)
        assert len(sequences) == 2
        assert sequences[0] == ("Read", "Edit", "Write")
        assert sequences[1] == ("Edit", "Write", "Bash:git-status")

    def test_too_few_tools(self):
        tool_calls = [
            {"tool_name": "Read", "timestamp": "2025-01-01T10:00:00Z"},
            {"tool_name": "Edit", "timestamp": "2025-01-01T10:00:01Z"},
        ]
        sequences = extract_tool_sequences(tool_calls)
        assert sequences == []

    def test_ordering_by_timestamp(self):
        # Out of order by timestamp
        tool_calls = [
            {"tool_name": "Write", "timestamp": "2025-01-01T10:00:02Z"},
            {"tool_name": "Read", "timestamp": "2025-01-01T10:00:00Z"},
            {"tool_name": "Edit", "timestamp": "2025-01-01T10:00:01Z"},
        ]
        sequences = extract_tool_sequences(tool_calls)
        assert sequences[0] == ("Read", "Edit", "Write")


class TestPromptNormalization:
    """Tests for prompt text normalization."""

    def test_lowercase(self):
        assert normalize_prompt("Hello World") == "hello world"

    def test_url_replacement(self):
        text = "Check out https://example.com/path for more info"
        assert "<url>" in normalize_prompt(text)
        assert "https://" not in normalize_prompt(text)

    def test_path_replacement(self):
        text = "Read the file at /Users/test/project/file.py"
        assert "<path>" in normalize_prompt(text)
        assert "/Users/" not in normalize_prompt(text)

    def test_whitespace_normalization(self):
        text = "Multiple   spaces   here"
        assert normalize_prompt(text) == "multiple spaces here"

    def test_combined_normalization(self):
        text = "Fix  bug in /src/main.py see https://github.com/issue"
        result = normalize_prompt(text)
        assert "fix bug in <path> see <url>" == result


class TestExtractPromptPrefix:
    """Tests for prompt prefix extraction."""

    def test_extract_5_tokens(self):
        text = "help me fix the bug in the login function"
        prefix = extract_prompt_prefix(text)
        assert prefix == "help me fix the bug"

    def test_short_prompt(self):
        text = "hello world"
        prefix = extract_prompt_prefix(text)
        assert prefix == "hello world"

    def test_custom_token_count(self):
        text = "one two three four five six seven"
        prefix = extract_prompt_prefix(text, n_tokens=3)
        assert prefix == "one two three"


class TestExtractPhraseNgrams:
    """Tests for phrase n-gram extraction."""

    def test_extract_5grams(self):
        text = "one two three four five six seven"
        phrases = extract_phrase_ngrams(text)
        assert len(phrases) == 3
        assert phrases[0] == ("one", "two", "three", "four", "five")
        assert phrases[1] == ("two", "three", "four", "five", "six")

    def test_short_text(self):
        text = "one two three"
        phrases = extract_phrase_ngrams(text)
        assert phrases == []


class TestNormalizeFilePath:
    """Tests for file path normalization."""

    def test_mac_user_path(self):
        path = "/Users/john/project/file.py"
        assert normalize_file_path(path) == "~/project/file.py"

    def test_linux_home_path(self):
        path = "/home/john/project/file.py"
        assert normalize_file_path(path) == "~/project/file.py"

    def test_wsl_path(self):
        path = "/mnt/c/Users/john/project/file.py"
        assert normalize_file_path(path) == "~/project/file.py"

    def test_relative_path(self):
        path = "src/file.py"
        assert normalize_file_path(path) == "src/file.py"


class TestMergeOverlappingSequences:
    """Tests for sequence merging logic."""

    def test_merge_adjacent_sequences(self):
        # ABC + BCD -> ABCD
        sequences = {
            ("A", "B", "C"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1"},
            ),
            ("B", "C", "D"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1"},
            ),
        }
        merged = merge_overlapping_sequences(sequences)
        assert len(merged) == 1
        assert "A → B → C → D" in merged[0].pattern_key

    def test_no_merge_different_counts(self):
        # Don't merge if counts are too different
        sequences = {
            ("A", "B", "C"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1"},
            ),
            ("B", "C", "D"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=2,  # Too different
                sessions={"s1"},
                projects={"p1"},
            ),
        }
        merged = merge_overlapping_sequences(sequences)
        assert len(merged) == 2

    def test_no_merge_no_overlap(self):
        sequences = {
            ("A", "B", "C"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1"},
            ),
            ("X", "Y", "Z"): RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1"},
            ),
        }
        merged = merge_overlapping_sequences(sequences)
        assert len(merged) == 2


class TestPatternDetector:
    """Integration tests for PatternDetector with database."""

    @pytest.fixture
    def db_with_minimal_data(self):
        """Create a temporary database with minimal test data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        database = Database(db_path)
        database.connect()

        for session in create_minimal_sessions():
            database.insert_session(session)

        yield database
        database.close()
        db_path.unlink()

    @pytest.fixture
    def db_with_realistic_data(self):
        """Create a temporary database with realistic test data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        database = Database(db_path)
        database.connect()

        for session in create_realistic_sessions():
            database.insert_session(session)

        yield database
        database.close()
        db_path.unlink()

    def test_detect_tool_sequences_minimal(self, db_with_minimal_data):
        """Test tool sequence detection with minimal data."""
        detector = PatternDetector(
            db=db_with_minimal_data,
            min_occurrences=2,
            min_sessions=2,
        )
        sequences = detector.detect_tool_sequences()

        # Should find git-status -> git-diff -> git-add pattern
        assert len(sequences) >= 1
        pattern_keys = [s.pattern_key for s in sequences]
        # The exact key depends on merging, but should contain git commands
        assert any("git-status" in k for k in pattern_keys)

    def test_detect_prompt_prefixes_minimal(self, db_with_minimal_data):
        """Test prompt prefix detection with minimal data."""
        detector = PatternDetector(
            db=db_with_minimal_data,
            min_occurrences=2,
            min_sessions=2,
        )
        prefixes = detector.detect_prompt_prefixes()

        # Should find "help me fix the bug" prefix
        assert len(prefixes) >= 1
        assert any("help me fix the" in p.pattern_key for p in prefixes)

    def test_detect_file_access_minimal(self, db_with_minimal_data):
        """Test file access detection with minimal data."""
        detector = PatternDetector(
            db=db_with_minimal_data,
            min_occurrences=2,
            min_sessions=2,
        )
        file_patterns = detector.detect_file_access()

        # Should find config.py accessed in multiple sessions
        assert len(file_patterns) >= 1
        # Check for normalized path
        assert any("config.py" in p.pattern_key for p in file_patterns)

    def test_detect_all_realistic(self, db_with_realistic_data):
        """Test full pattern detection with realistic data."""
        detector = PatternDetector(
            db=db_with_realistic_data,
            min_occurrences=3,
            min_sessions=2,
        )
        patterns = detector.detect_all()

        # Should have patterns in multiple categories
        assert "tool_sequences" in patterns
        assert "prompt_prefixes" in patterns
        assert "file_access" in patterns

        # Git workflow should be detected (appears 3 times)
        sequences = patterns["tool_sequences"]
        git_patterns = [s for s in sequences if "git" in s.pattern_key.lower()]
        assert len(git_patterns) >= 1

    def test_project_filter(self, db_with_realistic_data):
        """Test filtering by project."""
        detector = PatternDetector(
            db=db_with_realistic_data,
            min_occurrences=2,
            min_sessions=2,
            project_filter="project-alpha",
        )
        patterns = detector.detect_all()

        # All detected patterns should be from project-alpha
        for pattern_list in patterns.values():
            for pattern in pattern_list:
                assert "project-alpha" in pattern.projects

    def test_since_filter(self, db_with_realistic_data):
        """Test filtering by date."""
        detector = PatternDetector(
            db=db_with_realistic_data,
            min_occurrences=2,
            min_sessions=2,
            since="2025-01-05",
        )
        sessions = detector._get_filtered_sessions()

        # Should only include sessions from Jan 5 onwards
        for session in sessions:
            assert session["started_at"] >= "2025-01-05"


class TestDetectPatterns:
    """Tests for the main detect_patterns function."""

    @pytest.fixture
    def db_with_data(self):
        """Create a temporary database with test data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        database = Database(db_path)
        database.connect()

        for session in create_minimal_sessions():
            database.insert_session(session)

        yield database
        database.close()
        db_path.unlink()

    def test_output_structure(self, db_with_data):
        """Test that output has correct structure for JSON."""
        result = detect_patterns(
            db=db_with_data,
            min_occurrences=2,
            min_sessions=2,
        )

        # Check top-level structure
        assert "generated_at" in result
        assert "summary" in result
        assert "patterns" in result

        # Check summary structure
        summary = result["summary"]
        assert "total_sessions_analyzed" in summary
        assert "total_projects" in summary
        assert "patterns_found" in summary

        # Check patterns structure
        patterns = result["patterns"]
        assert "tool_sequences" in patterns
        assert "prompt_prefixes" in patterns
        assert "prompt_phrases" in patterns
        assert "file_access" in patterns

    def test_pattern_serialization(self, db_with_data):
        """Test that patterns serialize correctly."""
        result = detect_patterns(
            db=db_with_data,
            min_occurrences=2,
            min_sessions=2,
        )

        # Each pattern should have required fields
        for pattern_type, pattern_list in result["patterns"].items():
            for pattern in pattern_list:
                assert "pattern_type" in pattern
                assert "pattern_key" in pattern
                assert "occurrences" in pattern
                assert "sessions" in pattern
                assert "session_count" in pattern
                assert "projects" in pattern
                assert "project_count" in pattern
