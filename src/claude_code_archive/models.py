"""Data models for Claude Code archive."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ToolCall:
    """Represents a tool call made by the assistant."""

    id: str
    message_id: str
    session_id: str
    tool_name: str
    input_json: str
    timestamp: Optional[str] = None


@dataclass
class ToolResult:
    """Represents the result of a tool call."""

    id: str
    tool_call_id: str
    session_id: str
    content: str
    is_error: bool = False
    timestamp: Optional[str] = None


@dataclass
class Message:
    """Represents a message in a session."""

    id: str
    session_id: str
    type: str  # user, assistant, tool_result
    timestamp: str
    content: str
    parent_uuid: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Session:
    """Represents a Claude Code session."""

    id: str
    project: str
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    claude_version: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    model: Optional[str] = None
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
