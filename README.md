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
# Archive all sessions to SQLite (syncs both Claude Code and Codex by default)
uv run agent-audit sync

# Sync only one source
uv run agent-audit sync --source claude-code
uv run agent-audit sync --source codex

# Archive specific project
uv run agent-audit sync --project my-project

# Force re-archive existing sessions
uv run agent-audit sync --force

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
