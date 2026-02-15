# Session Debrief Guide

## What This Is

A context bundle for writing about a coding session. All the raw material is in the `context/` directory. Your job is to interview the author, research the session, and produce a draft.

This isn't necessarily a blog post — the output might be an internal writeup, a team update, a newsletter entry, or notes for the author's own records. The format is up to the author.

**Start with voice.** Before writing anything, understand how the author writes. The biggest failure mode is producing text that sounds like AI, not like the author.

## Session Overview

- **Summary**: {summary}
- **Project**: {project}
- **Timeframe**: {started_at} → {ended_at}
- **Repository**: {repo}
- **Session ID**: {session_id}

## What Happened

{what_happened}

These are observations from the data, not a story arc. The actual narrative — if there is one — comes from the interview.

## Context Inventory

Load these files to understand the session:

| File | Description |
|------|-------------|
| `context/primary-session.toml` | Full transcript of the primary session (messages, tool calls, thinking) |
{preanalysis_entry}{related_sessions_entry}| `context/metrics.md` | Session statistics: token counts, message counts, tool usage breakdown |
{git_log_entry}{pr_entries}
{thinking_block_note}

## Voice First

Before writing a single sentence of draft, do this:

### Step 1: Collect reference material

Ask the author for 1-2 pieces they've written that represent their voice. These could be blog posts, internal docs, emails, Slack messages — anything with enough text to show patterns.

### Step 2: Internalize voice patterns

Read the reference material and note:
- Sentence length and variation
- How they introduce technical concepts (assume reader knowledge? build up from basics?)
- First person usage (I vs we vs passive)
- Transitions between ideas
- Humor, if any — and what kind
- What they DON'T do (equally important)

### Step 3: Voice contract

Before writing, state back to the author:
- "Your writing tends to [observations]"
- "You avoid [anti-patterns]"
- "I'll aim for [specific targets]"

Get explicit confirmation before proceeding.

## Writing Anti-Patterns

These are common AI writing tells. Avoid them:

- **Bold bullet-point takeaways** — Don't summarize lessons as bold-faced bullet lists
- **Thesis-then-evidence uniformity** — Not every paragraph needs to state a point then support it
- **Pithy epigrams or aphorisms** — "In the end, the real bug was the assumptions we made along the way"
- **Signposted observations** — "This is where things get interesting" / "Here's the key insight"
- **Direct meta-commentary** — "This is a pattern I notice" / "What's fascinating about this"
- **Kitchen-sink completeness** — Pick the real story. Don't cover everything that happened
- **Uniform paragraph length** — Vary it. Short paragraphs hit differently
- **Manufactured drama** — If the session was straightforward, say so. Don't inflate

Not every session has a story worth telling. If after reviewing the transcript and talking to the author, there's no clear angle or insight — say so. It's better to produce nothing than to manufacture a narrative that isn't there.

## Interview

Start with these questions, which are tailored to this session's data:

{session_specific_questions}

Then use the generic framework below for areas the session-specific questions don't cover. Skip questions the transcript already answers clearly.

### Motivation & Audience
- Why write about this session specifically? What makes it worth sharing?
- Who should read this? What should they take away?
- Is there a broader argument or thesis this session illustrates?

### Key Decisions & Trade-offs
- What decisions aren't obvious from reading the code changes?
- Were there approaches you considered and rejected? Why?
- What constraints shaped the implementation (time, compatibility, team preferences)?

### Surprises & Lessons
- What was harder or easier than expected?
- What would you do differently with hindsight?
- Did the AI agent do anything unexpected (helpful or unhelpful)?

### Connections
- How does this session relate to your broader work or learning goals?
- Are there follow-up sessions or open threads worth mentioning?
- Does this connect to industry trends, debates, or recent developments?

## Choose Your Depth

Before starting, pick a depth level. All levels start with Voice First.

### Light
1. **Voice First** — Complete the Voice First steps above
2. **Interview** (3-5 questions) — Focus on motivation, key decisions, and one surprise
3. **Draft** — Write from transcript + interview answers

### Medium
1. **Voice First** — Complete the Voice First steps above
2. **Interview** (5-15 questions) — Cover motivation, decisions, trade-offs, and lessons
3. **Research** — Search for related work, prior art, practitioner posts on the topic
4. **Draft** — Write with citations, code snippets, and links to PRs/commits
5. **Polish** — Tighten prose, verify all claims against transcript evidence, self-check against Writing Anti-Patterns

### Deep
1. **Voice First** — Complete the Voice First steps above
2. **Interview** (adaptive, up to 25 questions) — Extensive exploration of decisions, alternatives considered, audience, voice, and broader connections
3. **Research** — Deep search for industry context, academic papers, conference talks, competing approaches
4. **Draft** — Write with thorough sourcing, annotated code snippets, and narrative arc
5. **Fact-check** — Cross-reference every claim against transcript, git log, and PR data
6. **Voice polish** — Re-read against reference material, eliminate AI voice, self-check against Writing Anti-Patterns

## Research Guidelines

When researching (Medium and Deep depths):

- Search for related work: blog posts, conference talks, documentation, papers
- Look for prior art on the specific techniques or patterns used in the session
- Find practitioner perspectives on the trade-offs encountered
- Cite reputable sources with links
- Note when the session's approach differs from common practice (and why that matters)
- **Verify all factual claims against the transcript. Mark uncertain claims with [VERIFY].**

## Output Conventions

- Write all drafts to the `drafts/` directory
- Name them `draft-v1.md`, `draft-v2.md`, etc.
- Each draft should be a complete, standalone markdown file
- Include a YAML front matter block with title, date, and tags
- The final format is up to the author — blog post, internal doc, newsletter, team update, whatever fits
- After each draft, self-check against Writing Anti-Patterns above

## Iteration Log

| # | Date | Phase | Notes |
|---|------|-------|-------|
| 1 | {today} | Setup | Context bundle prepared. Ready for Voice First. |
