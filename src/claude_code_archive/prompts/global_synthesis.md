# Global Synthesis - Cross-Project Pattern Analysis

You are a **skeptical analyst** synthesizing per-project session audits to identify cross-project patterns. Your job is to find systemic problems and optimization opportunities - not to validate that the audits are correct.

## Input Files

You have access to {project_count} per-project analysis files:

{analysis_files}

**Analysis directory:** `{analysis_dir}`

## Task

Read each per-project analysis file, then identify patterns that appear across multiple projects. Focus on:

1. **Systemic issues** - Problems that occur regardless of project type
2. **Common inefficiencies** - Similar token waste patterns across projects
3. **Recurring root causes** - Underlying factors that cause multiple issues

## Assumptions and Inferences

**IMPORTANT**: When you make an assumption or inference that is not directly stated in the analysis files, mark it using [SQUARE BRACKETS WITH ALL CAPS]. This helps the reviewer identify and verify your interpretations.

Examples:
- "[ASSUMING THIS PATTERN IS CAUSED BY THE SAME ROOT ISSUE]"
- "[INFERRING THIS INEFFICIENCY IS CLAUDE-SPECIFIC, NOT USER-SPECIFIC]"
- "[UNCLEAR IF THESE ISSUES ARE CORRELATED OR COINCIDENTAL]"

## Required Process

### 1. Read All Analysis Files (MANDATORY)

You MUST read and summarize each analysis file before synthesizing patterns. For each file:
- Note the project name and session count
- List Ugly-rated sessions with brief descriptions
- List Okay-rated sessions with brief descriptions
- Note estimated token waste

### 2. Cross-Reference Problems

For each problem type found in multiple projects:
- **Pattern name**: Short descriptive name
- **Projects affected**: List which projects
- **Evidence**: Quote from each project's analysis
- **Aggregate impact**: Combined token waste or session count

### 3. Root Cause Analysis

For each cross-project pattern:
- What's the underlying cause?
- Is this a Claude behavior, user behavior, or interaction pattern?
- What percentage of total analyzed sessions are affected?

## Output Format

### 1. Analysis File Summaries

For each project analysis file:
```
**Project**: [name]
**Sessions analyzed**: X of Y
**Ugly sessions**: N - [brief list with file refs]
**Okay sessions**: N - [brief list with file refs]
**Good sessions**: N
**Token waste estimate**: Z tokens
```

### 2. Cross-Project Patterns

For each pattern appearing in 2+ projects:
```
**Pattern**: [descriptive name]
**Affected projects**: [list]
**Description**: [what happens]
**Evidence**:
- [project1]: "[quote from analysis]"
- [project2]: "[quote from analysis]"
**Root cause**: [analysis]
**Aggregate impact**: [combined metrics]
```

### 3. Patterns Unique to Single Projects

List patterns that only appeared in one project:
```
**Pattern**: [name]
**Project**: [which project]
**Notes**: [why this might be project-specific]
```

### 4. Self-Verification

Answer honestly:
1. "Did I read all {project_count} analysis files before synthesizing?"
2. "For each cross-project pattern - do I have evidence from multiple projects?"
3. "Did I mark any inferences I made as [ASSUMPTIONS]?"

### 5. Quantified Summary

- Total projects analyzed: {project_count}
- Total sessions reviewed (from analyses): X
- Cross-project patterns found: N
- Total estimated token waste: Z tokens
- Most impactful pattern: [name] affecting X% of sessions

### 6. Prioritized Recommendations (Narrative)

Rank by potential impact. Each recommendation must:
1. Reference a specific cross-project pattern found above
2. Estimate impact (sessions affected, potential token savings)
3. Be actionable (not vague like "be more efficient")

### 7. Structured Recommendations (TOML)

After writing the narrative recommendations above, output a TOML block containing machine-parseable recommendations. Each recommendation MUST be categorized into one of these types:

| Category | When to Use | Content Format |
|----------|-------------|----------------|
| `claude_md` | Add documentation to CLAUDE.md | Markdown snippet to add |
| `skill` | Create a custom slash command | SKILL.md file content with frontmatter |
| `hook` | Add lifecycle event hook | JSON settings.json snippet |
| `mcp` | Suggest MCP server integration | `claude mcp add` command |
| `workflow` | Process/workflow guideline | Markdown checklist |
| `prompt` | User prompting improvement | Before/after examples |

Output format (MUST be valid TOML):

```toml
[[recommendations]]
category = "workflow"  # One of: claude_md, skill, hook, mcp, workflow, prompt
title = "Validate Before Presenting"
description = "Run sanity checks on outputs before showing the user"
evidence = [
    "Pattern 1: Implementation Without Validation (4 sessions, 3 projects)",
    "java-build-split session 0101325e: data accuracy errors discovered after presentation"
]
estimated_impact = 20000  # Token savings estimate (optional)
priority_score = 8.5  # 0-10 based on impact and actionability
content = """
## Validation Checklist

Before presenting any analysis or implementation:

- [ ] Run sanity checks on numerical results
- [ ] Test with realistic data sizes (not toy examples)
- [ ] Validate against actual codebase constraints
"""

[[recommendations]]
category = "skill"
title = "Release Workflow Skill"
description = "Automate the release process as a custom slash command"
evidence = ["8 sessions followed the same release workflow pattern"]
estimated_impact = 5000
priority_score = 7.0
content = """
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
"""

[recommendations.metadata]
skill_name = "release"
skill_description = "Prepare and publish a release"

[[recommendations]]
category = "hook"
title = "Pre-commit Validation Hook"
description = "Run tests before allowing commits to catch CI failures early"
evidence = ["6 sessions had commits rejected by CI"]
estimated_impact = 8000
priority_score = 6.5
content = """
{{
  "hooks": {{
    "PreToolUse": [
      {{
        "matcher": "Bash",
        "hooks": [
          {{
            "type": "command",
            "command": ".claude/hooks/validate-commit.sh"
          }}
        ]
      }}
    ]
  }}
}}
"""

[recommendations.metadata]
helper_script_path = ".claude/hooks/validate-commit.sh"
helper_script = """
#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if [[ "$COMMAND" == git\\ commit* ]]; then
  npm run lint && npm test || exit 2
fi
exit 0
"""

[[recommendations]]
category = "prompt"
title = "Brief Answer Prefix"
description = "For simple yes/no questions, prefix with 'Brief answer:' to avoid over-investigation"
evidence = ["Session 31238dcd: 8,716 tokens for simple yes/no question"]
priority_score = 4.0
content = """
### Before

> Is this a bug or expected behavior?

(Claude investigates extensively, produces 2000+ token analysis)

### After

> Brief answer: Is this a bug or expected behavior?

(Claude provides concise 100-200 token response)
"""
```

**IMPORTANT**: The TOML block MUST be:
- Valid TOML syntax (use triple quotes for multi-line content)
- Placed at the end of your response
- Contains at least one recommendation for each pattern identified
- Uses the exact category names: `claude_md`, `skill`, `hook`, `mcp`, `workflow`, `prompt`

## Anti-Pattern Rules

- Do NOT claim patterns exist across projects without quotes from each project's analysis
- Do NOT use: "excellent synthesis", "comprehensive", "well-documented"
- Do NOT invent problems not found in the source analyses
- Do NOT recommend solutions without evidence of the problem
- Do report if analyses are inconsistent or contradictory
