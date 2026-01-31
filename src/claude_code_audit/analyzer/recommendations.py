"""Recommendation generation from global synthesis."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import tomllib


class RecommendationCategory(str, Enum):
    """Category types for recommendations."""

    CLAUDE_MD = "claude_md"  # CLAUDE.md documentation additions
    SKILL = "skill"  # Custom slash commands
    HOOK = "hook"  # Lifecycle event hooks
    MCP = "mcp"  # MCP server integrations
    WORKFLOW = "workflow"  # Process/workflow guidelines
    PROMPT = "prompt"  # User prompting improvements


@dataclass
class Recommendation:
    """A single actionable recommendation from analysis.

    Attributes:
        category: Type of recommendation (determines output format)
        title: Short descriptive title
        description: Detailed explanation of the recommendation
        evidence: List of references to analysis findings
        estimated_impact: Token savings estimate (optional)
        priority_score: Calculated priority based on impact/actionability
        content: The actual content to generate (markdown, JSON, etc.)
        metadata: Category-specific metadata
    """

    category: RecommendationCategory
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    estimated_impact: Optional[int] = None
    priority_score: float = 0.0
    content: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def output_filename(self) -> str:
        """Generate appropriate filename based on category."""
        slug = self.title.lower().replace(" ", "-").replace("/", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

        match self.category:
            case RecommendationCategory.CLAUDE_MD:
                return "claude-md-additions.md"
            case RecommendationCategory.SKILL:
                name = self.metadata.get("skill_name", slug)
                return f"skill-{name}.md"
            case RecommendationCategory.HOOK:
                return f"hook-{slug}.md"
            case RecommendationCategory.MCP:
                return f"mcp-{slug}.md"
            case RecommendationCategory.WORKFLOW:
                return f"workflow-{slug}.md"
            case RecommendationCategory.PROMPT:
                return f"prompt-{slug}.md"


def _extract_toml_blocks(content: str) -> list[str]:
    """Extract all TOML blocks from markdown content.

    Handles embedded ``` markers inside TOML multi-line strings by tracking
    triple-quote state. A ``` only ends the TOML block if we're not inside
    a triple-quoted string.

    Args:
        content: Markdown content with fenced TOML blocks

    Returns:
        List of TOML content strings (without fences)
    """
    blocks = []
    pos = 0

    while True:
        # Find the next ```toml block
        start = content.find("```toml\n", pos)
        if start == -1:
            break

        block_start = start + 8  # Skip past "```toml\n"

        # Scan through the content tracking triple-quote state
        # We're looking for ``` that's NOT inside a """ string
        scan_pos = block_start
        in_triple_quote = False
        end = -1

        while scan_pos < len(content):
            # Check for triple quote (""")
            if content[scan_pos : scan_pos + 3] == '"""':
                in_triple_quote = not in_triple_quote
                scan_pos += 3
                continue

            # Check for closing fence ``` (only valid if not in triple quote)
            if not in_triple_quote and content[scan_pos : scan_pos + 4] == "\n```":
                # Verify this isn't a language specifier like ```python
                after_fence = scan_pos + 4
                if after_fence >= len(content):
                    end = scan_pos
                    break
                next_char = content[after_fence]
                if not next_char.isalpha():
                    # This is the closing fence
                    end = scan_pos
                    break

            scan_pos += 1

        if end != -1:
            blocks.append(content[block_start:end])
            pos = end + 4
        else:
            # Unclosed block, skip it
            pos = block_start

    return blocks


def parse_recommendations_from_synthesis(synthesis_path: Path) -> list[Recommendation]:
    """Parse recommendations from a global synthesis file.

    The synthesis file should contain one or more TOML blocks with structured
    recommendations. Each block is delimited by ```toml and ``` markers.
    All [[recommendations]] from all blocks are combined.

    Args:
        synthesis_path: Path to the global-synthesis.md file

    Returns:
        List of Recommendation objects

    Raises:
        ValueError: If no valid TOML block is found
    """
    content = synthesis_path.read_text()

    # Extract all TOML blocks
    toml_blocks = _extract_toml_blocks(content)

    if not toml_blocks:
        raise ValueError(
            f"No TOML block found in {synthesis_path}. "
            "Ensure synthesis was generated with structured output enabled."
        )

    # Parse each block and collect all recommendations
    # Some blocks may have invalid TOML (e.g., unescaped backslashes from LLM output)
    # We parse what we can and warn about failures
    all_recommendations_data = []
    parse_warnings = []
    for i, toml_content in enumerate(toml_blocks):
        try:
            data = tomllib.loads(toml_content)
            all_recommendations_data.extend(data.get("recommendations", []))
        except tomllib.TOMLDecodeError as e:
            parse_warnings.append(f"Warning: Skipping TOML block {i + 1}: {e}")

    if not all_recommendations_data:
        if parse_warnings:
            raise ValueError(
                "No valid recommendations found. TOML parse errors:\n"
                + "\n".join(parse_warnings)
            )
        raise ValueError("No recommendations found in any TOML block")

    recommendations = []
    for rec_data in all_recommendations_data:
        try:
            category = RecommendationCategory(rec_data.get("category", "workflow"))
        except ValueError:
            category = RecommendationCategory.WORKFLOW

        rec = Recommendation(
            category=category,
            title=rec_data.get("title", "Untitled"),
            description=rec_data.get("description", ""),
            evidence=rec_data.get("evidence", []),
            estimated_impact=rec_data.get("estimated_impact"),
            priority_score=rec_data.get("priority_score", 0.0),
            content=rec_data.get("content", ""),
            metadata=rec_data.get("metadata", {}),
        )
        recommendations.append(rec)

    return recommendations


class RecommendationGenerator:
    """Generates output files from recommendations."""

    def __init__(self, output_dir: Path):
        """Initialize the generator.

        Args:
            output_dir: Directory to write generated files
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self, recommendations: list[Recommendation]) -> list[Path]:
        """Generate output files for all recommendations.

        Args:
            recommendations: List of recommendations to generate

        Returns:
            List of paths to generated files
        """
        generated = []

        for rec in recommendations:
            path = self._generate_one(rec)
            if path:
                generated.append(path)

        return generated

    def _generate_one(self, rec: Recommendation) -> Optional[Path]:
        """Generate output for a single recommendation."""
        match rec.category:
            case RecommendationCategory.CLAUDE_MD:
                return self._generate_claude_md(rec)
            case RecommendationCategory.SKILL:
                return self._generate_skill(rec)
            case RecommendationCategory.HOOK:
                return self._generate_hook(rec)
            case RecommendationCategory.MCP:
                return self._generate_mcp(rec)
            case RecommendationCategory.WORKFLOW:
                return self._generate_workflow(rec)
            case RecommendationCategory.PROMPT:
                return self._generate_prompt(rec)

    def _generate_claude_md(self, rec: Recommendation) -> Path:
        """Generate CLAUDE.md snippet recommendation."""
        output = f"""# CLAUDE.md Addition: {rec.title}

## Recommendation

{rec.description}

## Suggested Addition

```markdown
{rec.content}
```

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        if rec.estimated_impact:
            output += (
                f"\n## Estimated Impact\n\n~{rec.estimated_impact:,} tokens saved\n"
            )

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path

    def _generate_skill(self, rec: Recommendation) -> Path:
        """Generate skill definition file."""
        skill_name = rec.metadata.get("skill_name", "custom-skill")

        output = f"""# Skill Recommendation: /{skill_name}

## Description

{rec.description}

## Create File

Create `.claude/skills/{skill_name}/SKILL.md`:

```markdown
{rec.content}
```

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        if rec.estimated_impact:
            output += (
                f"\n## Estimated Impact\n\n~{rec.estimated_impact:,} tokens saved\n"
            )

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path

    def _generate_hook(self, rec: Recommendation) -> Path:
        """Generate hook configuration recommendation."""
        output = f"""# Hook Recommendation: {rec.title}

## Description

{rec.description}

## Configuration

Add to `.claude/settings.json`:

```json
{rec.content}
```

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        if rec.estimated_impact:
            output += (
                f"\n## Estimated Impact\n\n~{rec.estimated_impact:,} tokens saved\n"
            )

        # Check for helper script in metadata
        if helper_script := rec.metadata.get("helper_script"):
            output += f"""
## Helper Script

{rec.metadata.get("helper_script_path", "Create helper script")}:

```bash
{helper_script}
```
"""

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path

    def _generate_mcp(self, rec: Recommendation) -> Path:
        """Generate MCP server recommendation."""
        output = f"""# MCP Server Recommendation: {rec.title}

## Description

{rec.description}

## Installation

```bash
{rec.content}
```

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        if env_vars := rec.metadata.get("env_vars"):
            output += "\n## Required Environment Variables\n\n"
            for var, desc in env_vars.items():
                output += f"- `{var}`: {desc}\n"

        if usage := rec.metadata.get("usage_examples"):
            output += "\n## Example Usage\n\n"
            for example in usage:
                output += f"- {example}\n"

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path

    def _generate_workflow(self, rec: Recommendation) -> Path:
        """Generate workflow guideline recommendation."""
        output = f"""# Workflow Recommendation: {rec.title}

## Description

{rec.description}

## Checklist

{rec.content}

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        if rec.estimated_impact:
            output += (
                f"\n## Estimated Impact\n\n~{rec.estimated_impact:,} tokens saved\n"
            )

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path

    def _generate_prompt(self, rec: Recommendation) -> Path:
        """Generate prompt improvement recommendation."""
        output = f"""# Prompt Improvement: {rec.title}

## Description

{rec.description}

## Before/After Examples

{rec.content}

## Evidence

"""
        for e in rec.evidence:
            output += f"- {e}\n"

        path = self.output_dir / rec.output_filename
        path.write_text(output)
        return path
