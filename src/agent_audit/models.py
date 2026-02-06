"""Data models for Claude Code archive."""

import re
from dataclasses import dataclass, field
from typing import Optional

# Regex to match git commit output: [branch hash] message
COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")

# Regex to detect repo from git push output (GitHub pull request links)
REPO_PUSH_PATTERN = re.compile(
    r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)/pull/new/"
)

# Regex to extract owner/repo from a git remote URL (any platform)
# Matches: https://host/owner/repo(.git), git@host:owner/repo(.git)
# Also handles GitLab nested groups: host/group/subgroup/project
REPO_URL_PATTERN = re.compile(
    r"(?:https?://|git@)([^/:\s]+)[/:](.+?)(?:\.git)?$"
)

# Deprecated alias
GITHUB_REPO_PATTERN = REPO_PUSH_PATTERN

# Known hosting platforms mapped by hostname
KNOWN_PLATFORMS: dict[str, str] = {
    "github.com": "github",
    "gitlab.com": "gitlab",
    "bitbucket.org": "bitbucket",
}


def detect_platform(hostname: str) -> str | None:
    """Detect platform from hostname. Returns None for unrecognized hosts."""
    return KNOWN_PLATFORMS.get(hostname.lower())


@dataclass
class Commit:
    """Represents a git commit extracted from tool results."""

    id: str
    session_id: str
    commit_hash: str
    message: str
    timestamp: Optional[str] = None


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
    thinking: Optional[str] = None
    stop_reason: Optional[str] = None
    is_sidechain: bool = False
    is_compact_summary: bool = False  # True for session continuation messages
    has_images: bool = False  # True if message contains image content
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Session:
    """Represents a coding agent session (Claude Code, Codex, etc.)."""

    id: str
    project: str
    agent_type: str = "claude-code"  # "claude-code" or "codex"
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    slug: Optional[str] = None
    summary: Optional[str] = None
    title: Optional[str] = None  # Session title (from web API or derived)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    claude_version: Optional[str] = None  # Also used for codex CLI version
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    model: Optional[str] = None
    parent_session_id: Optional[str] = None  # For agent sessions, links to parent
    is_warmup: bool = False  # True if this is a warmup/cache-priming session
    is_sidechain: bool = False  # True if session contains sidechain messages
    repo: Optional[str] = None  # Repo as "owner/name" (or "group/subgroup/project" for GitLab)
    repo_platform: Optional[str] = None  # "github", "gitlab", "bitbucket", or None
    session_context: Optional[str] = None  # Raw session_context JSON
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    commits: list[Commit] = field(
        default_factory=list
    )  # Git commits extracted from tool results

    @property
    def github_repo(self) -> Optional[str]:
        """Deprecated: use ``repo`` instead."""
        return self.repo

    @github_repo.setter
    def github_repo(self, value: Optional[str]) -> None:
        """Deprecated: use ``repo`` instead."""
        self.repo = value
