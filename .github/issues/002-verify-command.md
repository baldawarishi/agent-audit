# `verify` — Run a verification pipeline on session changes using dynamically-determined sub-agents informed by transcript analysis

## Problem

After an agent makes changes across one or more sessions, there's no automated way to verify that **the change itself is correct**. Not "did the agent behave well" (that's `diagnose`), but "does this code work, is it complete, is it consistent across sessions."

The transcripts tell you what was intended and how much changed. The repo state tells you what actually changed. Together they inform what kind of verification is needed — you don't spin up a 4-agent security panel for a README edit, and you don't run a single linter pass for an auth system refactor.

The roles, agent count, scope, convergence criteria, and run counts should all be **determined dynamically** based on what the transcripts and changes actually contain — not from a hardcoded menu.

## CLI

```bash
# Verify from specific sessions
agent-audit verify --session <id> [--session <id2> ...]
agent-audit verify --project <name> [--since <date>]

# Auto-detect current active session (no args)
agent-audit verify

# Override auto-detected complexity
agent-audit verify --level full
agent-audit verify --level simple

# Control minimum repeated runs for confidence
agent-audit verify --runs 3
```

**Hard rules:**
- No `--plan`, no `--apply`. Single command, runs end-to-end, produces a report.
- No `--repo`, `--commits`, `--branch` flags. Agents discover the scope themselves from transcripts and repo access.
- No `--session` given: auto-detect the active session from the CWD project path (`~/.claude/projects/<project-path>/`). If no active session detected, hard error.
- `--level` and `--runs` are overrides passed to the planning agent as constraints — they don't bypass the planner, they constrain it.

## How it works

The pipeline has one planning phase and one execution phase. The planning phase is itself an agent call that reads the transcripts and determines *everything* about how verification should proceed.

### Phase 1: Verification Planning (single agent call)

A planning agent receives:
- The full session transcript(s)
- Access to the repo (to run git commands, read files, inspect state as it sees fit)
- Research context on multi-agent verification (linked below in References)

It produces a verification plan that answers **five questions**:

#### 1. What roles are needed?

Not from a fixed menu. The planner reads the transcript, understands what the agent did, and determines what perspectives are needed to verify *this specific change*. A database migration might need a "schema consistency" role and a "data integrity" role. An auth refactor might need "security" and "behavioral equivalence." A CSS redesign might need just "visual regression." The roles are **invented for the task**, described in natural language, and may not map to any predefined category.

In practice, the planner will likely converge on a small set of recurring perspectives (correctness, regression, security, consistency) — and that's fine. **The real value isn't novel role names; it's that the planner writes scoped instructions specific to the change.** A "security" check for an auth refactor gets completely different instructions than a "security" check for a file upload feature. The specificity of scope-per-role is the differentiator.

#### 2. How many agents?

Based on the scope and the distinct perspectives needed. Research shows gains saturate beyond ~4 without structured coordination, and unstructured multi-agent can perform worse than single-agent. The planner should internalize these tradeoffs (see References below).

#### 3. What should each agent look at?

Each agent gets a scoped focus derived from the transcript. Not "look at everything" but "session 2 changed the auth middleware — verify the token validation logic against the test suite and check if the API contract changed." Specificity comes from transcript understanding.

#### 4. What details do we converge on?

What constitutes a "pass"? What findings matter vs. noise? The planner defines convergence criteria per check:
- For some checks it's binary (tests pass or don't)
- For others it's judgment-based (is the refactor complete?)
- The planner decides the consolidation strategy — majority vote, unanimous agreement, or orchestrator judgment

This is informed by research showing that noisy verification gets ignored (see OpenAI reference below). Precision matters more than recall.

#### 5. How many runs are necessary?

Per check, not globally. A deterministic check (run tests) needs 1 run. A judgment-based check (is this refactor complete?) benefits from 3+ independent runs to surface disagreement. The planner decides based on how subjective each check is.

**Known risk:** The planner is doing a lot in one call — all five questions. This is ironic given the research it's built on (Qodo's insight: "a single LLM struggles because it conflates distinct cognitive tasks"). For v1, use structured output that forces the planner through each question sequentially. If planner quality becomes a bottleneck, split into a scope assessment step and a verification design step.

### Phase 2: Verification Execution

The orchestrator executes the plan:
- Spawns agents with the roles, scope, and instructions defined by the planner
- Each agent gets transcript(s) + repo access and discovers details within its assigned scope
- Agents are autonomous about scope discovery — some will run `git diff`, some will `git log`, some will just read the transcript and reason about intent
- Runs repeated checks where the plan calls for it
- Consolidates findings per the convergence criteria defined in the plan

### Phase 3: Report

Stored at `archive/reports/verify/YYYYMMDD-HHMMSS/report.md` (follows existing `archive/analysis/run-YYYYMMDD-HHMMSS/` convention). Summary printed to terminal.

**The report MUST have a one-line verdict at the top:** `PASS`, `FAIL`, or `NEEDS REVIEW (N findings)`. If the user has to read 200 lines to figure out "can I merge this?", the report won't be used. Detail below the verdict.

The report includes:
- **Top-line verdict** (PASS / FAIL / NEEDS REVIEW)
- **Planner reasoning** (why these roles, why this many agents, why these convergence criteria)
- **Per-check results** with agreement rates where repeated runs were used
- **Findings** with severity and specificity
- **Areas flagged for human judgment**

Example repeated-run output:
```
## check_3 — Correctness (3 runs)
- Agreement: 3/3 → PASS
- Effective error rate: ~0.03 (vs ~0.1 single run)
- Consensus: Migration complete. All 14 files correctly updated.

## check_5 — Security (2 runs)
- Agreement: 1/2 → NEEDS REVIEW
- Run 1: PASS — token caching follows existing patterns
- Run 2: FAIL — cached tokens not invalidated on password change
- Action: Human review required.
```

Over time, across multiple verify runs, agreement data accumulates and can inform better default run counts per check type.

## Current session support (Mode B)

`verify` supports verifying the current in-progress session (not just completed sessions). When no `--session` is given, auto-detect from CWD project path.

Note: when verifying the current session, the verification agents' work becomes part of the same transcript. This means `diagnose` run later on that session will see both the original work and the verification. This is fine — but `diagnose` should be aware of this distinction so it doesn't recommend "improvements" to the verification phase.

## References — Research context for the planning agent prompt

The planning agent's system prompt should reference this research. Link these in the issue and embed key findings in the prompt so implementers and the agents picking up this work have grounding context.

### On agent count and topology

- **[DeepMind: "Towards a Science of Scaling Agent Systems"](https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/)** — Accuracy saturates or fluctuates beyond ~4 agents without structured topology. Five coordination topologies matter: Single-Agent (SAS), Independent MAS, Decentralized MAS, Centralized MAS, Hybrid MAS. Topology matters more than agent count.
- **["Single-agent or Multi-agent Systems? Why Not Both?"](https://arxiv.org/pdf/2505.18286)** (arXiv 2025) — LLM-based complexity scoring to route between single and multi-agent. MAS outperforms on complex tasks, SAS remains more efficient for simple ones. Performance gains from MAS increase substantially as task complexity rises.
- **[ICLR 2025: Multi-agent debate scaling challenges](https://d2jud02ci9yv69.cloudfront.net/2025-04-28-mad-159/blog/mad/)** — Debate frameworks don't consistently outperform self-consistency when compute is equalized. Benefit comes from structured specialization, not more agents arguing.

### On fuzzy/dynamic roles

- **[CodeAgent (EMNLP 2024)](https://aclanthology.org/2024.emnlp-main.632/)** — Six roles across four sequential phases with QA-Checker supervisor. 92.96% hit rate on vulnerability analysis. Key insight: instructor-assistant pairs with drift prevention via Newton-Raphson optimization.
- **[Qodo 2.0](https://www.qodo.ai/blog/introducing-qodo-2-0-agentic-code-review/)** — 12+ specialized agents, each in dedicated context window with domain knowledge. Orchestrator determines which experts to activate based on PR nature. Judge layer resolves conflicts. Core insight: "A single LLM struggles with comprehensive review because it conflates distinct cognitive tasks."
- **["From Persona to Personalization"](https://arxiv.org/html/2404.18231v1)** (Survey 2024) — LLMs as "superpositions of beliefs and personas." Role-playing mechanisms make behavior more consistent with role responsibilities and thinking patterns.

### On verification precision and convergence

- **[OpenAI: "A Practical Approach to Verifying Code at Scale"](https://alignment.openai.com/scaling-code-verification/)** — Verification consumes far fewer tokens than generation but catches most high-severity issues. **Precision over recall** — defenses fail when they're too noisy. When the reviewer leaves a comment, authors address it with a code change 52.7% of the time. Steerability via custom instructions or repo-level AGENTS.md.
- **[Anthropic: Alignment Auditing Agents](https://alignment.anthropic.com/2025/automated-auditing/)** — Super-agent aggregation across multiple independent investigations improved success from 13% to 42%. Full transcript preservation for auditability.

### On diff-based and commit-based review

- **[Baz.co: Building an AI Code Review Agent](https://baz.co/resources/building-an-ai-code-review-agent-advanced-diffing-parsing-and-agentic-workflows)** — Three technical layers: difftastic (syntax-aware parsing), tree-sitter (historical AST tracking with persistent IDs), git (versioning). Repo-aware review outperforms diff-only.
- **[ICSE 2025: Automated Code Review In Practice](https://arxiv.org/html/2412.18531v2)** — 73.8% of LLM review comments accounted for in PRs across 22 repos. Better at detecting functional errors than other categories.

### On complexity routing

- **[MasRouter (ACL 2025)](https://aclanthology.org/2025.acl-long.757.pdf)** — Production-validated approach to routing between agent configurations for optimal cost-performance tradeoffs.
- **[Qodo 2.0 orchestrator](https://www.qodo.ai/blog/introducing-qodo-2-0-agentic-code-review/)** — Orchestrator determines which expert agents to activate based on the PR's nature. Documentation updates don't trigger deep security analysis; payment flow changes demand it.
- **[LangChain State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)** — 57% of respondents have agents in production. Human review (59.8%) remains most common. LLM-as-judge (53.3%) increasingly used. Only 52% have adopted formal evals.

## Relationship to `diagnose`

Loosely related. Shared transcript parsing infrastructure. Different goals.

| | `diagnose` | `verify` |
|---|---|---|
| **Question** | "What was the agent missing?" | "Is the change correct?" |
| **Focus** | Agent's knowledge gaps | Code's correctness |
| **Input** | Session transcripts (deep-read) | Transcripts + repo state |
| **Output** | Reviewable plan with checkboxes | Verification report with verdict |
| **Workflow** | Plan → review → apply | Single command → report |
| **When to use** | After a frustrating session | Before merging/shipping |

`verify` is purely diagnostic — it produces a report, not fixes. If someone wants fixes, they take the report into their next session or feed it to `diagnose`.

## Implementation notes

- New Click command in `cli.py`
- New prompt templates in `prompts/`:
  - `verify_planner.md` — the planning agent prompt with research context embedded and structured output format that forces sequential answering of the 5 questions
  - `verify_agent.md` — base template for spawned verification agents, parameterized by role and scope
  - `verify_consolidation.md` — judge/consolidation prompt for resolving conflicts and producing the report
- Use `AnalyzerClaudeClient` for agent calls; extend if needed for parallel agent spawning
- Session auto-detection: scan `~/.claude/projects/` for active session matching CWD
- Report to `archive/reports/verify/YYYYMMDD-HHMMSS/report.md`
- `--level` override: passed to the planner as a constraint ("user wants full verification regardless of your complexity assessment")
- `--runs` override: passed to the planner as a minimum ("use at least N runs per agent check")

## Key modules to modify/extend

- `src/agent_audit/cli.py` — new `verify` command
- `src/agent_audit/prompts/` — new `verify_planner.md`, `verify_agent.md`, `verify_consolidation.md`
- `src/agent_audit/analyzer/` — new verification pipeline module (planner, agent spawner, orchestrator, consolidator)
- `src/agent_audit/analyzer/claude_client.py` — extend for multi-agent spawning if needed
- `tests/` — tests for planning, agent execution, consolidation, report format
