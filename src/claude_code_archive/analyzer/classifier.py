"""Phase 2: LLM-based pattern classification."""

import json
from dataclasses import dataclass
from importlib.resources import files as resource_files
from pathlib import Path
from typing import TYPE_CHECKING

from .patterns import RawPattern

if TYPE_CHECKING:
    from .claude_client import AnalyzerClaudeClient


@dataclass
class ClassifiedPattern:
    """A pattern with LLM-generated classification."""

    raw_pattern: RawPattern
    category: str  # "skill" | "claude_md" | "hook"
    scope: str  # "global" | "project:{name}" | "subdir:{path}"
    confidence: str  # "high" | "medium" | "low"
    reasoning: str
    suggested_name: str
    suggested_content: str

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "pattern_type": self.raw_pattern.pattern_type,
            "pattern_key": self.raw_pattern.pattern_key,
            "occurrences": self.raw_pattern.occurrences,
            "session_count": len(self.raw_pattern.sessions),
            "project_count": len(self.raw_pattern.projects),
            "projects": sorted(self.raw_pattern.projects),
            "first_seen": self.raw_pattern.first_seen,
            "last_seen": self.raw_pattern.last_seen,
            "category": self.category,
            "scope": self.scope,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "suggested_name": self.suggested_name,
            "suggested_content": self.suggested_content,
        }


def load_prompt_template() -> str:
    """Load the classification prompt template.

    Returns:
        The prompt template string with {placeholders}
    """
    # Use importlib.resources to load from package
    try:
        template_path = resource_files("claude_code_archive.prompts").joinpath(
            "classification.md"
        )
        return template_path.read_text()
    except Exception:
        # Fallback to file path for development
        module_dir = Path(__file__).parent.parent
        template_path = module_dir / "prompts" / "classification.md"
        return template_path.read_text()


def build_classification_prompt(
    patterns: dict,
    num_projects: int,
    date_range: str,
    global_threshold: float = 0.3,
    max_patterns: int = 50,
) -> str:
    """Build the classification prompt with pattern data.

    Args:
        patterns: Dict of patterns from detect_patterns()
        num_projects: Total number of projects in the archive
        date_range: Human-readable date range string
        global_threshold: Fraction of projects for global scope (default 0.3)
        max_patterns: Maximum patterns to include (default 50)

    Returns:
        Complete prompt string ready to send to Claude
    """
    template = load_prompt_template()

    # Flatten and sort patterns by occurrences (most frequent first)
    all_patterns = []
    for pattern_type, pattern_list in patterns.items():
        for p in pattern_list:
            all_patterns.append(p)

    # Sort by occurrences descending, then limit
    all_patterns.sort(key=lambda x: x.get("occurrences", 0), reverse=True)
    all_patterns = all_patterns[:max_patterns]

    patterns_json = json.dumps(all_patterns, indent=2)

    return template.format(
        patterns_json=patterns_json,
        num_projects=num_projects,
        date_range=date_range,
        global_threshold_pct=int(global_threshold * 100),
    )


def parse_classification_response(
    response_json: dict,
    raw_patterns_by_key: dict[str, RawPattern],
) -> list[ClassifiedPattern]:
    """Parse LLM classification response into ClassifiedPattern objects.

    Args:
        response_json: Parsed JSON from Claude response
        raw_patterns_by_key: Map of pattern_key to RawPattern

    Returns:
        List of ClassifiedPattern objects
    """
    classifications = response_json.get("classifications", [])
    results = []

    for item in classifications:
        pattern_key = item.get("pattern_key", "")
        raw_pattern = raw_patterns_by_key.get(pattern_key)

        if not raw_pattern:
            # Try to find a close match (Claude might slightly modify the key)
            for key, pattern in raw_patterns_by_key.items():
                if pattern_key in key or key in pattern_key:
                    raw_pattern = pattern
                    break

        if not raw_pattern:
            # Create a placeholder RawPattern if we can't find the original
            raw_pattern = RawPattern(
                pattern_type=item.get("pattern_type", "unknown"),
                pattern_key=pattern_key,
                occurrences=item.get("occurrences", 0),
            )

        # Validate and normalize values
        category = item.get("category", "claude_md")
        if category not in ("skill", "claude_md", "hook"):
            category = "claude_md"

        scope = item.get("scope", "global")
        if not (
            scope == "global"
            or scope.startswith("project:")
            or scope.startswith("subdir:")
        ):
            scope = "global"

        confidence = item.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        results.append(
            ClassifiedPattern(
                raw_pattern=raw_pattern,
                category=category,
                scope=scope,
                confidence=confidence,
                reasoning=item.get("reasoning", ""),
                suggested_name=item.get("suggested_name", ""),
                suggested_content=item.get("suggested_content", ""),
            )
        )

    return results


def compute_scope(
    pattern: RawPattern,
    total_projects: int,
    global_threshold: float = 0.3,
) -> str:
    """Compute the recommended scope for a pattern.

    This is a heuristic fallback when LLM classification is not available.

    Args:
        pattern: The raw pattern to analyze
        total_projects: Total number of projects in the archive
        global_threshold: Fraction of projects for global scope

    Returns:
        Scope string: "global", "project:{name}", or "subdir:{path}"
    """
    project_count = len(pattern.projects)

    if total_projects == 0:
        return "global"

    # Check if pattern appears in enough projects to be global
    if project_count / total_projects >= global_threshold:
        return "global"

    # If only one project, scope to that project
    if project_count == 1:
        project_name = list(pattern.projects)[0]
        return f"project:{project_name}"

    # Multiple projects but not enough for global - default to global anyway
    # This could be refined with subdir detection in the future
    return "global"


def compute_confidence(pattern: RawPattern) -> str:
    """Compute confidence score for a pattern based on heuristics.

    Args:
        pattern: The raw pattern to analyze

    Returns:
        Confidence level: "high", "medium", or "low"
    """
    session_count = len(pattern.sessions)
    project_count = len(pattern.projects)
    occurrences = pattern.occurrences

    # High confidence: appears many times across many sessions/projects
    if occurrences >= 10 and session_count >= 5 and project_count >= 2:
        return "high"

    # Medium confidence: moderate occurrence
    if occurrences >= 5 and session_count >= 3:
        return "medium"

    # Low confidence: just meets thresholds
    return "low"


class PatternClassifier:
    """Classifies patterns using Claude LLM."""

    def __init__(
        self,
        client: "AnalyzerClaudeClient",
        global_threshold: float = 0.3,
        max_patterns: int = 50,
    ):
        self.client = client
        self.global_threshold = global_threshold
        self.max_patterns = max_patterns

    async def classify(
        self,
        patterns_result: dict,
    ) -> list[ClassifiedPattern]:
        """Classify all patterns using Claude.

        Args:
            patterns_result: The full result from detect_patterns()

        Returns:
            List of ClassifiedPattern objects
        """
        # Build pattern lookup map
        raw_patterns_by_key: dict[str, RawPattern] = {}
        for pattern_type, pattern_list in patterns_result["patterns"].items():
            for p in pattern_list:
                # p is a dict from to_dict()
                key = p["pattern_key"]
                raw_patterns_by_key[key] = RawPattern(
                    pattern_type=p["pattern_type"],
                    pattern_key=key,
                    occurrences=p["occurrences"],
                    sessions=set(p.get("sessions", [])),
                    projects=set(p.get("projects", [])),
                    first_seen=p.get("first_seen"),
                    last_seen=p.get("last_seen"),
                    examples=p.get("examples", []),
                )

        # Compute date range
        summary = patterns_result["summary"]

        # Find earliest and latest dates from patterns
        all_first = []
        all_last = []
        for patterns in patterns_result["patterns"].values():
            for p in patterns:
                if p.get("first_seen"):
                    all_first.append(p["first_seen"])
                if p.get("last_seen"):
                    all_last.append(p["last_seen"])

        if all_first and all_last:
            date_range = f"{min(all_first)[:10]} to {max(all_last)[:10]}"
        else:
            date_range = "unknown"

        # Build prompt
        prompt = build_classification_prompt(
            patterns=patterns_result["patterns"],
            num_projects=summary["total_projects"],
            date_range=date_range,
            global_threshold=self.global_threshold,
            max_patterns=self.max_patterns,
        )

        # Query Claude
        response = await self.client.query(prompt)

        # Parse response
        response_json = self.client.parse_json_response(response)

        return parse_classification_response(response_json, raw_patterns_by_key)


async def classify_patterns(
    patterns_result: dict,
    global_threshold: float = 0.3,
    max_patterns: int = 50,
) -> list[ClassifiedPattern]:
    """Main entry point for pattern classification.

    This function manages the Claude client lifecycle.

    Args:
        patterns_result: The full result from detect_patterns()
        global_threshold: Fraction of projects for global scope (default 0.3)
        max_patterns: Maximum patterns to classify (default 50)

    Returns:
        List of ClassifiedPattern objects
    """
    # Import at runtime to avoid requiring claude_agent_sdk at module load time
    from .claude_client import AnalyzerClaudeClient

    async with AnalyzerClaudeClient() as client:
        classifier = PatternClassifier(client, global_threshold, max_patterns)
        return await classifier.classify(patterns_result)
