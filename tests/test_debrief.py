"""Tests for debrief module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_audit.cli import main
from agent_audit.debrief import (
    _analyze_thinking_blocks,
    _analyze_tool_patterns,
    _build_timeline_summary,
    _categorize_commits,
    _compose_session_specific_questions,
    _compose_what_happened,
    _compute_autonomy_ratio,
    _describe_session_characteristics,
    _detect_key_moments,
    _extract_opening_context,
    build_metrics_summary,
    build_session_preanalysis,
    discover_related_sessions,
    gather_git_context,
    gather_pr_context,
    generate_session_guide,
    generate_slug,
    prepare_debrief,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_archive_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _make_session_dict(
    session_id="abc12345-6789-0000-0000-000000000000",
    project="test-project",
    summary="Test session summary",
    title=None,
    slug=None,
    started_at="2026-02-10T10:00:00Z",
    ended_at="2026-02-10T12:00:00Z",
    cwd="/tmp/test-project",
    repo="owner/test-repo",
    repo_platform="github",
    model="claude-sonnet-4-20250514",
    total_input_tokens=5000,
    total_output_tokens=10000,
    total_cache_read_tokens=2000,
    **kwargs,
):
    """Create a test session dict."""
    d = {
        "id": session_id,
        "project": project,
        "agent_type": "claude-code",
        "cwd": cwd,
        "git_branch": "main",
        "slug": slug,
        "summary": summary,
        "title": title,
        "parent_session_id": None,
        "started_at": started_at,
        "ended_at": ended_at,
        "claude_version": "1.0.0",
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        "model": model,
        "is_warmup": False,
        "is_sidechain": False,
        "repo": repo,
        "repo_platform": repo_platform,
        "session_context": None,
    }
    d.update(kwargs)
    return d


def _make_message(
    msg_type="user",
    content="Test message",
    thinking=None,
    msg_id="msg-1",
    timestamp="2026-02-10T10:00:00Z",
    **kwargs,
):
    """Create a test message dict."""
    return {
        "id": msg_id,
        "session_id": kwargs.get("session_id", "test-session"),
        "type": msg_type,
        "timestamp": timestamp,
        "content": content,
        "parent_uuid": None,
        "model": kwargs.get("model"),
        "input_tokens": kwargs.get("input_tokens", 0),
        "output_tokens": kwargs.get("output_tokens", 0),
        "thinking": thinking,
        "stop_reason": kwargs.get("stop_reason"),
        "is_sidechain": False,
    }


def _make_tool_call(tool_name="Bash", tc_id="tc-1", timestamp="2026-02-10T10:00:00Z"):
    """Create a test tool call dict."""
    return {
        "id": tc_id,
        "message_id": "msg-1",
        "session_id": "test-session",
        "tool_name": tool_name,
        "input_json": "{}",
        "timestamp": timestamp,
    }


def _make_commit(message="Fix bug", commit_id="commit-1", timestamp="2026-02-10T10:00:00Z"):
    """Create a test commit dict."""
    return {
        "id": commit_id,
        "session_id": "test-session",
        "commit_hash": "abc1234",
        "message": message,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Pre-analysis helper tests
# ---------------------------------------------------------------------------


class TestExtractOpeningContext:
    """Tests for _extract_opening_context."""

    def test_extracts_user_messages(self):
        messages = [
            _make_message("user", "First prompt"),
            _make_message("assistant", "Response"),
            _make_message("user", "Second prompt"),
        ]
        result = _extract_opening_context(messages)
        assert "First prompt" in result
        assert "Second prompt" in result

    def test_truncates_long_messages(self):
        long_content = "A" * 600
        messages = [_make_message("user", long_content)]
        result = _extract_opening_context(messages)
        assert len(result) <= 504  # 500 + "..."
        assert result.endswith("...")

    def test_handles_empty_messages(self):
        result = _extract_opening_context([])
        assert result == "No user messages found."

    def test_limits_to_three_messages(self):
        messages = [
            _make_message("user", f"Prompt {i}", msg_id=f"m{i}")
            for i in range(5)
        ]
        result = _extract_opening_context(messages)
        assert "Prompt 0" in result
        assert "Prompt 1" in result
        assert "Prompt 2" in result
        assert "Prompt 3" not in result

    def test_skips_assistant_messages(self):
        messages = [
            _make_message("assistant", "AI response"),
            _make_message("user", "User prompt"),
        ]
        result = _extract_opening_context(messages)
        assert "AI response" not in result
        assert "User prompt" in result


class TestCategorizeCommits:
    """Tests for _categorize_commits."""

    def test_categorizes_ci_commits(self):
        commits = [
            _make_commit("Fix ruff lint errors"),
            _make_commit("Update CI pipeline"),
            _make_commit("Add mypy check"),
        ]
        result = _categorize_commits(commits)
        assert result["category_counts"]["ci"] == 3

    def test_categorizes_feature_commits(self):
        commits = [
            _make_commit("Add user authentication"),
            _make_commit("Implement search feature"),
        ]
        result = _categorize_commits(commits)
        assert result["category_counts"]["feature"] == 2

    def test_categorizes_mixed_commits(self):
        commits = [
            _make_commit("Fix ruff lint errors"),
            _make_commit("Add new feature"),
            _make_commit("Fix bug in parser"),
            _make_commit("Refactor database module"),
            _make_commit("Some random change"),
        ]
        result = _categorize_commits(commits)
        assert result["category_counts"]["ci"] == 1
        assert result["category_counts"]["feature"] == 1
        assert result["category_counts"]["fix"] == 1
        assert result["category_counts"]["refactor"] == 1
        assert result["category_counts"]["other"] == 1

    def test_summary_text(self):
        commits = [
            _make_commit("Fix ruff lint errors"),
            _make_commit("Fix CI pipeline"),
        ]
        result = _categorize_commits(commits)
        assert "Of 2 commits" in result["summary"]
        assert "2 ci" in result["summary"]

    def test_empty_commits(self):
        result = _categorize_commits([])
        assert result["summary"] == "No commits"
        assert result["category_counts"] == {}

    def test_categorizes_oom_prevention_as_fix(self):
        commits = [
            _make_commit("Cap field-matcher states at 1024 to prevent exponential OOM"),
            _make_commit("Limit recursion depth to avoid stack overflow"),
        ]
        result = _categorize_commits(commits)
        assert result["category_counts"].get("fix") == 2
        assert result["category_counts"].get("other", 0) == 0


class TestDescribeSessionCharacteristics:
    """Tests for _describe_session_characteristics."""

    def test_with_exploration_tools(self):
        tool_calls = (
            [_make_tool_call("Bash", tc_id=f"b{i}") for i in range(7)]
            + [_make_tool_call("Read", tc_id=f"r{i}") for i in range(3)]
        )
        result = _describe_session_characteristics([], tool_calls, [])
        assert "Bash" in result
        assert "exploration/debugging-heavy" in result

    def test_with_implementation_tools(self):
        tool_calls = (
            [_make_tool_call("Edit", tc_id=f"e{i}") for i in range(5)]
            + [_make_tool_call("Write", tc_id=f"w{i}") for i in range(3)]
            + [_make_tool_call("Bash", tc_id=f"b{i}") for i in range(2)]
        )
        result = _describe_session_characteristics([], tool_calls, [])
        assert "implementation-heavy" in result

    def test_with_ci_commits(self):
        commits = [_make_commit(f"Fix ruff lint {i}") for i in range(5)]
        # Need at least 1 tool call to avoid empty observations
        result = _describe_session_characteristics([], [], commits)
        assert "ci-related" in result

    def test_no_patterns(self):
        # With 0 messages, the "Short session" observation triggers
        # Only truly empty when there are some messages but nothing notable
        messages = [_make_message("user", f"m{i}", msg_id=f"m{i}") for i in range(30)]
        result = _describe_session_characteristics(messages, [], [])
        # 30 messages is not "long" or "short" — no tool calls, no commits
        assert "No notable patterns observed." == result

    def test_long_session_noted(self):
        messages = [_make_message("user", f"m{i}", msg_id=f"m{i}") for i in range(150)]
        result = _describe_session_characteristics(messages, [], [])
        assert "Long session" in result
        assert "150 messages" in result


class TestComputeAutonomyRatio:
    """Tests for _compute_autonomy_ratio."""

    def test_high_autonomy(self):
        messages = (
            [_make_message("user", "hi", msg_id=f"u{i}") for i in range(2)]
            + [_make_message("assistant", "resp", msg_id=f"a{i}") for i in range(30)]
        )
        ratio, desc = _compute_autonomy_ratio(messages)
        assert ratio < 0.10
        assert "High AI autonomy" in desc

    def test_moderate_autonomy(self):
        messages = (
            [_make_message("user", "hi", msg_id=f"u{i}") for i in range(5)]
            + [_make_message("assistant", "resp", msg_id=f"a{i}") for i in range(25)]
        )
        ratio, desc = _compute_autonomy_ratio(messages)
        assert 0.10 <= ratio < 0.25
        assert "Moderate autonomy" in desc

    def test_zero_messages(self):
        ratio, desc = _compute_autonomy_ratio([])
        assert ratio == 0.0
        assert "No messages" in desc


class TestAnalyzeToolPatterns:
    """Tests for _analyze_tool_patterns."""

    def test_counts_tools(self):
        tool_calls = [
            _make_tool_call("Bash", tc_id="1"),
            _make_tool_call("Read", tc_id="2"),
            _make_tool_call("Bash", tc_id="3"),
        ]
        result = _analyze_tool_patterns(tool_calls)
        assert result["counts"]["Bash"] == 2
        assert result["counts"]["Read"] == 1

    def test_dominant_description(self):
        tool_calls = [_make_tool_call("Bash", tc_id=str(i)) for i in range(10)]
        result = _analyze_tool_patterns(tool_calls)
        assert "Bash" in result["dominant_description"]
        assert "10/10" in result["dominant_description"]

    def test_empty_tool_calls(self):
        result = _analyze_tool_patterns([])
        assert result["counts"] == {}
        assert result["top_trigrams"] == []

    def test_trigrams_computed(self):
        tool_calls = [
            _make_tool_call("Bash", tc_id="1"),
            _make_tool_call("Read", tc_id="2"),
            _make_tool_call("Edit", tc_id="3"),
            _make_tool_call("Bash", tc_id="4"),
            _make_tool_call("Read", tc_id="5"),
            _make_tool_call("Edit", tc_id="6"),
        ]
        result = _analyze_tool_patterns(tool_calls)
        assert len(result["top_trigrams"]) > 0
        # The sequence Bash→Read→Edit should appear twice
        trigrams = dict(result["top_trigrams"])
        assert ("Bash", "Read", "Edit") in trigrams
        assert trigrams[("Bash", "Read", "Edit")] == 2


class TestAnalyzeThinkingBlocks:
    """Tests for _analyze_thinking_blocks."""

    def test_counts_thinking_messages(self):
        messages = [
            _make_message("assistant", "response", thinking="I think..."),
            _make_message("assistant", "response2", thinking=None),
            _make_message("assistant", "response3", thinking="More thinking"),
        ]
        result = _analyze_thinking_blocks(messages)
        assert result["count"] == 2
        assert result["available"] is True

    def test_empty_thinking(self):
        messages = [
            _make_message("assistant", "response", thinking=None),
            _make_message("assistant", "response2", thinking=""),
        ]
        result = _analyze_thinking_blocks(messages)
        assert result["count"] == 0
        assert result["available"] is False


class TestDetectKeyMoments:
    """Tests for _detect_key_moments."""

    def test_detects_corrections(self):
        messages = [
            _make_message("assistant", "I'll do X", msg_id="a1"),
            _make_message("user", "No, do Y instead", msg_id="u1"),
            _make_message("assistant", "OK, doing Y", msg_id="a2"),
            _make_message("user", "Actually, try Z", msg_id="u2"),
        ]
        result = _detect_key_moments(messages)
        assert len(result) == 2
        assert "No, do Y instead" in result[0]["content"]
        assert "Actually, try Z" in result[1]["content"]

    def test_caps_at_10(self):
        messages = []
        for i in range(25):
            messages.append(_make_message("assistant", f"response {i}", msg_id=f"a{i}"))
            messages.append(_make_message("user", f"No, wrong {i}", msg_id=f"u{i}"))
        result = _detect_key_moments(messages)
        assert len(result) == 10

    def test_ignores_long_messages(self):
        messages = [
            _make_message("assistant", "I'll do X", msg_id="a1"),
            _make_message("user", "No " + "A" * 300, msg_id="u1"),
        ]
        result = _detect_key_moments(messages)
        assert len(result) == 0

    def test_ignores_non_corrections(self):
        messages = [
            _make_message("assistant", "I'll do X", msg_id="a1"),
            _make_message("user", "Looks good!", msg_id="u1"),
        ]
        result = _detect_key_moments(messages)
        assert len(result) == 0

    def test_detects_user_interruptions(self):
        messages = [
            _make_message("assistant", "I'm working on...", msg_id="a1"),
            _make_message("user", "[Request interrupted by user]", msg_id="u1"),
            _make_message("user", "Do something else", msg_id="u2"),
        ]
        result = _detect_key_moments(messages)
        assert len(result) >= 1
        assert "interrupted" in result[0]["content"].lower()

    def test_detects_doesnt_work(self):
        messages = [
            _make_message("assistant", "I fixed it", msg_id="a1"),
            _make_message("user", "doesn't work. try another way", msg_id="u1"),
        ]
        result = _detect_key_moments(messages)
        assert len(result) == 1


class TestBuildTimelineSummary:
    """Tests for _build_timeline_summary."""

    def test_continuous_session(self):
        # All messages within a few minutes — single work session
        messages = (
            [_make_message("user", f"msg{i}", msg_id=f"u{i}",
                           timestamp=f"2026-02-10T10:0{i}:00Z") for i in range(7)]
            + [_make_message("assistant", f"resp{i}", msg_id=f"a{i}",
                             timestamp=f"2026-02-10T10:1{i}:00Z") for i in range(5)]
        )
        result = _build_timeline_summary(messages, [])
        assert "Single continuous session" in result
        assert "12 messages" in result

    def test_detects_temporal_gaps(self):
        # Two work sessions with a 2-hour gap between them
        messages = [
            _make_message("user", "morning work", msg_id="u1",
                          timestamp="2026-02-10T10:00:00Z"),
            _make_message("assistant", "resp", msg_id="a1",
                          timestamp="2026-02-10T10:05:00Z"),
            _make_message("user", "more morning", msg_id="u2",
                          timestamp="2026-02-10T10:10:00Z"),
            # 2-hour gap
            _make_message("user", "afternoon work", msg_id="u3",
                          timestamp="2026-02-10T12:15:00Z"),
            _make_message("assistant", "resp2", msg_id="a2",
                          timestamp="2026-02-10T12:20:00Z"),
            _make_message("user", "more afternoon", msg_id="u4",
                          timestamp="2026-02-10T12:25:00Z"),
        ]
        result = _build_timeline_summary(messages, [])
        assert "2 distinct work sessions" in result

    def test_empty_messages(self):
        result = _build_timeline_summary([], [])
        assert "No messages" in result

    def test_very_short_session(self):
        messages = [_make_message("user", "hi"), _make_message("assistant", "hello")]
        result = _build_timeline_summary(messages, [])
        assert "Very short session" in result

    def test_includes_commit_distribution(self):
        messages = [
            _make_message("user", f"m{i}", msg_id=f"m{i}",
                          timestamp=f"2026-02-10T10:{i:02d}:00Z")
            for i in range(6)
        ]
        commits = [
            _make_commit("Late commit", timestamp="2026-02-10T10:05:00Z"),
        ]
        result = _build_timeline_summary(messages, commits)
        assert "Commits:" in result


# ---------------------------------------------------------------------------
# Pre-analysis integration test
# ---------------------------------------------------------------------------


class TestBuildSessionPreanalysis:
    """Tests for build_session_preanalysis."""

    def test_returns_all_required_keys(self):
        messages = [
            _make_message("user", "Add fuzz testing"),
            _make_message("assistant", "I'll help with that"),
        ]
        result = build_session_preanalysis(messages, [], [], _make_session_dict())
        expected_keys = {
            "opening_context", "session_characteristics", "autonomy_ratio",
            "autonomy_description", "tool_patterns", "commit_categories",
            "thinking_blocks", "key_moments", "timeline_summary",
            "total_messages", "user_messages", "total_commits",
        }
        assert expected_keys == set(result.keys())

    def test_opening_context_from_messages(self):
        messages = [
            _make_message("user", "Add fuzz testing to quamina-rs"),
            _make_message("assistant", "Sure thing"),
        ]
        result = build_session_preanalysis(messages, [], [], _make_session_dict())
        assert "Add fuzz testing" in result["opening_context"]

    def test_total_counts(self):
        messages = [
            _make_message("user", "hi", msg_id="u1"),
            _make_message("assistant", "hello", msg_id="a1"),
            _make_message("user", "do X", msg_id="u2"),
        ]
        commits = [_make_commit("Fix something")]
        result = build_session_preanalysis(
            messages, [], commits, _make_session_dict()
        )
        assert result["total_messages"] == 3
        assert result["user_messages"] == 2
        assert result["total_commits"] == 1

    def test_preanalysis_md_is_valid_markdown(self):
        from agent_audit.debrief import _render_preanalysis_md

        messages = [
            _make_message("user", "Add fuzz testing"),
            _make_message("assistant", "OK", thinking="Let me think..."),
        ]
        tool_calls = [_make_tool_call("Bash")]
        commits = [_make_commit("Add fuzz harness")]
        preanalysis = build_session_preanalysis(
            messages, tool_calls, commits, _make_session_dict()
        )
        md = _render_preanalysis_md(preanalysis)
        assert md.startswith("# Session Pre-Analysis")
        assert "## Opening Context" in md
        assert "## Tool Patterns" in md
        assert "## Commits" in md
        assert "## Thinking Blocks" in md
        assert "## Timeline" in md


# ---------------------------------------------------------------------------
# Composition helper tests
# ---------------------------------------------------------------------------


class TestComposeWhatHappened:
    """Tests for _compose_what_happened."""

    def test_includes_opening(self):
        preanalysis = build_session_preanalysis(
            [_make_message("user", "Add fuzz testing to quamina-rs"),
             _make_message("assistant", "OK")],
            [], [], _make_session_dict(),
        )
        result = _compose_what_happened(preanalysis, _make_session_dict())
        assert "Add fuzz testing" in result

    def test_includes_autonomy(self):
        messages = (
            [_make_message("user", "hi", msg_id=f"u{i}") for i in range(2)]
            + [_make_message("assistant", "resp", msg_id=f"a{i}") for i in range(20)]
        )
        preanalysis = build_session_preanalysis(
            messages, [], [], _make_session_dict()
        )
        result = _compose_what_happened(preanalysis, _make_session_dict())
        assert "22 messages" in result

    def test_includes_commit_messages(self):
        commits = [
            _make_commit("Fix buffer overflow in parser"),
            _make_commit("Add input validation"),
        ]
        preanalysis = build_session_preanalysis(
            [_make_message("user", "fix parser")], [], commits,
            _make_session_dict(),
        )
        result = _compose_what_happened(preanalysis, _make_session_dict())
        # Should include actual commit messages, not just counts
        assert "Fix buffer overflow" in result or "input validation" in result

    def test_separates_ci_from_key_commits(self):
        commits = [
            _make_commit("Fix OOM in matcher"),
            _make_commit("ci: retrigger CI"),
            _make_commit("ci: pin nightly"),
        ]
        preanalysis = build_session_preanalysis(
            [_make_message("user", "fix stuff")], [], commits,
            _make_session_dict(),
        )
        result = _compose_what_happened(preanalysis, _make_session_dict())
        # CI commits mentioned separately as infrastructure work
        assert "CI" in result or "ci" in result.lower()
        assert "Fix OOM" in result or "Key commits" in result


class TestComposeSessionSpecificQuestions:
    """Tests for _compose_session_specific_questions."""

    def test_ci_heavy_commits(self):
        commits = [_make_commit(f"Fix ruff lint {i}") for i in range(5)]
        preanalysis = build_session_preanalysis(
            [_make_message("user", "fix linting")], [], commits,
            _make_session_dict(),
        )
        result = _compose_session_specific_questions(preanalysis)
        assert "CI" in result or "ci" in result.lower()
        assert "yak-shave" in result

    def test_high_autonomy(self):
        messages = (
            [_make_message("user", "do everything", msg_id="u0")]
            + [_make_message("assistant", f"step {i}", msg_id=f"a{i}")
               for i in range(30)]
        )
        preanalysis = build_session_preanalysis(
            messages, [], [], _make_session_dict(),
        )
        result = _compose_session_specific_questions(preanalysis)
        assert "autonomy" in result.lower()

    def test_always_has_surprise_question(self):
        preanalysis = build_session_preanalysis(
            [_make_message("user", "simple task"),
             _make_message("assistant", "done")],
            [], [], _make_session_dict(),
        )
        result = _compose_session_specific_questions(preanalysis)
        assert "surprise" in result.lower()

    def test_key_moments_referenced(self):
        messages = [
            _make_message("assistant", "I'll do X", msg_id="a1"),
            _make_message("user", "No, that's wrong", msg_id="u1"),
        ]
        preanalysis = build_session_preanalysis(
            messages, [], [], _make_session_dict(),
        )
        result = _compose_session_specific_questions(preanalysis)
        assert "wrong" in result.lower() or "course correction" in result.lower()


# ---------------------------------------------------------------------------
# Existing test classes (updated where needed)
# ---------------------------------------------------------------------------


class TestDiscoverRelatedSessions:
    """Tests for discover_related_sessions."""

    def test_returns_sessions_from_same_project(self):
        primary = _make_session_dict()
        related1 = _make_session_dict(
            session_id="related-1",
            started_at="2026-02-10T09:00:00Z",
        )
        related2 = _make_session_dict(
            session_id="related-2",
            started_at="2026-02-10T14:00:00Z",
        )

        db = MagicMock()
        db.get_sessions_by_project.return_value = [primary, related1, related2]

        result = discover_related_sessions(db, primary)

        assert len(result) == 2
        db.get_sessions_by_project.assert_called_once_with("test-project")

    def test_excludes_primary_session(self):
        primary = _make_session_dict()

        db = MagicMock()
        db.get_sessions_by_project.return_value = [primary]

        result = discover_related_sessions(db, primary)

        assert len(result) == 0

    def test_sorts_by_date_proximity(self):
        primary = _make_session_dict(started_at="2026-02-10T12:00:00Z")
        close = _make_session_dict(
            session_id="close",
            started_at="2026-02-10T11:00:00Z",
        )
        far = _make_session_dict(
            session_id="far",
            started_at="2026-02-01T10:00:00Z",
        )

        db = MagicMock()
        db.get_sessions_by_project.return_value = [primary, far, close]

        result = discover_related_sessions(db, primary)

        assert len(result) == 2
        assert result[0]["id"] == "close"
        assert result[1]["id"] == "far"

    def test_respects_max_results(self):
        primary = _make_session_dict()
        sessions = [primary] + [
            _make_session_dict(
                session_id=f"session-{i}",
                started_at=f"2026-02-{10+i:02d}T10:00:00Z",
            )
            for i in range(20)
        ]

        db = MagicMock()
        db.get_sessions_by_project.return_value = sessions

        result = discover_related_sessions(db, primary, max_results=5)

        assert len(result) == 5

    def test_handles_no_related_sessions(self):
        primary = _make_session_dict()

        db = MagicMock()
        db.get_sessions_by_project.return_value = [primary]

        result = discover_related_sessions(db, primary)

        assert result == []

    def test_handles_missing_dates(self):
        primary = _make_session_dict(started_at=None)
        related = _make_session_dict(session_id="related", started_at=None)

        db = MagicMock()
        db.get_sessions_by_project.return_value = [primary, related]

        result = discover_related_sessions(db, primary)

        assert len(result) == 1


class TestGenerateSlug:
    """Tests for generate_slug."""

    def test_generates_from_summary(self):
        session = _make_session_dict(summary="Generalize github_repo field")
        slug = generate_slug(session)
        assert slug == "generalize-github-repo-field"

    def test_falls_back_to_title(self):
        session = _make_session_dict(summary=None, title="My Cool Feature")
        slug = generate_slug(session)
        assert slug == "my-cool-feature"

    def test_falls_back_to_slug_field(self):
        session = _make_session_dict(summary=None, title=None, slug="existing-slug")
        slug = generate_slug(session)
        assert slug == "existing-slug"

    def test_falls_back_to_session_id_prefix(self):
        session = _make_session_dict(summary=None, title=None, slug=None)
        slug = generate_slug(session)
        assert slug == "abc12345"

    def test_falls_back_to_first_user_message(self):
        session = _make_session_dict(summary=None, title=None, slug=None)
        slug = generate_slug(session, first_user_message="Add fuzz testing to quamina-rs")
        assert slug == "add-fuzz-testing-to-quamina-rs"

    def test_first_user_message_not_used_when_summary_exists(self):
        session = _make_session_dict(summary="Real summary")
        slug = generate_slug(session, first_user_message="First prompt")
        assert slug == "real-summary"

    def test_handles_special_characters(self):
        session = _make_session_dict(summary="Fix bug #123 (critical!)")
        slug = generate_slug(session)
        assert slug == "fix-bug-123-critical"

    def test_truncates_long_slugs(self):
        session = _make_session_dict(summary="A" * 100 + " very long summary text")
        slug = generate_slug(session)
        assert len(slug) <= 60


class TestBuildMetricsSummary:
    """Tests for build_metrics_summary."""

    def test_includes_session_info(self):
        primary = _make_session_dict()
        db = MagicMock()
        db.get_messages_for_session.return_value = [
            {"type": "user", "id": "m1"},
            {"type": "assistant", "id": "m2"},
            {"type": "user", "id": "m3"},
        ]
        db.get_tool_calls_for_session.return_value = [
            {"tool_name": "Bash", "id": "tc1"},
            {"tool_name": "Read", "id": "tc2"},
            {"tool_name": "Bash", "id": "tc3"},
        ]
        db.get_commits_for_session.return_value = []

        result = build_metrics_summary(db, primary, [])

        assert "# Session Metrics" in result
        assert "test-project" in result
        assert "Total messages: 3" in result
        assert "User messages: 2" in result
        assert "Assistant messages: 1" in result

    def test_includes_token_counts(self):
        primary = _make_session_dict(
            total_input_tokens=5000,
            total_output_tokens=10000,
            total_cache_read_tokens=2000,
        )
        db = MagicMock()
        db.get_messages_for_session.return_value = []
        db.get_tool_calls_for_session.return_value = []
        db.get_commits_for_session.return_value = []

        result = build_metrics_summary(db, primary, [])

        assert "5,000" in result
        assert "10,000" in result
        assert "2,000" in result

    def test_includes_tool_breakdown(self):
        primary = _make_session_dict()
        db = MagicMock()
        db.get_messages_for_session.return_value = []
        db.get_tool_calls_for_session.return_value = [
            {"tool_name": "Bash", "id": "1"},
            {"tool_name": "Read", "id": "2"},
            {"tool_name": "Bash", "id": "3"},
        ]
        db.get_commits_for_session.return_value = []

        result = build_metrics_summary(db, primary, [])

        assert "| Bash | 2 |" in result
        assert "| Read | 1 |" in result

    def test_includes_related_sessions_stats(self):
        primary = _make_session_dict()
        related = [
            _make_session_dict(
                session_id="r1",
                total_input_tokens=3000,
                total_output_tokens=6000,
            ),
        ]
        db = MagicMock()
        db.get_messages_for_session.return_value = []
        db.get_tool_calls_for_session.return_value = []
        db.get_commits_for_session.return_value = []

        result = build_metrics_summary(db, primary, related)

        assert "Related Sessions" in result
        assert "1 other sessions" in result

    def test_includes_commits(self):
        primary = _make_session_dict()
        db = MagicMock()
        db.get_messages_for_session.return_value = []
        db.get_tool_calls_for_session.return_value = []
        db.get_commits_for_session.return_value = [
            {"commit_hash": "abc1234", "message": "Fix bug"},
        ]

        result = build_metrics_summary(db, primary, [])

        assert "abc1234" in result
        assert "Fix bug" in result

    def test_includes_commit_categorization_when_preanalysis_provided(self):
        primary = _make_session_dict()
        db = MagicMock()
        messages = [_make_message("user", "hi")]
        tool_calls = []
        commits = [_make_commit("Fix ruff lint"), _make_commit("Fix CI")]
        preanalysis = build_session_preanalysis(
            messages, tool_calls, commits, primary,
        )

        result = build_metrics_summary(
            db, primary, [],
            preanalysis=preanalysis,
            messages=messages,
            tool_calls=tool_calls,
            commits=commits,
        )

        assert "Commit Categorization" in result
        assert "Autonomy" in result
        assert "Notable Patterns" in result

    def test_backward_compatible_without_preanalysis(self):
        primary = _make_session_dict()
        db = MagicMock()
        db.get_messages_for_session.return_value = []
        db.get_tool_calls_for_session.return_value = []
        db.get_commits_for_session.return_value = []

        result = build_metrics_summary(db, primary, [])

        assert "# Session Metrics" in result
        assert "Commit Categorization" not in result

    def test_skips_db_queries_when_data_provided(self):
        primary = _make_session_dict()
        db = MagicMock()
        messages = [{"type": "user", "id": "m1"}]
        tool_calls = [{"tool_name": "Bash", "id": "tc1"}]
        commits = []

        build_metrics_summary(
            db, primary, [],
            messages=messages,
            tool_calls=tool_calls,
            commits=commits,
        )

        db.get_messages_for_session.assert_not_called()
        db.get_tool_calls_for_session.assert_not_called()
        db.get_commits_for_session.assert_not_called()


class TestGenerateSessionGuide:
    """Tests for generate_session_guide."""

    def test_renders_template(self, tmp_path):
        primary = _make_session_dict()
        context_dir = tmp_path / "context"
        drafts_dir = tmp_path / "drafts"
        context_dir.mkdir()
        drafts_dir.mkdir()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=context_dir,
            drafts_dir=drafts_dir,
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "# Session Debrief Guide" in result
        assert "test-project" in result
        assert "Test session summary" in result

    def test_includes_related_sessions_entry(self, tmp_path):
        primary = _make_session_dict()
        related = [_make_session_dict(session_id="related-1")]

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=related,
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "related-sessions.md" in result

    def test_includes_git_entry_when_available(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=True,
            has_prs=False,
            pr_files=[],
        )

        assert "git-log.md" in result

    def test_excludes_git_entry_when_unavailable(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "git-log.md" not in result

    def test_includes_pr_entries(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=True,
            pr_files=["pr-42.md", "pr-43.md"],
        )

        assert "pr-42.md" in result
        assert "pr-43.md" in result

    def test_includes_depth_levels(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "### Light" in result
        assert "### Medium" in result
        assert "### Deep" in result

    def test_includes_interview_framework(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "Motivation & Audience" in result
        assert "Key Decisions & Trade-offs" in result
        assert "Surprises & Lessons" in result

    def test_includes_iteration_log(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "Iteration Log" in result
        assert "Setup" in result

    def test_includes_voice_first_section(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "Voice First" in result
        assert "Voice contract" in result

    def test_includes_writing_anti_patterns(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "Writing Anti-Patterns" in result
        assert "Kitchen-sink completeness" in result

    def test_includes_what_happened_when_preanalysis_provided(self, tmp_path):
        primary = _make_session_dict()
        messages = [
            _make_message("user", "Add fuzz testing"),
            _make_message("assistant", "OK"),
        ]
        preanalysis = build_session_preanalysis(
            messages, [], [], primary,
        )

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
            preanalysis=preanalysis,
        )

        assert "What Happened" in result
        assert "Add fuzz testing" in result
        assert "session-preanalysis.md" in result

    def test_includes_session_specific_questions(self, tmp_path):
        primary = _make_session_dict()
        commits = [_make_commit(f"Fix ruff lint {i}") for i in range(5)]
        preanalysis = build_session_preanalysis(
            [_make_message("user", "fix linting")], [], commits, primary,
        )

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
            preanalysis=preanalysis,
        )

        assert "yak-shave" in result

    def test_backward_compatible_without_preanalysis(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        # Should still render, just with fallback content
        assert "# Session Debrief Guide" in result
        assert "surprise" in result.lower()

    def test_no_story_acknowledgment(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "Not every session has a story" in result

    def test_format_agnostic(self, tmp_path):
        primary = _make_session_dict()

        result = generate_session_guide(
            primary_session=primary,
            related_sessions=[],
            context_dir=tmp_path / "context",
            drafts_dir=tmp_path / "drafts",
            has_git=False,
            has_prs=False,
            pr_files=[],
        )

        assert "format is up to the author" in result


class TestGatherGitContext:
    """Tests for gather_git_context."""

    def test_returns_empty_when_cwd_missing(self):
        result = gather_git_context(
            cwd=None,
            start_date="2026-02-10",
            end_date="2026-02-11",
        )
        assert result == ""

    def test_returns_empty_when_cwd_doesnt_exist(self):
        result = gather_git_context(
            cwd="/nonexistent/path/that/does/not/exist",
            start_date="2026-02-10",
            end_date="2026-02-11",
        )
        assert result == ""

    @patch("agent_audit.debrief.shutil.which")
    def test_returns_empty_when_git_unavailable(self, mock_which, tmp_path):
        mock_which.return_value = None
        result = gather_git_context(
            cwd=str(tmp_path),
            start_date="2026-02-10",
            end_date="2026-02-11",
        )
        assert result == ""

    @patch("agent_audit.debrief.subprocess.run")
    @patch("agent_audit.debrief.shutil.which")
    def test_returns_formatted_output(self, mock_which, mock_run, tmp_path):
        mock_which.return_value = "/usr/bin/git"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc1234 Fix bug\ndef5678 Add feature\n",
        )

        result = gather_git_context(
            cwd=str(tmp_path),
            start_date="2026-02-10T10:00:00Z",
            end_date="2026-02-11T10:00:00Z",
        )

        assert "# Git Log" in result
        assert "abc1234 Fix bug" in result
        assert "def5678 Add feature" in result
        assert "2 commits" in result

    @patch("agent_audit.debrief.subprocess.run")
    @patch("agent_audit.debrief.shutil.which")
    def test_handles_subprocess_timeout(self, mock_which, mock_run, tmp_path):
        import subprocess

        mock_which.return_value = "/usr/bin/git"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)

        result = gather_git_context(
            cwd=str(tmp_path),
            start_date="2026-02-10",
            end_date="2026-02-11",
        )

        assert result == ""


class TestGatherPrContext:
    """Tests for gather_pr_context."""

    def test_returns_empty_when_no_repo(self):
        result = gather_pr_context(
            repo=None,
            repo_platform="github",
            commits=[],
        )
        assert result == []

    def test_returns_empty_when_not_github(self):
        result = gather_pr_context(
            repo="owner/repo",
            repo_platform="gitlab",
            commits=[],
        )
        assert result == []

    @patch("agent_audit.debrief.shutil.which")
    def test_returns_empty_when_gh_unavailable(self, mock_which):
        mock_which.return_value = None
        result = gather_pr_context(
            repo="owner/repo",
            repo_platform="github",
            commits=[{"commit_hash": "abc1234"}],
        )
        assert result == []

    @patch("agent_audit.debrief.subprocess.run")
    @patch("agent_audit.debrief.shutil.which")
    def test_returns_pr_data(self, mock_which, mock_run):
        import json

        mock_which.return_value = "/usr/bin/gh"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "number": 42,
                    "title": "Fix the thing",
                    "url": "https://github.com/owner/repo/pull/42",
                    "state": "MERGED",
                    "body": "Fixes a bug.",
                }
            ]),
        )

        result = gather_pr_context(
            repo="owner/repo",
            repo_platform="github",
            commits=[{"commit_hash": "abc1234"}],
        )

        assert len(result) == 1
        pr_num, pr_md = result[0]
        assert pr_num == 42
        assert "Fix the thing" in pr_md
        assert "MERGED" in pr_md

    @patch("agent_audit.debrief.subprocess.run")
    @patch("agent_audit.debrief.shutil.which")
    def test_deduplicates_prs(self, mock_which, mock_run):
        import json

        mock_which.return_value = "/usr/bin/gh"
        pr_data = json.dumps([
            {"number": 42, "title": "Same PR", "url": "", "state": "MERGED", "body": ""}
        ])
        mock_run.return_value = MagicMock(returncode=0, stdout=pr_data)

        result = gather_pr_context(
            repo="owner/repo",
            repo_platform="github",
            commits=[
                {"commit_hash": "abc1234"},
                {"commit_hash": "def5678"},
            ],
        )

        # Should only have one PR despite two commits matching it
        assert len(result) == 1

    @patch("agent_audit.debrief.subprocess.run")
    @patch("agent_audit.debrief.shutil.which")
    def test_handles_subprocess_timeout(self, mock_which, mock_run):
        import subprocess

        mock_which.return_value = "/usr/bin/gh"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)

        result = gather_pr_context(
            repo="owner/repo",
            repo_platform="github",
            commits=[{"commit_hash": "abc1234"}],
        )

        assert result == []


class TestPrepareDebrief:
    """Tests for prepare_debrief end-to-end."""

    def _setup_mock_db(self, primary_session):
        """Create a mock DB with standard responses."""
        db = MagicMock()
        db.get_session_by_id_prefix.return_value = primary_session
        db.get_sessions_by_project.return_value = [primary_session]
        db.get_messages_for_session.return_value = [
            {
                "id": "msg-1",
                "session_id": primary_session["id"],
                "type": "user",
                "timestamp": "2026-02-10T10:00:00Z",
                "content": "Hello",
                "parent_uuid": None,
                "model": None,
                "input_tokens": 100,
                "output_tokens": 0,
                "thinking": None,
                "stop_reason": None,
                "is_sidechain": False,
            },
            {
                "id": "msg-2",
                "session_id": primary_session["id"],
                "type": "assistant",
                "timestamp": "2026-02-10T10:00:01Z",
                "content": "Hi there!",
                "parent_uuid": None,
                "model": "claude-sonnet-4-20250514",
                "input_tokens": 0,
                "output_tokens": 200,
                "thinking": None,
                "stop_reason": "end_turn",
                "is_sidechain": False,
            },
        ]
        db.get_tool_calls_for_session.return_value = []
        db.get_tool_results_for_session.return_value = []
        db.get_commits_for_session.return_value = []
        return db

    def test_creates_output_directory(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        assert result.exists()
        assert result.is_dir()
        assert "debriefs" in str(result)

    def test_creates_context_and_drafts_dirs(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        assert (result / "context").is_dir()
        assert (result / "drafts").is_dir()

    def test_creates_primary_session_toml(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        toml_file = result / "context" / "primary-session.toml"
        assert toml_file.exists()
        content = toml_file.read_text()
        assert "[session]" in content

    def test_creates_metrics_file(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        metrics_file = result / "context" / "metrics.md"
        assert metrics_file.exists()
        content = metrics_file.read_text()
        assert "Session Metrics" in content

    def test_creates_session_guide(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        guide_file = result / "session-guide.md"
        assert guide_file.exists()
        content = guide_file.read_text()
        assert "Session Debrief Guide" in content
        assert "test-project" in content

    def test_raises_on_no_match(self, temp_archive_dir):
        db = MagicMock()
        db.get_session_by_id_prefix.return_value = None
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        with pytest.raises(ValueError, match="No session found"):
            prepare_debrief(db, cfg, "nonexistent", archive_dir=temp_archive_dir)

    def test_directory_name_includes_date_and_slug(self, temp_archive_dir):
        primary = _make_session_dict(
            summary="Repo generalization",
            started_at="2026-02-11T10:00:00Z",
        )
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        assert "2026_02_11" in result.name
        assert "repo-generalization" in result.name

    def test_creates_related_sessions_when_present(self, temp_archive_dir):
        primary = _make_session_dict()
        related = _make_session_dict(
            session_id="related-session-id",
            started_at="2026-02-10T09:00:00Z",
        )
        db = self._setup_mock_db(primary)
        db.get_sessions_by_project.return_value = [primary, related]
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        related_file = result / "context" / "related-sessions.md"
        assert related_file.exists()
        content = related_file.read_text()
        assert "Related Sessions" in content

    def test_creates_preanalysis_file(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        preanalysis_file = result / "context" / "session-preanalysis.md"
        assert preanalysis_file.exists()
        content = preanalysis_file.read_text()
        assert "# Session Pre-Analysis" in content
        assert "Opening Context" in content

    def test_slug_uses_first_user_message_when_no_summary(self, temp_archive_dir):
        primary = _make_session_dict(
            summary=None,
            title=None,
            slug=None,
        )
        db = self._setup_mock_db(primary)
        # The mock already returns "Hello" as the first user message
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        assert "hello" in result.name.lower()

    def test_guide_includes_voice_first(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        guide_content = (result / "session-guide.md").read_text()
        assert "Voice First" in guide_content
        assert "Writing Anti-Patterns" in guide_content

    def test_metrics_include_preanalysis_sections(self, temp_archive_dir):
        primary = _make_session_dict()
        db = self._setup_mock_db(primary)
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        metrics_content = (result / "context" / "metrics.md").read_text()
        assert "Commit Categorization" in metrics_content
        assert "Autonomy" in metrics_content
        assert "Notable Patterns" in metrics_content

    def test_related_sessions_include_first_prompt(self, temp_archive_dir):
        primary = _make_session_dict()
        related = _make_session_dict(
            session_id="related-session-id",
            started_at="2026-02-10T09:00:00Z",
        )
        db = self._setup_mock_db(primary)
        db.get_sessions_by_project.return_value = [primary, related]
        cfg = MagicMock()
        cfg.archive_dir = temp_archive_dir

        result = prepare_debrief(db, cfg, "abc123", archive_dir=temp_archive_dir)

        related_content = (result / "context" / "related-sessions.md").read_text()
        assert "First prompt" in related_content


class TestCliDebrief:
    """Tests for the debrief CLI command."""

    def test_debrief_help(self, runner):
        result = runner.invoke(main, ["debrief", "--help"])
        assert result.exit_code == 0
        assert "--session" in result.output
        assert "debrief context bundle" in result.output

    def test_debrief_no_db(self, runner, temp_archive_dir):
        result = runner.invoke(
            main,
            [
                "debrief",
                "--session", "abc123",
                "--archive-dir", str(temp_archive_dir),
            ],
        )
        assert result.exit_code == 0
        assert "No archive database found" in result.output

    def test_debrief_session_not_found(self, runner, temp_archive_dir):
        """Debrief command with a session that doesn't exist in DB."""
        from agent_audit.database import Database

        # Create an empty database
        db = Database(temp_archive_dir / "sessions.db")
        with db:
            pass  # Just initialize schema

        result = runner.invoke(
            main,
            [
                "debrief",
                "--session", "nonexistent",
                "--archive-dir", str(temp_archive_dir),
            ],
        )
        assert result.exit_code == 0
        assert "No session found" in result.output

    def test_debrief_requires_session(self, runner):
        result = runner.invoke(main, ["debrief"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "--session" in result.output


class TestGetSessionByIdPrefix:
    """Tests for the Database.get_session_by_id_prefix method."""

    def test_finds_session_by_prefix(self, temp_archive_dir):
        from agent_audit.database import Database
        from agent_audit.models import Session

        db = Database(temp_archive_dir / "sessions.db")
        with db:
            session = Session(
                id="abc12345-full-session-id",
                project="test",
                started_at="2026-02-10T10:00:00Z",
            )
            db.insert_session(session)

            result = db.get_session_by_id_prefix("abc123")

            assert result is not None
            assert result["id"] == "abc12345-full-session-id"

    def test_returns_none_for_no_match(self, temp_archive_dir):
        from agent_audit.database import Database

        db = Database(temp_archive_dir / "sessions.db")
        with db:
            result = db.get_session_by_id_prefix("nonexistent")
            assert result is None

    def test_raises_on_ambiguous_prefix(self, temp_archive_dir):
        from agent_audit.database import Database
        from agent_audit.models import Session

        db = Database(temp_archive_dir / "sessions.db")
        with db:
            db.insert_session(Session(
                id="abc12345-session-1",
                project="test",
            ))
            db.insert_session(Session(
                id="abc12345-session-2",
                project="test",
            ))

            with pytest.raises(ValueError, match="Ambiguous"):
                db.get_session_by_id_prefix("abc123")
