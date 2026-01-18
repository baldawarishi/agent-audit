"""Tests for analyzer pattern detection and classification."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from claude_code_archive.analyzer.claude_client import AnalyzerClaudeClient
from claude_code_archive.analyzer.classifier import (
    ClassifiedPattern,
    build_classification_prompt,
    compute_confidence,
    compute_scope,
    load_prompt_template,
    parse_classification_response,
)
from claude_code_archive.analyzer.renderer import (
    render_recommendations_markdown,
    render_summary_stdout,
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


# ============================================================================
# Phase 3b Tests: Claude Client, Classifier, and Renderer
# ============================================================================


class TestAnalyzerClaudeClient:
    """Tests for Claude SDK client wrapper."""

    def test_extract_json_plain(self):
        """Test extracting plain JSON."""
        response = '{"key": "value"}'
        result = AnalyzerClaudeClient.extract_json(response)
        assert result == '{"key": "value"}'

    def test_extract_json_code_block(self):
        """Test extracting JSON from markdown code block."""
        response = """Here is the result:

```json
{"key": "value"}
```

That's the output."""
        result = AnalyzerClaudeClient.extract_json(response)
        assert result == '{"key": "value"}'

    def test_extract_json_generic_code_block(self):
        """Test extracting JSON from generic code block."""
        response = """```
{"key": "value"}
```"""
        result = AnalyzerClaudeClient.extract_json(response)
        assert result == '{"key": "value"}'

    def test_parse_json_response_valid(self):
        """Test parsing valid JSON response."""
        response = '{"classifications": []}'
        result = AnalyzerClaudeClient.parse_json_response(response)
        assert result == {"classifications": []}

    def test_parse_json_response_invalid(self):
        """Test parsing invalid JSON raises ValueError."""
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            AnalyzerClaudeClient.parse_json_response("not json at all")


class TestClassifier:
    """Tests for pattern classification logic."""

    def test_load_prompt_template(self):
        """Test that prompt template loads successfully."""
        template = load_prompt_template()
        assert "{patterns_input}" in template
        assert "{pattern_count}" in template
        assert "{num_projects}" in template
        assert "{date_range}" in template

    def test_build_classification_prompt(self):
        """Test building classification prompt with data."""
        patterns = {
            "tool_sequences": [
                {
                    "pattern_type": "tool_sequence",
                    "pattern_key": "A -> B -> C",
                    "occurrences": 10,
                }
            ],
            "prompt_prefixes": [],
            "prompt_phrases": [],
            "file_access": [],
        }

        prompt = build_classification_prompt(
            patterns=patterns,
            num_projects=5,
            date_range="2025-01-01 to 2025-01-15",
            global_threshold=0.3,
        )

        assert "5" in prompt  # num_projects
        assert "2025-01-01 to 2025-01-15" in prompt
        assert "30%" in prompt  # global threshold
        assert "A -> B -> C" in prompt
        assert "1 patterns" in prompt  # pattern_count

    def test_build_classification_prompt_with_file(self):
        """Test building classification prompt with file-based input."""
        patterns = {
            "tool_sequences": [
                {
                    "pattern_type": "tool_sequence",
                    "pattern_key": "A -> B -> C",
                    "occurrences": 10,
                }
            ],
            "prompt_prefixes": [],
            "prompt_phrases": [],
            "file_access": [],
        }

        prompt = build_classification_prompt(
            patterns=patterns,
            num_projects=5,
            date_range="2025-01-01 to 2025-01-15",
            global_threshold=0.3,
            patterns_file="patterns.json",
        )

        assert "Read the patterns from `patterns.json`" in prompt
        assert "A -> B -> C" not in prompt  # Not inline when using file

    def test_compute_scope_global(self):
        """Test scope detection for global patterns."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=10,
            projects={"p1", "p2", "p3", "p4"},  # 4 of 10 = 40%
        )

        scope = compute_scope(pattern, total_projects=10, global_threshold=0.3)
        assert scope == "global"

    def test_compute_scope_project(self):
        """Test scope detection for project-specific patterns."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=10,
            projects={"my-project"},  # Only 1 project
        )

        scope = compute_scope(pattern, total_projects=10, global_threshold=0.3)
        assert scope == "project:my-project"

    def test_compute_scope_edge_case(self):
        """Test scope detection with 2 projects (below threshold)."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=10,
            projects={"p1", "p2"},  # 2 of 10 = 20%, below 30%
        )

        scope = compute_scope(pattern, total_projects=10, global_threshold=0.3)
        # Should default to global since multiple projects involved
        assert scope == "global"

    def test_compute_confidence_high(self):
        """Test high confidence detection."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=15,
            sessions={"s1", "s2", "s3", "s4", "s5", "s6"},
            projects={"p1", "p2", "p3"},
        )

        confidence = compute_confidence(pattern)
        assert confidence == "high"

    def test_compute_confidence_medium(self):
        """Test medium confidence detection."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=6,
            sessions={"s1", "s2", "s3"},
            projects={"p1"},
        )

        confidence = compute_confidence(pattern)
        assert confidence == "medium"

    def test_compute_confidence_low(self):
        """Test low confidence detection."""
        pattern = RawPattern(
            pattern_type="tool_sequence",
            pattern_key="test",
            occurrences=3,
            sessions={"s1", "s2"},
            projects={"p1"},
        )

        confidence = compute_confidence(pattern)
        assert confidence == "low"

    def test_parse_classification_response(self):
        """Test parsing classification response from Claude."""
        response_json = {
            "classifications": [
                {
                    "pattern_key": "git-status -> git-diff",
                    "category": "skill",
                    "scope": "global",
                    "confidence": "high",
                    "reasoning": "Common git workflow",
                    "suggested_name": "git-review",
                    "suggested_content": "---\nname: git-review\n---",
                }
            ]
        }

        raw_patterns = {
            "git-status -> git-diff": RawPattern(
                pattern_type="tool_sequence",
                pattern_key="git-status -> git-diff",
                occurrences=10,
                sessions={"s1", "s2"},
                projects={"p1", "p2"},
            )
        }

        result = parse_classification_response(response_json, raw_patterns)

        assert len(result) == 1
        classified = result[0]
        assert classified.category == "skill"
        assert classified.scope == "global"
        assert classified.confidence == "high"
        assert classified.suggested_name == "git-review"

    def test_parse_classification_response_validates_category(self):
        """Test that invalid categories are normalized."""
        response_json = {
            "classifications": [
                {
                    "pattern_key": "test",
                    "category": "invalid_category",
                    "scope": "global",
                    "confidence": "high",
                    "reasoning": "",
                    "suggested_name": "",
                    "suggested_content": "",
                }
            ]
        }

        result = parse_classification_response(response_json, {})

        assert result[0].category == "claude_md"  # Default fallback

    def test_parse_classification_response_validates_confidence(self):
        """Test that invalid confidence is normalized."""
        response_json = {
            "classifications": [
                {
                    "pattern_key": "test",
                    "category": "skill",
                    "scope": "global",
                    "confidence": "very_high",  # Invalid
                    "reasoning": "",
                    "suggested_name": "",
                    "suggested_content": "",
                }
            ]
        }

        result = parse_classification_response(response_json, {})

        assert result[0].confidence == "low"  # Default fallback


class TestRenderer:
    """Tests for markdown rendering."""

    @pytest.fixture
    def sample_classifications(self):
        """Create sample classifications for testing."""
        return [
            ClassifiedPattern(
                raw_pattern=RawPattern(
                    pattern_type="tool_sequence",
                    pattern_key="git-status -> git-diff",
                    occurrences=47,
                    sessions={"s1", "s2", "s3"},
                    projects={"proj-a", "proj-b", "proj-c"},
                    first_seen="2025-01-01T10:00:00Z",
                    last_seen="2025-01-15T10:00:00Z",
                ),
                category="skill",
                scope="global",
                confidence="high",
                reasoning="Universal git workflow pattern",
                suggested_name="git-review",
                suggested_content="---\nname: git-review\n---",
            ),
            ClassifiedPattern(
                raw_pattern=RawPattern(
                    pattern_type="file_access",
                    pattern_key="~/project/config.py",
                    occurrences=25,
                    sessions={"s1", "s2"},
                    projects={"my-api"},
                    first_seen="2025-01-01T10:00:00Z",
                    last_seen="2025-01-10T10:00:00Z",
                ),
                category="claude_md",
                scope="project:my-api",
                confidence="medium",
                reasoning="Frequently accessed config file",
                suggested_name="config-reference",
                suggested_content="## Configuration\n\nKey settings...",
            ),
        ]

    def test_render_recommendations_markdown_structure(self, sample_classifications):
        """Test that markdown has correct structure."""
        markdown = render_recommendations_markdown(
            classifications=sample_classifications,
            total_sessions=100,
            total_projects=10,
        )

        assert "# Workflow Analysis Recommendations" in markdown
        assert "## Global Recommendations" in markdown
        assert "## Project: my-api" in markdown
        assert "### Tool Sequence: git-status -> git-diff" in markdown
        assert "### File Access: ~/project/config.py" in markdown

    def test_render_recommendations_markdown_metadata(self, sample_classifications):
        """Test that pattern metadata is included."""
        markdown = render_recommendations_markdown(
            classifications=sample_classifications,
            total_sessions=100,
            total_projects=10,
        )

        assert "**Category**: Skill" in markdown
        assert "**Confidence**: high" in markdown
        assert "47" in markdown  # occurrences
        assert "**Time span**: 2025-01-01 to 2025-01-15" in markdown

    def test_render_recommendations_markdown_details_block(self, sample_classifications):
        """Test that suggested content is in details block."""
        markdown = render_recommendations_markdown(
            classifications=sample_classifications,
            total_sessions=100,
            total_projects=10,
        )

        assert "<details>" in markdown
        assert "</details>" in markdown
        assert "Suggested SKILL.md" in markdown

    def test_render_summary_stdout(self, sample_classifications):
        """Test stdout summary rendering."""
        summary = render_summary_stdout(
            classifications=sample_classifications,
            total_sessions=100,
            total_projects=10,
        )

        assert "Analyzed 100 sessions across 10 projects" in summary
        assert "Skill: 1" in summary
        assert "CLAUDE.md: 1" in summary
        assert "high: 1" in summary
        assert "medium: 1" in summary
        assert "global: 1" in summary
        assert "project-specific: 1" in summary

    def test_render_empty_classifications(self):
        """Test rendering with no classifications."""
        markdown = render_recommendations_markdown(
            classifications=[],
            total_sessions=0,
            total_projects=0,
        )

        assert "# Workflow Analysis Recommendations" in markdown
        # Should still have header but no sections


@pytest.mark.asyncio
class TestPatternClassifierIntegration:
    """Integration tests for pattern classifier with mocked Claude client."""

    @pytest.fixture
    def mock_claude_response(self):
        """Sample Claude response for classification."""
        return {
            "classifications": [
                {
                    "pattern_key": "Bash:git-status -> Bash:git-diff -> Bash:git-add",
                    "category": "skill",
                    "scope": "global",
                    "confidence": "high",
                    "reasoning": "Common git workflow",
                    "suggested_name": "commit-workflow",
                    "suggested_content": "---\nname: commit-workflow\n---",
                }
            ]
        }

    @pytest.fixture
    def sample_patterns_result(self):
        """Sample patterns result from detect_patterns."""
        return {
            "generated_at": "2025-01-17T10:00:00Z",
            "summary": {
                "total_sessions_analyzed": 10,
                "total_projects": 3,
                "patterns_found": {
                    "tool_sequences": 1,
                    "prompt_prefixes": 0,
                    "prompt_phrases": 0,
                    "file_access": 0,
                },
            },
            "patterns": {
                "tool_sequences": [
                    {
                        "pattern_type": "tool_sequence",
                        "pattern_key": "Bash:git-status -> Bash:git-diff -> Bash:git-add",
                        "occurrences": 15,
                        "sessions": ["s1", "s2", "s3"],
                        "session_count": 3,
                        "projects": ["p1", "p2"],
                        "project_count": 2,
                        "first_seen": "2025-01-01T10:00:00Z",
                        "last_seen": "2025-01-15T10:00:00Z",
                    }
                ],
                "prompt_prefixes": [],
                "prompt_phrases": [],
                "file_access": [],
            },
        }

    async def test_classifier_with_mocked_client(
        self, mock_claude_response, sample_patterns_result
    ):
        """Test classifier with mocked Claude SDK client."""
        import json

        from claude_code_archive.analyzer.classifier import PatternClassifier

        # Create mock client
        mock_client = MagicMock(spec=AnalyzerClaudeClient)
        mock_client.query = AsyncMock(
            return_value=json.dumps(mock_claude_response)
        )
        mock_client.parse_json_response = MagicMock(
            return_value=mock_claude_response
        )

        classifier = PatternClassifier(
            client=mock_client, global_threshold=0.3, patterns_file=None
        )

        # Run classification
        results = await classifier.classify(sample_patterns_result)

        # Verify results
        assert len(results) == 1
        assert results[0].category == "skill"
        assert results[0].scope == "global"
        assert results[0].confidence == "high"
        assert results[0].suggested_name == "commit-workflow"

        # Verify client was called
        mock_client.query.assert_called_once()
