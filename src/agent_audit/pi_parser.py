"""Parse Pi agent JSONL session files."""

import json
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


PI_HOME = Path.home() / ".pi" / "agent" / "sessions"


def get_pi_home() -> Path:
    return PI_HOME


def discover_pi_sessions(pi_home: Path | None = None) -> Iterator[tuple[Path, str]]:
    """Discover all Pi session files.

    Pi stores sessions under ~/.pi/agent/sessions/<encoded-project-path>/*.jsonl
    where the project path is encoded as --Users-name-path-to-project--

    Yields tuples of (file_path, project_name).
    """
    home = pi_home or get_pi_home()
    if not home.exists():
        return

    for project_dir in home.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = _decode_pi_project_name(project_dir.name)

        for jsonl_file in project_dir.glob("*.jsonl"):
            yield jsonl_file, project_name


def _decode_pi_project_name(encoded: str) -> str:
    """Decode Pi's project directory name to a readable project name.

    Pi encodes paths like: --Users-rishibaldawa-workspaces-quamina-rs--
    This is a rough approximation used only as a fallback when the session
    header doesn't contain a cwd. The parse_pi_session function will
    override the project name using the real cwd from session data.
    """
    name = encoded.strip("-")
    if not name:
        return encoded

    # Add leading dash so get_project_name_from_dir's prefix matching works
    # (it expects "-Users-..." format like Claude Code directory names)
    from .parser import get_project_name_from_dir
    return get_project_name_from_dir("-" + name)


def parse_pi_session(file_path: Path, project_name: str) -> Session:
    """Parse a Pi JSONL session file into a Session object."""
    session_id = ""
    session = Session(
        id=file_path.stem,  # Temporary, will be replaced by session header id
        project=project_name,
        agent_type="pi",
    )

    messages: list[Message] = []
    all_tool_calls: list[ToolCall] = []
    all_tool_results: list[ToolResult] = []
    all_commits: list[Commit] = []
    detected_repo: str | None = None

    total_input = 0
    total_output = 0
    total_cache = 0

    for obj in _iter_jsonl(file_path):
        entry_type = obj.get("type")
        timestamp = obj.get("timestamp", "")

        # Session header
        if entry_type == "session":
            session_id = obj.get("id", file_path.stem)
            session.id = session_id
            if obj.get("cwd"):
                session.cwd = obj["cwd"]
                # Derive project name from cwd to match Claude Code conventions
                session.project = project_name_from_cwd(obj["cwd"])
            continue

        # Model change
        if entry_type == "model_change":
            model_id = obj.get("modelId")
            provider = obj.get("provider", "")
            if model_id and not session.model:
                session.model = model_id
            if provider and not session.claude_version:
                session.claude_version = f"pi-{provider}"
            continue

        # Message entries
        if entry_type == "message":
            msg_data = obj.get("message", {})
            if not msg_data:
                continue

            role = msg_data.get("role", "")
            content = msg_data.get("content", "")

            # Update timestamps
            if timestamp:
                if not session.started_at or timestamp < session.started_at:
                    session.started_at = timestamp
                if not session.ended_at or timestamp > session.ended_at:
                    session.ended_at = timestamp

            # Extract text from content (can be string or array of blocks)
            text = _extract_text(content)
            thinking = _extract_thinking(content)

            # The message ID used for FK relationships
            this_msg_id = obj.get("id", str(uuid.uuid4()))

            # Extract tool calls from assistant messages
            msg_tool_calls: list[ToolCall] = []
            if role == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        tool_input = block.get("input") or block.get("arguments", {})
                        tc = ToolCall(
                            id=block.get("id", str(uuid.uuid4())),
                            message_id=this_msg_id,
                            session_id=session.id,
                            tool_name=block.get("name", "unknown"),
                            input_json=json.dumps(tool_input) if isinstance(tool_input, dict) else json.dumps({"arguments": str(tool_input)}),
                            timestamp=timestamp,
                        )
                        msg_tool_calls.append(tc)
                        all_tool_calls.append(tc)

            # Handle toolResult role (Pi sends tool results as separate messages)
            if role == "toolResult":
                result_text = _extract_text(content)
                tool_call_id = msg_data.get("toolCallId", "")
                tr = ToolResult(
                    id=str(uuid.uuid4()),
                    tool_call_id=tool_call_id,
                    session_id=session.id,
                    content=result_text[:10000],
                    is_error=msg_data.get("isError", False),
                    timestamp=timestamp,
                )
                all_tool_results.append(tr)

                # Extract commits from tool results
                for match in COMMIT_PATTERN.finditer(result_text):
                    all_commits.append(
                        Commit(
                            id=str(uuid.uuid4()),
                            session_id=session.id,
                            commit_hash=match.group(1),
                            message=match.group(2),
                            timestamp=timestamp,
                        )
                    )
                # Detect repo
                if not detected_repo:
                    repo_match = REPO_PUSH_PATTERN.search(result_text)
                    if repo_match:
                        detected_repo = repo_match.group(1)

            # Extract usage info (Pi uses "input"/"output" keys)
            usage = msg_data.get("usage", {})
            input_tokens = usage.get("input", 0) or usage.get("input_tokens", 0)
            output_tokens = usage.get("output", 0) or usage.get("output_tokens", 0)
            cache_tokens = usage.get("cacheRead", 0) or usage.get("cache_read_input_tokens", 0)
            total_input += input_tokens
            total_output += output_tokens
            total_cache += cache_tokens

            # Determine message type
            if role == "user":
                msg_type = "user"
            elif role == "assistant":
                msg_type = "assistant"
            elif role == "toolResult":
                msg_type = "tool_result"
            else:
                msg_type = role or "unknown"

            msg = Message(
                id=this_msg_id,
                session_id=session.id,
                type=msg_type,
                timestamp=timestamp,
                content=text,
                parent_uuid=obj.get("parentId"),
                model=session.model,
                input_tokens=input_tokens if input_tokens else None,
                output_tokens=output_tokens if output_tokens else None,
                thinking=thinking,
                tool_calls=msg_tool_calls,
            )
            messages.append(msg)

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.commits = all_commits
    session.total_input_tokens = total_input
    session.total_output_tokens = total_output
    session.total_cache_read_tokens = total_cache

    if not session.repo and detected_repo:
        session.repo = detected_repo
        session.repo_platform = "github"

    session.is_warmup = _is_warmup(session)

    return session


def _extract_text(content) -> str:
    """Extract text from Pi message content (string or array of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "toolResult":
                    texts.append(f"[Tool Result: {str(block.get('content', ''))[:200]}...]")
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts)
    return str(content)


def _extract_thinking(content) -> str | None:
    """Extract thinking content from Pi message blocks."""
    if not isinstance(content, list):
        return None
    thinking_parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking", "")
            if text:
                thinking_parts.append(text)
    return "\n".join(thinking_parts) if thinking_parts else None


def _iter_jsonl(path: Path) -> Iterator[dict]:
    """Iterate over JSONL objects in a file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        yield obj
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _is_warmup(session: Session) -> bool:
    """Detect if a Pi session is a warmup session."""
    if not session.messages:
        return False
    for msg in session.messages:
        if msg.type == "user":
            content = msg.content.strip() if msg.content else ""
            if content.lower() == "warmup":
                return True
            break
    return False
