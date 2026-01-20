# Session Analysis

You are analyzing archived Claude Code sessions for the **{project}** project to identify patterns, inefficiencies, and optimization opportunities.

## Context

**Project Metrics:**
- Sessions: {session_count}
- Total turns: {turn_count} (user + assistant exchanges)
- Input tokens: {input_tokens:,}
- Output tokens: {output_tokens:,}
- Tool calls: {tool_call_count}

**Session Transcripts:**
- Location: `{toml_dir}`
- Format: TOML files containing full conversation transcripts

## Session Quality Heuristics

Use these heuristics to categorize sessions:

| Quality | Indicators |
|---------|------------|
| **Good** | Few turns, low tokens, task completed efficiently |
| **Okay** | Medium turns/tokens, some iteration or clarification needed |
| **Ugly** | Many turns, high tokens, back-and-forth struggles, restarts, or undoing work |

## Your Task

1. **Read session transcripts** from `{toml_dir}` using the Read tool
2. **Sample sessions** - you don't need to read all {session_count} sessions:
   - Start with 3-5 sessions to get a feel for the project
   - If patterns emerge, focus on sessions that seem problematic (high turns/tokens)
   - Read more if needed to confirm patterns
3. **Analyze each session** you read for:
   - What was the user trying to accomplish?
   - How efficiently was it accomplished?
   - What went well? What didn't?
   - Were there unnecessary iterations or struggles?

## Output Format

Generate a markdown document with these sections:

### 1. Executive Summary
A 2-3 sentence overview of the project's session health and key findings.

### 2. Session Summaries
For each session you analyzed in detail:

```
#### Session: {slug or id}
- **File**: `{toml_file_path}`
- **Turns**: X | **Tokens**: Y input / Z output
- **Quality**: Good/Okay/Ugly
- **Task**: What the user was trying to do
- **Outcome**: Whether/how it was accomplished
- **Notes**: Key observations about efficiency or struggles
```

### 3. Patterns Observed
List recurring patterns you noticed across sessions:
- Common tasks users perform
- Tools frequently used together
- Repeated workflows or questions
- Common points of friction or confusion

### 4. Potential Optimizations
Pragmatic, actionable suggestions:
- CLAUDE.md additions (context that would help)
- Skill candidates (repeated workflows worth automating)
- Common mistakes to document
- Workflows that could be streamlined

**Important**: Keep optimizations realistic and grounded in what you observed. Avoid generic advice.

## Guidelines

- Be specific - reference actual session content and file paths
- Be pragmatic - suggest things that would actually help, not theoretical improvements
- Be honest - if sessions look fine, say so; don't invent problems
- Include file paths so humans can dig deeper into specific sessions
- Focus on patterns that appear multiple times, not one-off issues
