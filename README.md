# claude-code-audit

Archive Claude Code transcripts in a structured, analyzable format.

Inspired by [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts).

## Installation

```bash
cd claude-code-audit
uv sync
```

## Usage

```bash
# Archive all sessions to SQLite (incremental - skips already archived)
uv run claude-code-audit sync

# Archive specific project
uv run claude-code-audit sync --project my-project

# Force re-archive existing sessions
uv run claude-code-audit sync --force

# Render sessions as TOML transcripts
uv run claude-code-audit render

# Render specific session to stdout
uv run claude-code-audit render --session 2619c35b --stdout

# Render all sessions for a project
uv run claude-code-audit render --project java

# Show archive statistics
uv run claude-code-audit stats

# Analyze sessions (per-project analysis with Claude)
uv run claude-code-audit analyze

# Synthesize cross-project patterns from analysis
uv run claude-code-audit analyze --synthesize archive/analysis/run-YYYYMMDD-HHMMSS

# Generate recommendation files from synthesis
uv run claude-code-audit analyze --recommend archive/analysis/run-YYYYMMDD-HHMMSS/global-synthesis.md

# Configure archive/projects directories
uv run claude-code-audit config --archive-dir /path/to/archive
uv run claude-code-audit config --show
```

## Output

- `archive/sessions.db` - SQLite database (primary storage)
- `archive/transcripts/{project}/{date}-{session-id}.toml` - TOML transcripts
- `archive/analysis/run-{timestamp}/` - Analysis outputs:
  - `{project}.md` - Per-project session analysis
  - `global-synthesis.md` - Cross-project patterns with TOML recommendations
  - `validation-report.md` - Quality gate results
  - `recommendations/` - Generated recommendation files

## Configuration

Settings are stored in `~/.config/claude-code-audit/config.json`:

```json
{
  "archive_dir": "/path/to/archive",
  "projects_dir": "~/.claude/projects"
}
```
