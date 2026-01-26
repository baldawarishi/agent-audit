# Recommendations Design Document

Reference document for generating actionable recommendations from session analysis.
Created: 2026-01-25

## Overview

The analyzer produces two types of analysis output:
1. **Per-project analysis** - Critical review of sessions for a specific project
2. **Global synthesis** - Cross-project patterns and aggregate findings

This document describes how to translate those findings into actionable recommendations that can be applied to improve Claude Code workflows.

## Analysis Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     analyze command                              │
├─────────────────────────────────────────────────────────────────┤
│  Phase 1: Per-Project Analysis                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ For each project:                                           ││
│  │ - Read session transcripts from TOML files                  ││
│  │ - Compare metrics against global baselines                  ││
│  │ - Identify Ugly/Okay/Good sessions with evidence            ││
│  │ - Quantify token waste and root causes                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                          ▼                                       │
│          archive/analysis/run-{ts}/{project}.md                  │
├─────────────────────────────────────────────────────────────────┤
│  Phase 2: Global Synthesis (--synthesize)                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ - Read all per-project analysis files                       ││
│  │ - Identify cross-project patterns                           ││
│  │ - Quantify aggregate impact                                 ││
│  │ - Generate prioritized recommendations                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                          ▼                                       │
│          archive/analysis/run-{ts}/global-synthesis.md           │
├─────────────────────────────────────────────────────────────────┤
│  Phase 3: Actionable Recommendations (--recommend)               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ - Parse recommendations from global synthesis               ││
│  │ - Generate CLAUDE.md additions                              ││
│  │ - Suggest workflow improvements                             ││
│  │ - Track recommendation application                          ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Current State

All three phases are implemented:
- `claude-code-archive analyze` - runs per-project analysis
- `claude-code-archive analyze --synthesize <dir>` - runs global synthesis with structured TOML output
- `claude-code-archive analyze --recommend <file>` - generates actionable outputs from synthesis

## Recommendation Categories

Based on the global synthesis findings, recommendations fall into these categories:

### 1. CLAUDE.md Additions

Documentation that helps Claude understand project context upfront.

**When to suggest:**
- Same file read 10+ times across sessions
- Same questions asked repeatedly
- Project-specific patterns that require explanation

**Example output:**
```markdown
## Recommended CLAUDE.md Addition

Based on analysis of 20 sessions, add to your project's CLAUDE.md:

### Git Workflow
This project uses Graphite for stacked PRs:
- Use `gt create` instead of `git checkout -b`
- Use `gt submit` instead of `gh pr create`
- Always check stack state with `gt log --stack` before operations
```

### 2. Workflow Guidelines

Process improvements based on identified inefficiencies.

**When to suggest:**
- Pattern of backtracking or corrections
- Validation failures discovered late
- Requirements misunderstandings

**Example output:**
```markdown
## Workflow Recommendation: Validate Before Present

Pattern found: 19% of sessions showed late discovery of errors

Suggested process:
1. Before presenting implementation, run basic correctness tests
2. For parsers: test with 5-10 sample inputs
3. For config changes: verify with dry-run
4. For multi-step workflows: create checklist upfront
```

### 3. Skills

Custom slash commands that automate repetitive multi-step workflows. Skills are stored in `.claude/skills/<name>/SKILL.md` and can be invoked with `/name`.

**When to suggest:**
- Same sequence of tool calls repeated across 5+ sessions
- Multi-step workflow with consistent pattern (e.g., lint → test → commit)
- Project-specific commands that Claude needs to learn

**Skill frontmatter options:**
- `name` - Slash command name (defaults to directory name)
- `description` - When Claude should use this skill
- `disable-model-invocation: true` - Only user can invoke (for side effects)
- `allowed-tools` - Tools Claude can use without permission
- `context: fork` - Run in isolated subagent
- `agent` - Which subagent type (Explore, Plan, etc.)

**Example output:**
```markdown
## Recommended Skill: /release

Pattern found: 8 sessions followed the same release workflow

Create `.claude/skills/release/SKILL.md`:
```yaml
---
name: release
description: Prepare and publish a release
disable-model-invocation: true
allowed-tools: Bash(npm:*), Bash(git:*), Bash(gh:*)
---

# Release Workflow

1. Run tests: `npm test`
2. Bump version: `npm version $ARGUMENTS`
3. Build: `npm run build`
4. Create tag and push: `git push --follow-tags`
5. Create GitHub release: `gh release create`
```
```

### 4. Hooks

Shell commands that run at specific lifecycle events. Configured in `.claude/settings.json` or `.claude/settings.local.json`.

**When to suggest:**
- Validation errors caught late that could be caught early
- Consistent post-action steps (e.g., always format after edit)
- Policy enforcement (e.g., never commit to main)

**Hook events:**
- `PreToolUse` - Before a tool executes (can block/allow/modify)
- `PostToolUse` - After a tool succeeds
- `UserPromptSubmit` - When user submits a prompt
- `Stop` - When Claude finishes responding
- `SessionStart` - When session begins

**Hook matchers (for tool events):**
- Exact match: `Write`, `Bash`
- Regex: `Edit|Write`, `Bash`
- All tools: `*`

**Example output:**
```markdown
## Recommended Hook: Pre-commit Validation

Pattern found: 6 sessions had commits rejected by CI that could have been caught locally

Add to `.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/validate-commit.sh"
          }
        ]
      }
    ]
  }
}
```

Where `validate-commit.sh` checks if it's a git commit and runs tests:
```bash
#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if [[ "$COMMAND" == git\ commit* ]]; then
  npm run lint && npm test || exit 2
fi
exit 0
```
```

**Example: Auto-format after file edits:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "prettier --write \"$CLAUDE_PROJECT_DIR\"/**/*.{js,ts,tsx}"
          }
        ]
      }
    ]
  }
}
```

### 5. Prompt Improvements

Suggestions for how users can prompt more effectively.

**When to suggest:**
- Ambiguous requirements led to rework
- User had to provide multiple corrections
- Simple questions received over-engineered answers

**Example output:**
```markdown
## Prompt Improvement Suggestion

Pattern: Over-investigation of simple questions (4 sessions)

Suggestion: For yes/no questions, prefix with "Brief answer:"
- Before: "Is this a bug or expected?"
- After: "Brief answer: Is this a bug or expected?"
```

### 6. MCP Server Suggestions

External tool integrations that could improve workflows.

**When to suggest:**
- Repeated manual lookups that an MCP could automate
- Integration with external services (Jira, Linear, Sentry, etc.)
- Database or API access patterns

**Example output:**
```markdown
## Recommended MCP: Linear Integration

Pattern found: 5 sessions involved manually copying Linear ticket details

Install the Linear MCP server:
```bash
claude mcp add linear
```

Then Claude can directly:
- Fetch ticket details: "What's the status of LIN-123?"
- Update tickets: "Mark LIN-123 as in progress"
- Create tickets: "Create a bug ticket for the auth issue"
```

## Recommendation Priority Scoring

Recommendations are ranked by:

1. **Sessions affected** - Number of sessions where pattern appeared
2. **Token waste** - Estimated tokens that could be saved
3. **Projects affected** - Cross-project patterns rank higher
4. **Actionability** - How easy is the recommendation to implement

```
Priority Score = (sessions_affected * 2) +
                 (token_waste / 10000) +
                 (projects_affected * 3) +
                 actionability_score
```

Where actionability_score:
- CLAUDE.md addition: 10 (copy-paste)
- Skill creation: 8 (create file, immediate benefit)
- Hook setup: 7 (create file + script, automates enforcement)
- MCP server: 6 (install + configure)
- Workflow guideline: 5 (process change)
- Prompt improvement: 3 (requires user behavior change)

## Phase 3 Implementation (Complete)

### 3.1 Parse Synthesis Output

The global synthesis prompt now outputs structured TOML recommendations. The parser extracts them:

```python
@dataclass
class Recommendation:
    category: RecommendationCategory  # enum: claude_md, skill, hook, mcp, workflow, prompt
    title: str
    description: str
    evidence: list[str]  # Pattern references and session quotes
    estimated_impact: Optional[int]  # Token savings estimate
    priority_score: float  # 0-10 based on impact and actionability
    content: str  # The actual content to generate
    metadata: dict  # Category-specific metadata (skill_name, helper_script, etc.)
```

Usage: `claude-code-archive analyze --recommend <path/to/global-synthesis.md>`

### 3.2 Generate Actionable Output

For each recommendation category, generate appropriate output:

**CLAUDE.md recommendations:**
- Output as markdown snippet ready to copy-paste
- Include source evidence for verification

**Skill recommendations:**
- Generate complete `.claude/skills/<name>/SKILL.md` file
- Include frontmatter with appropriate options
- Reference supporting files if needed

**Hook recommendations:**
- Generate `.claude/settings.json` additions
- Include any helper scripts needed
- Document hook behavior and exit codes

**MCP server recommendations:**
- Provide `claude mcp add` command
- Document required environment variables
- Show example usage

**Workflow recommendations:**
- Output as checklist format
- Reference specific session examples

**Prompt recommendations:**
- Output as before/after examples
- Keep suggestions concise

### 3.3 Track Application (Future)

Track which recommendations have been applied:
- Store in `archive/recommendations/applied.json`
- Re-analyze to measure impact
- Update priority based on results

## File Locations

- Analysis output: `archive/analysis/run-{timestamp}/`
- Per-project files: `archive/analysis/run-{timestamp}/{project}.md`
- Global synthesis: `archive/analysis/run-{timestamp}/global-synthesis.md`
- Prompts: `src/claude_code_archive/prompts/`
  - `session_analysis.md` - Per-project analysis prompt
  - `global_synthesis.md` - Cross-project synthesis prompt

## Prompt Design Principles

Both analysis prompts follow anti-sycophancy research:

1. **Critical framing** - "skeptical auditor" not "helpful assistant"
2. **Evidence requirements** - Must provide quotes for claims
3. **Assumption marking** - Use [BRACKETED ASSUMPTIONS] for inferences
4. **Self-verification** - Explicit questions to check own work
5. **Anti-pattern rules** - Explicitly forbid flattering language

## Example Findings

From the Experiment 2 global synthesis:

| Pattern | Sessions | Projects | Token Waste |
|---------|----------|----------|-------------|
| Implementation without validation | 4 | 3 | ~20,000 |
| Requirements misunderstanding | 4 | 3 | ~25,000 |
| Excessive thinking verbosity | 4 | 3 | ~30,000 |
| Test-after-show | 4 | 2 | ~15,000 |

Total recoverable waste: ~128,000 tokens across 6 recommendations.

## Related Files

- `docs/session-analysis-plan.md` - Experiment workflow and status
- `docs/analyzer-research.md` - Academic research on pattern mining (archived)
- `src/claude_code_archive/analyzer/session_analyzer.py` - Implementation
