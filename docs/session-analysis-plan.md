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

Based on sqlite data, provide Claude with for what's good vs okay vs ugly heuristics:

| Quality | Criteria (approximate) |
|---------|------------------------|
| **Good** | Few turns , low tokens , task completed |
| **Okay** | Medium turns , medium tokens, multiple repeativate work  |
| **Ugly** | Many turns, high tokens, lots of back-and-forth, sessions that start from sctracth or undo all previous work |

Some notes from past analysis of actual data:
- Average turns per session varies by project
- Average tokens varies widely
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
- Future Phase 3c of /Users/rishibaldawa/Development/claude-code-archive/docs/analyzer-design.md

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
1. `java-tools-ai-tools-repo-drift` - 206 sessions, high volume with patterns
2. `claude-archive` - 13 sessions, this project
3. `java-build-split` - 26 sessions, work project variety

This is hardcoded for now; will expand to all projects later by removing the hardcoding.

## Continuation Prompt

Paste this at the start of each new session:

```
Continue work on session analysis. Read docs/session-analysis-plan.md for context.

Current phase: [FILL IN]
Last completed: [FILL IN]
Next step: [FILL IN]

Continually ask me questions if any design, implementaion, or requirements are unclear before proceeding.

Approach: push often and check CI, use todos to manage context window usage, don't trust past interpretation and always read the code directly. Refactor as appropriate. Always TDD.
```

## Experiment Workflow (ONE AT A TIME)

**Rule:** Only one experiment active at a time. Complete verification before starting next.

### Per-Experiment Steps

1. **Start:** Update experiment status to `IN PROGRESS` in this file
2. **Implement:** Make code changes, commit often
3. **Run:** Execute the experiment
4. **Output:** Note output file paths in experiment log
5. **Verify:** User manually reviews output, provides feedback
6. **Update Plan:** Record learnings, update status to `DONE` or `FAILED`
7. **Next:** Only then move to next experiment

### Manual Verification Checklist

After each experiment, user reviews:
- [ ] Output files exist at expected paths
- [ ] Content is readable and makes sense
- [ ] Insights are pragmatic (not over-the-top)
- [ ] File paths in output allow digging deeper
- [ ] Any obvious issues to fix before next experiment?

---

## Experiment Log

### Experiment 1: Implement Phase 1 Runner
**Goal:** Create `analyze` command that runs per-project analysis
**Status:** DONE
**Output:** `archive/analysis/run-20260120-034634/` - 3 project files
**Verify:** User reviewed - insights are useful, found real inefficiencies

**Implementation Notes:**
- Added `Database.get_project_metrics()` for session/turn/token counts
- Created `analyzer/session_analyzer.py` with `SessionAnalyzer` class
- Modified `analyze` command - new session analysis is default, `--legacy` for old
- Prompt template at `prompts/session_analysis.md`
- Projects: java-tools-ai-tools-repo-drift (206), claude-archive (13), java-build-split (26)

**Key Findings:**
- 16% warmup session overhead identified
- Batch processing inefficiencies (25 turns → could be 1)
- Clear PR workflow patterns emerged

### Experiment 2: Global Synthesis
**Goal:** Run Phase 2 on Experiment 1 outputs
**Status:** NOT STARTED
**Output:** `archive/analysis/run-20260120-034634/global-synthesis.md`
**Verify:** User confirms cross-project patterns are meaningful

### Experiment 3: Interactive Exploration
**Goal:** Test asking questions against analysis files
**Status:** BLOCKED (needs Exp 2)
**Verify:** Claude can answer questions and dig into TOML when needed

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

## Implementation Summary

**Modify:** `cli.py` (analyze command), keep `database.py` for metrics
**Remove:** `analyzer/classifier.py`, `analyzer/claude_client.py` (use subprocess instead)
**Simplify:** `analyzer/patterns.py`, `analyzer/renderer.py`

**Flow:**
1. Query SQLite for project metrics (turns, tokens, tool counts)
2. Write context file with metrics + instructions + TOML folder path
3. Invoke `claude --print -p {prompt}` via subprocess
4. Show progress: "Analyzing project 1/3: repo-drift..."
5. Output to `archive/analysis/run-{timestamp}/{project}.md`

**Prompt template:** See `src/claude_code_archive/prompts/session_analysis.md` (to be created)

## Related Files

- `docs/analyzer-issues.md` - Problems with current analyzer
- `docs/analyzer-research.md` - Academic research on pattern mining
- `docs/analyzer-design.md` - Original analyzer design (Phase 3c reference)
- `src/claude_code_archive/analyzer/` - Current analyzer code (to be replaced/simplified)
