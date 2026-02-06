"""Tests for JSONL parser."""

import json
import tempfile
from pathlib import Path


from agent_audit.parser import (
    extract_text_content,
    extract_thinking_content,
    extract_tool_calls,
    extract_tool_results,
    extract_commits,
    detect_repo_from_content,
    detect_github_repo_from_content,
    extract_repo_from_session_context,
    has_image_content,
    parse_jsonl_file,
    parse_session,
    get_project_name_from_dir,
    is_tmp_directory,
    is_warmup_session,
    is_sidechain_session,
)
from agent_audit.models import Session, Message


class TestExtractTextContent:
    def test_string_content(self):
        assert extract_text_content("hello world") == "hello world"

    def test_text_block(self):
        content = [{"type": "text", "text": "hello"}]
        assert extract_text_content(content) == "hello"

    def test_multiple_text_blocks(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
        assert extract_text_content(content) == "hello\nworld"

    def test_filters_thinking_blocks(self):
        content = [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "hello"},
        ]
        assert extract_text_content(content) == "hello"

    def test_empty_content(self):
        assert extract_text_content([]) == ""
        assert extract_text_content("") == ""


class TestExtractThinkingContent:
    def test_extracts_thinking_block(self):
        content = [
            {"type": "thinking", "thinking": "Let me think about this..."},
            {"type": "text", "text": "hello"},
        ]
        assert extract_thinking_content(content) == "Let me think about this..."

    def test_multiple_thinking_blocks(self):
        content = [
            {"type": "thinking", "thinking": "First thought"},
            {"type": "text", "text": "response"},
            {"type": "thinking", "thinking": "Second thought"},
        ]
        assert extract_thinking_content(content) == "First thought\nSecond thought"

    def test_no_thinking_returns_none(self):
        content = [{"type": "text", "text": "hello"}]
        assert extract_thinking_content(content) is None

    def test_string_content_returns_none(self):
        assert extract_thinking_content("hello") is None

    def test_empty_content_returns_none(self):
        assert extract_thinking_content([]) is None


class TestExtractToolCalls:
    def test_extracts_tool_use(self):
        content = [
            {
                "type": "tool_use",
                "id": "toolu_123",
                "name": "Bash",
                "input": {"command": "ls"},
            }
        ]
        calls = extract_tool_calls(
            content, "msg_1", "session_1", "2026-01-01T00:00:00Z"
        )
        assert len(calls) == 1
        assert calls[0].tool_name == "Bash"
        assert calls[0].id == "toolu_123"
        assert json.loads(calls[0].input_json) == {"command": "ls"}

    def test_no_tool_calls(self):
        content = [{"type": "text", "text": "hello"}]
        calls = extract_tool_calls(
            content, "msg_1", "session_1", "2026-01-01T00:00:00Z"
        )
        assert len(calls) == 0


class TestExtractToolResults:
    def test_extracts_tool_result(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_123",
                "content": "output here",
            }
        ]
        results = extract_tool_results(content, "session_1", "2026-01-01T00:00:00Z")
        assert len(results) == 1
        assert results[0].tool_call_id == "toolu_123"
        assert results[0].content == "output here"

    def test_error_result(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_123",
                "content": "error",
                "is_error": True,
            }
        ]
        results = extract_tool_results(content, "session_1", "2026-01-01T00:00:00Z")
        assert results[0].is_error is True


class TestParseJsonlFile:
    def test_parses_valid_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type": "user", "message": {"content": "hello"}}\n')
            f.write('{"type": "assistant", "message": {"content": "hi"}}\n')
            f.flush()

            entries = list(parse_jsonl_file(Path(f.name)))
            assert len(entries) == 2
            assert entries[0]["type"] == "user"
            assert entries[1]["type"] == "assistant"

    def test_skips_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"valid": true}\n')
            f.write("invalid json line\n")
            f.write('{"also": "valid"}\n')
            f.flush()

            entries = list(parse_jsonl_file(Path(f.name)))
            assert len(entries) == 2


class TestParseSession:
    def test_parses_session(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "test-session",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "cwd": "/test",
                        "version": "2.1.9",
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "test-session",
                        "uuid": "msg-2",
                        "parentUuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:01Z",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "hi there"}],
                            "model": "claude-opus-4-5-20251101",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.project == "test-project"
            assert session.cwd == "/test"
            assert session.claude_version == "2.1.9"
            assert len(session.messages) == 2
            assert session.total_input_tokens == 10
            assert session.total_output_tokens == 5

    def test_parses_thinking_blocks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "msg-2",
                        "timestamp": "2026-01-01T10:00:01Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "Let me think..."},
                                {"type": "text", "text": "Here is my response"},
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.messages[1].thinking == "Let me think..."
            assert session.messages[1].content == "Here is my response"

    def test_parses_slug(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "slug": "dapper-questing-pascal",
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.slug == "dapper-questing-pascal"

    def test_parses_summary(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "summary",
                        "summary": "User asked a question and got a response",
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.summary == "User asked a question and got a response"

    def test_parses_stop_reason(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": "response",
                            "stop_reason": "end_turn",
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.messages[0].stop_reason == "end_turn"

    def test_parses_is_sidechain(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "isSidechain": True,
                        "message": {"role": "assistant", "content": "response"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.messages[0].is_sidechain is True

    def test_parses_parent_session_id_for_agent(self):
        """Agent sessions have sessionId pointing to parent, different from their own ID."""
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="agent-abc123", suffix=".jsonl", delete=False
        ) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "agentId": "abc123",  # Agent's own ID
                        "sessionId": "parent-session-uuid",  # Parent session
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.parent_session_id == "parent-session-uuid"

    def test_no_parent_for_regular_session(self):
        """Regular sessions have sessionId == own ID, so no parent should be set."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # Filename determines session ID
            session_id = Path(f.name).stem
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "sessionId": session_id,  # Same as own ID
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.parent_session_id is None


class TestGetProjectNameFromDir:
    def test_extracts_last_component(self):
        assert (
            get_project_name_from_dir("-Users-john-Development-myproject")
            == "myproject"
        )

    def test_skips_common_paths(self):
        # New algorithm keeps multi-part project names together
        assert get_project_name_from_dir("-Users-john-Projects-cool-app") == "cool-app"

    def test_handles_simple_name(self):
        assert get_project_name_from_dir("myproject") == "myproject"

    def test_strips_home_prefix(self):
        assert get_project_name_from_dir("-home-user-projects-myapp") == "myapp"

    def test_strips_mnt_prefix(self):
        assert get_project_name_from_dir("-mnt-c-Users-name-code-webapp") == "webapp"

    def test_skips_intermediate_dirs(self):
        # Should skip: repos, src, dev, work, documents, github, git
        assert get_project_name_from_dir("-Users-john-github-my-repo") == "my-repo"
        assert get_project_name_from_dir("-Users-john-src-backend") == "backend"


class TestIsWarmupSession:
    def test_detects_warmup_message(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Warmup",
                ),
                Message(
                    id="2",
                    session_id="test",
                    type="assistant",
                    timestamp="",
                    content="Starting exploration...",
                ),
            ],
        )
        assert is_warmup_session(session) is True

    def test_detects_warmup_case_insensitive(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="warmup",
                ),
            ],
        )
        assert is_warmup_session(session) is True

    def test_detects_warmup_with_whitespace(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="  Warmup  ",
                ),
            ],
        )
        assert is_warmup_session(session) is True

    def test_rejects_non_warmup(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Hello, help me with code",
                ),
            ],
        )
        assert is_warmup_session(session) is False

    def test_rejects_warmup_in_longer_message(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Do a warmup exercise",
                ),
            ],
        )
        assert is_warmup_session(session) is False

    def test_handles_empty_session(self):
        session = Session(id="test", project="test", messages=[])
        assert is_warmup_session(session) is False


class TestIsSidechainSession:
    def test_detects_sidechain_messages(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Warmup",
                    is_sidechain=True,
                ),
            ],
        )
        assert is_sidechain_session(session) is True

    def test_rejects_non_sidechain(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Hello",
                    is_sidechain=False,
                ),
            ],
        )
        assert is_sidechain_session(session) is False

    def test_handles_mixed_messages(self):
        session = Session(
            id="test",
            project="test",
            messages=[
                Message(
                    id="1",
                    session_id="test",
                    type="user",
                    timestamp="",
                    content="Hello",
                    is_sidechain=False,
                ),
                Message(
                    id="2",
                    session_id="test",
                    type="assistant",
                    timestamp="",
                    content="Hi",
                    is_sidechain=True,
                ),
            ],
        )
        assert is_sidechain_session(session) is True

    def test_handles_empty_session(self):
        session = Session(id="test", project="test", messages=[])
        assert is_sidechain_session(session) is False


class TestParseSessionWarmupDetection:
    def test_sets_is_warmup_flag(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {"role": "user", "content": "Warmup"},
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "msg-2",
                        "timestamp": "2026-01-01T10:00:01Z",
                        "message": {
                            "role": "assistant",
                            "content": "Starting exploration...",
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.is_warmup is True

    def test_sets_is_sidechain_flag(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "isSidechain": True,
                        "message": {"role": "user", "content": "Warmup"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.is_sidechain is True

    def test_regular_session_no_flags(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {"role": "user", "content": "Help me with code"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.is_warmup is False
            assert session.is_sidechain is False


class TestIsTmpDirectory:
    def test_detects_tmp_prefix(self):
        assert is_tmp_directory("-tmp-pytest-123") is True

    def test_detects_var_folders(self):
        assert is_tmp_directory("-var-folders-9g-abc123") is True

    def test_detects_private_var_folders(self):
        # macOS full path
        assert is_tmp_directory("-private-var-folders-9g-1c2c-pytest-test") is True

    def test_detects_private_tmp(self):
        assert is_tmp_directory("-private-tmp-test-session") is True

    def test_detects_pytest_anywhere(self):
        assert is_tmp_directory("-Users-john-pytest-cache-test") is True
        assert is_tmp_directory("-home-user-code-pytest-4-tmpdir") is True

    def test_allows_normal_projects(self):
        assert is_tmp_directory("-Users-john-Development-myproject") is False
        assert is_tmp_directory("-home-user-projects-app") is False
        assert is_tmp_directory("myproject") is False

    def test_case_insensitive(self):
        assert is_tmp_directory("-TMP-test") is True
        assert is_tmp_directory("-Private-Var-Folders-abc") is True


class TestExtractCommits:
    def test_extracts_commit_from_tool_result(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "[main abc1234] Fix the bug\n1 file changed",
            }
        ]
        commits = extract_commits(content, "session-1", "2026-01-01T10:00:00Z")
        assert len(commits) == 1
        assert commits[0].commit_hash == "abc1234"
        assert commits[0].message == "Fix the bug"
        assert commits[0].session_id == "session-1"

    def test_extracts_multiple_commits(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "[main abc1234] First commit\n[main def5678] Second commit\n",
            }
        ]
        commits = extract_commits(content, "session-1", "2026-01-01T10:00:00Z")
        assert len(commits) == 2
        assert commits[0].commit_hash == "abc1234"
        assert commits[1].commit_hash == "def5678"

    def test_handles_branch_with_slash(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "[feature/my-branch 1234567] Added feature\n",
            }
        ]
        commits = extract_commits(content, "session-1", "2026-01-01T10:00:00Z")
        assert len(commits) == 1
        assert commits[0].commit_hash == "1234567"
        assert commits[0].message == "Added feature"

    def test_no_commits_returns_empty(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "No commits here",
            }
        ]
        commits = extract_commits(content, "session-1", "2026-01-01T10:00:00Z")
        assert len(commits) == 0


class TestDetectRepoFromContent:
    def test_detects_repo_from_git_push(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "remote: Create a pull request for 'feature' on GitHub by visiting:\nremote:      https://github.com/owner/repo/pull/new/feature\n",
            }
        ]
        repo = detect_repo_from_content(content)
        assert repo == "owner/repo"

    def test_returns_none_when_no_match(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "Just some regular output",
            }
        ]
        repo = detect_repo_from_content(content)
        assert repo is None

    def test_handles_non_list_content(self):
        repo = detect_repo_from_content("string content")
        assert repo is None

    def test_deprecated_alias_works(self):
        """detect_github_repo_from_content still works as an alias."""
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "https://github.com/owner/repo/pull/new/feature",
            }
        ]
        repo = detect_github_repo_from_content(content)
        assert repo == "owner/repo"


class TestExtractRepoFromSessionContext:
    def test_extracts_from_git_info(self):
        session_context = {
            "outcomes": [
                {"type": "git_repository", "git_info": {"repo": "owner/repo-name"}}
            ]
        }
        repo, platform = extract_repo_from_session_context(session_context)
        assert repo == "owner/repo-name"
        assert platform is None  # outcomes don't include hostname

    def test_extracts_from_sources_url(self):
        session_context = {
            "sources": [
                {
                    "type": "git_repository",
                    "url": "https://github.com/owner/my-project.git",
                }
            ]
        }
        repo, platform = extract_repo_from_session_context(session_context)
        assert repo == "owner/my-project"
        assert platform == "github"

    def test_extracts_gitlab_from_sources_url(self):
        session_context = {
            "sources": [
                {
                    "type": "git_repository",
                    "url": "https://gitlab.com/group/subgroup/project.git",
                }
            ]
        }
        repo, platform = extract_repo_from_session_context(session_context)
        assert repo == "group/subgroup/project"
        assert platform == "gitlab"

    def test_extracts_bitbucket_from_sources_url(self):
        session_context = {
            "sources": [
                {
                    "type": "git_repository",
                    "url": "https://bitbucket.org/team/repo.git",
                }
            ]
        }
        repo, platform = extract_repo_from_session_context(session_context)
        assert repo == "team/repo"
        assert platform == "bitbucket"

    def test_prefers_outcomes_over_sources(self):
        session_context = {
            "outcomes": [
                {"type": "git_repository", "git_info": {"repo": "outcomes/repo"}}
            ],
            "sources": [
                {"type": "git_repository", "url": "https://github.com/sources/repo.git"}
            ],
        }
        repo, platform = extract_repo_from_session_context(session_context)
        assert repo == "outcomes/repo"

    def test_returns_none_for_empty_context(self):
        assert extract_repo_from_session_context(None) == (None, None)
        assert extract_repo_from_session_context({}) == (None, None)


class TestHasImageContent:
    def test_detects_image_block(self):
        content = [
            {
                "type": "image",
                "source": {"media_type": "image/png", "data": "base64..."},
            }
        ]
        assert has_image_content(content) is True

    def test_detects_image_in_tool_result(self):
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": [
                    {
                        "type": "image",
                        "source": {"media_type": "image/png", "data": "base64..."},
                    }
                ],
            }
        ]
        assert has_image_content(content) is True

    def test_returns_false_for_no_images(self):
        content = [{"type": "text", "text": "Hello world"}]
        assert has_image_content(content) is False

    def test_handles_non_list_content(self):
        assert has_image_content("string content") is False


class TestParseSessionNewFields:
    def test_parses_is_compact_summary(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "isCompactSummary": True,
                        "message": {"role": "user", "content": "Continuation..."},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert len(session.messages) == 1
            assert session.messages[0].is_compact_summary is True

    def test_parses_repo_from_context(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "session_context": {
                            "outcomes": [
                                {
                                    "type": "git_repository",
                                    "git_info": {"repo": "owner/my-repo"},
                                }
                            ]
                        },
                        "message": {"role": "user", "content": "Hello"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.repo == "owner/my-repo"
            # Deprecated alias still works
            assert session.github_repo == "owner/my-repo"

    def test_parses_repo_from_git_push(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool-1",
                                    "content": "https://github.com/owner/repo/pull/new/feature",
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.repo == "owner/repo"
            assert session.repo_platform == "github"

    def test_parses_commits_from_tool_results(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool-1",
                                    "content": "[main abc1234] Fix bug\n",
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert len(session.commits) == 1
            assert session.commits[0].commit_hash == "abc1234"
            assert session.commits[0].message == "Fix bug"

    def test_parses_title(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "title": "My Session Title",
                        "message": {"role": "user", "content": "Hello"},
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert session.title == "My Session Title"

    def test_parses_has_images(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "media_type": "image/png",
                                        "data": "abc123",
                                    },
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.flush()

            session = parse_session(Path(f.name), "test-project")
            assert len(session.messages) == 1
            assert session.messages[0].has_images is True
