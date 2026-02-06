"""Parse Codex CLI JSONL session files (rollout files)."""

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterator

from .models import (
    Commit,
    COMMIT_PATTERN,
    REPO_PUSH_PATTERN,
    REPO_URL_PATTERN,
    detect_platform,
    Message,
    Session,
    ToolCall,
    ToolResult,
)


CODEX_HOME_ENV = "CODEX_HOME"
DEFAULT_CODEX_HOME = "~/.codex"
CODEX_SESSIONS_SUBDIR = "sessions"
CODEX_ARCHIVED_SESSIONS_SUBDIR = "archived_sessions"

# Pattern: rollout-YYYY-MM-DDThh-mm-ss-UUID.jsonl
ROLLOUT_FILENAME_RE = re.compile(
    r"^rollout-(?P<ts>.+)-(?P<uuid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$"
)


def get_codex_home() -> Path:
    """Get Codex home directory from env or default."""
    raw = os.environ.get(CODEX_HOME_ENV, DEFAULT_CODEX_HOME)
    return Path(raw).expanduser().resolve()


def discover_codex_sessions(
    codex_home: Path | None = None, include_archived: bool = True
) -> Iterator[tuple[Path, str]]:
    """Discover all Codex rollout files.

    Yields tuples of (file_path, project_name).
    Project name is derived from the session's cwd metadata.
    """
    home = codex_home or get_codex_home()

    sessions_dir = home / CODEX_SESSIONS_SUBDIR
    if sessions_dir.exists():
        yield from _iter_rollout_files_with_project(sessions_dir)

    if include_archived:
        archived_dir = home / CODEX_ARCHIVED_SESSIONS_SUBDIR
        if archived_dir.exists():
            yield from _iter_rollout_files_with_project(archived_dir)


def _iter_rollout_files_with_project(base_dir: Path) -> Iterator[tuple[Path, str]]:
    """Iterate rollout files and extract project names from metadata."""
    for rollout_file in base_dir.rglob("rollout-*.jsonl"):
        project_name = _extract_project_from_rollout(rollout_file)
        yield rollout_file, project_name


def _extract_project_from_rollout(rollout_path: Path) -> str:
    """Extract project name from rollout file's session_meta cwd."""
    try:
        with open(rollout_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "session_meta":
                        payload = obj.get("payload", {})
                        cwd = payload.get("cwd")
                        if cwd:
                            return Path(cwd).name
                except json.JSONDecodeError:
                    continue
                # Only check first few lines for metadata
                break
    except OSError:
        pass
    return "unknown-project"


def get_session_id_from_filename(path: Path) -> str | None:
    """Extract session UUID from rollout filename."""
    match = ROLLOUT_FILENAME_RE.match(path.name)
    if not match:
        return None
    return match.group("uuid")


def parse_codex_session(file_path: Path, project_name: str) -> Session:
    """Parse a Codex rollout JSONL file into a Session object."""
    session_id = get_session_id_from_filename(file_path) or file_path.stem

    session = Session(
        id=session_id,
        project=project_name,
        agent_type="codex",
    )

    messages: list[Message] = []
    all_tool_calls: list[ToolCall] = []
    all_tool_results: list[ToolResult] = []
    all_commits: list[Commit] = []
    detected_repo: str | None = None

    total_input = 0
    total_output = 0
    total_cache = 0

    # Track seen user messages to dedupe (event_msg vs response_item)
    seen_user_messages: set[str] = set()

    for obj in _iter_rollout_objects(file_path):
        timestamp = obj.get("timestamp", "")
        rollout_type = obj.get("type")
        payload = obj.get("payload", {})

        if not isinstance(payload, dict):
            continue

        # Update session timestamps
        if timestamp:
            if not session.started_at or timestamp < session.started_at:
                session.started_at = timestamp
            if not session.ended_at or timestamp > session.ended_at:
                session.ended_at = timestamp

        # Handle session_meta
        if rollout_type == "session_meta":
            _process_session_meta(session, payload)
            continue

        # Handle turn_context (contains model info)
        if rollout_type == "turn_context":
            if not session.model and payload.get("model"):
                session.model = payload.get("model")
            continue

        # Handle event_msg
        if rollout_type == "event_msg":
            event_type = payload.get("type")

            if event_type == "user_message":
                msg_text = payload.get("message", "")
                if msg_text and msg_text not in seen_user_messages:
                    seen_user_messages.add(msg_text)
                    messages.append(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            type="user",
                            timestamp=timestamp,
                            content=msg_text,
                        )
                    )
                continue

            if event_type == "agent_message":
                msg_text = payload.get("message", "")
                if msg_text:
                    messages.append(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            type="assistant",
                            timestamp=timestamp,
                            content=msg_text,
                        )
                    )
                continue

            if event_type == "agent_reasoning":
                thinking_text = payload.get("text", "")
                if thinking_text:
                    # Add as assistant message with thinking
                    messages.append(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            type="assistant",
                            timestamp=timestamp,
                            content="",
                            thinking=thinking_text,
                        )
                    )
                continue

            if event_type == "token_count":
                info = payload.get("info")
                if isinstance(info, dict):
                    usage = info.get("last_token_usage", {})
                    total_input += usage.get("input_tokens", 0)
                    total_output += usage.get("output_tokens", 0)
                    total_cache += usage.get("cached_input_tokens", 0)
                continue

            # Skip other event types for now
            continue

        # Handle response_item
        if rollout_type == "response_item":
            item_type = payload.get("type")

            # Tool calls
            if item_type in ("function_call", "custom_tool_call", "local_shell_call"):
                msg_id = str(uuid.uuid4())
                call_id = payload.get("call_id", "")
                name = payload.get("name") or item_type
                arguments = payload.get("arguments", payload.get("input", ""))

                # Parse arguments if JSON string
                if isinstance(arguments, str):
                    try:
                        input_obj = json.loads(arguments)
                    except json.JSONDecodeError:
                        input_obj = {"arguments": arguments}
                else:
                    input_obj = arguments or {}

                tool_call = ToolCall(
                    id=call_id or str(uuid.uuid4()),
                    message_id=msg_id,
                    session_id=session_id,
                    tool_name=name,
                    input_json=json.dumps(input_obj),
                    timestamp=timestamp,
                )
                all_tool_calls.append(tool_call)

                messages.append(
                    Message(
                        id=msg_id,
                        session_id=session_id,
                        type="assistant",
                        timestamp=timestamp,
                        content="",
                        tool_calls=[tool_call],
                    )
                )
                continue

            # Tool results
            if item_type in ("function_call_output", "custom_tool_call_output"):
                call_id = payload.get("call_id", "")
                output = payload.get("output", "")
                is_error = False
                if isinstance(output, dict) and output.get("success") is False:
                    is_error = True

                output_str = (
                    json.dumps(output) if isinstance(output, dict) else str(output)
                )

                tool_result = ToolResult(
                    id=str(uuid.uuid4()),
                    tool_call_id=call_id,
                    session_id=session_id,
                    content=output_str[:10000],  # Truncate
                    is_error=is_error,
                    timestamp=timestamp,
                )
                all_tool_results.append(tool_result)

                messages.append(
                    Message(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        type="tool_result",
                        timestamp=timestamp,
                        content=output_str[:500] + "..."
                        if len(output_str) > 500
                        else output_str,
                    )
                )

                # Extract commits from tool output
                if isinstance(output, str):
                    for match in COMMIT_PATTERN.finditer(output):
                        all_commits.append(
                            Commit(
                                id=str(uuid.uuid4()),
                                session_id=session_id,
                                commit_hash=match.group(1),
                                message=match.group(2),
                                timestamp=timestamp,
                            )
                        )
                    # Detect repo from push output
                    if not detected_repo:
                        repo_match = REPO_PUSH_PATTERN.search(output)
                        if repo_match:
                            detected_repo = repo_match.group(1)
                continue

            # User/assistant messages in response_item
            if item_type == "message":
                role = payload.get("role")
                text = _extract_text_from_content(payload.get("content", []))

                if role == "user" and text:
                    if text not in seen_user_messages:
                        seen_user_messages.add(text)
                        messages.append(
                            Message(
                                id=str(uuid.uuid4()),
                                session_id=session_id,
                                type="user",
                                timestamp=timestamp,
                                content=text,
                            )
                        )
                elif role == "assistant" and text:
                    messages.append(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            type="assistant",
                            timestamp=timestamp,
                            content=text,
                        )
                    )
                continue

            # Reasoning (thinking)
            if item_type == "reasoning":
                summary = payload.get("summary", [])
                thinking_text = ""
                for item in summary:
                    if isinstance(item, dict) and item.get("type") == "summary_text":
                        thinking_text += item.get("text", "") + "\n"
                if thinking_text.strip():
                    messages.append(
                        Message(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            type="assistant",
                            timestamp=timestamp,
                            content="",
                            thinking=thinking_text.strip(),
                        )
                    )
                continue

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.commits = all_commits
    session.total_input_tokens = total_input
    session.total_output_tokens = total_output
    session.total_cache_read_tokens = total_cache

    if not session.repo and detected_repo:
        session.repo = detected_repo
        session.repo_platform = "github"  # push pattern is GitHub-specific

    # Detect warmup sessions
    session.is_warmup = _is_warmup_session(session)

    return session


def _process_session_meta(session: Session, payload: dict) -> None:
    """Extract session metadata from session_meta payload."""
    if payload.get("cwd"):
        session.cwd = payload.get("cwd")

    if payload.get("cli_version"):
        session.claude_version = f"codex-{payload.get('cli_version')}"

    git_info = payload.get("git", {})
    if isinstance(git_info, dict):
        if git_info.get("branch"):
            session.git_branch = git_info.get("branch")
        repo_url = git_info.get("repository_url")
        if isinstance(repo_url, str):
            match = REPO_URL_PATTERN.search(repo_url)
            if match:
                hostname = match.group(1)
                path = match.group(2)
                platform = detect_platform(hostname)
                session.repo = path
                session.repo_platform = platform


def _extract_text_from_content(content: Any) -> str:
    """Extract text from Codex content array."""
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in ("input_text", "output_text"):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return " ".join(parts).strip()


def _iter_rollout_objects(path: Path) -> Iterator[dict]:
    """Iterate over JSONL objects in a rollout file."""
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


def _is_warmup_session(session: Session) -> bool:
    """Detect if a Codex session is a warmup session."""
    if not session.messages:
        return False

    for msg in session.messages:
        if msg.type == "user":
            content = msg.content.strip() if msg.content else ""
            if content.lower() == "warmup":
                return True
            break

    return False
