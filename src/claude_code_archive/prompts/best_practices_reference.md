# Claude Code Best Practices Reference

This document catalogs key best practices from official Anthropic documentation. Use this as a checklist when validating synthesis recommendations for coverage gaps.

---

## 1. Verification & Testing

**Description**: Always validate outputs before presenting them. Run tests, sanity-check data, and verify implementation correctness.

**Keywords**: test, verify, validate, check, sanity, confirm, CI, build, lint

**Why it matters**: The highest-leverage improvement is asking Claude to verify its work before presenting it. This catches errors early, prevents rework loops, and builds trust.

**Recommendation should include**:
- Running tests before presenting "done"
- Validating numerical outputs against expectations
- Checking edge cases explicitly
- Confirming changes compile/build successfully

---

## 2. Context Management

**Description**: Use `/clear` and `/compact` to manage context window. Clear context when switching tasks to prevent confusion and token waste.

**Keywords**: clear, compact, context, reset, fresh, new conversation

**Why it matters**: Accumulated context from previous tasks can confuse Claude, waste tokens on irrelevant history, and cause Claude to follow outdated approaches.

**Recommendation should include**:
- Using `/clear` when switching between unrelated tasks
- Using `/compact` when context grows large but continuity is needed
- Recognizing when accumulated context is causing confusion

---

## 3. Plan Mode

**Description**: Use `/plan` or plan mode for complex multi-step tasks. Let Claude think through the approach before implementing.

**Keywords**: plan, plan mode, think first, design, architecture, approach, strategy

**Why it matters**: Planning before implementing prevents wasted work from wrong approaches, helps identify edge cases upfront, and improves solution quality.

**Recommendation should include**:
- Entering plan mode for tasks requiring 3+ files or complex logic
- Reviewing Claude's plan before approving implementation
- Using plan mode to explore unfamiliar codebases

---

## 4. Course Correction

**Description**: Use Escape key to interrupt Claude, and conversation rewind to undo mistakes. Don't let Claude continue down wrong paths.

**Keywords**: escape, interrupt, undo, rewind, stop, correct, wrong direction

**Why it matters**: Letting Claude continue on a wrong path wastes tokens and creates code that needs to be reverted. Early interruption saves significant effort.

**Recommendation should include**:
- Pressing Escape as soon as Claude's approach looks wrong
- Using conversation rewind (click trash icon on messages) to undo mistakes
- Not waiting for Claude to finish before course-correcting

---

## 5. CLAUDE.md Best Practices

**Description**: Keep CLAUDE.md brief (10-15 lines) with project-specific rules Claude can't infer. Use skills for detailed workflows.

**Keywords**: CLAUDE.md, project rules, instructions, guidelines, memory

**Why it matters**: CLAUDE.md loads every session, so keeping it small reduces token usage. Detailed guidelines belong in skills which load on-demand.

**Recommendation should include**:
- Project-specific conventions (naming, file structure)
- Build/test commands if non-standard
- Links to key documentation
- Avoiding lengthy explanations (use skills instead)

---

## 6. Extended Thinking

**Description**: Configure thinking mode (concise/verbose/none) based on task complexity. Use verbose thinking for complex architectural decisions.

**Keywords**: thinking, extended thinking, reasoning, deep analysis, complex

**Why it matters**: Extended thinking improves quality on complex tasks but adds latency and tokens for simple tasks. Matching thinking level to task complexity optimizes both.

**Recommendation should include**:
- Using extended thinking for architectural decisions
- Using concise thinking for routine code changes
- Recognizing when a task needs deeper analysis

---

## 7. Prompt Specificity

**Description**: Be specific in prompts. Include file paths, function names, expected behavior, and constraints upfront.

**Keywords**: specific, explicit, clear, detailed prompt, constraints, requirements

**Why it matters**: Vague prompts lead to Claude exploring multiple approaches or making wrong assumptions. Specific prompts get right answers faster.

**Recommendation should include**:
- Specifying exact file paths when known
- Describing expected behavior clearly
- Mentioning constraints (performance, compatibility, style)
- Providing examples when helpful

---

## 8. Subagent Usage

**Description**: Use subagents (Task tool) for parallelizable work and isolated explorations. Keeps main context clean.

**Keywords**: subagent, task, parallel, background, explore, fork

**Why it matters**: Subagents run in isolated context, preventing main conversation pollution. Parallel subagents can dramatically speed up multi-file explorations.

**Recommendation should include**:
- Using subagents for searching/exploring unfamiliar code
- Running independent tasks in parallel
- Keeping main context focused on primary task

---

## 9. CLI Tools Integration

**Description**: Use Claude Code's CLI tools (Bash, Read, Write, Edit) effectively. Prefer Edit over full file rewrites.

**Keywords**: bash, read, write, edit, glob, grep, cli, command

**Why it matters**: Using the right tool for each operation saves tokens and prevents errors. Edit operations are more precise than full file rewrites.

**Recommendation should include**:
- Using Edit for targeted changes vs Write for full rewrites
- Using Glob/Grep for code search vs manual navigation
- Leveraging Bash for build/test/git operations

---

## 10. Automation & Headless Mode

**Description**: Use headless mode (`-p` flag, `--allowedTools`) for automated workflows. Combine with CI/CD for powerful automation.

**Keywords**: headless, automation, -p flag, batch, CI, script, pipe

**Why it matters**: Automating repetitive Claude tasks (code review, test generation, documentation) saves human time and ensures consistency.

**Recommendation should include**:
- Using `-p` flag for single-prompt automation
- Configuring `--allowedTools` for safe automation
- Integrating with git hooks or CI pipelines

---

## 11. Interview Pattern

**Description**: Start feature work with an interview: ask Claude to ask questions about requirements before implementing.

**Keywords**: interview, requirements, clarify, questions, understand first

**Why it matters**: Having Claude ask clarifying questions surfaces ambiguities and edge cases before implementation, reducing rework.

**Recommendation should include**:
- Prompting Claude to ask 3-5 clarifying questions before starting
- Answering questions to refine requirements
- Using the interview to identify edge cases

---

## Usage Notes

When validating synthesis recommendations:

1. **Check coverage**: Does the synthesis have recommendations covering each of these 11 areas?
2. **Identify gaps**: Which areas have no corresponding recommendation?
3. **Generate proactive recommendations**: For gaps, create recommendations even if session data doesn't explicitly show the anti-pattern - these are proactive best practices.

A comprehensive synthesis should touch on at least 6-8 of these areas based on universal applicability.
