"""Tests for SQLite database operations."""

import tempfile
from pathlib import Path

import pytest

from claude_code_audit.database import Database
from claude_code_audit.models import Commit, Message, Session, ToolCall, ToolResult


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    database = Database(db_path)
    database.connect()
    yield database
    database.close()
    db_path.unlink()


@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        id="test-session-123",
        project="test-project",
        cwd="/test/path",
        git_branch="main",
        slug="dapper-questing-pascal",
        summary="A test session summary",
        started_at="2026-01-01T10:00:00Z",
        ended_at="2026-01-01T11:00:00Z",
        claude_version="2.1.9",
        total_input_tokens=100,
        total_output_tokens=50,
        total_cache_read_tokens=200,
        model="claude-opus-4-5-20251101",
        messages=[
            Message(
                id="msg-1",
                session_id="test-session-123",
                type="user",
                timestamp="2026-01-01T10:00:00Z",
                content="Hello",
            ),
            Message(
                id="msg-2",
                session_id="test-session-123",
                type="assistant",
                timestamp="2026-01-01T10:00:01Z",
                content="Hi there",
                model="claude-opus-4-5-20251101",
                input_tokens=100,
                output_tokens=50,
                thinking="Let me think about this...",
                stop_reason="end_turn",
                is_sidechain=False,
            ),
        ],
        tool_calls=[
            ToolCall(
                id="tool-1",
                message_id="msg-2",
                session_id="test-session-123",
                tool_name="Bash",
                input_json='{"command": "ls"}',
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


class TestDatabase:
    def test_session_not_exists(self, db):
        assert db.session_exists("nonexistent") is False

    def test_insert_and_check_exists(self, db, sample_session):
        db.insert_session(sample_session)
        assert db.session_exists("test-session-123") is True

    def test_get_session_ids(self, db, sample_session):
        db.insert_session(sample_session)
        ids = db.get_session_ids()
        assert "test-session-123" in ids

    def test_get_all_sessions(self, db, sample_session):
        db.insert_session(sample_session)
        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "test-session-123"
        assert sessions[0]["project"] == "test-project"

    def test_get_sessions_by_project(self, db, sample_session):
        db.insert_session(sample_session)
        sessions = db.get_sessions_by_project("test-project")
        assert len(sessions) == 1

        sessions = db.get_sessions_by_project("other-project")
        assert len(sessions) == 0

    def test_get_messages_for_session(self, db, sample_session):
        db.insert_session(sample_session)
        messages = db.get_messages_for_session("test-session-123")
        assert len(messages) == 2
        assert messages[0]["content"] == "Hello"
        assert messages[1]["content"] == "Hi there"

    def test_stores_new_session_fields(self, db, sample_session):
        db.insert_session(sample_session)
        sessions = db.get_all_sessions()
        assert sessions[0]["slug"] == "dapper-questing-pascal"
        assert sessions[0]["summary"] == "A test session summary"

    def test_stores_new_message_fields(self, db, sample_session):
        db.insert_session(sample_session)
        messages = db.get_messages_for_session("test-session-123")
        # Second message is the assistant message with new fields
        assert messages[1]["thinking"] == "Let me think about this..."
        assert messages[1]["stop_reason"] == "end_turn"
        assert messages[1]["is_sidechain"] == 0  # SQLite stores bool as 0/1

    def test_get_tool_calls_for_session(self, db, sample_session):
        db.insert_session(sample_session)
        tool_calls = db.get_tool_calls_for_session("test-session-123")
        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "Bash"

    def test_get_tool_results_for_session(self, db, sample_session):
        db.insert_session(sample_session)
        results = db.get_tool_results_for_session("test-session-123")
        assert len(results) == 1
        assert "file1.txt" in results[0]["content"]

    def test_get_stats(self, db, sample_session):
        db.insert_session(sample_session)
        stats = db.get_stats()
        assert stats["total_sessions"] == 1
        assert stats["total_messages"] == 2
        assert stats["total_tool_calls"] == 1
        assert stats["total_input_tokens"] == 100
        assert stats["total_output_tokens"] == 50
        assert "test-project" in stats["projects"]

    def test_insert_replaces_existing(self, db, sample_session):
        db.insert_session(sample_session)

        # Modify and re-insert
        sample_session.total_input_tokens = 999
        db.insert_session(sample_session)

        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["total_input_tokens"] == 999

    def test_context_manager(self, sample_session):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        with Database(db_path) as db:
            db.insert_session(sample_session)
            assert db.session_exists("test-session-123")

        db_path.unlink()

    def test_stores_parent_session_id(self, db):
        """Test that parent_session_id is stored correctly for agent sessions."""
        parent_session = Session(
            id="parent-session",
            project="test-project",
            started_at="2026-01-01T10:00:00Z",
        )
        child_session = Session(
            id="child-session",
            project="test-project",
            parent_session_id="parent-session",
            started_at="2026-01-01T10:01:00Z",
        )
        db.insert_session(parent_session)
        db.insert_session(child_session)

        sessions = db.get_all_sessions()
        child = next(s for s in sessions if s["id"] == "child-session")
        assert child["parent_session_id"] == "parent-session"

    def test_get_child_sessions(self, db):
        """Test getting all child sessions for a parent."""
        parent = Session(id="parent", project="p", started_at="2026-01-01T10:00:00Z")
        child1 = Session(id="child1", project="p", parent_session_id="parent", started_at="2026-01-01T10:01:00Z")
        child2 = Session(id="child2", project="p", parent_session_id="parent", started_at="2026-01-01T10:02:00Z")
        other = Session(id="other", project="p", started_at="2026-01-01T10:03:00Z")

        db.insert_session(parent)
        db.insert_session(child1)
        db.insert_session(child2)
        db.insert_session(other)

        children = db.get_child_sessions("parent")
        assert len(children) == 2
        assert {c["id"] for c in children} == {"child1", "child2"}

    def test_get_root_sessions(self, db):
        """Test getting sessions with no parent."""
        root1 = Session(id="root1", project="p", started_at="2026-01-01T10:00:00Z")
        root2 = Session(id="root2", project="p", started_at="2026-01-01T10:01:00Z")
        child = Session(id="child", project="p", parent_session_id="root1", started_at="2026-01-01T10:02:00Z")

        db.insert_session(root1)
        db.insert_session(root2)
        db.insert_session(child)

        roots = db.get_root_sessions()
        assert len(roots) == 2
        assert {r["id"] for r in roots} == {"root1", "root2"}

    def test_get_session_tree(self, db):
        """Test reconstructing a session tree with nested children."""
        root = Session(id="root", project="p", started_at="2026-01-01T10:00:00Z")
        child1 = Session(id="child1", project="p", parent_session_id="root", started_at="2026-01-01T10:01:00Z")
        grandchild = Session(id="grandchild", project="p", parent_session_id="child1", started_at="2026-01-01T10:02:00Z")

        db.insert_session(root)
        db.insert_session(child1)
        db.insert_session(grandchild)

        tree = db.get_session_tree("root")
        assert tree["session"]["id"] == "root"
        assert len(tree["children"]) == 1
        assert tree["children"][0]["session"]["id"] == "child1"
        assert len(tree["children"][0]["children"]) == 1
        assert tree["children"][0]["children"][0]["session"]["id"] == "grandchild"

    def test_get_project_metrics(self, db):
        """Test getting aggregate metrics for a project."""
        # Create 2 sessions with multiple messages
        session1 = Session(
            id="s1",
            project="my-project",
            started_at="2026-01-01T10:00:00Z",
            ended_at="2026-01-01T11:00:00Z",
            total_input_tokens=100,
            total_output_tokens=200,
            messages=[
                Message(id="m1", session_id="s1", type="user", timestamp="2026-01-01T10:00:00Z", content="Hello"),
                Message(id="m2", session_id="s1", type="assistant", timestamp="2026-01-01T10:00:01Z", content="Hi"),
                Message(id="m3", session_id="s1", type="user", timestamp="2026-01-01T10:00:02Z", content="Help"),
                Message(id="m4", session_id="s1", type="assistant", timestamp="2026-01-01T10:00:03Z", content="Sure"),
            ],
            tool_calls=[
                ToolCall(id="tc1", message_id="m2", session_id="s1", tool_name="Read", input_json="{}", timestamp="2026-01-01T10:00:01Z"),
                ToolCall(id="tc2", message_id="m4", session_id="s1", tool_name="Edit", input_json="{}", timestamp="2026-01-01T10:00:03Z"),
            ],
        )
        session2 = Session(
            id="s2",
            project="my-project",
            started_at="2026-01-02T10:00:00Z",
            ended_at="2026-01-02T11:00:00Z",
            total_input_tokens=150,
            total_output_tokens=250,
            messages=[
                Message(id="m5", session_id="s2", type="user", timestamp="2026-01-02T10:00:00Z", content="Test"),
                Message(id="m6", session_id="s2", type="assistant", timestamp="2026-01-02T10:00:01Z", content="Ok"),
            ],
            tool_calls=[
                ToolCall(id="tc3", message_id="m6", session_id="s2", tool_name="Bash", input_json="{}", timestamp="2026-01-02T10:00:01Z"),
            ],
        )
        # Another project - should not be counted
        other_session = Session(
            id="s3",
            project="other-project",
            started_at="2026-01-03T10:00:00Z",
            total_input_tokens=999,
            total_output_tokens=999,
        )

        db.insert_session(session1)
        db.insert_session(session2)
        db.insert_session(other_session)

        metrics = db.get_project_metrics("my-project")

        assert metrics["session_count"] == 2
        assert metrics["turn_count"] == 3  # 2 turns in s1 + 1 turn in s2 (user+assistant pairs)
        assert metrics["total_input_tokens"] == 250  # 100 + 150
        assert metrics["total_output_tokens"] == 450  # 200 + 250
        assert metrics["tool_call_count"] == 3  # 2 + 1

    def test_get_project_metrics_empty(self, db):
        """Test getting metrics for non-existent project."""
        metrics = db.get_project_metrics("nonexistent")
        assert metrics["session_count"] == 0
        assert metrics["turn_count"] == 0
        assert metrics["total_input_tokens"] == 0
        assert metrics["total_output_tokens"] == 0
        assert metrics["tool_call_count"] == 0

    def test_get_global_percentiles(self, db):
        """Test getting global percentile statistics across all projects."""
        # Create sessions with varying message counts and tokens
        sessions = [
            # Small session: 2 messages
            Session(
                id="s1", project="p1", started_at="2026-01-01T10:00:00Z",
                total_output_tokens=100,
                messages=[
                    Message(id="m1", session_id="s1", type="user", timestamp="2026-01-01T10:00:00Z", content="Hi"),
                    Message(id="m2", session_id="s1", type="assistant", timestamp="2026-01-01T10:00:01Z", content="Hello"),
                ],
            ),
            # Medium session: 4 messages
            Session(
                id="s2", project="p1", started_at="2026-01-01T11:00:00Z",
                total_output_tokens=500,
                messages=[
                    Message(id="m3", session_id="s2", type="user", timestamp="2026-01-01T11:00:00Z", content="Help"),
                    Message(id="m4", session_id="s2", type="assistant", timestamp="2026-01-01T11:00:01Z", content="Sure"),
                    Message(id="m5", session_id="s2", type="user", timestamp="2026-01-01T11:00:02Z", content="More"),
                    Message(id="m6", session_id="s2", type="assistant", timestamp="2026-01-01T11:00:03Z", content="Ok"),
                ],
            ),
            # Large session: 6 messages
            Session(
                id="s3", project="p2", started_at="2026-01-01T12:00:00Z",
                total_output_tokens=1000,
                messages=[
                    Message(id="m7", session_id="s3", type="user", timestamp="2026-01-01T12:00:00Z", content="A"),
                    Message(id="m8", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:01Z", content="B"),
                    Message(id="m9", session_id="s3", type="user", timestamp="2026-01-01T12:00:02Z", content="C"),
                    Message(id="m10", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:03Z", content="D"),
                    Message(id="m11", session_id="s3", type="user", timestamp="2026-01-01T12:00:04Z", content="E"),
                    Message(id="m12", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:05Z", content="F"),
                ],
            ),
            # Very large session: 10 messages
            Session(
                id="s4", project="p2", started_at="2026-01-01T13:00:00Z",
                total_output_tokens=2000,
                messages=[
                    Message(id=f"m{i}", session_id="s4", type="user" if i % 2 == 0 else "assistant",
                            timestamp=f"2026-01-01T13:00:{i:02d}Z", content=f"Msg{i}")
                    for i in range(13, 23)
                ],
            ),
        ]

        for session in sessions:
            db.insert_session(session)

        percentiles = db.get_global_percentiles()

        # Should have p50, p75, p90 for messages and tokens
        assert "p50_msgs" in percentiles
        assert "p75_msgs" in percentiles
        assert "p90_msgs" in percentiles
        assert "p50_tokens" in percentiles
        assert "p75_tokens" in percentiles
        assert "p90_tokens" in percentiles

        # With 4 sessions: [2, 4, 6, 10] messages
        # Percentiles should increase monotonically
        assert percentiles["p50_msgs"] >= 2  # At least min
        assert percentiles["p75_msgs"] >= percentiles["p50_msgs"]  # Monotonic
        assert percentiles["p90_msgs"] >= percentiles["p75_msgs"]  # Monotonic
        assert percentiles["p90_msgs"] <= 10  # At most max

    def test_get_global_percentiles_empty(self, db):
        """Test getting global percentiles with no sessions."""
        percentiles = db.get_global_percentiles()

        # Should return zeros or defaults for empty database
        assert percentiles["p50_msgs"] == 0
        assert percentiles["p75_msgs"] == 0
        assert percentiles["p90_msgs"] == 0
        assert percentiles["p50_tokens"] == 0
        assert percentiles["p75_tokens"] == 0
        assert percentiles["p90_tokens"] == 0

    def test_get_project_session_stats(self, db):
        """Test getting session statistics for a specific project."""
        # Create sessions for one project
        sessions = [
            Session(
                id="s1", project="my-project", started_at="2026-01-01T10:00:00Z",
                total_output_tokens=100,
                messages=[
                    Message(id="m1", session_id="s1", type="user", timestamp="2026-01-01T10:00:00Z", content="Hi"),
                    Message(id="m2", session_id="s1", type="assistant", timestamp="2026-01-01T10:00:01Z", content="Hello"),
                ],
            ),
            Session(
                id="s2", project="my-project", started_at="2026-01-01T11:00:00Z",
                total_output_tokens=500,
                messages=[
                    Message(id="m3", session_id="s2", type="user", timestamp="2026-01-01T11:00:00Z", content="Help"),
                    Message(id="m4", session_id="s2", type="assistant", timestamp="2026-01-01T11:00:01Z", content="Sure"),
                    Message(id="m5", session_id="s2", type="user", timestamp="2026-01-01T11:00:02Z", content="More"),
                    Message(id="m6", session_id="s2", type="assistant", timestamp="2026-01-01T11:00:03Z", content="Ok"),
                ],
            ),
            Session(
                id="s3", project="my-project", started_at="2026-01-01T12:00:00Z",
                total_output_tokens=1000,
                messages=[
                    Message(id="m7", session_id="s3", type="user", timestamp="2026-01-01T12:00:00Z", content="A"),
                    Message(id="m8", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:01Z", content="B"),
                    Message(id="m9", session_id="s3", type="user", timestamp="2026-01-01T12:00:02Z", content="C"),
                    Message(id="m10", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:03Z", content="D"),
                    Message(id="m11", session_id="s3", type="user", timestamp="2026-01-01T12:00:04Z", content="E"),
                    Message(id="m12", session_id="s3", type="assistant", timestamp="2026-01-01T12:00:05Z", content="F"),
                ],
            ),
            # Different project - should not be included
            Session(
                id="s4", project="other-project", started_at="2026-01-01T13:00:00Z",
                total_output_tokens=9999,
                messages=[
                    Message(id=f"m{i}", session_id="s4", type="user" if i % 2 == 0 else "assistant",
                            timestamp=f"2026-01-01T13:00:{i:02d}Z", content=f"Msg{i}")
                    for i in range(13, 33)  # 20 messages
                ],
            ),
        ]

        for session in sessions:
            db.insert_session(session)

        stats = db.get_project_session_stats("my-project")

        # Should have avg, min, max for messages and tokens
        assert stats["avg_msgs"] == 4  # (2 + 4 + 6) / 3 = 4
        assert stats["min_msgs"] == 2
        assert stats["max_msgs"] == 6
        assert stats["avg_tokens"] == 533  # (100 + 500 + 1000) / 3 ≈ 533
        assert stats["min_tokens"] == 100
        assert stats["max_tokens"] == 1000

    def test_get_project_session_stats_empty(self, db):
        """Test getting project stats for non-existent project."""
        stats = db.get_project_session_stats("nonexistent")

        assert stats["avg_msgs"] == 0
        assert stats["min_msgs"] == 0
        assert stats["max_msgs"] == 0
        assert stats["avg_tokens"] == 0
        assert stats["min_tokens"] == 0
        assert stats["max_tokens"] == 0

    def test_stores_github_repo(self, db):
        """Test storing and retrieving github_repo field."""
        session = Session(
            id="github-session",
            project="test",
            github_repo="owner/repo-name",
        )
        db.insert_session(session)

        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["github_repo"] == "owner/repo-name"

    def test_stores_title(self, db):
        """Test storing and retrieving title field."""
        session = Session(
            id="titled-session",
            project="test",
            title="My Session Title",
        )
        db.insert_session(session)

        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["title"] == "My Session Title"

    def test_stores_session_context(self, db):
        """Test storing and retrieving session_context field."""
        session = Session(
            id="context-session",
            project="test",
            session_context='{"outcomes": [], "sources": []}',
        )
        db.insert_session(session)

        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_context"] == '{"outcomes": [], "sources": []}'

    def test_stores_is_compact_summary(self, db):
        """Test storing and retrieving is_compact_summary field."""
        session = Session(
            id="compact-session",
            project="test",
            messages=[
                Message(
                    id="msg-1",
                    session_id="compact-session",
                    type="user",
                    timestamp="2026-01-01T10:00:00Z",
                    content="Continuation...",
                    is_compact_summary=True,
                ),
            ],
        )
        db.insert_session(session)

        messages = db.get_messages_for_session("compact-session")
        assert len(messages) == 1
        assert messages[0]["is_compact_summary"] == 1  # SQLite stores as 1

    def test_stores_has_images(self, db):
        """Test storing and retrieving has_images field."""
        session = Session(
            id="images-session",
            project="test",
            messages=[
                Message(
                    id="msg-1",
                    session_id="images-session",
                    type="user",
                    timestamp="2026-01-01T10:00:00Z",
                    content="Image message",
                    has_images=True,
                ),
            ],
        )
        db.insert_session(session)

        messages = db.get_messages_for_session("images-session")
        assert len(messages) == 1
        assert messages[0]["has_images"] == 1  # SQLite stores as 1

    def test_stores_and_retrieves_commits(self, db):
        """Test storing and retrieving commits."""
        session = Session(
            id="commit-session",
            project="test",
            commits=[
                Commit(
                    id="commit-1",
                    session_id="commit-session",
                    commit_hash="abc1234",
                    message="Fix the bug",
                    timestamp="2026-01-01T10:00:00Z",
                ),
                Commit(
                    id="commit-2",
                    session_id="commit-session",
                    commit_hash="def5678",
                    message="Add feature",
                    timestamp="2026-01-01T10:05:00Z",
                ),
            ],
        )
        db.insert_session(session)

        commits = db.get_commits_for_session("commit-session")
        assert len(commits) == 2
        assert commits[0]["commit_hash"] == "abc1234"
        assert commits[0]["message"] == "Fix the bug"
        assert commits[1]["commit_hash"] == "def5678"
        assert commits[1]["message"] == "Add feature"

    def test_get_sessions_by_github_repo(self, db):
        """Test getting sessions by github_repo."""
        session1 = Session(id="s1", project="p1", github_repo="owner/repo")
        session2 = Session(id="s2", project="p2", github_repo="owner/repo")
        session3 = Session(id="s3", project="p3", github_repo="other/repo")

        db.insert_session(session1)
        db.insert_session(session2)
        db.insert_session(session3)

        sessions = db.get_sessions_by_github_repo("owner/repo")
        assert len(sessions) == 2
        ids = {s["id"] for s in sessions}
        assert ids == {"s1", "s2"}

    def test_stats_includes_commits(self, db):
        """Test that stats include commit count."""
        session = Session(
            id="stats-session",
            project="test",
            commits=[
                Commit(id="c1", session_id="stats-session", commit_hash="abc", message="msg", timestamp=""),
                Commit(id="c2", session_id="stats-session", commit_hash="def", message="msg", timestamp=""),
            ],
        )
        db.insert_session(session)

        stats = db.get_stats()
        assert stats["total_commits"] == 2

    def test_stats_includes_github_repos(self, db):
        """Test that stats include github_repos list."""
        session1 = Session(id="s1", project="p1", github_repo="owner/repo1")
        session2 = Session(id="s2", project="p2", github_repo="owner/repo2")
        session3 = Session(id="s3", project="p3")  # No repo

        db.insert_session(session1)
        db.insert_session(session2)
        db.insert_session(session3)

        stats = db.get_stats()
        assert "github_repos" in stats
        assert set(stats["github_repos"]) == {"owner/repo1", "owner/repo2"}
