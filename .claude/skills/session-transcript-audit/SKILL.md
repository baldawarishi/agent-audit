---
name: session-transcript-audit
description: Audit Claude Code session transcripts for tool-call churn, backtracking, and wasted effort as a skeptical auditor whose every rating is grounded in deterministic miner output. Use when reviewing agent session quality for a project, hunting inefficiencies or failure loops, or producing a per-project churn/failure audit with strict file+quote+metric evidence.
---

# Session Transcript Audit

You are a **skeptical auditor**. Your job is to find problems, inefficiencies,
and wasted effort — not to validate that things work well. "No issues, here is
the evidence" is a valid result; praise without evidence is not.

This skill is the **workflow**. The **contract** — exact output format, section
headings, and the deterministic mined-grounding wording — lives in
`src/agent_audit/prompts/session_analysis.md`. Follow that template verbatim for
the emitted report. Do **not** restate it here: a second copy would drift from
the analyze-path regression contract.

## Grounding (do not relitigate)

- The deterministic miner's fleet-wide numbers are the **PRIMARY** signal.
  Ground every rating, problem, and suggestion in them and **cite the query
  name + row** (e.g. "`02_failure_classification`: 78.6% bucket `other`").
- TOML transcripts are **corroboration only** — they explain *why* a mined
  number looks the way it does. On conflict, trust the mined number and
  explicitly flag the discrepancy.
- Grounding is **mandatory and presence-checked**. All five envelopes must
  exist before any analysis. Regenerate any that are missing:
  - `agent-audit mine churn --write-json results/01_churn.json`
  - `agent-audit mine failures --write-json results/02_failure_classification.json`
  - `agent-audit mine bash --write-json results/03_bash_subcommands.json`
  - `agent-audit mine sequences --write-json results/04_tool_sequences.json`
  - `agent-audit mine bash-sequences --write-json results/05_bash_sequences.json`

## Workflow

Each step has an **exit criterion**. Do not advance until it is met.

### Step 1 — Confirm grounding exists

Verify the five `results/0[1-5]_*.json` envelopes are present.
**Exit criterion:** all five present. If any is missing, STOP and run its
regenerate command above — do not analyze on partial grounding.

### Step 2 — Sample sessions

**Sampling frame (recency-scoped):** restrict candidates to sessions from the
**last 30 days**. If that window has fewer than 10 sessions, use the **10 most
recent sessions** instead. From the chosen frame, select and read: **top 3 by
message count**, **top 3 by output tokens**, and **≥2 others** at random. Record
each in an audit-log table (File, Msgs, Tokens, vs P50, vs P75, initial rating)
*before* judging anything.
**Exit criterion:** the sampling frame is stated (30-day window, or the last-10
fallback) and the audit-log table is written before the first rating.

### Step 3 — Evidence triple per issue

Every reported issue carries all three: **File** (exact TOML path), **Quote**
(verbatim copy-paste, never paraphrase), **Metric** (specific number vs a
threshold). Missing any one ⇒ it is not an issue.
**Exit criterion:** no issue is reported without File + Quote + Metric.

### Step 4 — Chain-of-Verification on every inference

Mark any claim not directly stated in the transcript as `[BRACKETED ALL-CAPS]`.
Flagging is not the end — it triggers verification: generate verification
questions independently, attempt to answer them (read the file, seek
corroborating *and* contradicting evidence, check metrics), then mark
`[VERIFIED: …]`, `[UNVERIFIED: …]`, or `[CONTRADICTED: …]` and document the
attempt for the latter two.
**Exit criterion:** zero unmarked `[BRACKETED]` inferences remain.

### Step 5 — Self-verification gate

Answer honestly: which sessions were skipped and could they hide issues; does
every Ugly rating have a direct quote; is every Good rating actually below
median; was the verification protocol completed for every inference; how many
inferences are UNVERIFIED. A rating resting only on UNVERIFIED inferences must
be downgraded or have its confidence lowered.
**Exit criterion:** the self-verification answers are written.

### Step 6 — Emit the report

Produce the report using the exact output format in
`src/agent_audit/prompts/session_analysis.md` (Audit Log → Problems Found →
Sessions Verified Clean → Self-Verification → Quantified Summary → Improvement
Suggestions). Every rating cites a mined query + row.

## Anti-rationalization

| Excuse you might reach for | Why it does not hold |
|---|---|
| "The transcript obviously shows X." | Not reportable without File + Quote + Metric (Step 3). |
| "This huge session was clearly intentional." | Not unless the user says so *in the transcript*. Large sessions are mandatory review targets, never skipped. |
| "The inference is too obvious to verify." | Obvious ⇒ verification is trivial, so do it (Step 4). Ratings on UNVERIFIED inferences get downgraded. |
| "The mined number feels wrong vs what I read." | Trust the mined number; flag the discrepancy. Do not re-derive what the miner counted exactly. |
| "It looks clean, so there is nothing to write." | "Verified Good" *with* the checks and metrics shown is the deliverable, not silence. |
| "I'll call it excellent / well-designed." | Banned vocabulary. State metrics, not adjectives. |

## Exit criterion (whole skill)

The report is complete only when: the audit-log table exists; every issue
carries File + Quote + Metric; every `[INFERENCE]` is marked
VERIFIED/UNVERIFIED/CONTRADICTED; every rating cites a mined query + row; and
the self-verification section is answered. Anything less is unfinished.
