"""Render sessions as TOML transcripts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Session, ToolCall


def format_timestamp(iso_timestamp: Optional[str]) -> str:
    """Format an ISO timestamp for TOML."""
    if not iso_timestamp:
        return ""
    # TOML uses RFC 3339 format
    return iso_timestamp.replace("Z", "+00:00") if iso_timestamp else ""


def escape_toml_string(s: str) -> str:
    """Escape a string for TOML basic string (double quotes)."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_tool_call_toml(tool_call: ToolCall, result_content: Optional[str] = None) -> list[str]:
    """Render a tool call as TOML lines."""
    lines = []
    lines.append("[[turns.assistant.tool_calls]]")
    lines.append(f'tool = "{tool_call.tool_name}"')
    lines.append(f'id = "{tool_call.id}"')
    if tool_call.timestamp:
        lines.append(f'timestamp = "{format_timestamp(tool_call.timestamp)}"')

    # Parse input JSON
    try:
        input_data = json.loads(tool_call.input_json)
    except json.JSONDecodeError:
        input_data = {"raw": tool_call.input_json}

    # Render input as inline table or sub-table depending on complexity
    if isinstance(input_data, dict):
        lines.append("")
        lines.append("[turns.assistant.tool_calls.input]")
        for key, value in input_data.items():
            if isinstance(value, str):
                if "\n" in value or len(value) > 80:
                    lines.append(f"{key} = '''")
                    lines.append(value)
                    lines.append("'''")
                else:
                    lines.append(f'{key} = "{escape_toml_string(value)}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            else:
                # Complex value - serialize as JSON string
                lines.append(f'{key} = "{escape_toml_string(json.dumps(value))}"')

    if result_content:
        lines.append("")
        lines.append("[turns.assistant.tool_calls.result]")
        lines.append("content = '''")
        lines.append(result_content)
        lines.append("'''")

    return lines


def render_session_toml(session: Session) -> str:
    """Render a session as a TOML document."""
    lines = []

    # Session metadata
    lines.append("[session]")
    lines.append(f'id = "{session.id}"')
    if session.slug:
        lines.append(f'slug = "{escape_toml_string(session.slug)}"')
    lines.append(f'project = "{session.project}"')
    if session.parent_session_id:
        lines.append(f'parent_session_id = "{session.parent_session_id}"')
    if session.cwd:
        lines.append(f'cwd = "{escape_toml_string(session.cwd)}"')
    if session.git_branch:
        lines.append(f'git_branch = "{escape_toml_string(session.git_branch)}"')
    if session.summary:
        lines.append("summary = '''")
        lines.append(session.summary)
        lines.append("'''")
    if session.started_at:
        lines.append(f'started_at = "{format_timestamp(session.started_at)}"')
    if session.ended_at:
        lines.append(f'ended_at = "{format_timestamp(session.ended_at)}"')
    if session.model:
        lines.append(f'model = "{session.model}"')
    if session.claude_version:
        lines.append(f'claude_version = "{session.claude_version}"')
    lines.append(f"input_tokens = {session.total_input_tokens}")
    lines.append(f"output_tokens = {session.total_output_tokens}")
    lines.append(f"cache_read_tokens = {session.total_cache_read_tokens}")
    lines.append("")

    # Build tool results lookup
    tool_results_by_call_id = {tr.tool_call_id: tr for tr in session.tool_results}

    # Group messages into turns
    turn_number = 0
    current_user_content: Optional[str] = None
    current_user_timestamp: Optional[str] = None
    pending_assistant_content: list[str] = []
    pending_assistant_thinking: list[str] = []
    pending_tool_calls: list[tuple[ToolCall, Optional[str]]] = []

    def flush_turn():
        nonlocal turn_number, current_user_content, current_user_timestamp
        nonlocal pending_assistant_content, pending_assistant_thinking, pending_tool_calls

        if current_user_content is None and not pending_assistant_content and not pending_tool_calls:
            return

        turn_number += 1
        lines.append("[[turns]]")
        lines.append(f"number = {turn_number}")
        if current_user_timestamp:
            lines.append(f'timestamp = "{format_timestamp(current_user_timestamp)}"')
        lines.append("")

        if current_user_content:
            lines.append("[turns.user]")
            lines.append("content = '''")
            lines.append(current_user_content)
            lines.append("'''")
            lines.append("")

        if pending_assistant_content or pending_assistant_thinking:
            lines.append("[turns.assistant]")
            combined_content = "\n".join(pending_assistant_content)
            if combined_content.strip():
                lines.append("content = '''")
                lines.append(combined_content)
                lines.append("'''")
            combined_thinking = "\n".join(pending_assistant_thinking)
            if combined_thinking.strip():
                lines.append("thinking = '''")
                lines.append(combined_thinking)
                lines.append("'''")
            lines.append("")

        for tc, result in pending_tool_calls:
            lines.extend(render_tool_call_toml(tc, result))
            lines.append("")

        # Reset
        current_user_content = None
        current_user_timestamp = None
        pending_assistant_content = []
        pending_assistant_thinking = []
        pending_tool_calls = []

    for message in session.messages:
        if message.type == "user" and message.content.strip():
            # Flush previous turn if exists
            flush_turn()
            current_user_content = message.content
            current_user_timestamp = message.timestamp

        elif message.type == "assistant":
            if message.content.strip():
                pending_assistant_content.append(message.content)
            if message.thinking and message.thinking.strip():
                pending_assistant_thinking.append(message.thinking)

            for tool_call in message.tool_calls:
                result_content = None
                if tool_call.id in tool_results_by_call_id:
                    result_content = tool_results_by_call_id[tool_call.id].content
                pending_tool_calls.append((tool_call, result_content))

    # Flush final turn
    flush_turn()

    return "\n".join(lines)


def render_session_to_file(session: Session, output_dir: Path) -> Path:
    """Render a session to a TOML file."""
    project_dir = output_dir / session.project
    project_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    date_str = ""
    if session.started_at:
        try:
            dt = datetime.fromisoformat(session.started_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            date_str = session.started_at[:10]
    else:
        date_str = "unknown-date"

    short_id = session.id[:8]
    filename = f"{date_str}-{short_id}.toml"
    output_path = project_dir / filename

    content = render_session_toml(session)
    output_path.write_text(content, encoding="utf-8")

    return output_path
