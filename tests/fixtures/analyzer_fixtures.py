"""Fixture data for analyzer tests."""

from claude_code_archive.models import Message, Session, ToolCall


def create_minimal_sessions() -> list[Session]:
    """Create minimal test sessions with obvious patterns.

    3 sessions across 2 projects with:
    - Repeated git workflow (git-status -> git-diff -> git-add)
    - Repeated file access (config.py)
    - Similar prompt prefixes
    """
    return [
        # Session 1: project-a, git workflow
        Session(
            id="session-1",
            project="project-a",
            cwd="/Users/test/project-a",
            started_at="2025-01-01T10:00:00Z",
            ended_at="2025-01-01T11:00:00Z",
            messages=[
                Message(
                    id="msg-1-1",
                    session_id="session-1",
                    type="user",
                    timestamp="2025-01-01T10:00:00Z",
                    content="help me fix the bug in the login function",
                ),
                Message(
                    id="msg-1-2",
                    session_id="session-1",
                    type="assistant",
                    timestamp="2025-01-01T10:01:00Z",
                    content="I'll check the code and make the fix.",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id="tc-1-1",
                    message_id="msg-1-2",
                    session_id="session-1",
                    tool_name="Read",
                    input_json='{"file_path": "/Users/test/project-a/src/config.py"}',
                    timestamp="2025-01-01T10:01:01Z",
                ),
                ToolCall(
                    id="tc-1-2",
                    message_id="msg-1-2",
                    session_id="session-1",
                    tool_name="Bash",
                    input_json='{"command": "git status"}',
                    timestamp="2025-01-01T10:01:02Z",
                ),
                ToolCall(
                    id="tc-1-3",
                    message_id="msg-1-2",
                    session_id="session-1",
                    tool_name="Bash",
                    input_json='{"command": "git diff"}',
                    timestamp="2025-01-01T10:01:03Z",
                ),
                ToolCall(
                    id="tc-1-4",
                    message_id="msg-1-2",
                    session_id="session-1",
                    tool_name="Bash",
                    input_json='{"command": "git add ."}',
                    timestamp="2025-01-01T10:01:04Z",
                ),
            ],
        ),
        # Session 2: project-a, git workflow again
        Session(
            id="session-2",
            project="project-a",
            cwd="/Users/test/project-a",
            started_at="2025-01-02T10:00:00Z",
            ended_at="2025-01-02T11:00:00Z",
            messages=[
                Message(
                    id="msg-2-1",
                    session_id="session-2",
                    type="user",
                    timestamp="2025-01-02T10:00:00Z",
                    content="help me fix the bug in the user model",
                ),
                Message(
                    id="msg-2-2",
                    session_id="session-2",
                    type="assistant",
                    timestamp="2025-01-02T10:01:00Z",
                    content="I'll fix that for you.",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id="tc-2-1",
                    message_id="msg-2-2",
                    session_id="session-2",
                    tool_name="Read",
                    input_json='{"file_path": "/Users/test/project-a/src/config.py"}',
                    timestamp="2025-01-02T10:01:01Z",
                ),
                ToolCall(
                    id="tc-2-2",
                    message_id="msg-2-2",
                    session_id="session-2",
                    tool_name="Bash",
                    input_json='{"command": "git status"}',
                    timestamp="2025-01-02T10:01:02Z",
                ),
                ToolCall(
                    id="tc-2-3",
                    message_id="msg-2-2",
                    session_id="session-2",
                    tool_name="Bash",
                    input_json='{"command": "git diff HEAD~1"}',
                    timestamp="2025-01-02T10:01:03Z",
                ),
                ToolCall(
                    id="tc-2-4",
                    message_id="msg-2-2",
                    session_id="session-2",
                    tool_name="Bash",
                    input_json='{"command": "git add -A"}',
                    timestamp="2025-01-02T10:01:04Z",
                ),
            ],
        ),
        # Session 3: project-b, similar patterns
        Session(
            id="session-3",
            project="project-b",
            cwd="/Users/test/project-b",
            started_at="2025-01-03T10:00:00Z",
            ended_at="2025-01-03T11:00:00Z",
            messages=[
                Message(
                    id="msg-3-1",
                    session_id="session-3",
                    type="user",
                    timestamp="2025-01-03T10:00:00Z",
                    content="help me fix the bug in the database connection",
                ),
                Message(
                    id="msg-3-2",
                    session_id="session-3",
                    type="assistant",
                    timestamp="2025-01-03T10:01:00Z",
                    content="Looking into it now.",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id="tc-3-1",
                    message_id="msg-3-2",
                    session_id="session-3",
                    tool_name="Read",
                    input_json='{"file_path": "/Users/test/project-b/config.py"}',
                    timestamp="2025-01-03T10:01:01Z",
                ),
                ToolCall(
                    id="tc-3-2",
                    message_id="msg-3-2",
                    session_id="session-3",
                    tool_name="Bash",
                    input_json='{"command": "git status"}',
                    timestamp="2025-01-03T10:01:02Z",
                ),
                ToolCall(
                    id="tc-3-3",
                    message_id="msg-3-2",
                    session_id="session-3",
                    tool_name="Bash",
                    input_json='{"command": "git diff"}',
                    timestamp="2025-01-03T10:01:03Z",
                ),
                ToolCall(
                    id="tc-3-4",
                    message_id="msg-3-2",
                    session_id="session-3",
                    tool_name="Bash",
                    input_json='{"command": "git add src/"}',
                    timestamp="2025-01-03T10:01:04Z",
                ),
            ],
        ),
    ]


def create_realistic_sessions() -> list[Session]:
    """Create realistic test sessions with mixed patterns and noise.

    10 sessions across 4 projects with:
    - Multiple overlapping tool sequences
    - Various prompt patterns
    - File access across projects
    - Some noise/unique patterns
    """
    sessions = []

    # Sessions 1-3: project-alpha with commit workflow
    for i in range(1, 4):
        sessions.append(Session(
            id=f"real-session-{i}",
            project="project-alpha",
            cwd="/Users/dev/project-alpha",
            started_at=f"2025-01-0{i}T10:00:00Z",
            ended_at=f"2025-01-0{i}T11:00:00Z",
            messages=[
                Message(
                    id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    type="user",
                    timestamp=f"2025-01-0{i}T10:00:00Z",
                    content="please review the changes and commit them",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id=f"real-tc-{i}-1",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "git status"}',
                    timestamp=f"2025-01-0{i}T10:01:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-2",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "git diff"}',
                    timestamp=f"2025-01-0{i}T10:02:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-3",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "git add ."}',
                    timestamp=f"2025-01-0{i}T10:03:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-4",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "git commit -m \\"Update\\""}',
                    timestamp=f"2025-01-0{i}T10:04:00Z",
                ),
            ],
        ))

    # Sessions 4-6: project-beta with npm workflow
    for i in range(4, 7):
        sessions.append(Session(
            id=f"real-session-{i}",
            project="project-beta",
            cwd="/Users/dev/project-beta",
            started_at=f"2025-01-0{i}T10:00:00Z",
            ended_at=f"2025-01-0{i}T11:00:00Z",
            messages=[
                Message(
                    id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    type="user",
                    timestamp=f"2025-01-0{i}T10:00:00Z",
                    content="run the tests and check for errors",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id=f"real-tc-{i}-1",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "npm install"}',
                    timestamp=f"2025-01-0{i}T10:01:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-2",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "npm test"}',
                    timestamp=f"2025-01-0{i}T10:02:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-3",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json='{"command": "npm run lint"}',
                    timestamp=f"2025-01-0{i}T10:03:00Z",
                ),
            ],
        ))

    # Sessions 7-8: project-gamma with file access patterns
    for i in range(7, 9):
        sessions.append(Session(
            id=f"real-session-{i}",
            project="project-gamma",
            cwd="/Users/dev/project-gamma",
            started_at=f"2025-01-0{i}T10:00:00Z",
            ended_at=f"2025-01-0{i}T11:00:00Z",
            messages=[
                Message(
                    id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    type="user",
                    timestamp=f"2025-01-0{i}T10:00:00Z",
                    content="update the configuration settings",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id=f"real-tc-{i}-1",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Read",
                    input_json='{"file_path": "/Users/dev/project-gamma/settings.json"}',
                    timestamp=f"2025-01-0{i}T10:01:00Z",
                ),
                ToolCall(
                    id=f"real-tc-{i}-2",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Edit",
                    input_json='{"file_path": "/Users/dev/project-gamma/settings.json", "old_string": "a", "new_string": "b"}',
                    timestamp=f"2025-01-0{i}T10:02:00Z",
                ),
            ],
        ))

    # Sessions 9-10: project-delta with unique patterns (noise)
    for i in range(9, 11):
        sessions.append(Session(
            id=f"real-session-{i}",
            project="project-delta",
            cwd="/Users/dev/project-delta",
            started_at=f"2025-01-{i:02d}T10:00:00Z",
            ended_at=f"2025-01-{i:02d}T11:00:00Z",
            messages=[
                Message(
                    id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    type="user",
                    timestamp=f"2025-01-{i:02d}T10:00:00Z",
                    content=f"unique request number {i}",
                ),
            ],
            tool_calls=[
                ToolCall(
                    id=f"real-tc-{i}-1",
                    message_id=f"real-msg-{i}-1",
                    session_id=f"real-session-{i}",
                    tool_name="Bash",
                    input_json=f'{{"command": "echo {i}"}}',
                    timestamp=f"2025-01-{i:02d}T10:01:00Z",
                ),
            ],
        ))

    return sessions
