"""Parse Claude Code JSONL session files."""

import json
import uuid
from pathlib import Path
from typing import Iterator

from .models import Message, Session, ToolCall, ToolResult


def parse_jsonl_file(file_path: Path) -> Iterator[dict]:
    """Yield each JSON object from a JSONL file."""
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def extract_text_content(content) -> str:
    """Extract text content from message content (string or array)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    if isinstance(result_content, str):
                        texts.append(f"[Tool Result: {result_content[:200]}...]")
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts)
    return str(content)


def extract_tool_calls(content, message_id: str, session_id: str, timestamp: str) -> list[ToolCall]:
    """Extract tool calls from message content."""
    tool_calls = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", str(uuid.uuid4())),
                        message_id=message_id,
                        session_id=session_id,
                        tool_name=block.get("name", "unknown"),
                        input_json=json.dumps(block.get("input", {})),
                        timestamp=timestamp,
                    )
                )
    return tool_calls


def extract_tool_results(content, session_id: str, timestamp: str) -> list[ToolResult]:
    """Extract tool results from message content."""
    tool_results = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_results.append(
                    ToolResult(
                        id=str(uuid.uuid4()),
                        tool_call_id=block.get("tool_use_id", ""),
                        session_id=session_id,
                        content=str(block.get("content", ""))[:10000],  # Truncate large results
                        is_error=block.get("is_error", False),
                        timestamp=timestamp,
                    )
                )
    return tool_results


def parse_session(file_path: Path, project_name: str) -> Session:
    """Parse a JSONL session file into a Session object."""
    session_id = file_path.stem
    if session_id.startswith("agent-"):
        session_id = session_id[6:]  # Remove "agent-" prefix for ID

    session = Session(
        id=session_id,
        project=project_name,
    )

    messages = []
    all_tool_calls = []
    all_tool_results = []

    total_input = 0
    total_output = 0
    total_cache = 0

    for entry in parse_jsonl_file(file_path):
        entry_type = entry.get("type")

        # Skip non-message types
        if entry_type in ("file-history-snapshot", "queue-operation"):
            continue

        # Extract session metadata from first user message
        if not session.cwd and entry.get("cwd"):
            session.cwd = entry.get("cwd")
        if not session.git_branch and entry.get("gitBranch"):
            session.git_branch = entry.get("gitBranch")
        if not session.claude_version and entry.get("version"):
            session.claude_version = entry.get("version")

        timestamp = entry.get("timestamp", "")
        message_data = entry.get("message", {})

        if not message_data:
            continue

        # Update session timestamps
        if timestamp:
            if not session.started_at or timestamp < session.started_at:
                session.started_at = timestamp
            if not session.ended_at or timestamp > session.ended_at:
                session.ended_at = timestamp

        role = message_data.get("role", "")
        content = message_data.get("content", "")
        msg_uuid = entry.get("uuid", str(uuid.uuid4()))

        # Extract usage for assistant messages
        usage = message_data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_tokens = usage.get("cache_read_input_tokens", 0)

        total_input += input_tokens
        total_output += output_tokens
        total_cache += cache_tokens

        # Get model from assistant messages
        model = message_data.get("model")
        if model and not session.model:
            session.model = model

        # Determine message type
        if entry_type == "user":
            # Check if this is actually a tool result
            has_tool_result = False
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        has_tool_result = True
                        break

            if has_tool_result:
                msg_type = "tool_result"
                results = extract_tool_results(content, session_id, timestamp)
                all_tool_results.extend(results)
            else:
                msg_type = "user"
        elif entry_type == "assistant":
            msg_type = "assistant"
            tool_calls = extract_tool_calls(content, msg_uuid, session_id, timestamp)
            all_tool_calls.extend(tool_calls)
        else:
            msg_type = entry_type or "unknown"

        message = Message(
            id=msg_uuid,
            session_id=session_id,
            type=msg_type,
            timestamp=timestamp,
            content=extract_text_content(content),
            parent_uuid=entry.get("parentUuid"),
            model=model,
            input_tokens=input_tokens if input_tokens else None,
            output_tokens=output_tokens if output_tokens else None,
            tool_calls=extract_tool_calls(content, msg_uuid, session_id, timestamp) if msg_type == "assistant" else [],
        )
        messages.append(message)

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.total_input_tokens = total_input
    session.total_output_tokens = total_output
    session.total_cache_read_tokens = total_cache

    return session


def discover_sessions(projects_dir: Path) -> Iterator[tuple[Path, str]]:
    """Discover all session files in the projects directory.

    Yields tuples of (file_path, project_name).
    """
    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        # Convert directory name to project name
        # e.g., "-Users-rishibaldawa-Development-myproject" -> "myproject"
        project_name = project_dir.name.split("-")[-1] if "-" in project_dir.name else project_dir.name

        # Also try to get a better name from the path
        parts = project_dir.name.replace("-", "/").lstrip("/")
        if parts:
            project_name = Path(parts).name or project_name

        for jsonl_file in project_dir.glob("*.jsonl"):
            yield jsonl_file, project_name


def get_project_name_from_dir(dir_name: str) -> str:
    """Extract a readable project name from a project directory name."""
    # e.g., "-Users-rishibaldawa-Development-myproject" -> "myproject"
    # Convert dashes back to path separators and get the last component
    parts = dir_name.lstrip("-").split("-")

    # Find the last meaningful part (skip common path components)
    skip_parts = {"Users", "home", "Development", "Projects", "repos", "src"}
    for part in reversed(parts):
        if part and part not in skip_parts:
            return part

    return dir_name
