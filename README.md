# claude-code-archive

Archive Claude Code transcripts in a structured, analyzable format.

Inspired by [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts).

## Installation

```bash
cd ~/Development/claude-code-archive
uv sync
```

## Usage

```bash
# Archive all sessions to SQLite (incremental - skips already archived)
claude-code-archive sync

# Archive specific project
claude-code-archive sync --project my-project

# Force re-archive existing sessions
claude-code-archive sync --force

# Render sessions as TOML transcripts
claude-code-archive render

# Render specific session to stdout
claude-code-archive render --session 2619c35b --stdout

# Render all sessions for a project
claude-code-archive render --project java

# Show archive statistics
claude-code-archive stats

# Configure archive/projects directories
claude-code-archive config --archive-dir /path/to/archive
claude-code-archive config --show
```

## Output

- `archive/sessions.db` - SQLite database (primary storage)
- `archive/transcripts/{project}/{date}-{session-id}.toml` - TOML transcripts (on-demand via `render`)

## Configuration

Settings are stored in `~/.config/claude-code-archive/config.json`:

```json
{
  "archive_dir": "/path/to/archive",
  "projects_dir": "~/.claude/projects"
}
```
