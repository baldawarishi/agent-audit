"""Tests for recommendations module."""

import pytest

from claude_code_audit.analyzer.recommendations import (
    Recommendation,
    RecommendationCategory,
    RecommendationGenerator,
    parse_recommendations_from_synthesis,
)


class TestRecommendationCategory:
    """Tests for RecommendationCategory enum."""

    def test_all_categories_exist(self):
        """All expected categories are defined."""
        assert RecommendationCategory.CLAUDE_MD.value == "claude_md"
        assert RecommendationCategory.SKILL.value == "skill"
        assert RecommendationCategory.HOOK.value == "hook"
        assert RecommendationCategory.MCP.value == "mcp"
        assert RecommendationCategory.WORKFLOW.value == "workflow"
        assert RecommendationCategory.PROMPT.value == "prompt"


class TestRecommendation:
    """Tests for Recommendation dataclass."""

    def test_basic_recommendation(self):
        """Create a basic recommendation."""
        rec = Recommendation(
            category=RecommendationCategory.WORKFLOW,
            title="Test Recommendation",
            description="A test description",
        )

        assert rec.category == RecommendationCategory.WORKFLOW
        assert rec.title == "Test Recommendation"
        assert rec.description == "A test description"
        assert rec.evidence == []
        assert rec.estimated_impact is None
        assert rec.priority_score == 0.0

    def test_full_recommendation(self):
        """Create a recommendation with all fields."""
        rec = Recommendation(
            category=RecommendationCategory.SKILL,
            title="Release Skill",
            description="Automate release workflow",
            evidence=["Pattern found in 8 sessions"],
            estimated_impact=5000,
            priority_score=7.5,
            content="# SKILL.md content",
            metadata={"skill_name": "release"},
        )

        assert rec.category == RecommendationCategory.SKILL
        assert rec.estimated_impact == 5000
        assert rec.priority_score == 7.5
        assert "skill_name" in rec.metadata

    def test_output_filename_claude_md(self):
        """CLAUDE.md recommendations have consistent filename."""
        rec = Recommendation(
            category=RecommendationCategory.CLAUDE_MD,
            title="Add Git Workflow",
            description="Document git workflow",
        )
        assert rec.output_filename == "claude-md-additions.md"

    def test_output_filename_skill(self):
        """Skill recommendations use skill name in filename."""
        rec = Recommendation(
            category=RecommendationCategory.SKILL,
            title="Release Skill",
            description="Automate release",
            metadata={"skill_name": "release"},
        )
        assert rec.output_filename == "skill-release.md"

    def test_output_filename_skill_without_metadata(self):
        """Skill without metadata uses slugified title."""
        rec = Recommendation(
            category=RecommendationCategory.SKILL,
            title="My Custom Skill",
            description="A custom skill",
        )
        assert rec.output_filename == "skill-my-custom-skill.md"

    def test_output_filename_workflow(self):
        """Workflow recommendations use slugified title."""
        rec = Recommendation(
            category=RecommendationCategory.WORKFLOW,
            title="Validate Before Presenting",
            description="Run checks first",
        )
        assert rec.output_filename == "workflow-validate-before-presenting.md"

    def test_output_filename_sanitizes_special_chars(self):
        """Filename sanitizes special characters."""
        rec = Recommendation(
            category=RecommendationCategory.WORKFLOW,
            title="Test/Validate & Check!",
            description="Testing",
        )
        # Should remove special chars, keep alphanumeric and hyphens
        filename = rec.output_filename
        assert "/" not in filename
        assert "&" not in filename
        assert "!" not in filename


class TestParseRecommendationsFromSynthesis:
    """Tests for parsing recommendations from synthesis files."""

    def test_parse_valid_toml(self, tmp_path):
        """Parse recommendations from valid TOML block."""
        synthesis_content = '''# Global Synthesis

Some narrative content here.

## Recommendations

```toml
[[recommendations]]
category = "workflow"
title = "Test Recommendation"
description = "A test"
evidence = ["Pattern 1", "Pattern 2"]
estimated_impact = 1000
priority_score = 5.0
content = """
## Checklist

- [ ] Item 1
- [ ] Item 2
"""
```
'''
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        recommendations = parse_recommendations_from_synthesis(synthesis_path)

        assert len(recommendations) == 1
        rec = recommendations[0]
        assert rec.category == RecommendationCategory.WORKFLOW
        assert rec.title == "Test Recommendation"
        assert rec.description == "A test"
        assert rec.evidence == ["Pattern 1", "Pattern 2"]
        assert rec.estimated_impact == 1000
        assert rec.priority_score == 5.0
        assert "## Checklist" in rec.content

    def test_parse_multiple_recommendations(self, tmp_path):
        """Parse multiple recommendations from TOML block."""
        synthesis_content = """# Synthesis

```toml
[[recommendations]]
category = "workflow"
title = "First"
description = "First recommendation"

[[recommendations]]
category = "skill"
title = "Second"
description = "Second recommendation"
```
"""
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        recommendations = parse_recommendations_from_synthesis(synthesis_path)

        assert len(recommendations) == 2
        assert recommendations[0].category == RecommendationCategory.WORKFLOW
        assert recommendations[1].category == RecommendationCategory.SKILL

    def test_parse_with_metadata(self, tmp_path):
        """Parse recommendations with metadata section."""
        synthesis_content = """# Synthesis

```toml
[[recommendations]]
category = "skill"
title = "Release"
description = "Release workflow"
content = "SKILL content"

[recommendations.metadata]
skill_name = "release"
skill_description = "Automate releases"
```
"""
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        recommendations = parse_recommendations_from_synthesis(synthesis_path)

        assert len(recommendations) == 1
        assert recommendations[0].metadata["skill_name"] == "release"

    def test_parse_no_toml_block(self, tmp_path):
        """Raise error when no TOML block found."""
        synthesis_content = "# Synthesis\n\nNo TOML here."
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        with pytest.raises(ValueError, match="No TOML block found"):
            parse_recommendations_from_synthesis(synthesis_path)

    def test_parse_invalid_toml(self, tmp_path):
        """Raise error for invalid TOML syntax."""
        synthesis_content = """# Synthesis

```toml
[[recommendations]
invalid toml syntax here
```
"""
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        with pytest.raises(ValueError, match="No valid recommendations found"):
            parse_recommendations_from_synthesis(synthesis_path)

    def test_parse_unknown_category_defaults_to_workflow(self, tmp_path):
        """Unknown category defaults to workflow."""
        synthesis_content = """# Synthesis

```toml
[[recommendations]]
category = "unknown_category"
title = "Test"
description = "Test"
```
"""
        synthesis_path = tmp_path / "global-synthesis.md"
        synthesis_path.write_text(synthesis_content)

        recommendations = parse_recommendations_from_synthesis(synthesis_path)

        assert recommendations[0].category == RecommendationCategory.WORKFLOW


class TestRecommendationGenerator:
    """Tests for RecommendationGenerator class."""

    def test_creates_output_directory(self, tmp_path):
        """Generator creates output directory if it doesn't exist."""
        output_dir = tmp_path / "recommendations"
        assert not output_dir.exists()

        RecommendationGenerator(output_dir)

        assert output_dir.exists()

    def test_generate_workflow(self, tmp_path):
        """Generate workflow recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.WORKFLOW,
            title="Validate First",
            description="Run checks before presenting",
            evidence=["Pattern 1: found in 4 sessions"],
            estimated_impact=5000,
            content="- [ ] Check 1\n- [ ] Check 2",
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        assert paths[0].name == "workflow-validate-first.md"

        content = paths[0].read_text()
        assert "# Workflow Recommendation: Validate First" in content
        assert "Run checks before presenting" in content
        assert "Pattern 1: found in 4 sessions" in content
        assert "~5,000 tokens saved" in content
        assert "- [ ] Check 1" in content

    def test_generate_claude_md(self, tmp_path):
        """Generate CLAUDE.md recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.CLAUDE_MD,
            title="Git Workflow",
            description="Document the git workflow",
            content="## Git\nUse `gt create` for branches",
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        assert paths[0].name == "claude-md-additions.md"

        content = paths[0].read_text()
        assert "# CLAUDE.md Addition: Git Workflow" in content
        assert "## Suggested Addition" in content
        assert "## Git" in content

    def test_generate_skill(self, tmp_path):
        """Generate skill recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.SKILL,
            title="Release Skill",
            description="Automate releases",
            content="---\nname: release\n---\n# Release",
            metadata={"skill_name": "release"},
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        assert paths[0].name == "skill-release.md"

        content = paths[0].read_text()
        assert "# Skill Recommendation: /release" in content
        assert ".claude/skills/release/SKILL.md" in content

    def test_generate_hook(self, tmp_path):
        """Generate hook recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.HOOK,
            title="Pre-commit Hook",
            description="Validate before commits",
            content='{"hooks": {}}',
            metadata={
                "helper_script_path": ".claude/hooks/validate.sh",
                "helper_script": "#!/bin/bash\nexit 0",
            },
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        content = paths[0].read_text()
        assert "# Hook Recommendation: Pre-commit Hook" in content
        assert ".claude/settings.json" in content
        assert "## Helper Script" in content
        assert "#!/bin/bash" in content

    def test_generate_mcp(self, tmp_path):
        """Generate MCP recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.MCP,
            title="Linear Integration",
            description="Integrate with Linear",
            content="claude mcp add linear",
            metadata={
                "env_vars": {"LINEAR_API_KEY": "API key for Linear"},
                "usage_examples": ["Fetch ticket LIN-123"],
            },
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        content = paths[0].read_text()
        assert "# MCP Server Recommendation: Linear Integration" in content
        assert "claude mcp add linear" in content
        assert "LINEAR_API_KEY" in content
        assert "Fetch ticket LIN-123" in content

    def test_generate_prompt(self, tmp_path):
        """Generate prompt improvement recommendation file."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        rec = Recommendation(
            category=RecommendationCategory.PROMPT,
            title="Brief Answer Prefix",
            description="Use prefix for simple questions",
            content="### Before\n> Is this a bug?\n\n### After\n> Brief: Is this a bug?",
        )

        paths = generator.generate_all([rec])

        assert len(paths) == 1
        content = paths[0].read_text()
        assert "# Prompt Improvement: Brief Answer Prefix" in content
        assert "## Before/After Examples" in content
        assert "### Before" in content

    def test_generate_all_categories(self, tmp_path):
        """Generate files for all recommendation categories."""
        output_dir = tmp_path / "recommendations"
        generator = RecommendationGenerator(output_dir)

        recommendations = [
            Recommendation(
                category=RecommendationCategory.CLAUDE_MD,
                title="Doc",
                description="Description",
            ),
            Recommendation(
                category=RecommendationCategory.SKILL,
                title="Skill",
                description="Description",
            ),
            Recommendation(
                category=RecommendationCategory.HOOK,
                title="Hook",
                description="Description",
            ),
            Recommendation(
                category=RecommendationCategory.MCP,
                title="MCP",
                description="Description",
            ),
            Recommendation(
                category=RecommendationCategory.WORKFLOW,
                title="Workflow",
                description="Description",
            ),
            Recommendation(
                category=RecommendationCategory.PROMPT,
                title="Prompt",
                description="Description",
            ),
        ]

        paths = generator.generate_all(recommendations)

        assert len(paths) == 6

        # Check all files were created
        filenames = [p.name for p in paths]
        assert "claude-md-additions.md" in filenames
        assert "skill-skill.md" in filenames
        assert "hook-hook.md" in filenames
        assert "mcp-mcp.md" in filenames
        assert "workflow-workflow.md" in filenames
        assert "prompt-prompt.md" in filenames
