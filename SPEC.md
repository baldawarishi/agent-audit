# claude-code-archive Specification

Archive Claude Code transcripts from `~/.claude/projects/` into SQLite with TOML export.

**Reference**: [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts) - HTML renderer, source at `src/claude_code_transcripts/__init__.py`

## Data Flow

```
~/.claude/projects/           sync           archive/sessions.db
├── {project-dir}/       ─────────────►     (SQLite)
│   ├── {uuid}.jsonl                              │
│   └── agent-{hash}.jsonl                        │
                                                  │
                              render              ▼
                         ◄─────────────────  archive/transcripts/
                                             └── {project}/{date}-{id}.toml
```

## JSONL Source Format

Each line in `~/.claude/projects/{project-dir}/{session}.jsonl`:

### Entry Types
| Type | Has Message | Description |
|------|-------------|-------------|
| `user` | Yes | User message (may contain tool_result blocks) |
| `assistant` | Yes | Assistant response (may contain tool_use blocks) |
| `summary` | No | AI-generated session summary |
| `system` | No | Telemetry (turn duration, etc.) |
| `file-history-snapshot` | No | File state snapshots |
| `queue-operation` | No | Queue management |
| `progress` | No | Progress indicators |

### Entry Fields
```json
{
  "type": "user|assistant|summary|system|...",
  "sessionId": "uuid",
  "uuid": "message-uuid",
  "parentUuid": "parent-uuid|null",
  "timestamp": "ISO8601",
  "cwd": "/working/directory",
  "version": "2.1.9",
  "gitBranch": "branch-name",
  "slug": "human-readable-session-name",
  "sessionId": "uuid (for agent sessions: parent session ID; for regular: own ID)",
  "agentId": "agent-own-id (only in agent sessions)",
  "isSidechain": false,
  "todos": [...],
  "summary": "AI-generated summary text",
  "message": {
    "role": "user|assistant",
    "content": "string | array of content blocks",
    "model": "claude-opus-4-5-20251101",
    "stop_reason": "end_turn|max_tokens|tool_use",
    "usage": {"input_tokens": 123, "output_tokens": 456, "cache_read_input_tokens": 789}
  }
}
```

### Content Block Types
```json
{"type": "text", "text": "..."}
{"type": "thinking", "thinking": "..."}
{"type": "tool_use", "id": "toolu_xxx", "name": "Bash", "input": {...}}
{"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "...", "is_error": false}
```

## SQLite Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    cwd TEXT,
    git_branch TEXT,
    slug TEXT,                    -- human-readable name
    parent_session_id TEXT,       -- for agent sessions
    summary TEXT,                 -- AI-generated summary
    started_at TEXT,
    ended_at TEXT,
    claude_version TEXT,
    model TEXT,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read_tokens INTEGER DEFAULT 0
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    parent_uuid TEXT,
    type TEXT NOT NULL,           -- user, assistant, tool_result
    timestamp TEXT,
    content TEXT,
    thinking TEXT,                -- thinking block content (if captured)
    model TEXT,
    stop_reason TEXT,             -- end_turn, max_tokens, tool_use
    input_tokens INTEGER,
    output_tokens INTEGER,
    is_sidechain BOOLEAN DEFAULT FALSE
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    tool_name TEXT NOT NULL,
    input_json TEXT,
    timestamp TEXT
);

CREATE TABLE tool_results (
    id TEXT PRIMARY KEY,
    tool_call_id TEXT REFERENCES tool_calls(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    content TEXT,
    is_error BOOLEAN DEFAULT FALSE,
    timestamp TEXT
);

-- Indexes
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_timestamp ON messages(timestamp);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_results_session ON tool_results(session_id);
CREATE INDEX idx_sessions_project ON sessions(project);
CREATE INDEX idx_sessions_started ON sessions(started_at);
CREATE INDEX idx_sessions_parent ON sessions(parent_session_id);
```

## Parsing Rules

### Project Name Extraction
Directory names like `-Users-john-Development-myproject` are converted to readable names:
1. Strip common prefixes: `-home-`, `-Users-`, `-mnt-c-Users-`
2. Skip intermediate directories: `projects`, `code`, `repos`, `src`, `dev`, `work`, `documents`, `development`, `github`, `git`
3. Join remaining meaningful parts with dashes

### Message Filtering
Skip entries during parsing:
- `isMeta: true` - system metadata messages
- Content starting with `<command-name>` or `<local-command-` - CLI commands
- Entry types: `file-history-snapshot`, `queue-operation`, `progress`, `system`

## CLI Commands

### `sync` - Archive sessions to SQLite
```
claude-code-archive sync [--projects-dir PATH] [--archive-dir PATH] [--project TEXT] [--force]
```
- Incremental by default (skips existing sessions)
- Extracts project name from directory path (see Parsing Rules)
- Aggregates token usage per session
- Runs database migrations automatically

### `render` - Generate TOML transcripts
```
claude-code-archive render [--archive-dir PATH] [--output-dir PATH] [--session TEXT] [--project TEXT] [--stdout]
```

### `stats` - Display statistics
```
claude-code-archive stats [--archive-dir PATH]
```

### `config` - Manage configuration
```
claude-code-archive config [--archive-dir PATH] [--projects-dir PATH] [--show]
```

## TOML Output Format

```toml
[session]
id = "uuid"
slug = "dapper-questing-pascal"
project = "project-name"
cwd = "/working/directory"
git_branch = "branch"
summary = "AI-generated session summary"
started_at = "ISO8601"
ended_at = "ISO8601"
model = "claude-opus-4-5-20251101"

[[turns]]
number = 1
timestamp = "ISO8601"

[turns.user]
content = '''User message'''

[turns.assistant]
content = '''Assistant response'''
thinking = '''Optional thinking content'''

[[turns.assistant.tool_calls]]
tool = "Bash"
id = "toolu_xxx"
[turns.assistant.tool_calls.input]
command = "ls -la"
[turns.assistant.tool_calls.result]
content = '''Tool output'''
```

## Configuration

Location: `~/.config/claude-code-archive/config.json`
```json
{"archive_dir": "/path/to/archive", "projects_dir": "~/.claude/projects"}
```

## Module Structure

```
src/claude_code_archive/
├── __init__.py      # Version
├── cli.py           # Click CLI
├── config.py        # Configuration
├── database.py      # SQLite operations
├── models.py        # Dataclasses
├── parser.py        # JSONL parsing
└── toml_renderer.py # TOML generation
```

## Planned Enhancements

### Completed
- [x] Phase 1: Capture `thinking`, `slug`, `summary`, `stop_reason`, `is_sidechain`
- [x] Better project name extraction (simonw algorithm)
- [x] Filter meta/system messages from output
- [x] Database migrations for schema updates

### Phase 2: Agent Relationships (Completed)
- [x] Capture parent session from `sessionId` field (for agent sessions, sessionId points to parent)
- [x] Query to reconstruct full agent tree (`get_session_tree`, `get_child_sessions`, `get_root_sessions`)

### Phase 3: Export Formats
- [ ] Markdown export (for committing to repos)
- [ ] JSON export (for external tools)

## Error Handling

- Invalid JSON lines: Skip with warning, continue
- Missing files: Report error, continue with others
- Database errors: Fail fast
- Empty sessions (no messages): Skip

## Testing

1. Parser tests: All entry types, content blocks
2. Database tests: CRUD, schema, incremental sync
3. Renderer tests: TOML format validation
4. CLI tests: All commands execute correctly
5. Integration: Full sync → render cycle
