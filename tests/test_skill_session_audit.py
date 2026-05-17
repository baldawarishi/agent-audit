"""Smoke + regression tests for the session-transcript-audit Skill.

Step 9 (transcript-mining plan): the Skill is an ADDED artifact — it must be
discoverable by local Claude Code (project-scope `.claude/skills/`) and capture
the load-bearing methodology, while the `analyze` orchestrator stays untouched
this increment (no skill rerouting).
"""

import inspect
import re
from pathlib import Path

from agent_audit.analyzer.claude_client import AnalyzerClaudeClient

REPO_ROOT = Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "session-transcript-audit"
SKILL_MD = SKILL_DIR / "SKILL.md"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Hand-parse `---` YAML frontmatter (no yaml dep — single-line k: v)."""
    assert text.startswith("---\n"), "SKILL.md must open with a --- frontmatter"
    _, fm, body = text.split("---\n", 2)
    meta: dict[str, str] = {}
    for line in fm.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body


class TestSkillDiscoverability:
    """The Skill exists where local Claude Code auto-discovers project skills."""

    def test_skill_md_exists_at_project_scope(self):
        assert SKILL_MD.is_file(), f"missing {SKILL_MD}"

    def test_name_is_semantic_not_ordinal(self):
        meta, _ = _split_frontmatter(SKILL_MD.read_text())
        name = meta.get("name", "")
        # Lowercase letters/digits/hyphens, <=64 (Claude Code frontmatter rule).
        assert re.fullmatch(r"[a-z0-9-]{1,64}", name), f"bad skill name: {name!r}"
        # Invariant: semantic name, NEVER an ordinal `NN_...` like the scripts.
        assert not re.match(r"^\d", name), f"name must not be ordinal: {name!r}"
        assert name == SKILL_DIR.name, "frontmatter name must match the directory"

    def test_description_is_present_and_within_budget(self):
        meta, _ = _split_frontmatter(SKILL_MD.read_text())
        desc = meta.get("description", "")
        assert desc, "description is required for model discovery"
        # Combined description budget is 1,536 chars in the skill listing.
        assert len(desc) <= 1536
        low = desc.lower()
        assert "audit" in low and ("churn" in low or "wasted" in low)


class TestMethodologyCaptured:
    """The body carries the load-bearing methodology (workflow-shaped)."""

    def test_body_has_loadbearing_sections(self):
        _, body = _split_frontmatter(SKILL_MD.read_text())
        # Skeptical-auditor framing.
        assert "skeptical auditor" in body.lower()
        # Chain-of-Verification protocol + its three terminal markers.
        assert "Chain-of-Verification" in body
        for marker in ("[VERIFIED", "[UNVERIFIED", "[CONTRADICTED"):
            assert marker in body, f"missing CoVe marker {marker}"
        # File + Quote + Metric evidence triple.
        for term in ("File", "Quote", "Metric"):
            assert term in body, f"missing evidence-triple term {term}"
        # Addy-style workflow: steps with exit criteria + anti-rationalization.
        assert "Exit criterion" in body
        assert "Anti-rationalization" in body
        # User-steered recency sampling frame (2026-05-17). Normalize first:
        # markdown bold markers and line wraps split these phrases.
        flat = re.sub(r"\s+", " ", body.replace("*", ""))
        assert "last 30 days" in flat
        assert "10 most recent sessions" in flat

    def test_references_canonical_prompt_not_duplicate(self):
        """Must point at the canonical contract so the two cannot drift."""
        _, body = _split_frontmatter(SKILL_MD.read_text())
        assert "prompts/session_analysis.md" in body

    def test_names_all_five_grounding_stages(self):
        _, body = _split_frontmatter(SKILL_MD.read_text())
        for stage in ("01_churn", "02_failure_classification",
                      "03_bash_subcommands", "04_tool_sequences",
                      "05_bash_sequences"):
            assert stage in body, f"missing grounding stage {stage}"


class TestOrchestratorUntouched:
    """Step 9 ADDS an artifact; it must not reroute the analyze path."""

    def test_no_src_code_references_the_skill(self):
        """No src/*.py wires THIS skill in — proves zero behavioral change.

        Match only the specific skill name. A bare ``.claude/skills`` substring
        false-positives on the pre-existing, unrelated skill-recommendation
        generator (``recommendations.py`` emits ``.claude/skills/{name}`` as
        advice text); that is not orchestrator rerouting.
        """
        offenders = [
            str(py)
            for py in (REPO_ROOT / "src").rglob("*.py")
            if "session-transcript-audit" in py.read_text()
        ]
        assert not offenders, f"orchestrator references skill: {offenders}"

    def test_claude_client_still_defaults_options_none(self):
        """The SDK is still constructed plain — no setting_sources/Skill wiring."""
        sig = inspect.signature(AnalyzerClaudeClient.__init__)
        assert sig.parameters["options"].default is None
