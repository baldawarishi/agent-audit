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

### 6. Prioritized Recommendations

Rank by potential impact. Each recommendation must:
1. Reference a specific cross-project pattern found above
2. Estimate impact (sessions affected, potential token savings)
3. Be actionable (not vague like "be more efficient")

## Anti-Pattern Rules

- Do NOT claim patterns exist across projects without quotes from each project's analysis
- Do NOT use: "excellent synthesis", "comprehensive", "well-documented"
- Do NOT invent problems not found in the source analyses
- Do NOT recommend solutions without evidence of the problem
- Do report if analyses are inconsistent or contradictory
