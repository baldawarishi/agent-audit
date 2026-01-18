# Pattern Classification

You are analyzing workflow patterns from Claude Code sessions to generate actionable recommendations.

## Context

- **Total Projects**: {num_projects}
- **Date Range**: {date_range}
- **Pattern Count**: {pattern_count} patterns to analyze
- **Global Threshold**: Patterns appearing in {global_threshold_pct}% or more of projects should be scoped as "global"

## Tools Available

- **Read**: Use this to read the patterns file if provided (for large pattern sets)
- **TodoWrite**: Use this to track your progress through the analysis

## Input Patterns

{patterns_input}

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

## Classification Task

For each pattern you choose to classify, determine:

1. **category**: What type of recommendation this should become
   - `skill`: A repeatable workflow that should become a reusable skill (SKILL.md)
   - `claude_md`: Context or documentation that should be added to CLAUDE.md
   - `hook`: A validation or automation hook (pre/post tool use)

2. **scope**: Where the recommendation should be applied
   - `global`: Apply to ~/.claude/ (pattern appears in {global_threshold_pct}%+ of projects)
   - `project:{{name}}`: Apply to specific project's .claude/ directory
   - `subdir:{{path}}`: Apply to a subdirectory within a project

3. **confidence**: How confident the classification is
   - `high`: Clear pattern with obvious purpose and benefit
   - `medium`: Pattern is useful but may need human refinement
   - `low`: Uncertain classification, human review recommended

4. **reasoning**: Brief explanation of why this classification was chosen

5. **suggested_name**: A short, descriptive name for the skill/hook/doc section

6. **suggested_content**: The actual content to generate (SKILL.md, CLAUDE.md snippet, or hook config)

## Classification Guidelines

### Understanding Tool Names
Pattern keys use specific naming conventions:
- **Native tools**: `Read`, `Edit`, `Write`, `Grep`, `Glob`, `TodoWrite` - these are Claude Code's built-in tools
- **Bash commands**: `Bash:command` format (e.g., `Bash:git-status`, `Bash:grep`, `Bash:ls`) - these are shell commands run via Bash tool

**Important distinctions**:
- `Grep` (native tool) is already optimal - don't suggest migrating to itself
- `Bash:grep` (shell command) could potentially use the native `Grep` tool instead
- `Bash:git-*` commands are appropriate - git has no native tool equivalent

### Tool Sequences → Skills
- Repeated tool sequences (especially git workflows, build commands, test runs) are good skill candidates
- The sequence should represent a coherent workflow, not random tool usage
- Include the detected tool sequence as the basis for the skill's steps

### File Access Patterns → CLAUDE.md
- Files read repeatedly across sessions indicate important context
- Suggest documenting key information from these files in CLAUDE.md
- Configuration files, constants, and shared utilities are common candidates

### Prompt Patterns → Skills or CLAUDE.md
- Repeated prompt prefixes suggest recurring tasks → skill candidates
- Repeated explanatory phrases suggest missing documentation → CLAUDE.md candidates

### Content Brevity
Keep `suggested_content` concise and actionable:
- **Skills**: Include name, description, allowed-tools, and 3-5 clear steps
- **CLAUDE.md**: 1-2 paragraphs with key points, not exhaustive documentation
- **Hooks**: Just the hook configuration JSON
- Avoid lengthy examples or tutorials - focus on the essential guidance

### Scope Detection
- Count unique projects for each pattern
- If project_count / total_projects >= {global_threshold_pct}/100, scope is "global"
- Otherwise, if pattern appears in only one project, scope is "project:{{name}}"
- If pattern appears in a specific subdirectory consistently, scope is "subdir:{{path}}"

## Few-Shot Examples

### Example 1: Git Commit Workflow (Tool Sequence)

**Input Pattern:**
```json
{{
  "pattern_type": "tool_sequence",
  "pattern_key": "Bash:git-status -> Bash:git-diff -> Bash:git-add -> Bash:git-commit",
  "occurrences": 47,
  "project_count": 8,
  "projects": ["api-server", "web-client", "cli-tool", "docs", "shared-lib", "mobile-app", "data-pipeline", "infra"]
}}
```

**Output:**
```json
{{
  "pattern_key": "Bash:git-status -> Bash:git-diff -> Bash:git-add -> Bash:git-commit",
  "category": "skill",
  "scope": "global",
  "confidence": "high",
  "reasoning": "Git commit workflow appears in 8/10 projects (80%). This is a universal development pattern that benefits from automation.",
  "suggested_name": "commit-workflow",
  "suggested_content": "---\\nname: commit-workflow\\ndescription: Review and commit changes with a standard git workflow\\nallowed-tools: Bash(git *)\\n---\\n\\n# Commit Workflow\\n\\nFollow this sequence when committing changes:\\n\\n1. Check status: `git status`\\n2. Review changes: `git diff`\\n3. Stage files: `git add <files>` (or `git add .` for all)\\n4. Commit with descriptive message: `git commit -m \\"<type>: <description>\\"\\""
}}
```

### Example 2: Config File Access (File Pattern)

**Input Pattern:**
```json
{{
  "pattern_type": "file_access",
  "pattern_key": "~/project/src/config.py",
  "occurrences": 41,
  "project_count": 1,
  "projects": ["my-api"],
  "session_count": 15
}}
```

**Output:**
```json
{{
  "pattern_key": "~/project/src/config.py",
  "category": "claude_md",
  "scope": "project:my-api",
  "confidence": "medium",
  "reasoning": "Configuration file read 41 times across 15 sessions in a single project. Key settings should be documented in CLAUDE.md to reduce repeated file reads.",
  "suggested_name": "configuration-reference",
  "suggested_content": "## Configuration\\n\\nKey settings in `src/config.py`:\\n\\n- `DATABASE_URL`: PostgreSQL connection string\\n- `API_TIMEOUT`: Request timeout in seconds (default: 30)\\n- `DEBUG`: Enable debug mode (default: False)\\n\\nModify these settings via environment variables or directly in the config file."
}}
```

### Example 3: Test Workflow (Prompt Prefix)

**Input Pattern:**
```json
{{
  "pattern_type": "prompt_prefix",
  "pattern_key": "run the tests and",
  "occurrences": 23,
  "project_count": 4,
  "projects": ["web-client", "api-server", "shared-lib", "cli-tool"]
}}
```

**Output:**
```json
{{
  "pattern_key": "run the tests and",
  "category": "skill",
  "scope": "global",
  "confidence": "medium",
  "reasoning": "Test-related prompt appears across 4/10 projects (40%). A test-running skill would standardize the workflow.",
  "suggested_name": "run-tests",
  "suggested_content": "---\\nname: run-tests\\ndescription: Run project tests and report results\\nallowed-tools: Bash(npm test), Bash(pytest), Bash(cargo test)\\n---\\n\\n# Run Tests\\n\\n1. Detect project type (package.json, pyproject.toml, Cargo.toml)\\n2. Run appropriate test command\\n3. Report results summary\\n4. If failures, show relevant error details"
}}
```

### Example 4: Low Confidence Pattern

**Input Pattern:**
```json
{{
  "pattern_type": "prompt_phrase",
  "pattern_key": "make sure to check the",
  "occurrences": 5,
  "project_count": 2,
  "projects": ["project-a", "project-b"]
}}
```

**Output:**
```json
{{
  "pattern_key": "make sure to check the",
  "category": "claude_md",
  "scope": "global",
  "confidence": "low",
  "reasoning": "Phrase is too generic to determine specific intent. Could be about tests, linting, or other checks. Human review needed.",
  "suggested_name": "verification-checklist",
  "suggested_content": "## Verification Checklist\\n\\nBefore completing tasks, ensure:\\n\\n- [ ] Tests pass\\n- [ ] Linting passes\\n- [ ] Documentation updated\\n\\n(Please customize this checklist based on your specific workflow)"
}}
```

## Output Format

Return a JSON array of classified patterns:

```json
{{
  "classifications": [
    {{
      "pattern_key": "...",
      "category": "skill|claude_md|hook",
      "scope": "global|project:name|subdir:path",
      "confidence": "high|medium|low",
      "reasoning": "...",
      "suggested_name": "...",
      "suggested_content": "..."
    }}
  ]
}}
```

Respond ONLY with the valid, parseable JSON object, no additional text.
