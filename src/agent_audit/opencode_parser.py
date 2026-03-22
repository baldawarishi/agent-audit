"""Parse OpenCode sessions from SQLite database."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterator

from .models import (
    Commit,
    COMMIT_PATTERN,
    REPO_PUSH_PATTERN,
    Message,
    Session,
    ToolCall,
    ToolResult,
)
from .parser import project_name_from_cwd


OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def get_opencode_db() -> Path:
    return OPENCODE_DB_PATH


def discover_opencode_sessions(db_path: Path | None = None) -> Iterator[tuple[str, str]]:
    """Discover all OpenCode sessions from its SQLite database.

    Yields tuples of (session_id, project_name).
    """
    path = db_path or get_opencode_db()
    if not path.exists():
        return

    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT id, title, directory FROM session ORDER BY time_created"
        )
        for row in cursor.fetchall():
            if row["directory"]:
                project_name = project_name_from_cwd(row["directory"])
            else:
                project_name = "unknown"
            yield row["id"], project_name
        conn.close()
    except sqlite3.Error:
        return


def parse_opencode_session(
    session_id: str, project_name: str, db_path: Path | None = None
) -> Session:
    """Parse an OpenCode session from SQLite into a Session object."""
    path = db_path or get_opencode_db()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Get session metadata
    cursor = conn.execute("SELECT * FROM session WHERE id = ?", (session_id,))
    session_row = cursor.fetchone()
    if not session_row:
        conn.close()
        raise ValueError(f"Session {session_id} not found in OpenCode database")

    session = Session(
        id=session_id,
        project=project_name,
        agent_type="opencode",
        cwd=session_row["directory"],
        title=session_row["title"],
        slug=session_row["slug"],
    )

    # Convert epoch ms to ISO timestamp
    created_ms = session_row["time_created"]
    if created_ms:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
        session.started_at = dt.isoformat()

    updated_ms = session_row["time_updated"]
    if updated_ms:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc)
        session.ended_at = dt.isoformat()

    # Get messages with their parts
    messages: list[Message] = []
    all_tool_calls: list[ToolCall] = []
    all_tool_results: list[ToolResult] = []
    all_commits: list[Commit] = []
    detected_repo: str | None = None

    total_input = 0
    total_output = 0

    msg_cursor = conn.execute(
        "SELECT id, data, time_created FROM message WHERE session_id = ? ORDER BY time_created",
        (session_id,),
    )

    for msg_row in msg_cursor.fetchall():
        msg_id = msg_row["id"]
        msg_time_ms = msg_row["time_created"]

        try:
            msg_data = json.loads(msg_row["data"])
        except (json.JSONDecodeError, TypeError):
            continue

        role = msg_data.get("role", "")
        if not role:
            continue

        # Convert timestamp
        from datetime import datetime, timezone
        timestamp = ""
        if msg_time_ms:
            dt = datetime.fromtimestamp(msg_time_ms / 1000, tz=timezone.utc)
            timestamp = dt.isoformat()

        # Extract model info (two formats: nested dict or flat keys)
        model_info = msg_data.get("model", {})
        if isinstance(model_info, dict):
            model_id = model_info.get("modelID")
            provider = model_info.get("providerID", "")
        else:
            model_id = msg_data.get("modelID")
            provider = msg_data.get("providerID", "")
        if model_id and not session.model:
            session.model = model_id
        if provider and not session.claude_version:
            session.claude_version = f"opencode-{provider}"

        # Extract usage (two formats: "usage" dict or "tokens" dict)
        usage = msg_data.get("usage") or msg_data.get("tokens") or {}
        if isinstance(usage, dict):
            input_tokens = usage.get("input", 0)
            output_tokens = usage.get("output", 0)
            total_input += input_tokens
            total_output += output_tokens
        else:
            input_tokens = 0
            output_tokens = 0

        # Get parts for this message
        part_cursor = conn.execute(
            "SELECT data FROM part WHERE message_id = ? ORDER BY time_created",
            (msg_id,),
        )

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        msg_tool_calls: list[ToolCall] = []

        for part_row in part_cursor.fetchall():
            try:
                part_data = json.loads(part_row["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            part_type = part_data.get("type", "")

            if part_type == "text":
                text = part_data.get("text", "")
                if text:
                    text_parts.append(text)

            elif part_type == "reasoning":
                text = part_data.get("text", "")
                if text:
                    thinking_parts.append(text)

            elif part_type in ("tool-invocation", "tool"):
                # "tool-invocation" is the documented format;
                # "tool" is the format seen in real OpenCode data
                if part_type == "tool":
                    tool_name = part_data.get("tool", "unknown")
                    tool_id = part_data.get("callID", str(uuid.uuid4()))
                    state = part_data.get("state", {})
                    tool_input = state.get("input", {}) if isinstance(state, dict) else {}
                    tool_output = state.get("output", "")
                    tool_status = state.get("status", "") if isinstance(state, dict) else ""
                else:
                    tool_name = part_data.get("toolName", "unknown")
                    tool_id = part_data.get("toolInvocationId", str(uuid.uuid4()))
                    tool_input = part_data.get("input", {})
                    tool_output = part_data.get("result", {})
                    tool_status = part_data.get("state", "")

                tc = ToolCall(
                    id=str(tool_id),
                    message_id=msg_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    input_json=json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
                    timestamp=timestamp,
                )
                msg_tool_calls.append(tc)
                all_tool_calls.append(tc)

                # Check for tool result
                if tool_output:
                    result_text = json.dumps(tool_output) if isinstance(tool_output, dict) else str(tool_output)
                    is_error = tool_status in ("error", "failed")

                    tr = ToolResult(
                        id=str(uuid.uuid4()),
                        tool_call_id=str(tool_id),
                        session_id=session_id,
                        content=result_text[:10000],
                        is_error=is_error,
                        timestamp=timestamp,
                    )
                    all_tool_results.append(tr)

                    # Extract commits
                    for match in COMMIT_PATTERN.finditer(result_text):
                        all_commits.append(
                            Commit(
                                id=str(uuid.uuid4()),
                                session_id=session_id,
                                commit_hash=match.group(1),
                                message=match.group(2),
                                timestamp=timestamp,
                            )
                        )
                    if not detected_repo:
                        repo_match = REPO_PUSH_PATTERN.search(result_text)
                        if repo_match:
                            detected_repo = repo_match.group(1)

        content = "\n".join(text_parts)
        thinking = "\n".join(thinking_parts) if thinking_parts else None

        msg_type = "assistant" if role == "assistant" else "user"

        msg = Message(
            id=msg_id,
            session_id=session_id,
            type=msg_type,
            timestamp=timestamp,
            content=content,
            model=session.model,
            input_tokens=input_tokens if input_tokens else None,
            output_tokens=output_tokens if output_tokens else None,
            thinking=thinking,
            tool_calls=msg_tool_calls,
        )
        messages.append(msg)

    conn.close()

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.commits = all_commits
    session.total_input_tokens = total_input
    session.total_output_tokens = total_output

    if not session.repo and detected_repo:
        session.repo = detected_repo
        session.repo_platform = "github"

    session.is_warmup = _is_warmup(session)

    return session


def _is_warmup(session: Session) -> bool:
    """Detect if an OpenCode session is a warmup session."""
    if not session.messages:
        return False
    for msg in session.messages:
        if msg.type == "user":
            content = msg.content.strip() if msg.content else ""
            if content.lower() == "warmup":
                return True
            break
    return False
