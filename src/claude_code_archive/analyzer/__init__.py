"""Analyzer module for session analysis using Claude."""

from .session_analyzer import (
    SessionAnalyzer,
    build_global_synthesis_prompt,
    build_session_analysis_prompt,
    load_global_synthesis_template,
    load_session_analysis_template,
)

# Lazy import for Claude client (requires claude_agent_sdk)


def __getattr__(name: str):
    """Lazy import for optional dependencies."""
    if name == "AnalyzerClaudeClient":
        from . import claude_client

        return claude_client.AnalyzerClaudeClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Session analysis
    "SessionAnalyzer",
    "build_session_analysis_prompt",
    "load_session_analysis_template",
    "build_global_synthesis_prompt",
    "load_global_synthesis_template",
    # Claude client (lazy loaded)
    "AnalyzerClaudeClient",
]
