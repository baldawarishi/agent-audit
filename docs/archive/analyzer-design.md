# Analyzer Design Document

Reference document for implementing the `analyze` command (Phase 3).
Created: 2025-01-17

## Overview

The analyzer detects repeated patterns in Claude Code sessions and generates actionable recommendations for skills, CLAUDE.md content, and workflow improvements.

```
┌─────────────────────────────────────────────────────────────────┐
│                     analyze command                              │
├─────────────────────────────────────────────────────────────────┤
│  Phase 1: Pattern Detection (no LLM)                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ Tool Sequences  │  │ Prompt Patterns │  │ File Access     │ │
│  │ (3-gram)        │  │ (prefix+phrase) │  │ Patterns        │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
│           └────────────────────┼────────────────────┘          │
│                                ▼                                │
│                      Raw Patterns JSON                          │
├─────────────────────────────────────────────────────────────────┤
│  Phase 2: Smart Classification (LLM - Opus 4.5)                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Prompt: patterns + ideal-agents-md-guide + best practices   ││
│  │ Output: category, scope, confidence, suggested_content      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                ▼                                │
│              {archive-dir}/analysis/recommendations-{ts}.md     │
└─────────────────────────────────────────────────────────────────┘
```

## Module Structure

```
src/claude_code_archive/
├── analyzer/
│   ├── __init__.py       # Exports main analyze() function
│   ├── patterns.py       # Phase 1: pattern detection
│   ├── classifier.py     # Phase 2: LLM classification
│   ├── claude_client.py  # Claude SDK wrapper
│   └── renderer.py       # Markdown output generation
├── prompts/
│   └── classification.md # LLM prompt template with few-shot examples
```

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "click>=8.0",
    "claude-agent-sdk>=0.1.12",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.21.0",
    "mypy>=1.0",
    "ruff>=0.4",
]
```

## CLI Interface

```bash
claude-code-archive analyze \
  [--archive-dir PATH] \
  [--project TEXT] \
  [--since DATE] \
  [--patterns-only] \
  [--min-occurrences N] \
  [--min-sessions N] \
  [--global-threshold FLOAT] \
  [--output PATH]
```

### Defaults & Assumptions

| Flag | Default | Notes |
|------|---------|-------|
| `--archive-dir` | `./archive` | Location of sessions.db |
| `--project` | None (all) | Filter to specific project |
| `--since` | None (all time) | ISO date filter |
| `--patterns-only` | False | Skip Phase 2, output raw patterns |
| `--min-occurrences` | 3 | Minimum total pattern occurrences |
| `--min-sessions` | 2 | Minimum distinct sessions |
| `--global-threshold` | 0.3 | 30% of projects = global scope |
| `--output` | `{archive-dir}/analysis/recommendations-{datetime}.md` | Output path |

### API Key Handling

- `ANTHROPIC_API_KEY` env var required for Phase 2
- Lazy check: only validated when Phase 2 starts
- `--patterns-only` works without API key
- Fail hard if key missing/invalid (no fallbacks)

## Phase 1: Pattern Detection

### 1.1 Tool Sequence Detection

Extract 3-grams of tool calls per session, count across all sessions.

```python
def extract_tool_sequences(session_id: str, db: Database) -> list[tuple[str, ...]]:
    """Extract 3-grams of normalized tool names."""
    tool_calls = db.get_tool_calls_for_session(session_id)
    tools = [normalize_tool(tc) for tc in sorted(tool_calls, key=lambda x: x['timestamp'])]
    return [tuple(tools[i:i+3]) for i in range(len(tools) - 2)]
```

#### Bash Command Normalization

Depth 2 for known multi-part commands:

```python
SUBCOMMAND_TOOLS = {
    "git", "docker", "kubectl", "npm", "yarn", "pip", "cargo",
    "go", "gh", "aws", "gcloud", "az", "terraform", "make"
}

def normalize_bash_command(input_json: str) -> str:
    """Extract command signature for pattern matching."""
    data = json.loads(input_json)
    cmd = data.get("command", "")

    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = cmd.split()

    if not parts:
        return "unknown"

    base = parts[0]

    # Depth 2 for known tools
    if base in SUBCOMMAND_TOOLS and len(parts) > 1:
        subcmd = parts[1]
        if not subcmd.startswith("-") and not subcmd.startswith("/"):
            return f"{base}-{subcmd}"

    return base
```

#### Sequence Merging

If overlapping 3-grams have similar counts and confident ordering doesn't matter, merge into longer sequence:

```
(git-status, git-diff, git-add) + (git-diff, git-add, git-commit)
→ (git-status, git-diff, git-add, git-commit)
```

Only merge when high confidence. Otherwise, log as separate patterns.

### 1.2 Prompt Pattern Detection

Two types of patterns:

#### Whole-prompt prefix matching

```python
def normalize_prompt(text: str) -> str:
    """Normalize prompt for pattern matching."""
    text = text.lower()
    # Remove URLs
    text = re.sub(r'https?://\S+', '<url>', text)
    # Normalize paths (test both approaches)
    text = re.sub(r'(/[\w\-./]+)+', '<path>', text)
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text

def extract_prefix(text: str, n_tokens: int = 5) -> str:
    """Extract first N tokens as pattern key."""
    tokens = normalize_prompt(text).split()[:n_tokens]
    return ' '.join(tokens)
```

#### Sub-section phrase detection (5-grams within prompts)

```python
def extract_phrase_patterns(messages: list[str], n: int = 5, min_count: int = 3):
    """Find repeated phrases across messages."""
    phrase_counts = Counter()
    phrase_sources = defaultdict(set)

    for i, msg in enumerate(messages):
        words = normalize_prompt(msg).split()
        for j in range(len(words) - n + 1):
            phrase = tuple(words[j:j+n])
            phrase_counts[phrase] += 1
            phrase_sources[phrase].add(i)

    return {
        phrase: {"count": count, "sources": phrase_sources[phrase]}
        for phrase, count in phrase_counts.items()
        if count >= min_count and len(phrase_sources[phrase]) >= 2
    }
```

### 1.3 File Access Pattern Detection

Track files that are repeatedly read/edited across sessions:

```python
def extract_file_patterns(db: Database) -> dict:
    """Find files accessed repeatedly."""
    file_counts = Counter()
    file_sessions = defaultdict(set)
    file_projects = defaultdict(set)

    for session in db.get_all_sessions():
        tool_calls = db.get_tool_calls_for_session(session['id'])
        for tc in tool_calls:
            if tc['tool_name'] in ('Read', 'Edit', 'Write'):
                input_data = json.loads(tc['input_json'])
                file_path = input_data.get('file_path', '')
                if file_path:
                    # Normalize path (remove user-specific prefixes)
                    normalized = normalize_file_path(file_path)
                    file_counts[normalized] += 1
                    file_sessions[normalized].add(session['id'])
                    file_projects[normalized].add(session['project'])

    return {
        path: {
            "count": count,
            "sessions": file_sessions[path],
            "projects": file_projects[path]
        }
        for path, count in file_counts.items()
        if count >= 3 and len(file_sessions[path]) >= 2
    }
```

### 1.4 Pattern Data Structure

```python
@dataclass
class RawPattern:
    pattern_type: str           # "tool_sequence", "prompt_prefix", "prompt_phrase", "file_access"
    pattern_key: str            # Normalized pattern identifier
    occurrences: int            # Total count
    sessions: set[str]          # Session IDs
    projects: set[str]          # Project names
    first_seen: str             # ISO timestamp
    last_seen: str              # ISO timestamp
    examples: list[str]         # Sample raw values (for context)
```

### 1.5 Phase 1 Output

`--patterns-only` outputs pretty JSON:

```json
{
  "generated_at": "2025-01-17T10:30:00",
  "summary": {
    "total_sessions_analyzed": 150,
    "total_projects": 12,
    "patterns_found": {
      "tool_sequences": 23,
      "prompt_prefixes": 15,
      "prompt_phrases": 8,
      "file_access": 31
    }
  },
  "patterns": {
    "tool_sequences": [...],
    "prompt_prefixes": [...],
    "prompt_phrases": [...],
    "file_access": [...]
  }
}
```

Also prints summary to stdout.

## Phase 2: Smart Classification

### 2.1 Claude Client

Follow repo-drift pattern using `claude_agent_sdk`:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock

class AnalyzerClaudeClient:
    """Wrapper for Claude SDK for pattern classification."""

    async def __aenter__(self):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = ClaudeSDKClient()
        await self.client.connect()
        return self

    async def __aexit__(self, *args):
        await self.client.disconnect()

    async def classify_patterns(self, patterns_json: str) -> dict:
        """Send all patterns to Claude for classification."""
        prompt = self._build_classification_prompt(patterns_json)
        await self.client.query(prompt)
        response = await self._collect_response()
        return self._parse_response(response)
```

### 2.2 Classification Prompt

Load from `src/claude_code_archive/prompts/classification.md`.

Template with `{placeholders}`:
- `{patterns_json}` - The raw patterns from Phase 1
- `{num_projects}` - Total projects in archive
- `{date_range}` - Time span of data

Include few-shot examples in the prompt.

### 2.3 Classification Output

```python
@dataclass
class ClassifiedPattern:
    raw_pattern: RawPattern
    category: str              # "skill" | "claude_md" | "hook"
    scope: str                 # "global" | "project:{name}" | "subdir:{path}"
    confidence: str            # "high" | "medium" | "low"
    reasoning: str             # LLM explanation
    suggested_name: str        # e.g., "commit-workflow"
    suggested_content: str     # Generated SKILL.md or CLAUDE.md snippet
```

### 2.4 Scope Detection

LLM decides scope based on:
- Pattern in 30%+ of projects → `global`
- Pattern in single project → `project:{name}`
- Pattern only in specific subdirectory → `subdir:{path}`

## Output Format

### Markdown (by scope)

```markdown
# Workflow Analysis Recommendations
Generated: 2025-01-17T10:30:00
Archive: ./archive (150 sessions, 12 projects)

## Global Recommendations
Patterns appearing in 30%+ of projects.

### Tool Sequence: git-status → git-diff → git-add → git-commit
- **Category**: Skill
- **Confidence**: high
- **Occurrences**: 47 across 12 sessions
- **Time span**: 2024-08-15 to 2025-01-17
- **Projects**: project-a, project-b, project-c (+5 more)

<details><summary>Suggested SKILL.md</summary>

```yaml
---
name: commit-workflow
description: Stage and commit changes with review
allowed-tools: Bash(git *)
---

# Commit Workflow

1. Check status: `git status`
2. Review changes: `git diff`
3. Stage files: `git add <files>`
4. Commit: `git commit -m "message"`
```

</details>

---

## Project: my-api
Patterns specific to this project.

### File Access: src/core/config.py
- **Category**: CLAUDE.md
- **Confidence**: medium
- **Read 41 times** across 15 sessions
- **Reasoning**: Frequently referenced configuration file. Document key settings in CLAUDE.md.

<details><summary>Suggested CLAUDE.md addition</summary>

```markdown
## Configuration

Key settings in `src/core/config.py`:
- `DATABASE_URL`: PostgreSQL connection string
- `API_TIMEOUT`: Request timeout in seconds (default: 30)
```

</details>
```

## Implementation Plan

### Phase 3a: Detection & Output (no LLM)

1. [ ] Create `analyzer/` subpackage structure
2. [ ] Implement `patterns.py`:
   - [ ] Tool sequence extraction (3-grams)
   - [ ] Bash command normalization (depth 2)
   - [ ] Prompt prefix extraction (5 tokens)
   - [ ] Prompt phrase extraction (5-grams)
   - [ ] File access pattern extraction
   - [ ] Sequence merging logic
3. [ ] Implement `renderer.py`:
   - [ ] Pretty JSON output for `--patterns-only`
   - [ ] Stdout summary
4. [ ] Add CLI command to `cli.py`
5. [ ] Write tests:
   - [ ] Minimal fixtures (2-3 sessions)
   - [ ] Realistic fixtures (~10 sessions)
   - [ ] Unit tests for each pattern type

### Phase 3b: LLM Classification

6. [ ] Create `prompts/classification.md` template
7. [ ] Implement `claude_client.py`:
   - [ ] Async context manager
   - [ ] API key validation
   - [ ] Query and response collection
   - [ ] JSON parsing with validation
8. [ ] Implement `classifier.py`:
   - [ ] Load prompt template
   - [ ] Build classification prompt
   - [ ] Parse classification results
9. [ ] Extend `renderer.py`:
   - [ ] Full markdown output with recommendations
   - [ ] Grouping by scope
10. [ ] Write tests:
    - [ ] Mock Claude client
    - [ ] Classification parsing tests

### Phase 3c: Apply Logic (future)

11. [ ] Checkbox parsing
12. [ ] Skill generation
13. [ ] CLAUDE.md updates
14. [ ] Hook suggestions

## Testing Strategy

### Fixtures

**Minimal** (`tests/fixtures/minimal/`):
- 2-3 small sessions
- Obvious patterns (same tool sequence repeated)
- Use for unit tests

**Realistic** (`tests/fixtures/realistic/`):
- ~10 sessions mimicking real usage
- Mixed patterns, some noise
- Use for integration tests

### Mocking

For LLM tests, mock `ClaudeSDKClient`:

```python
@pytest.fixture
def mock_claude_client(mocker):
    mock = mocker.patch('claude_code_archive.analyzer.claude_client.ClaudeSDKClient')
    # Configure mock responses
    return mock
```

## Key Decisions Reference

| Decision | Choice |
|----------|--------|
| Tool sequence window | 3-grams |
| Bash tokenization | Depth 2 for known tools |
| Prompt patterns | Prefix (5 tokens) + sub-section phrases (5-grams) |
| Overlapping sequences | Merge if confident ordering doesn't matter |
| Temporal info | Time span (first/last seen) |
| Error status | Ignore for v1 |
| Threshold | Y occurrences across Z sessions, configurable |
| Global scope | 30% of projects |
| Output path | `{archive-dir}/analysis/recommendations-{datetime}.md` |
| Output grouping | By scope |
| LLM model | Opus 4.5 (SDK default) |
| LLM call strategy | Batch all patterns in one call |
| LLM error handling | Fail hard (no fallbacks) |
| Prompt template | Markdown with `{placeholders}`, few-shot examples |
| Async | Use `asyncio.run()` in CLI |
| API key check | Lazy (only when Phase 2 starts) |
| Progress | Simple print statements |
| Tests | Minimal + realistic fixtures |
| Module structure | Subpackage (`analyzer/`) |
| Phase 1 output | Pretty JSON + stdout summary |

## Reference Documents

- `docs/pattern-detection-research.md` - Algorithm alternatives and research
- `~/Downloads/ideal-agents-md-guide.md` - Best practices for AGENTS.md/CLAUDE.md
- `/Users/rishibaldawa/Development/repo-drift/src/claude_client.py` - Claude SDK pattern reference
