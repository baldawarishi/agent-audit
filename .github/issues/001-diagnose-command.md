# `diagnose` — Deep-analyze sessions to identify agent knowledge gaps and produce reviewable fix plans

## Problem

`analyze` operates at the global/cross-project level — it identifies systemic patterns across all projects. But when a specific session goes badly (agent hallucinates imports, reruns the wrong test command 4 times, rebuilds existing utilities from scratch), there's no way to:

1. Go deep into that session
2. Identify exactly what context, rules, or tools the agent was missing
3. Produce the specific artifacts that would prevent recurrence

This is **"harness engineering as a service"** — inspired by:
- [mitchellh.com/writing/my-ai-adoption-journey](https://mitchellh.com/writing/my-ai-adoption-journey) — systematic failure documentation in AGENTS.md, giving agents verification mechanisms so they fix their own mistakes, building programmed tools alongside documentation
- [lucumr.pocoo.org/2026/1/31/pi/](https://lucumr.pocoo.org/2026/1/31/pi/) — contextual specialization via custom skills, self-extending agent environments, minimal core that agents extend themselves

The core insight from both: when an agent fails, it's almost always because it was missing something — context about the codebase, a rule about how the project works, a tool that would let it verify its own work, or a skill that constrains its scope. Today you manually read transcripts, notice the failure, and add a line to CLAUDE.md. This command automates that loop.

## CLI

```bash
# Generate a plan (always the default, always the only behavior)
agent-audit diagnose --session <id> [--session <id2> ...]
agent-audit diagnose --project <name> [--since <date>]
# → Plan written to archive/plans/diagnose/20250115-143000/plan.md

# Apply a reviewed plan (--plan is REQUIRED, hard error without it)
agent-audit diagnose --apply --plan <path/to/plan.md>

# Dry-run
agent-audit diagnose --apply --plan <path/to/plan.md> --dry-run
```

**Hard rules:**
- `--apply` without `--plan`: hard error. No fallbacks. No convenience shortcuts.
- No `--auto` mode. The review step is mandatory.
- No idempotency. Applying the same plan twice creates duplicates — that's the user's problem.

## What it does

1. **Deep-reads session transcript(s)** — every tool call, every backtrack, every hallucinated reference, every retry loop. Not summary-level — exhaustive.
2. **Cross-references against actual codebase/environment state** (git history at session time, installed packages, actual module structure) to determine what the agent *should* have known.
3. **Classifies each failure** into what was missing:

| Classification | Output Artifact | Example |
|---|---|---|
| **Missing context** | CLAUDE.md section | Agent didn't know `core.caching.manager` exists, tried `utils.cache_manager` 3 times |
| **Missing rule** | CLAUDE.md line | Agent ran `pytest` directly 4 times; project requires `make test` |
| **Missing guardrail** | Hook config | Agent kept trying to modify generated files that shouldn't be hand-edited |
| **Missing tool** | Shell script | Agent had no way to verify DB migrations, so it guessed the schema |
| **Missing skill** | Skill definition | Agent repeated the same 15-step release workflow manually across 3 sessions |

These map directly to the existing `RecommendationCategory` enum in `recommendations.py` (`claude_md`, `skill`, `hook`, `workflow`, `prompt`).

## Plan format

Single markdown file. No separate JSON. The CLI parses it directly.

```markdown
# Diagnose Plan
# Generated: 2025-01-15T14:30:00
# Sessions: abc123, def789
# Command: agent-audit diagnose --session abc123 --session def789

---

## action_1 — Add module layout context to CLAUDE.md
- **Type:** context
- **Target:** CLAUDE.md
- **Confidence:** high
- **Evidence:** Agent tried to import `utils.cache_manager` in tool calls
  tc_0042, tc_0047, tc_0051 — failed each time. Actual module is
  `core.caching.manager`. ~2,400 tokens wasted.
- [x] Apply

`` `markdown
## Module Layout
- Caching: `core.caching.manager` (NOT utils.cache_manager)
- Database: `core.db.session` (NOT utils.db)
`` `

---

## action_2 — Add pre-command hook to warn on direct pytest
- **Type:** guardrail
- **Target:** .claude/settings.json
- **Confidence:** high
- **Evidence:** Agent ran `python -m pytest tests/` in tool calls tc_0023,
  tc_0031, tc_0038, tc_0044 — failed each time. Project uses `make test`.
- [ ] Apply

`` `json
{
  "hooks": {
    "pre_command": [
      { "match": "pytest", "warn": "Use 'make test' instead of pytest directly" }
    ]
  }
}
`` `

---

## action_3 — Document shared utilities to prevent reinvention
- **Type:** context
- **Target:** CLAUDE.md
- **Confidence:** medium
- **Evidence:** Agent wrote 45 lines of pagination logic in session def789.
  `shared/pagination.py` already has identical functionality. Agent never
  explored the `shared/` directory.
- [ ] Apply

`` `markdown
## Shared Utilities (check before writing new code)
- Pagination: `shared/pagination.py`
- Rate limiting: `shared/rate_limiter.py`
- Retry logic: `shared/retry.py`
`` `
```

**Parser contract:** `## action_<id>` headers, `- [x] Apply` / `- [ ] Apply` checkboxes, fenced code blocks for content. Action IDs are the contract between the markdown and the parser.

## Difference from `analyze`

| | `analyze` | `diagnose` |
|---|---|---|
| **Scope** | All sessions in a project | Specific session(s) |
| **Depth** | Metrics + patterns | Every tool call, every failure |
| **Output** | Markdown analysis + TOML recommendations | Reviewable plan with checkboxes |
| **Actionability** | Interpret and manually apply | Check boxes and `--apply --plan` |
| **Goal** | Cross-project pattern identification | Per-session root cause analysis |

## Implementation notes

- New Click command in `cli.py` following existing patterns (`@main.command()` + `@click.option()`)
- Reuse `parser.py` / `codex_parser.py` for transcript reading
- Reuse `database.py` for session lookup (`get_sessions_by_project`, tool_calls/tool_results tables)
- New prompt template `prompts/diagnose.md` for deep session analysis — focused on failure classification, not metrics (unlike `session_analysis.md`)
- Use `AnalyzerClaudeClient` for the diagnostic analysis call
- Plan output to `archive/plans/diagnose/YYYYMMDD-HHMMSS/plan.md` (follows existing `archive/analysis/run-YYYYMMDD-HHMMSS/` convention)
- Apply mode: reads the plan markdown, parses checked actions, writes target files
- The plan markdown parser should be strict: regex-match `## action_\d+`, `- \[x\] Apply`, and extract fenced code blocks

## Key modules to modify/extend

- `src/agent_audit/cli.py` — new `diagnose` command
- `src/agent_audit/prompts/` — new `diagnose.md` prompt template
- `src/agent_audit/analyzer/session_analyzer.py` — new `diagnose_sessions()` method (or new module)
- `src/agent_audit/analyzer/` — new plan parser and plan applier modules
- `tests/` — tests for plan parsing, plan application, and the CLI command
