# Session Analysis Plan

Created: 2026-01-19
Status: Ready to implement

## Overview

A human-in-the-loop approach to understanding session patterns before automating recommendations. Replaces the LLM classifier with structured analysis that Claude agents can build on.

## Goals

1. Understand what patterns actually matter (vs noise)
2. Incremental improvements, not groundbreaking changes
3. Each experiment ends with manual verification
4. Analysis files enable future interactive exploration

## Architecture

```
Phase 1: Per-project analysis
├── For each archive project folder:
│   ├── Query sqlite for session metrics (good/bad/ugly definitions)
│   ├── Point Claude at TOML files in archive/transcripts/{project}/
│   ├── Claude randomly picks sessions, reads until patterns emerge
│   └── Output: archive/analysis/run-{timestamp}/{project}.md

Phase 2: Global synthesis
├── Point Claude at archive/analysis/run-{timestamp}/*.md
├── Find cross-project patterns worth optimizing
└── Output: archive/analysis/run-{timestamp}/global-synthesis.md

Phase 3: Interactive exploration (free)
└── User can spin up Claude, point at analysis folder
    └── File paths in analysis let Claude dig into raw TOML when needed
```

## Session Quality Definitions

Based on sqlite data, provide Claude with these heuristics:

| Quality | Criteria (approximate) |
|---------|------------------------|
| **Good** | Few turns (<5), low tokens (<20k), task completed |
| **Okay** | Medium turns (5-15), medium tokens (20k-50k) |
| **Ugly** | Many turns (>15), high tokens (>50k), lots of back-and-forth |

These come from actual data:
- Average turns per session varies by project (5-18)
- Average tokens varies widely (28k-55k)
- High token sessions often indicate struggling or complex tasks

## Output Format Requirements

Each project analysis file must include:

1. **Session summaries** with file paths to source TOML
2. **Metrics observed** (turns, tokens, duration, tools used)
3. **Patterns worth noting** (interesting observations)
4. **Potential optimizations** (things that could help)

Format should support:
- Human review (readable markdown)
- Claude analysis (structured enough to parse)
- Future Phase 3c (skill generation, CLAUDE.md updates)

## Implementation Details

### File Locations

- Input: `archive/transcripts/{project}/*.toml`
- Metrics: `archive/sessions.db` (sqlite)
- Output: `archive/analysis/run-{timestamp}/{project}.md`
- Global: `archive/analysis/run-{timestamp}/global-synthesis.md`

### Projects in Archive

```
Total: 38 project folders
Top by session count:
- java-tools-ai-tools-repo-drift (206 sessions)
- quamina-go-rs-quamina-rs (121 sessions)
- personal-rishibaldawa-banking-ai-onboarding (31 sessions)
- java-build-split (26 sessions)
- repo-drift (21 sessions)
```

### Hardcoded Starting Projects

For initial validation, run on 3 projects in parallel:
1. `repo-drift` - 21 sessions, known project
2. `claude-archive` - 13 sessions, this project
3. `cap-finreq` - 20 sessions, work project variety

This is hardcoded for now; will expand to all projects later.

## Continuation Prompt

Paste this at the start of each new session:

```
Continue work on session analysis. Read docs/session-analysis-plan.md for context.

Current phase: [FILL IN]
Last completed: [FILL IN]
Next step: [FILL IN]

Ask me questions if anything is unclear before proceeding.
```

## Experiment Log

### Experiment 1: Implement Phase 1 Runner
**Goal:** Create script that runs per-project analysis for 3 projects
**Status:** IN PROGRESS
**Projects:** repo-drift, claude-archive, cap-finreq
**Verification:** Manual review of output files in `archive/analysis/run-{timestamp}/`

### Experiment 2: Global Synthesis
**Goal:** Run Phase 2 on Experiment 1 outputs
**Status:** Blocked on Experiment 1
**Verification:** Manual review of global-synthesis.md

### Experiment 3: Interactive Exploration
**Goal:** Test asking questions against analysis files
**Status:** Blocked on Experiment 2
**Verification:** Can Claude answer questions and dig into TOML when needed?

---

## TOML Structure (Resolved)

Each session TOML file contains:

```toml
[session]
id = "uuid"
slug = "human-readable-slug"
project = "project-name"
cwd = "/path/to/working/dir"
git_branch = "branch-name"
started_at = "ISO timestamp"
ended_at = "ISO timestamp"
model = "claude-opus-4-5-20251101"
claude_version = "2.1.1"
input_tokens = 2775
output_tokens = 13593
cache_read_tokens = 4581111

[[turns]]
number = 1
timestamp = "ISO timestamp"

[turns.user]
content = "user message"

[turns.assistant]
content = "assistant response"
thinking = "thinking content (if available)"
```

## Design Decisions (Resolved)

1. **Analysis depth:** Detailed - step-by-step what was tried, what worked/didn't
2. **Pattern threshold:** Let Claude decide, but focus on pragmatic optimizations (not over-the-top)
3. **Include thinking blocks:** Yes - may reveal reasoning patterns
4. **Data sources:**
   - SQLite for exact stats/numbers (turn counts, token usage, tool call counts)
   - TOML for browsing/reading session content
   - Can extend TOML export if more fields would help Claude form opinions

## Implementation Details

### Current Code to Modify

**Keep:**
- `cli.py` - Modify `analyze` command
- `database.py` - Use for metrics queries

**Replace/Simplify:**
- `analyzer/classifier.py` - Remove LLM classifier (not working for us)
- `analyzer/claude_client.py` - Remove (will use subprocess instead)
- `analyzer/patterns.py` - Keep for metrics extraction, simplify
- `analyzer/renderer.py` - Simplify or remove

### New Approach

```python
# In cli.py analyze command:

1. Query SQLite for project metrics:
   - Sessions per project
   - Avg turns, tokens per session
   - Tool call counts

2. For each project (3 hardcoded for now):
   a. Create context file with:
      - Project metrics from SQLite
      - Good/bad/ugly session definitions
      - Instructions for Claude
      - Path to TOML files

   b. Invoke Claude CLI:
      subprocess.run([
          "claude", "--print",
          "-p", prompt_with_context_file_path,
          "--output-format", "text"
      ])

   c. Capture output to:
      archive/analysis/run-{timestamp}/{project}.md

3. Show progress:
   - "Analyzing project 1/3: repo-drift..."
   - "Analyzing project 2/3: claude-archive..."
   - etc.
```

### Hardcoded Projects (for testing)

```python
TEST_PROJECTS = [
    "repo-drift",      # 21 sessions, known project
    "claude-archive",  # 13 sessions, this project
    "cap-finreq",      # 20 sessions, work variety
]
```

### Claude Prompt Template

```markdown
# Session Analysis for {project}

## Your Task
Read sessions from `{toml_folder}` to understand usage patterns.
Pick sessions randomly. Keep reading until you see patterns worth optimizing.
Focus on pragmatic improvements, not over-the-top suggestions.

## Project Metrics (from database)
- Total sessions: {session_count}
- Avg turns per session: {avg_turns}
- Avg tokens per session: {avg_tokens}

## Session Quality Definitions
- **Good**: <5 turns, <20k tokens - quick, efficient
- **Okay**: 5-15 turns, 20-50k tokens - normal work
- **Ugly**: >15 turns, >50k tokens - struggling or complex

## Output Format
Write detailed analysis to `{output_file}`:
1. Sessions reviewed (with file paths)
2. Patterns observed
3. Potential optimizations
4. Things that worked well
```

## Related Files

- `docs/analyzer-issues.md` - Problems with current analyzer
- `docs/analyzer-research.md` - Academic research on pattern mining
- `docs/analyzer-design.md` - Original analyzer design (Phase 3c reference)
- `src/claude_code_archive/analyzer/` - Current analyzer code (to be replaced/simplified)
