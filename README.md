# Agent Audit

Archive Claude Code and Codex CLI transcripts in a structured, analyzable format.

Inspired by [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts) and [prateek/codex-transcripts](https://github.com/prateek/codex-transcripts).

## Installation

```bash
cd agent-audit
uv sync
```

## Usage

```bash
# Archive all sessions to SQLite (append-only — safe to run repeatedly)
uv run agent-audit sync

# Sync only one source
uv run agent-audit sync --source claude-code
uv run agent-audit sync --source codex
uv run agent-audit sync --source pi
uv run agent-audit sync --source opencode
uv run agent-audit sync --source goose
uv run agent-audit sync --source gemini-cli

# Archive specific project
uv run agent-audit sync --project my-project

# Render sessions as TOML transcripts
uv run agent-audit render

# Render specific session to stdout
uv run agent-audit render --session 2619c35b --stdout

# Render all sessions for a project
uv run agent-audit render --project java

# Show archive statistics
uv run agent-audit stats

# Analyze sessions (per-project analysis with Claude)
uv run agent-audit analyze

# Synthesize cross-project patterns from analysis
uv run agent-audit analyze --synthesize archive/analysis/run-YYYYMMDD-HHMMSS

# Generate recommendation files from synthesis
uv run agent-audit analyze --recommend archive/analysis/run-YYYYMMDD-HHMMSS/global-synthesis.md

# Prepare debrief context for a session
uv run agent-audit debrief --session abc123

# List available deterministic transcript-mining queries
uv run agent-audit mine list

# Rank sessions by tool-call churn — sequences x (1 + failure ratio).
# Read-only over archive/sessions.db; no LLM. Prints the top N worst sessions.
uv run agent-audit mine churn --top 20

# Same, but ALSO persist the full result set (every scored session + meta)
# as JSON so you can diff churn before/after a fix. Plain `mine churn`
# writes nothing; the file is created only because --write-json is passed.
uv run agent-audit mine churn --write-json results/01_churn.json

# Configure archive/projects directories
uv run agent-audit config --archive-dir /path/to/archive
uv run agent-audit config --show
```

## Output

- `archive/sessions.db` - SQLite database (primary storage)
- `archive/transcripts/{project}/{date}-{session-id}.toml` - TOML transcripts
- `archive/analysis/run-{timestamp}/` - Analysis outputs:
  - `{project}.md` - Per-project session analysis
  - `global-synthesis.md` - Cross-project patterns with TOML recommendations
  - `validation-report.md` - Quality gate results
  - `recommendations/` - Generated recommendation files
- `archive/debriefs/{date}_{slug}/` - Debrief context bundles:
  - `session-guide.md` - Interactive session guide for Claude Code
  - `context/` - Gathered context (transcripts, git log, PRs, metrics)
  - `drafts/` - Draft output directory
- `results/{query}.json` - Saved mining-query results, written only when
  `mine ... --write-json PATH` is passed (regenerable artifact; git-ignored)

## Configuration

Settings are stored in `~/.config/agent-audit/config.json`:

```json
{
  "archive_dir": "/path/to/archive",
  "projects_dir": "~/.claude/projects"
}
```

Session sources:
- **Claude Code**: `~/.claude/projects/`
- **Codex CLI**: `~/.codex/sessions/` (or `$CODEX_HOME/sessions/`)
- **Pi**: `~/.pi/agent/sessions/`
- **OpenCode**: `~/.local/share/opencode/opencode.db`
- **Goose**: `~/.local/share/goose/sessions/`
- **Gemini CLI**: `~/.gemini/tmp/<project>/chats/`
