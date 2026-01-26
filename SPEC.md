# claude-code-archive Specification

Archive Claude Code transcripts from `~/.claude/projects/` into SQLite with TOML export and workflow analysis.

## Data Flow

```
~/.claude/projects/           sync           archive/sessions.db
├── {project-dir}/       ─────────────►     (SQLite)
│   ├── {uuid}.jsonl                              │
│   └── agent-{hash}.jsonl                        │
                                                  │ render
                                                  ▼
                                          archive/transcripts/
                                          └── {project}/{date}-{id}.toml
                                                  │
                                                  │ analyze
                                                  ▼
                                          archive/analysis/run-{ts}/
                                          ├── {project}.md      (per-project)
                                          └── global-synthesis.md
                                                  │
                                                  │ (future: apply)
                                                  ▼
                                          ~/.claude/skills/
                                          .claude/skills/
                                          .claude/settings.json
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
claude-code-archive analyze [--archive-dir PATH] [--project TEXT] [--limit N]
claude-code-archive analyze --synthesize <analysis-dir>
```

Analyzes session transcripts using LLM to identify inefficiencies and generate recommendations.

**Phase 1 (per-project):** Reads TOML transcripts, compares metrics against baselines, categorizes sessions as Ugly/Okay/Good with evidence, identifies root causes of inefficiency.

**Phase 2 (global synthesis):** `--synthesize` reads all per-project analyses, identifies cross-project patterns, quantifies aggregate impact, generates prioritized recommendations.

### `config` - Manage configuration
```
claude-code-archive config [--archive-dir PATH] [--projects-dir PATH] [--show]
```

## Analyze Command

### Analysis Pipeline

```
Phase 1: Per-Project Analysis
┌─────────────────────────────────────────────────────────────┐
│ For each project:                                           │
│ - Read session transcripts from TOML files                  │
│ - Compare metrics against global baselines                  │
│ - Identify Ugly/Okay/Good sessions with evidence            │
│ - Quantify token waste and root causes                      │
└─────────────────────────────────────────────────────────────┘
                         ▼
         archive/analysis/run-{ts}/{project}.md

Phase 2: Global Synthesis (--synthesize)
┌─────────────────────────────────────────────────────────────┐
│ - Read all per-project analysis files                       │
│ - Identify cross-project patterns                           │
│ - Quantify aggregate impact                                 │
│ - Generate prioritized recommendations                      │
└─────────────────────────────────────────────────────────────┘
                         ▼
         archive/analysis/run-{ts}/global-synthesis.md

Phase 3: Actionable Recommendations (future)
┌─────────────────────────────────────────────────────────────┐
│ - Parse recommendations from global synthesis               │
│ - Generate CLAUDE.md additions                              │
│ - Create skill definitions                                  │
│ - Suggest hook configurations                               │
│ - Track recommendation application                          │
└─────────────────────────────────────────────────────────────┘
```

### Recommendation Categories

#### 1. CLAUDE.md Additions
Documentation that helps Claude understand project context upfront.
- Same file read 10+ times across sessions
- Same questions asked repeatedly
- Project-specific patterns that require explanation

#### 2. Workflow Guidelines
Process improvements based on identified inefficiencies.
- Pattern of backtracking or corrections
- Validation failures discovered late
- Requirements misunderstandings

#### 3. Skills
Custom slash commands that automate repetitive multi-step workflows.
- Same sequence of tool calls repeated across 5+ sessions
- Multi-step workflow with consistent pattern
- Project-specific commands that Claude needs to learn

Skills are stored in `.claude/skills/<name>/SKILL.md` with frontmatter options:
- `name`, `description`, `disable-model-invocation`, `allowed-tools`, `context`, `agent`

#### 4. Hooks
Shell commands that run at specific lifecycle events.
- Validation errors caught late that could be caught early
- Consistent post-action steps (e.g., always format after edit)
- Policy enforcement (e.g., never commit to main)

Hook events: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SessionStart`

#### 5. Prompt Improvements
Suggestions for how users can prompt more effectively.
- Ambiguous requirements led to rework
- User had to provide multiple corrections
- Simple questions received over-engineered answers

#### 6. MCP Server Suggestions
External tool integrations that could improve workflows.
- Repeated manual lookups that an MCP could automate
- Integration with external services (Jira, Linear, Sentry, etc.)
- Database or API access patterns

### Priority Scoring
Recommendations ranked by: sessions affected, token waste, projects affected, actionability.

### Output Locations

- Analysis output: `archive/analysis/run-{timestamp}/`
- Per-project files: `archive/analysis/run-{timestamp}/{project}.md`
- Global synthesis: `archive/analysis/run-{timestamp}/global-synthesis.md`

### Apply Logic (Future)
When Phase 3 is implemented:
1. Parse recommendations from global synthesis
2. For each recommendation:
   - CLAUDE.md: Output markdown snippet ready to copy-paste
   - Skills: Generate complete `.claude/skills/<name>/SKILL.md`
   - Hooks: Generate `.claude/settings.json` additions with helper scripts
   - MCP: Provide `claude mcp add` command with config
3. Track which recommendations have been applied in `archive/recommendations/applied.json`

## Module Structure

```
src/claude_code_archive/
├── cli.py           # Click CLI
├── config.py        # Configuration
├── database.py      # SQLite operations
├── models.py        # Dataclasses
├── parser.py        # JSONL parsing
├── toml_renderer.py # TOML generation
├── prompts/         # Analysis prompt templates
│   ├── session_analysis.md   # Per-project analysis prompt
│   └── global_synthesis.md   # Cross-project synthesis prompt
└── analyzer/        # LLM-powered analysis engine
    ├── __init__.py
    ├── claude_client.py      # Async Claude SDK wrapper
    └── session_analyzer.py   # Per-project + global synthesis orchestration
```

See `docs/recommendations-design.md` for detailed implementation design.

## Completed Work

- [x] Phase 1: Capture `thinking`, `slug`, `summary`, `stop_reason`, `is_sidechain`
- [x] Phase 1: Better project name extraction, filter meta/system messages
- [x] Phase 1: Database migrations for schema updates
- [x] Phase 2: Agent relationships (`parent_session_id`, `get_session_tree`, `get_child_sessions`)

## Phase 3: Workflow Analysis (Current)

### Phase 3a: Per-Project Analysis ✓
- [x] Create `analyzer/` subpackage structure
- [x] Async Claude SDK client wrapper
- [x] Session analysis prompt template (Jinja2)
- [x] Metrics comparison against global baselines
- [x] Session categorization (Ugly/Okay/Good) with evidence
- [x] Per-project markdown output

### Phase 3b: Global Synthesis ✓
- [x] Cross-project pattern identification
- [x] Aggregate impact quantification
- [x] Prioritized recommendation generation
- [x] Global synthesis markdown output
- [x] Anti-sycophancy prompt design (critical framing, evidence requirements)

### Phase 3c: Actionable Recommendations (future)
- [ ] Parse recommendations from global synthesis
- [ ] Generate CLAUDE.md additions
- [ ] Generate skill definitions (.claude/skills/<name>/SKILL.md)
- [ ] Generate hook configurations (.claude/settings.json)
- [ ] Suggest MCP server installations
- [ ] Track recommendation application

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
4. Analyzer tests: Session analysis, Claude client mocking, markdown generation
5. Apply tests: File generation, conflict handling (future)
6. Integration: Full sync → render → analyze cycle
