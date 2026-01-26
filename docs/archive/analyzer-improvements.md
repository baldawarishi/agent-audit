# Analyzer Improvements Investigation

Investigation into two improvements to the LLM classification phase.
Date: 2026-01-17

## Executive Summary

| Investigation | Feasibility | Recommendation | Complexity |
|---------------|-------------|----------------|------------|
| File-based pattern input | **Feasible** | Implement | Medium |
| Prompt-based chunking (TodoWrite/Task) | **Feasible** | Implement | Low |

Both improvements are feasible and complementary. Recommend implementing together:
1. File-based input (enables scale)
2. Prompt updates (let Claude manage chunking via TodoWrite/Task)

---

## Investigation 1: File-based Pattern Input

### Problem Statement

Current implementation embeds all patterns directly in the prompt (`classifier.py:97`):
```python
patterns_json = json.dumps(all_patterns, indent=2)
return template.format(patterns_json=patterns_json, ...)
```

This hits token limits, forcing `max_patterns=50` (default). With typical archives containing 200-1000+ patterns, we're only analyzing ~5-25% of detected patterns.

### Research Findings

#### claude-agent-sdk Capabilities

The SDK **does support file-based input** via built-in tools. Key documentation findings:

1. **Built-in Read tool**: The SDK includes `Read`, `Write`, `Bash`, etc. tools by default
2. **Configuration**: Enable via `ClaudeAgentOptions`:
   ```python
   options = ClaudeAgentOptions(
       allowed_tools=["Read"],
       cwd="/path/to/working/directory",
       permission_mode='acceptEdits'  # auto-accept file reads
   )
   ```
3. **ClaudeSDKClient support**: Works with the client we already use

Source: [Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python)

#### Current Implementation Gap

The current `claude_client.py:49` creates a bare client without options:
```python
self.client = ClaudeSDKClient()  # No options passed
```

This means Claude cannot use tools like `Read` even though the SDK supports them.

### Proposed Solution

#### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     classify_patterns()                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Write patterns to temp file                                  │
│     /tmp/claude-archive-patterns-{uuid}.json                     │
│                                                                  │
│  2. Configure ClaudeAgentOptions                                 │
│     allowed_tools=["Read"]                                       │
│     cwd=temp_dir                                                 │
│     permission_mode='acceptEdits'                                │
│                                                                  │
│  3. Prompt instructs Claude to read the file                     │
│     "Read the patterns from patterns.json and classify them"     │
│                                                                  │
│  4. Claude uses Read tool → file contents in context             │
│     (bypasses prompt token limit)                                │
│                                                                  │
│  5. Cleanup temp file after classification                       │
└─────────────────────────────────────────────────────────────────┘
```

#### Code Changes Required

**`claude_client.py`** - Add options support:
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

class AnalyzerClaudeClient:
    def __init__(self, options: ClaudeAgentOptions | None = None):
        self.options = options
        self.client: Optional[ClaudeSDKClient] = None

    async def _connect(self) -> None:
        # ... existing validation ...
        self.client = ClaudeSDKClient(options=self.options)
        await self.client.connect()
```

**`classifier.py`** - Use temp file for large pattern sets:
```python
import tempfile
from pathlib import Path

async def classify_patterns_with_file(
    patterns_result: dict,
    max_inline_patterns: int = 50,
) -> list[ClassifiedPattern]:
    all_patterns = flatten_patterns(patterns_result)

    if len(all_patterns) <= max_inline_patterns:
        # Use existing inline approach
        return await classify_patterns_inline(patterns_result)

    # Write to temp file for large pattern sets
    with tempfile.TemporaryDirectory() as temp_dir:
        patterns_file = Path(temp_dir) / "patterns.json"
        patterns_file.write_text(json.dumps(all_patterns, indent=2))

        options = ClaudeAgentOptions(
            allowed_tools=["Read"],
            cwd=temp_dir,
            permission_mode='acceptEdits'
        )

        async with AnalyzerClaudeClient(options=options) as client:
            prompt = build_file_based_prompt(patterns_file.name, ...)
            response = await client.query(prompt)
            # ... parse response ...
```

**`prompts/classification.md`** - Add file-reading variant:
```markdown
## Input Patterns

Read the patterns from `{patterns_file}` using the Read tool, then classify each pattern.

The file contains a JSON array of patterns to classify.
```

### Considerations

#### Token Limits Still Apply (But Higher)

The Read tool output goes into context, so there's still an effective limit. However:
- Prompt tokens: ~8K limit for comfortable operation
- Context window: ~200K tokens (Claude 3.5/Opus 4.5)
- Read tool output: treated as tool result, larger capacity

Estimated capacity: 1000-5000 patterns depending on pattern size.

#### Large File Warning

The SDK may warn about large files. Handle gracefully:
```python
# Chunk if file is very large (>100KB)
if patterns_file.stat().st_size > 100_000:
    return await classify_patterns_chunked(patterns_result)
```

#### Error Handling

- Tool execution may fail (permissions, file not found)
- Need fallback to inline approach if file-based fails

### Prototype Status

Not yet prototyped. Ready for implementation with above design.

---

## Investigation 2: Prompt-based Chunking with TodoWrite/Task

### Problem Statement

Current approach pre-filters patterns in Python (`classifier.py:94`):
```python
all_patterns.sort(key=lambda x: x.get("occurrences", 0), reverse=True)
all_patterns = all_patterns[:max_patterns]  # Hard limit of 50
```

This misses valuable patterns and doesn't leverage Claude's ability to:
- Intelligently prioritize patterns itself
- Use TodoWrite to track progress through large sets
- Use Task/subagents to chunk analysis

### SDK Capabilities Discovered

The SDK supports tools for self-managed chunking:

1. **`TodoWrite`** - Track progress through analysis
   ```python
   allowed_tools=["TodoWrite"]
   ```

2. **`Task`** - Spawn subagents for parallel/chunked work
   ```python
   allowed_tools=["Task"]
   ```

3. **`agents`** - Define custom subagent types
   ```python
   options = ClaudeAgentOptions(
       agents={
           "pattern-analyzer": AgentDefinition(
               description="Analyze a batch of patterns",
               prompt="Classify these patterns and return JSON...",
               tools=["Read"],
               model="haiku"  # Cheaper for batch work
           )
       }
   )
   ```

### Proposed Solution: Prompt Updates

Instead of complex Python scoring, **update the classification prompt** to guide Claude to:

1. **Not be limited to top N** - Look at all patterns intelligently
2. **Use TodoWrite** - Track analysis progress, manage context
3. **Prioritize intelligently** - Cross-project spread > raw occurrence count

#### Updated Prompt Template (key additions)

Add to `prompts/classification.md`:

```markdown
## Tools Available

- **TodoWrite**: Use this to track your progress through the analysis
- **Read**: Use this to read the patterns file if provided

## Analysis Strategy

You have {pattern_count} patterns to analyze.

### For Small Sets (< 50 patterns)
Analyze all patterns directly and return classifications.

### For Medium Sets (50-200 patterns)
1. Use TodoWrite to create a task list grouping patterns by type
2. Analyze each group, marking todos as you progress
3. Prioritize patterns that appear across multiple projects
4. Don't just look at occurrence count - a pattern in 5/36 projects
   with 20 occurrences may be MORE valuable than one in 1 project
   with 500 occurrences

### For Large Sets (200+ patterns)
1. Use TodoWrite to plan your analysis chunks
2. First pass: Quick scan to identify high-value patterns
   - Cross-project spread (appears in many projects)
   - Tool sequences (most actionable)
   - File access patterns (clear documentation candidates)
3. Second pass: Detailed classification of top candidates
4. Skip low-value patterns (single-project prompt phrases, etc.)

## Prioritization Guidelines

When deciding which patterns to classify in detail:

| Signal | Priority | Reasoning |
|--------|----------|-----------|
| Appears in 30%+ projects | HIGH | Global skill/doc candidate |
| Tool sequence pattern | HIGH | Most actionable |
| Appears in 3+ projects | MEDIUM | Cross-project value |
| File access pattern | MEDIUM | Clear doc candidate |
| Single-project pattern | LOW | Limited scope |
| Vague prompt phrase | LOW | Hard to action |

**Key insight**: A pattern in 5 projects with 20 occurrences > pattern in 1 project with 500 occurrences.

## Context Window Management

If analyzing many patterns:
- Don't try to hold all patterns in context at once
- Use TodoWrite to track which batches you've analyzed
- Summarize findings incrementally
- Focus on quality over quantity
```

### Code Changes Required

**`claude_client.py`** - Enable agentic tools:
```python
options = ClaudeAgentOptions(
    allowed_tools=["Read", "TodoWrite"],  # Enable chunking tools
    cwd=temp_dir,
    permission_mode='acceptEdits'
)
```

**`classifier.py`** - Pass pattern count, don't hard-limit:
```python
def build_classification_prompt(
    patterns: dict,
    num_projects: int,
    date_range: str,
    max_patterns: int | None = None,  # None = let Claude decide
) -> str:
    all_patterns = flatten_patterns(patterns)
    pattern_count = len(all_patterns)

    # For large sets, use file-based input (Investigation 1)
    if pattern_count > 100:
        patterns_input = "Read the patterns from `patterns.json`"
    else:
        patterns_input = f"```json\n{json.dumps(all_patterns)}\n```"

    return template.format(
        pattern_count=pattern_count,
        patterns_input=patterns_input,
        ...
    )
```

### Optional: Custom Subagent for Batch Analysis

For very large pattern sets, define a specialized subagent:

```python
options = ClaudeAgentOptions(
    allowed_tools=["Read", "TodoWrite", "Task"],
    agents={
        "batch-classifier": AgentDefinition(
            description="Classify a batch of patterns quickly",
            prompt="""You are a pattern classifier. Given a batch of patterns,
            return JSON classifications. Focus on actionability and cross-project spread.
            Be concise - this is a subtask of a larger analysis.""",
            tools=["Read"],
            model="haiku"  # Faster and cheaper for batch work
        )
    }
)
```

### Benefits of Prompt-based Approach

| Aspect | Python Scoring | Prompt-based |
|--------|---------------|--------------|
| Complexity | High (tunable weights) | Low (natural language) |
| Flexibility | Rigid formula | Claude adapts |
| Context management | Manual chunking | Claude manages via TodoWrite |
| Maintenance | Code changes | Prompt edits |
| Debuggability | Score values | Claude explains reasoning |

### Integration Points

1. **`prompts/classification.md`**: Add chunking strategy section
2. **`claude_client.py`**: Enable TodoWrite in allowed_tools
3. **`classifier.py`**: Remove hard max_patterns limit, pass pattern_count

---

## Implementation Recommendations

### Phase 1: Enable SDK Tools

**Effort**: 1-2 hours
**Impact**: Enables all subsequent improvements

1. Update `claude_client.py` to accept `ClaudeAgentOptions`
2. Enable `allowed_tools=["Read", "TodoWrite"]`
3. Set appropriate `cwd` and `permission_mode`

### Phase 2: Update Classification Prompt

**Effort**: 2-3 hours
**Impact**: Intelligent chunking without Python complexity

1. Add analysis strategy section to `prompts/classification.md`
2. Add prioritization guidelines (cross-project spread > raw count)
3. Add TodoWrite usage instructions for large sets
4. Remove hard `max_patterns` limit in `classifier.py`

### Phase 3: File-based Input (Scale)

**Effort**: 2-3 hours
**Impact**: 20x capacity increase

1. Add temp file writing logic to `classifier.py`
2. Update prompt to instruct Claude to read patterns file
3. Add fallback for tool execution failures

### Combined Result

With all improvements:
- Write 1000+ patterns to temp file
- Claude reads file via Read tool
- Uses TodoWrite to track progress through batches
- Intelligently prioritizes cross-project patterns
- Results cover all important patterns across the archive

---

## Testing Strategy

### SDK Tools Tests

```python
@pytest.mark.asyncio
async def test_tools_enabled():
    """Verify Read and TodoWrite tools are enabled."""
    patterns = generate_test_patterns(count=100)

    with patch_claude_client() as mock:
        result = await classify_patterns(patterns)

        # Verify tools were enabled
        assert "Read" in mock.options.allowed_tools
        assert "TodoWrite" in mock.options.allowed_tools

@pytest.mark.asyncio
async def test_file_based_classification():
    """Large pattern sets should use file-based approach."""
    patterns = generate_test_patterns(count=100)

    with patch_claude_client() as mock:
        mock.configure_read_tool_enabled()
        result = await classify_patterns(patterns)

        # Verify Read tool was offered
        assert "Read" in mock.options.allowed_tools

@pytest.mark.asyncio
async def test_fallback_on_tool_failure():
    """Should fall back to inline if file read fails."""
    patterns = generate_test_patterns(count=100)

    with patch_claude_client() as mock:
        mock.simulate_read_tool_failure()
        result = await classify_patterns(patterns)

        # Should still produce results via fallback
        assert len(result) > 0
```

### Prompt Content Tests

```python
def test_prompt_includes_pattern_count():
    """Prompt should include total pattern count for Claude."""
    patterns = generate_test_patterns(count=150)
    prompt = build_classification_prompt(patterns, num_projects=10)

    assert "150 patterns" in prompt or "pattern_count" in prompt

def test_prompt_includes_prioritization_guidelines():
    """Prompt should guide Claude on prioritization."""
    template = load_prompt_template()

    assert "cross-project" in template.lower()
    assert "TodoWrite" in template
```

---

## Appendix: Reference Documentation

- [Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [GitHub: claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python)
- Current implementation: `src/claude_code_archive/analyzer/classifier.py`
- Prompt template: `src/claude_code_archive/prompts/classification.md`
