# claude-code-archive Specification

Archive Claude Code transcripts from `~/.claude/projects/` into SQLite with TOML export and workflow analysis.

## Data Flow

```
~/.claude/projects/           sync           archive/sessions.db
├── {project-dir}/       ─────────────►     (SQLite)
│   ├── {uuid}.jsonl                              │
│   └── agent-{hash}.jsonl                        │
                                                  │ analyze
                                                  ▼
                             render         recommendations.md
                        ◄─────────────     (checkboxes + reasoning)
archive/transcripts/                              │
└── {project}/{date}-{id}.toml            analyze --apply
                                                  ▼
                                          ~/.claude/skills/
                                          .claude/skills/
                                          CLAUDE.md updates
```

## JSONL Source Format

Each line in `~/.claude/projects/{project-dir}/{session}.jsonl`:

| Type | Has Message | Description |
|------|-------------|-------------|
| `user` | Yes | User message (may contain tool_result blocks) |
| `assistant` | Yes | Assistant response (may contain tool_use blocks) |
| `summary` | No | AI-generated session summary |
| `system`, `file-history-snapshot`, `queue-operation`, `progress` | No | Filtered out |

### Entry Fields
```json
{
  "type": "user|assistant|summary|...",
  "sessionId": "uuid (for agents: parent session ID)",
  "agentId": "agent-own-id (only in agent sessions)",
  "uuid": "message-uuid",
  "parentUuid": "parent-uuid|null",
  "timestamp": "ISO8601",
  "cwd": "/working/directory",
  "version": "2.1.9",
  "gitBranch": "branch-name",
  "slug": "human-readable-session-name",
  "isSidechain": false,
  "summary": "AI-generated summary text",
  "message": {
    "role": "user|assistant",
    "content": "string | [{type: text|thinking|tool_use|tool_result, ...}]",
    "model": "claude-opus-4-5-20251101",
    "stop_reason": "end_turn|max_tokens|tool_use",
    "usage": {"input_tokens": 123, "output_tokens": 456, "cache_read_input_tokens": 789}
  }
}
```

## SQLite Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    cwd TEXT, git_branch TEXT, slug TEXT,
    parent_session_id TEXT,       -- for agent sessions
    summary TEXT,
    started_at TEXT, ended_at TEXT,
    claude_version TEXT, model TEXT,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read_tokens INTEGER DEFAULT 0
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    parent_uuid TEXT,
    type TEXT NOT NULL,           -- user, assistant, tool_result
    timestamp TEXT, content TEXT, thinking TEXT,
    model TEXT, stop_reason TEXT,
    input_tokens INTEGER, output_tokens INTEGER,
    is_sidechain BOOLEAN DEFAULT FALSE
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    tool_name TEXT NOT NULL,
    input_json TEXT, timestamp TEXT
);

CREATE TABLE tool_results (
    id TEXT PRIMARY KEY,
    tool_call_id TEXT REFERENCES tool_calls(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    content TEXT, is_error BOOLEAN DEFAULT FALSE, timestamp TEXT
);

CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_results_session ON tool_results(session_id);
CREATE INDEX idx_sessions_project ON sessions(project);
CREATE INDEX idx_sessions_parent ON sessions(parent_session_id);
```

## Parsing Rules

### Project Name Extraction
Directory names like `-Users-john-Development-myproject` → readable names:
1. Strip prefixes: `-home-`, `-Users-`, `-mnt-c-Users-`
2. Skip intermediate dirs: `projects`, `code`, `repos`, `src`, `dev`, `work`, `documents`, `development`, `github`, `git`

### Filtering
- Temp directories excluded by default: `-tmp-*`, `-var-folders-*`, `-private-var-*`, `pytest-`
- Skip entries: `isMeta: true`, content starting with `<command-name>` or `<local-command-`

## CLI Commands

### `sync` - Archive sessions to SQLite
```
claude-code-archive sync [--projects-dir PATH] [--archive-dir PATH] [--project TEXT] [--force] [--include-tmp-directories]
```

### `render` - Generate TOML transcripts
```
claude-code-archive render [--archive-dir PATH] [--output-dir PATH] [--session TEXT] [--project TEXT] [--stdout]
```

### `stats` - Display statistics
```
claude-code-archive stats [--archive-dir PATH]
```

### `analyze` - Generate workflow recommendations
```
claude-code-archive analyze [--archive-dir PATH] [--project TEXT] [--since DATE] [--output PATH]
claude-code-archive analyze --apply PATH
```

Analyzes archive to surface actionable recommendations for skills, hooks, CLAUDE.md, and permissions. Outputs markdown with checkboxes; user reviews and selects; `--apply` executes selected items.

### `config` - Manage configuration
```
claude-code-archive config [--archive-dir PATH] [--projects-dir PATH] [--show]
```

## Analyze Command

### Workflow
1. `analyze` scans archive, detects patterns, outputs `recommendations.md`
2. User reviews recommendations with reasoning, checks boxes for ones to apply
3. `analyze --apply recommendations.md` generates skills/hooks/docs for checked items

### Recommendation Categories

#### Skill Opportunities
Detect repeated patterns that could become skills:
- **Tool sequences**: Same tools called in same order across sessions
- **Prompt patterns**: Similar user messages appearing multiple times
- **Successful agent forks**: Sub-agent patterns that complete successfully

#### Scope Detection
| Signal | Target Location |
|--------|-----------------|
| Pattern in 50%+ of projects | `~/.claude/skills/` (global) |
| Pattern only in one project | `.claude/skills/` (project) |
| Pattern only in one directory | `subdir/.claude/skills/` |
| Repeated user explanation across projects | `~/.claude/CLAUDE.md` |
| Project-specific convention | `project/CLAUDE.md` |

#### Permission Friction
Identify tool calls that always succeed but require approval:
- Track approval/denial/error rates per tool pattern
- Suggest `allowed-tools` additions for high-approval patterns
- Distinguish global vs project-specific permissions

#### Hook Candidates
- **PreToolUse**: Tool calls with high error rates → validation hooks
- **PostToolUse**: Missing follow-up actions (e.g., edit model.py but no migration)
- **Blocking**: Dangerous patterns (rm -rf, writing to .env)

#### CLAUDE.md Gaps
- Files read repeatedly across sessions → document in context
- Repeated user explanations → capture once
- Tool errors from unknown conventions → document the convention

#### Agent Efficiency
- Agent spawn depth vs success rate
- Sessions with no meaningful output
- Patterns where parent could have done work directly

### Recommendation Format
```markdown
## Skill Opportunities

- [ ] **commit-workflow** [GLOBAL ~/.claude/skills/]

  Seen: 52 times across 9 projects
  Sequence: `git status` → `git diff` → confirm → `git add` → `git commit`
  Reasoning: Appears in 85% of projects with identical flow. ~4 turns saved per use.

  <details><summary>Generated SKILL.md</summary>

  ```yaml
  ---
  name: commit-workflow
  description: Stage and commit changes with review. Use when committing code.
  allowed-tools: Bash(git *)
  ---
  ```
  </details>

- [ ] **django-endpoint** [PROJECT my-api/.claude/skills/]

  Seen: 12 times, only in my-api
  Reasoning: Uses Django conventions specific to this repo. Not seen in 8 other Python projects.

## Permission Friction

- [ ] **Bash(npm install*)** [GLOBAL]

  89 approvals, 0 denials, 0 errors
  Reasoning: Always approved. Add to global allowed-tools.

## CLAUDE.md Gaps

- [ ] **Document src/core/config.py** [PROJECT my-api/CLAUDE.md]

  Read 41 times across 15 sessions
  Reasoning: Claude re-reads constantly. Extract key configs to CLAUDE.md.
```

### Apply Logic
When `--apply` is run:
1. Parse markdown, find checked items
2. For each checked item:
   - Skills: Create `SKILL.md` in target location
   - Permissions: Append to existing skill or create permissions skill
   - CLAUDE.md: Append section to appropriate file (create if needed)
   - Hooks: Add to `.claude/settings.json` or prompt for hook script location
3. Report what was created/modified

## Module Structure

```
src/claude_code_archive/
├── cli.py           # Click CLI
├── config.py        # Configuration
├── database.py      # SQLite operations
├── models.py        # Dataclasses
├── parser.py        # JSONL parsing
├── toml_renderer.py # TOML generation
└── analyzer.py      # Pattern detection + recommendation generation (new)
```

## Completed Work

- [x] Phase 1: Capture `thinking`, `slug`, `summary`, `stop_reason`, `is_sidechain`
- [x] Phase 1: Better project name extraction, filter meta/system messages
- [x] Phase 1: Database migrations for schema updates
- [x] Phase 2: Agent relationships (`parent_session_id`, `get_session_tree`, `get_child_sessions`)

## Phase 3: Workflow Analysis (Current)

- [ ] Pattern detection for tool sequences
- [ ] Scope detection (global vs project vs subfolder)
- [ ] Recommendation markdown generation with reasoning
- [ ] Checkbox parsing and apply logic
- [ ] Skill generation
- [ ] CLAUDE.md updates
- [ ] Hook suggestions

## Error Handling

- Invalid JSON lines: Skip with warning
- Missing files: Report, continue
- Database errors: Fail fast
- Empty sessions: Skip
- Apply conflicts: Warn, don't overwrite without `--force`

## Testing

1. Parser tests: All entry types, content blocks
2. Database tests: CRUD, schema, incremental sync
3. Renderer tests: TOML format validation
4. Analyzer tests: Pattern detection, scope inference, markdown generation
5. Apply tests: File generation, conflict handling
6. Integration: Full sync → analyze → apply cycle
