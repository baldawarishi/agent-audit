"""Parse Gemini CLI session JSON files."""

import json
import uuid
from pathlib import Path
from typing import Iterator

from .models import (
    Commit,
    COMMIT_PATTERN,
    Message,
    Session,
    ToolCall,
    ToolResult,
)
from .parser import project_name_from_cwd


GEMINI_HOME = Path.home() / ".gemini"


def get_gemini_home() -> Path:
    return GEMINI_HOME


def discover_gemini_sessions(home: Path | None = None) -> Iterator[tuple[Path, str]]:
    """Discover Gemini CLI session files.

    Gemini stores top-level sessions under
    ``~/.gemini/tmp/<project-slug>/chats/session-*.json`` and subagent
    sessions one level deeper under
    ``~/.gemini/tmp/<project-slug>/chats/session-<parent>/session-*.json``.

    Yields tuples of (file_path, project_name) where project_name is derived
    from the .project_root cwd via project_name_from_cwd, falling back to the
    directory slug if .project_root is missing.
    """
    base = (home or get_gemini_home()) / "tmp"
    if not base.exists():
        return

    for project_dir in base.iterdir():
        if not project_dir.is_dir():
            continue

        chats_dir = project_dir / "chats"
        if not chats_dir.is_dir():
            continue

        project_root_file = project_dir / ".project_root"
        if project_root_file.is_file():
            try:
                cwd = project_root_file.read_text(encoding="utf-8").strip()
            except OSError:
                cwd = ""
            project_name = project_name_from_cwd(cwd) if cwd else project_dir.name
        else:
            project_name = project_dir.name

        for session_file in sorted(chats_dir.rglob("session-*.json")):
            if session_file.is_file():
                yield session_file, project_name


def parse_gemini_session(file_path: Path, project_name: str) -> Session:
    """Parse a Gemini CLI session JSON file into a Session object."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    session_id = data.get("sessionId") or file_path.stem

    # Walk up the directory tree until we find .project_root (handles
    # both top-level chats/ and nested chats/session-<parent>/ subagents).
    cwd: str | None = None
    for ancestor in file_path.parents:
        candidate = ancestor / ".project_root"
        if candidate.is_file():
            try:
                cwd_text = candidate.read_text(encoding="utf-8").strip()
                if cwd_text:
                    cwd = cwd_text
            except OSError:
                pass
            break

    session = Session(
        id=session_id,
        project=project_name,
        agent_type="gemini-cli",
        claude_version="gemini-cli",
        started_at=data.get("startTime"),
        ended_at=data.get("lastUpdated"),
        cwd=cwd,
        summary=data.get("summary"),
    )

    # Subagent sessions are stored under chats/session-<parent>/session-*.json.
    # Mirrors the Claude Code convention in parser.py:283-289.
    if data.get("kind") == "subagent":
        session.is_sidechain = True
        parent_dir_name = file_path.parent.name
        if parent_dir_name.startswith("session-"):
            session.parent_session_id = parent_dir_name[len("session-"):]

    raw_messages = data.get("messages", []) or []
    raw_messages = _apply_rewind_and_set(raw_messages)

    sidecar_dir = _sidecar_dir_for(file_path, session_id)

    messages: list[Message] = []
    all_tool_calls: list[ToolCall] = []
    all_tool_results: list[ToolResult] = []
    total_input = 0
    total_output = 0
    model: str | None = None

    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue

        msg_type = raw.get("type")
        timestamp = raw.get("timestamp", "") or ""

        if msg_type == "user":
            content = raw.get("content")
            text = _extract_user_text(content)
            if not text:
                continue
            messages.append(
                Message(
                    id=raw.get("id") or str(uuid.uuid4()),
                    session_id=session_id,
                    type="user",
                    timestamp=timestamp,
                    content=text,
                    has_images=_user_has_media(content),
                )
            )
        elif msg_type == "gemini":
            content = raw.get("content")
            text = content if isinstance(content, str) else _extract_user_text(content)
            tokens = raw.get("tokens") or {}
            in_tok = tokens.get("input") or 0
            out_tok = tokens.get("output") or 0
            msg_model = raw.get("model")
            if msg_model and not model:
                model = msg_model
            total_input += in_tok
            total_output += out_tok

            this_msg_id = raw.get("id") or str(uuid.uuid4())

            msg_tool_calls: list[ToolCall] = []
            for tc_raw in raw.get("toolCalls") or []:
                if not isinstance(tc_raw, dict):
                    continue
                tc_id = tc_raw.get("id") or str(uuid.uuid4())
                args = tc_raw.get("args") if isinstance(tc_raw.get("args"), dict) else {}
                tc = ToolCall(
                    id=tc_id,
                    message_id=this_msg_id,
                    session_id=session_id,
                    tool_name=tc_raw.get("name", "unknown"),
                    input_json=json.dumps(args),
                    timestamp=tc_raw.get("timestamp") or timestamp,
                )
                msg_tool_calls.append(tc)
                all_tool_calls.append(tc)

                output_text = _extract_tool_output(tc_raw)
                if output_text.startswith("Output too large.") and sidecar_dir is not None:
                    sidecar_file = sidecar_dir / f"{tc_id}.txt"
                    if sidecar_file.is_file():
                        try:
                            output_text = sidecar_file.read_text(encoding="utf-8")
                        except OSError:
                            pass

                all_tool_results.append(
                    ToolResult(
                        id=str(uuid.uuid4()),
                        tool_call_id=tc_id,
                        session_id=session_id,
                        content=output_text,
                        is_error=tc_raw.get("status", "success") != "success",
                        timestamp=tc_raw.get("timestamp") or timestamp,
                    )
                )

            messages.append(
                Message(
                    id=this_msg_id,
                    session_id=session_id,
                    type="assistant",
                    timestamp=timestamp,
                    content=text or "",
                    model=msg_model,
                    input_tokens=in_tok or None,
                    output_tokens=out_tok or None,
                    thinking=_format_thoughts(raw.get("thoughts")),
                    tool_calls=msg_tool_calls,
                )
            )
        # info / error / warning → drop

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.total_input_tokens = total_input
    session.total_output_tokens = total_output
    if model:
        session.model = model

    # Extract commit hashes from assistant text
    for msg in messages:
        if msg.type != "assistant" or not msg.content:
            continue
        for match in COMMIT_PATTERN.finditer(msg.content):
            session.commits.append(
                Commit(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    commit_hash=match.group(1),
                    message=match.group(2),
                    timestamp=msg.timestamp,
                )
            )

    session.is_warmup = _is_warmup(session)

    return session


def _apply_rewind_and_set(raw_messages: list) -> list:
    """Replay $rewindTo (truncate to id, inclusive) and $set (patch fields)."""
    out: list = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        rec_type = raw.get("type")
        if rec_type == "$rewindTo":
            target_id = raw.get("id")
            for i, prior in enumerate(out):
                if isinstance(prior, dict) and prior.get("id") == target_id:
                    out = out[: i + 1]
                    break
            continue
        if rec_type == "$set":
            target_id = raw.get("id")
            patch = raw.get("patch") or {}
            if isinstance(patch, dict):
                for prior in out:
                    if isinstance(prior, dict) and prior.get("id") == target_id:
                        prior.update(patch)
                        break
            continue
        out.append(raw)
    return out


def _sidecar_dir_for(file_path: Path, session_id: str) -> Path | None:
    """Locate the tool-outputs/session-<id>/ sidecar directory if it exists."""
    for ancestor in file_path.parents:
        candidate = ancestor / "tool-outputs" / f"session-{session_id}"
        if candidate.is_dir():
            return candidate
    return None


def _extract_tool_output(tc_raw: dict) -> str:
    """Pull the output string from result[0].functionResponse.response.output."""
    result = tc_raw.get("result")
    if not isinstance(result, list) or not result:
        return ""
    first = result[0]
    if not isinstance(first, dict):
        return ""
    fr = first.get("functionResponse") or {}
    response = fr.get("response") or {}
    output = response.get("output", "")
    return output if isinstance(output, str) else str(output)


def _format_thoughts(thoughts) -> str | None:
    if not isinstance(thoughts, list):
        return None
    lines = []
    for t in thoughts:
        if not isinstance(t, dict):
            continue
        subject = (t.get("subject") or "").strip()
        description = (t.get("description") or "").strip()
        if subject and description:
            lines.append(f"{subject}: {description}")
        elif description:
            lines.append(description)
        elif subject:
            lines.append(subject)
    return "\n".join(lines) if lines else None


def _user_has_media(content) -> bool:
    if not isinstance(content, list):
        return False
    for part in content:
        if isinstance(part, dict) and ("inlineData" in part or "fileData" in part):
            return True
    return False


def _extract_user_text(content) -> str:
    """Extract text from a Gemini user message content (string or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return ""


def _is_warmup(session: Session) -> bool:
    """Detect a warmup session by a leading user message of 'warmup'."""
    if not session.messages:
        return False
    for msg in session.messages:
        if msg.type == "user":
            content = msg.content.strip() if msg.content else ""
            return content.lower() == "warmup"
    return False
