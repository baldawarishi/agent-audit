# Analyzer Issues & Improvement Opportunities

Investigation date: 2026-01-19
Status: Open for future work

## Executive Summary

The pattern analyzer produces recommendations that are often **false positives** due to:
1. Fixed n-gram size losing command context (pipelines vs standalone)
2. LLM classifier lacking context about Claude Code's tool system
3. Treating normal iterative workflows as "problems to fix"

## Issue 1: Pipeline Context Lost in N-gram Extraction

### Problem

Tool sequences are extracted as fixed-size n-grams (3-grams by default). A command like:

```bash
git log --oneline | grep "feat:" | head -10
```

Gets normalized to just `Bash:grep` and loses the pipeline context.

### Evidence

```
Bash:grep usage breakdown:
- 90% are in pipelines (git | grep, cat | grep, etc.) - VALID
- 10% are standalone grep calls - POTENTIALLY replaceable

Bash:find usage breakdown:
- 88% are piped
- 11% use -exec
- 9% are truly standalone (but use -maxdepth, -type, -o flags Glob doesn't support)
```

### Impact

The classifier sees `Bash:grep → Bash:grep → Read` and recommends "use native Grep tool" when 90% of those Bash:grep calls are legitimate pipeline usage.

### Potential Fixes

1. **Enhance normalization**: Parse the full command to detect pipelines
   ```python
   def normalize_bash_command(input_json):
       cmd = json.loads(input_json).get("command", "")
       if "|" in cmd:
           return "Bash:pipeline"  # or extract the full pipeline
       # ... existing logic
   ```

2. **Store richer metadata**: Keep pipeline context in pattern data
   ```python
   {
       "tool": "Bash:grep",
       "is_pipeline": True,
       "pipeline_position": "middle",  # first, middle, last
       "full_command": "git log | grep feat | head"
   }
   ```

3. **Different n-gram strategies**: Variable-length sequences that respect command boundaries

## Issue 2: LLM Classifier Lacks Claude Code Context

### Problem

The classifier prompt doesn't explain:
- What Claude Code's native tools actually do
- When Bash commands are appropriate vs native tools
- That pipelines require Bash (can't pipe native Grep output)

### Evidence

Classifier recommends "use Grep instead of Bash:grep" without understanding that:
- Native `Grep` tool can't be used in shell pipelines
- `Bash:grep` in a pipeline is the correct choice
- Only standalone `grep` calls could potentially use native Grep

### Potential Fixes

Add to classification prompt:

```markdown
## Claude Code Tool Context

### Native Tools vs Bash Commands

Claude Code has native tools (Grep, Glob, Read, Edit) AND a Bash tool for shell commands.

**When Bash is appropriate (don't recommend native tool):**
- Command is part of a pipeline: `git log | grep | head`
- Command uses features native tool lacks: `find -exec`, `grep -P` (PCRE)
- Command chains multiple operations: `cmd1 && cmd2`

**When native tool might be better:**
- Standalone search: `grep pattern file` → could use Grep tool
- Simple file listing: `find . -name "*.py"` → could use Glob tool

**Pattern key hints:**
- `Bash:X → Bash:Y → Bash:Z` likely a pipeline - don't suggest breaking it up
- Single `Bash:grep` followed by `Read` - might be replaceable
```

## Issue 3: Normal Workflows Flagged as Problems

### Problem

The analyzer treats common iterative patterns as inefficiencies:

| Pattern | Analyzer Says | Reality |
|---------|---------------|---------|
| `Grep → Grep → Grep` | "Avoid repeated searches" | Normal search refinement |
| `Read → Read → Read` | "Batch your reads" | Exploratory code reading |
| `Edit → Edit → Edit` | "Batch your edits" | Iterative development |
| `cd → cd → cd` | "Use absolute paths" | Maybe valid, maybe navigating |

### Evidence

- `Read → Read → Read`: 588 occurrences, 163 sessions - this is just how code exploration works
- `Edit → Edit → Edit`: 207 occurrences - iterative editing is normal

### Potential Fixes

1. **Distinguish "anti-patterns" from "normal patterns"**:
   - Anti-pattern: Using inferior tool when better one exists
   - Normal: Iterative use of appropriate tools

2. **Add pattern classification in prompt**:
   ```markdown
   ## Pattern Types

   ### Anti-patterns (recommend fixing)
   - Using Bash:grep standalone when Grep tool would work
   - Using Bash:ls repeatedly when Glob would work
   - Accessing same file 20+ times (should document in CLAUDE.md)

   ### Normal workflows (don't flag as problems)
   - Multiple Grep calls (search refinement)
   - Multiple Read calls (code exploration)
   - Multiple Edit calls (iterative development)
   - Pipeline commands via Bash
   ```

## Issue 4: N-gram Fixed Size Limitations

### Problem

Current implementation uses fixed 3-grams for tool sequences. This means:
- `A → B → C → D → E` becomes two patterns: `A → B → C` and `C → D → E`
- Long pipelines get fragmented
- Related sequences get split artificially

### Evidence

A git workflow like:
```
git status → git diff → git add → git commit → git push
```

Becomes:
- `git-status → git-diff → git-add`
- `git-add → git-commit → git-push`

These are merged later but the merging logic is imperfect.

### Potential Fixes

1. **Variable-length sequences**: Detect natural boundaries (time gaps, conversation turns)
2. **Session-aware extraction**: Extract full tool sequences per user message/task
3. **Hierarchical patterns**: `git-workflow` containing sub-patterns

## Issue 5: Prompt Phrases Overwhelming Signal

### Problem

11,198 prompt phrases detected vs 385 tool sequences. The sheer volume of prompt phrases drowns out more actionable patterns.

### Evidence

```
Patterns found:
  tool_sequences: 385
  prompt_prefixes: 52
  prompt_phrases: 11198  # 96% of all patterns!
  file_access: 168
```

Most prompt phrases are noise ("the", "and then", "please").

### Potential Fixes

1. **Better filtering**: Require prompt phrases to appear in 3+ projects
2. **Semantic deduplication**: Group similar phrases
3. **Separate analysis**: Don't mix prompt phrases with tool patterns in same classification call

## Recommended Next Steps

### Quick Wins (prompt changes only)

1. Add Claude Code tool context to classification prompt
2. Add "normal vs anti-pattern" guidance
3. Filter out pipeline-based Bash commands from "use native tool" recommendations

### Medium Effort (code changes)

1. Detect pipelines in Bash command normalization
2. Store `is_pipeline` metadata in patterns
3. Better prompt phrase filtering (min project count)

### Larger Refactors

1. Variable-length sequence extraction
2. Session/task-aware pattern boundaries
3. Hierarchical pattern representation

## Test Commands

```bash
# Check current pattern counts
claude-code-archive analyze --archive-dir ./archive --patterns-only

# Full analysis
claude-code-archive analyze --archive-dir ./archive

# Check Bash command breakdown
sqlite3 ./archive/sessions.db "SELECT COUNT(*) FROM tool_calls WHERE tool_name = 'Bash' AND input_json LIKE '%grep%'"
sqlite3 ./archive/sessions.db "SELECT input_json FROM tool_calls WHERE tool_name = 'Bash' AND input_json LIKE '%grep%'" | grep -c "|"
```

## Related Files

- `src/claude_code_archive/analyzer/patterns.py` - Pattern detection logic
- `src/claude_code_archive/analyzer/classifier.py` - LLM classification
- `src/claude_code_archive/prompts/classification.md` - Classification prompt
- `docs/analyzer-improvements.md` - Previous improvement investigation
