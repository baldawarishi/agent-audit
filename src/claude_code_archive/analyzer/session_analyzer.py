"""Session analyzer for per-project analysis using Claude."""

from pathlib import Path
from typing import Protocol


class ClaudeClient(Protocol):
    """Protocol for Claude client interface."""

    async def query(self, prompt: str) -> str:
        """Send a query to Claude and return the response."""
        ...


class DatabaseProtocol(Protocol):
    """Protocol for database interface."""

    def get_project_metrics(self, project: str) -> dict:
        """Get metrics for a project."""
        ...


def load_session_analysis_template() -> str:
    """Load the session analysis prompt template.

    Returns:
        The template string with placeholders.
    """
    template_path = Path(__file__).parent.parent / "prompts" / "session_analysis.md"
    return template_path.read_text()


def build_session_analysis_prompt(
    project: str,
    session_count: int,
    turn_count: int,
    input_tokens: int,
    output_tokens: int,
    tool_call_count: int,
    toml_dir: str,
) -> str:
    """Build the session analysis prompt with metrics.

    Args:
        project: Project name
        session_count: Number of sessions
        turn_count: Number of user+assistant turns
        input_tokens: Total input tokens
        output_tokens: Total output tokens
        tool_call_count: Total tool calls
        toml_dir: Path to TOML transcript directory

    Returns:
        Formatted prompt string.
    """
    template = load_session_analysis_template()

    return template.format(
        project=project,
        session_count=session_count,
        turn_count=turn_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_call_count=tool_call_count,
        toml_dir=toml_dir,
    )


class SessionAnalyzer:
    """Analyzes project sessions using Claude.

    Takes a Claude client and database, and produces markdown
    analysis for each project.
    """

    def __init__(
        self,
        client: ClaudeClient,
        db: DatabaseProtocol,
        toml_dir: Path,
    ):
        """Initialize the session analyzer.

        Args:
            client: Claude client for making queries
            db: Database for fetching metrics
            toml_dir: Base directory for TOML transcripts
        """
        self.client = client
        self.db = db
        self.toml_dir = toml_dir

    async def analyze_project(self, project: str) -> str:
        """Analyze sessions for a single project.

        Args:
            project: Project name to analyze

        Returns:
            Markdown analysis content.
        """
        # Get project metrics from database
        metrics = self.db.get_project_metrics(project)

        # Build the prompt
        project_toml_dir = self.toml_dir / project
        prompt = build_session_analysis_prompt(
            project=project,
            session_count=metrics["session_count"],
            turn_count=metrics["turn_count"],
            input_tokens=metrics["total_input_tokens"],
            output_tokens=metrics["total_output_tokens"],
            tool_call_count=metrics["tool_call_count"],
            toml_dir=str(project_toml_dir),
        )

        # Query Claude and return the response
        return await self.client.query(prompt)
