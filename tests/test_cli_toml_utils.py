"""Tests for CLI TOML utility functions."""

import pytest

from agent_audit.cli import (
    _extract_toml_from_synthesis,
    _replace_toml_in_synthesis,
    _parse_validation_toml,
    _format_validation_issues,
)


class TestExtractTomlFromSynthesis:
    def test_extracts_basic_toml_block(self):
        doc = 'Some markdown\n\n```toml\n[section]\nkey = "value"\n```\n\nMore text'
        result = _extract_toml_from_synthesis(doc)
        assert result is not None
        assert '[section]' in result
        assert 'key = "value"' in result

    def test_handles_embedded_triple_quotes_with_backticks_inside(self):
        """The triple-quote tracking must not treat ``` inside \"\"\" as a closing fence."""
        toml_content = '[[recommendations]]\ntitle = "test"\ncontent = """\nSome code:\n```python\nprint("hi")\n```\n"""\n'
        doc = f"# Synthesis\n\n```toml\n{toml_content}```\n"
        result = _extract_toml_from_synthesis(doc)
        assert result is not None
        assert "```python" in result
        assert "recommendations" in result

    def test_returns_none_when_no_toml_block(self):
        doc = "# Just markdown\n\nNo TOML here.\n"
        assert _extract_toml_from_synthesis(doc) is None


class TestReplaceTomlInSynthesis:
    def test_extract_after_replace_returns_new_content(self):
        """The key property: extract(replace(doc, new)) == new."""
        original_doc = '# Title\n\n```toml\n[old]\nkey = "old"\n```\n\n# Footer\n'
        new_toml = '[new]\nkey = "replaced"'

        replaced = _replace_toml_in_synthesis(original_doc, new_toml)
        extracted = _extract_toml_from_synthesis(replaced)

        assert extracted is not None
        assert extracted.strip() == new_toml.strip()

    def test_preserves_surrounding_markdown(self):
        doc = '# Title\n\n```toml\n[old]\n```\n\n# Footer\n'
        replaced = _replace_toml_in_synthesis(doc, '[new]\nkey = "val"')
        assert "# Title" in replaced
        assert "# Footer" in replaced

    def test_noop_when_no_toml_block(self):
        doc = "# No TOML\n\nJust text.\n"
        assert _replace_toml_in_synthesis(doc, "anything") == doc


class TestParseValidationToml:
    def test_parses_valid_validation_report(self):
        content = """# Validation Report

```toml
[validation]
total_reviewed = 3
passed = 2
needs_revision = 1
rejected = 0

[[review]]
title = "Add CLAUDE.md rules"
verdict = "PASS"
issues = []

[[review]]
title = "Bad recommendation"
verdict = "REVISE"
issues = ["No evidence provided"]
suggested_fix = "Add citations"
```
"""
        result = _parse_validation_toml(content)
        assert result is not None
        assert result["validation"]["total_reviewed"] == 3
        assert len(result["review"]) == 2

    def test_truncates_at_unparseable_section(self):
        """Truncates at unparseable trailing section and returns what it can."""
        content = """```toml
[validation]
total_reviewed = 1
passed = 1
needs_revision = 0
rejected = 0

[[review]]
title = "Good rec"
verdict = "PASS"
issues = []

[coverage_analysis]
this is = invalid toml {{{
```
"""
        result = _parse_validation_toml(content)
        assert result is not None
        assert result["validation"]["total_reviewed"] == 1

    def test_returns_none_for_no_toml(self):
        assert _parse_validation_toml("no toml here") is None


class TestFormatValidationIssues:
    def test_excludes_passing_reviews(self):
        data = {
            "review": [
                {"title": "Good", "verdict": "PASS", "issues": []},
                {"title": "Bad", "verdict": "REVISE", "issues": ["needs work"]},
            ]
        }
        result = _format_validation_issues(data)
        assert "Good" not in result
        assert "Bad" in result
        assert "needs work" in result

    def test_empty_when_all_pass(self):
        data = {"review": [{"title": "Fine", "verdict": "PASS", "issues": []}]}
        assert _format_validation_issues(data) == ""
