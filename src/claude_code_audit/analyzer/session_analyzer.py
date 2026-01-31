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

    def get_global_percentiles(self) -> dict:
        """Get global percentile statistics."""
        ...

    def get_project_session_stats(self, project: str) -> dict:
        """Get session statistics for a project."""
        ...


def load_session_analysis_template() -> str:
    """Load the session analysis prompt template.

    Returns:
        The template string with placeholders.
    """
    template_path = Path(__file__).parent.parent / "prompts" / "session_analysis.md"
    return template_path.read_text()


def load_global_synthesis_template() -> str:
    """Load the global synthesis prompt template.

    Returns:
        The template string with placeholders.
    """
    template_path = Path(__file__).parent.parent / "prompts" / "global_synthesis.md"
    return template_path.read_text()


def load_best_practices_reference() -> str:
    """Load the best practices reference document.

    Returns:
        The best practices reference content.
    """
    template_path = (
        Path(__file__).parent.parent / "prompts" / "best_practices_reference.md"
    )
    return template_path.read_text()


def load_validation_template() -> str:
    """Load the validation prompt template.

    Returns:
        The template string with placeholders.
    """
    template_path = (
        Path(__file__).parent.parent / "prompts" / "best_practices_validation.md"
    )
    return template_path.read_text()


def build_validation_prompt(synthesis_content: str) -> str:
    """Build the validation prompt with synthesis and best practices.

    Args:
        synthesis_content: The global synthesis markdown with TOML

    Returns:
        Formatted prompt string.
    """
    template = load_validation_template()
    best_practices = load_best_practices_reference()
    return template.format(
        synthesis=synthesis_content,
        best_practices=best_practices,
    )


def load_fix_template() -> str:
    """Load the recommendation fix prompt template.

    Returns:
        The template string with placeholders.
    """
    template_path = Path(__file__).parent.parent / "prompts" / "recommendation_fix.md"
    return template_path.read_text()


def build_fix_prompt(original_toml: str, validation_issues: str) -> str:
    """Build the fix prompt with original TOML and validation issues.

    Args:
        original_toml: The original TOML recommendations block
        validation_issues: Formatted string of issues to fix

    Returns:
        Formatted prompt string.
    """
    template = load_fix_template()
    return template.format(
        original_toml=original_toml,
        validation_issues=validation_issues,
    )


def build_global_synthesis_prompt(
    analysis_files: list[Path],
    analysis_dir: Path,
) -> str:
    """Build the global synthesis prompt with analysis file list.

    Args:
        analysis_files: List of paths to per-project analysis files
        analysis_dir: Directory containing the analysis files

    Returns:
        Formatted prompt string.
    """
    template = load_global_synthesis_template()

    # Format analysis files as a bulleted list
    files_list = "\n".join(f"- `{f.name}`" for f in analysis_files)

    return template.format(
        project_count=len(analysis_files),
        analysis_files=files_list,
        analysis_dir=str(analysis_dir),
    )


def build_session_analysis_prompt(
    project: str,
    session_count: int,
    turn_count: int,
    input_tokens: int,
    output_tokens: int,
    tool_call_count: int,
    toml_dir: str,
    global_p50_msgs: int,
    global_p75_msgs: int,
    global_p90_msgs: int,
    global_p50_tokens: int,
    project_avg_msgs: int,
    project_min_msgs: int,
    project_max_msgs: int,
    project_avg_tokens: int,
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
        global_p50_msgs: Global P50 message count
        global_p75_msgs: Global P75 message count
        global_p90_msgs: Global P90 message count
        global_p50_tokens: Global P50 output tokens
        project_avg_msgs: Project average message count
        project_min_msgs: Project minimum message count
        project_max_msgs: Project maximum message count
        project_avg_tokens: Project average output tokens

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
        global_p50_msgs=global_p50_msgs,
        global_p75_msgs=global_p75_msgs,
        global_p90_msgs=global_p90_msgs,
        global_p50_tokens=global_p50_tokens,
        project_avg_msgs=project_avg_msgs,
        project_min_msgs=project_min_msgs,
        project_max_msgs=project_max_msgs,
        project_avg_tokens=project_avg_tokens,
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

        # Get global percentiles and project-specific stats
        global_percentiles = self.db.get_global_percentiles()
        project_stats = self.db.get_project_session_stats(project)

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
            global_p50_msgs=global_percentiles["p50_msgs"],
            global_p75_msgs=global_percentiles["p75_msgs"],
            global_p90_msgs=global_percentiles["p90_msgs"],
            global_p50_tokens=global_percentiles["p50_tokens"],
            project_avg_msgs=project_stats["avg_msgs"],
            project_min_msgs=project_stats["min_msgs"],
            project_max_msgs=project_stats["max_msgs"],
            project_avg_tokens=project_stats["avg_tokens"],
        )

        # Query Claude and return the response
        return await self.client.query(prompt)

    async def synthesize_global(self, analysis_dir: Path) -> str:
        """Synthesize cross-project patterns from per-project analyses.

        Args:
            analysis_dir: Directory containing per-project analysis .md files

        Returns:
            Markdown synthesis content.

        Raises:
            ValueError: If no analysis files are found.
        """
        # Find all .md files except synthesis and validation outputs
        analysis_files = [
            f
            for f in sorted(analysis_dir.glob("*.md"))
            if f.name.lower() not in ("global-synthesis.md", "validation-report.md")
        ]

        if not analysis_files:
            raise ValueError(f"No analysis files found in {analysis_dir}")

        # Build the prompt
        prompt = build_global_synthesis_prompt(
            analysis_files=analysis_files,
            analysis_dir=analysis_dir,
        )

        # Query Claude and return the response
        return await self.client.query(prompt)

    async def validate_against_best_practices(self, synthesis_content: str) -> str:
        """Validate synthesis against best practices, returning validation report.

        Args:
            synthesis_content: The global synthesis markdown with TOML

        Returns:
            Validation report with PASS/NEEDS_REVISION/REJECT verdicts
        """
        prompt = build_validation_prompt(synthesis_content)
        return await self.client.query(prompt)

    async def fix_recommendations(
        self, original_toml: str, validation_issues: str
    ) -> str:
        """Fix recommendations based on validation issues.

        Args:
            original_toml: The original TOML recommendations block
            validation_issues: Formatted string describing issues to fix

        Returns:
            Corrected TOML block with fixed recommendations
        """
        prompt = build_fix_prompt(original_toml, validation_issues)
        return await self.client.query(prompt)
