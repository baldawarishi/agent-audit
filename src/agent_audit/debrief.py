"""Debrief context gathering and session guide generation."""

import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from .database import Database
from .models import Message, Session, ToolCall, ToolResult
from .toml_renderer import render_session_toml


def discover_related_sessions(
    db: Database, primary_session: dict, max_results: int = 10
) -> list[dict]:
    """Find sessions related to the primary session.

    Queries for sessions in the same project, ordered by date proximity
    to the primary session. Excludes the primary session itself.
    """
    project = primary_session["project"]
    sessions = db.get_sessions_by_project(project)
    # Filter out the primary session
    sessions = [s for s in sessions if s["id"] != primary_session["id"]]

    if not sessions:
        return []

    # Sort by date proximity to primary session
    primary_started = primary_session.get("started_at") or ""

    def date_distance(s: dict) -> float:
        s_date = s.get("started_at") or ""
        if not s_date or not primary_started:
            return float("inf")
        try:
            p_dt = datetime.fromisoformat(primary_started.replace("Z", "+00:00"))
            s_dt = datetime.fromisoformat(s_date.replace("Z", "+00:00"))
            return abs((p_dt - s_dt).total_seconds())
        except (ValueError, TypeError):
            return float("inf")

    sessions.sort(key=date_distance)
    return sessions[:max_results]


def gather_git_context(
    cwd: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> str:
    """Gather git log for the session's timeframe.

    Runs git log in the session's working directory. Returns formatted
    markdown string. Gracefully returns empty string if git is unavailable
    or the directory doesn't exist.
    """
    if not cwd or not Path(cwd).is_dir():
        return ""

    if not shutil.which("git"):
        return ""

    cmd = ["git", "log", "--oneline", "--no-decorate"]
    if start_date:
        # Strip time component for git's --after flag
        after = start_date[:10] if len(start_date) >= 10 else start_date
        cmd.extend(["--after", after])
    if end_date:
        before = end_date[:10] if len(end_date) >= 10 else end_date
        cmd.extend(["--before", before])

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""

        lines = result.stdout.strip().split("\n")
        formatted = "# Git Log\n\n"
        formatted += f"Working directory: `{cwd}`\n"
        if start_date:
            formatted += f"After: {start_date[:10]}\n"
        if end_date:
            formatted += f"Before: {end_date[:10]}\n"
        formatted += f"\n{len(lines)} commits:\n\n"
        formatted += "```\n"
        formatted += "\n".join(lines)
        formatted += "\n```\n"
        return formatted
    except (subprocess.TimeoutExpired, OSError):
        return ""


def gather_pr_context(
    repo: Optional[str],
    repo_platform: Optional[str],
    commits: list[dict],
) -> list[tuple[int, str]]:
    """Find PRs associated with the session's commits/repo.

    Uses `gh pr list` or `gh pr view` to find related PRs. Returns list of
    (pr_number, pr_markdown) tuples. Gracefully returns empty list if `gh`
    is unavailable or no PRs are found.
    """
    if not repo or repo_platform != "github":
        return []

    if not shutil.which("gh"):
        return []

    prs: list[tuple[int, str]] = []
    seen_pr_numbers: set[int] = set()

    # Try to find PRs by searching commit hashes
    for commit in commits:
        commit_hash = commit.get("commit_hash", "")
        if not commit_hash:
            continue

        try:
            result = subprocess.run(
                [
                    "gh", "pr", "list",
                    "--repo", repo,
                    "--search", commit_hash,
                    "--state", "all",
                    "--json", "number,title,url,state,body",
                    "--limit", "5",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue

            pr_data = json.loads(result.stdout)
            for pr in pr_data:
                pr_num = pr.get("number", 0)
                if pr_num and pr_num not in seen_pr_numbers:
                    seen_pr_numbers.add(pr_num)
                    md = _format_pr_markdown(pr, repo)
                    prs.append((pr_num, md))

        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            continue

    # If no PRs found via commits, try listing recent merged PRs for the repo
    if not prs:
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "list",
                    "--repo", repo,
                    "--state", "merged",
                    "--json", "number,title,url,state,body",
                    "--limit", "5",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                pr_data = json.loads(result.stdout)
                for pr in pr_data:
                    pr_num = pr.get("number", 0)
                    if pr_num and pr_num not in seen_pr_numbers:
                        seen_pr_numbers.add(pr_num)
                        md = _format_pr_markdown(pr, repo)
                        prs.append((pr_num, md))
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            pass

    return prs


def _format_pr_markdown(pr: dict, repo: str) -> str:
    """Format a PR dict as markdown."""
    number = pr.get("number", "?")
    title = pr.get("title", "Untitled")
    url = pr.get("url", "")
    state = pr.get("state", "unknown")
    body = pr.get("body", "") or ""

    md = f"# PR #{number}: {title}\n\n"
    md += f"- **Repository**: {repo}\n"
    md += f"- **State**: {state}\n"
    if url:
        md += f"- **URL**: {url}\n"
    md += "\n"
    if body:
        md += "## Description\n\n"
        md += body + "\n"
    return md


# ---------------------------------------------------------------------------
# Pre-analysis helpers
# ---------------------------------------------------------------------------


def _extract_opening_context(messages: list[dict]) -> str:
    """Extract the first 1-3 user messages as opening context."""
    user_msgs = [m for m in messages if m.get("type") == "user"]
    if not user_msgs:
        return "No user messages found."

    parts = []
    for msg in user_msgs[:3]:
        content = (msg.get("content") or "").strip()
        if len(content) > 500:
            content = content[:500] + "..."
        if content:
            parts.append(content)

    return "\n\n---\n\n".join(parts) if parts else "No user messages found."


def _categorize_commits(commits: list[dict]) -> dict:
    """Categorize commits by keyword matching on their messages."""
    categories: dict[str, list[dict]] = {
        "ci": [],
        "fix": [],
        "docs": [],
        "refactor": [],
        "test": [],
        "feature": [],
        "other": [],
    }

    keyword_map: list[tuple[str, set[str]]] = [
        ("ci", {"ci", "pipeline", "workflow", "actions", "lint", "ruff", "mypy",
                "pre-commit", "formatting", "format", "linter", "flake"}),
        ("fix", {"fix", "bug", "patch", "resolve", "hotfix", "repair", "correct",
                "prevent", "cap", "oom", "crash", "harden", "limit", "overflow",
                "underflow", "panic", "abort"}),
        ("test", {"test", "spec", "coverage", "assert"}),
        ("docs", {"doc", "readme", "documentation", "comment", "changelog"}),
        ("refactor", {"refactor", "rename", "restructure", "reorganize", "clean",
                      "simplify", "extract", "move"}),
        ("feature", {"add", "feat", "feature", "implement", "new", "support",
                     "introduce", "create"}),
    ]

    for commit in commits:
        msg = (commit.get("message") or "").lower()
        matched = False

        for category, keywords in keyword_map:
            if any(kw in msg for kw in keywords):
                categories[category].append(commit)
                matched = True
                break

        if not matched:
            categories["other"].append(commit)

    category_counts = {k: len(v) for k, v in categories.items() if v}
    total = len(commits)
    summary_parts = []
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        summary_parts.append(f"{count} {cat}")

    summary = (
        f"Of {total} commits: " + ", ".join(summary_parts)
        if summary_parts
        else "No commits"
    )

    return {
        "categories": categories,
        "category_counts": category_counts,
        "summary": summary,
    }


def _describe_session_characteristics(
    messages: list[dict],
    tool_calls: list[dict],
    commits: list[dict],
) -> str:
    """Describe observable session characteristics.

    Returns plain-English observations about tool usage, commit patterns,
    and message flow.  Does NOT classify the session into a fixed category —
    the arc only becomes clear after the interview.
    """
    observations: list[str] = []

    # Tool usage patterns
    if tool_calls:
        tool_counter: Counter = Counter(tc["tool_name"] for tc in tool_calls)
        total_tc = len(tool_calls)
        top_tools = tool_counter.most_common(3)

        tool_desc = ", ".join(
            f"{name} ({count}/{total_tc}, {count * 100 // total_tc}%)"
            for name, count in top_tools
        )
        observations.append(f"Top tools: {tool_desc}")

        bash_pct = tool_counter.get("Bash", 0) * 100 // total_tc if total_tc else 0
        read_pct = tool_counter.get("Read", 0) * 100 // total_tc if total_tc else 0
        edit_pct = tool_counter.get("Edit", 0) * 100 // total_tc if total_tc else 0
        write_pct = tool_counter.get("Write", 0) * 100 // total_tc if total_tc else 0

        if bash_pct + read_pct > 60:
            observations.append(
                "Tool mix is exploration/debugging-heavy (Bash + Read dominant)"
            )
        elif edit_pct + write_pct > 40:
            observations.append(
                "Tool mix is implementation-heavy (Edit + Write dominant)"
            )

    # Commit patterns
    if commits:
        commit_cats = _categorize_commits(commits)
        cat_counts = commit_cats["category_counts"]
        if cat_counts:
            top_cat = max(cat_counts, key=lambda k: cat_counts[k])
            if cat_counts[top_cat] > len(commits) * 0.4:
                observations.append(
                    f"Commit pattern: {cat_counts[top_cat]} of {len(commits)} "
                    f"commits are {top_cat}-related"
                )

    # Message volume
    total = len(messages)
    user_count = sum(1 for m in messages if m.get("type") == "user")
    if total > 100:
        observations.append(f"Long session: {total} messages, {user_count} from user")
    elif total < 20:
        observations.append(f"Short session: {total} messages")

    return ". ".join(observations) + "." if observations else "No notable patterns observed."


def _compute_autonomy_ratio(messages: list[dict]) -> tuple[float, str]:
    """Compute and describe the ratio of user messages to total messages."""
    total = len(messages)
    if total == 0:
        return 0.0, "No messages in session"

    user_msgs = sum(1 for m in messages if m.get("type") == "user")
    ratio = user_msgs / total

    if ratio < 0.10:
        desc = f"High AI autonomy — {user_msgs} user messages in {total} total"
    elif ratio < 0.25:
        desc = f"Moderate autonomy — {user_msgs} user messages in {total} total"
    elif ratio < 0.50:
        desc = f"Collaborative — {user_msgs} user messages in {total} total"
    else:
        desc = f"User-driven — {user_msgs} user messages in {total} total"

    return ratio, desc


def _analyze_tool_patterns(tool_calls: list[dict]) -> dict:
    """Analyze tool usage patterns beyond simple counts."""
    if not tool_calls:
        return {
            "counts": {},
            "dominant_description": "No tool calls in session",
            "top_trigrams": [],
        }

    counter: Counter = Counter(tc["tool_name"] for tc in tool_calls)
    total = len(tool_calls)

    top = counter.most_common(1)[0]
    dominant_description = (
        f"{top[0]} is the most-used tool "
        f"({top[1]}/{total} calls, {top[1] * 100 // total}%)"
    )

    # 3-grams of tool sequences
    tool_names = [tc["tool_name"] for tc in tool_calls]
    trigram_counter: Counter = Counter()
    for i in range(len(tool_names) - 2):
        trigram_counter[(tool_names[i], tool_names[i + 1], tool_names[i + 2])] += 1

    top_trigrams = trigram_counter.most_common(5)

    return {
        "counts": dict(counter.most_common()),
        "dominant_description": dominant_description,
        "top_trigrams": top_trigrams,
    }


def _analyze_thinking_blocks(messages: list[dict]) -> dict:
    """Count messages with thinking blocks."""
    total = len(messages)
    with_thinking = sum(
        1 for m in messages
        if m.get("thinking") and (m["thinking"] or "").strip()
    )

    return {
        "count": with_thinking,
        "total_messages": total,
        "available": with_thinking > 0,
    }


def _detect_key_moments(messages: list[dict]) -> list[dict]:
    """Detect moments where the user corrected or redirected the AI.

    Looks for:
    - Short user messages after assistant messages containing correction language
    - User-initiated interruptions (``[Request interrupted by user]``)
    """
    correction_patterns = [
        "no,", "no ", "wrong", "actually", "instead", "don't", "doesn't",
        "didn't", "stop", "wait", "not what", "that's not", "rather",
        "try ", "nope", "shouldn't", "won't work", "doesn't work",
        "didn't work", "not right", "can't",
    ]

    moments: list[dict] = []
    for i, msg in enumerate(messages):
        if msg.get("type") != "user":
            continue

        content = (msg.get("content") or "").strip()
        if not content:
            continue

        # Detect user interruptions
        if "[request interrupted by user" in content.lower():
            moments.append({
                "index": i,
                "content": "[User interrupted the AI]",
                "timestamp": msg.get("timestamp", ""),
            })
            if len(moments) >= 10:
                break
            continue

        # Skip long messages for correction detection
        if len(content) > 200:
            continue

        # Must be preceded by an assistant message
        if i == 0:
            continue
        prev = messages[i - 1]
        if prev.get("type") != "assistant":
            continue

        content_lower = content.lower()
        if any(pattern in content_lower for pattern in correction_patterns):
            moments.append({
                "index": i,
                "content": content[:200],
                "timestamp": msg.get("timestamp", ""),
            })

        if len(moments) >= 10:
            break

    return moments


def _build_timeline_summary(messages: list[dict], commits: list[dict]) -> str:
    """Describe the temporal structure of the session.

    Detects gaps > 1 hour to identify distinct work sessions, then
    describes the distribution of messages and commits across them.
    """
    if not messages:
        return "No messages to analyze."

    total = len(messages)
    if total < 3:
        return f"Very short session with {total} messages."

    # Detect temporal gaps to find distinct work sessions
    gap_threshold = 3600  # 1 hour in seconds
    work_sessions: list[list[dict]] = [[]]
    for i, msg in enumerate(messages):
        if i == 0:
            work_sessions[0].append(msg)
            continue
        ts_curr = msg.get("timestamp") or ""
        ts_prev = messages[i - 1].get("timestamp") or ""
        if ts_curr and ts_prev:
            try:
                from datetime import datetime as _dt
                # Parse ISO timestamps (handle Z and +00:00)
                t_curr = ts_curr.replace("Z", "+00:00")
                t_prev = ts_prev.replace("Z", "+00:00")
                dt_curr = _dt.fromisoformat(t_curr)
                dt_prev = _dt.fromisoformat(t_prev)
                gap = (dt_curr - dt_prev).total_seconds()
                if gap > gap_threshold:
                    work_sessions.append([])
            except (ValueError, TypeError):
                pass
        work_sessions[-1].append(msg)

    # Describe work sessions if there are multiple
    parts: list[str] = []
    if len(work_sessions) > 1:
        session_descs: list[str] = []
        for j, ws in enumerate(work_sessions, 1):
            n_msgs = len(ws)
            n_user = sum(1 for m in ws if m.get("type") == "user")
            session_descs.append(f"{n_msgs} msgs, {n_user} from user")
        parts.append(
            f"Session spans {len(work_sessions)} distinct work sessions "
            f"(gaps > 1 hour): {'; '.join(session_descs)}"
        )
    else:
        parts.append(f"Single continuous session with {total} messages")

    # Split into thirds for commit distribution
    third = total // 3
    thirds = [
        messages[:third],
        messages[third:2 * third],
        messages[2 * third:],
    ]

    # Commit distribution
    if commits and thirds[0] and thirds[1]:
        t1_end = thirds[0][-1].get("timestamp") or ""
        t2_end = thirds[1][-1].get("timestamp") or ""
        if t1_end and t2_end:
            early = sum(
                1 for c in commits if (c.get("timestamp") or "") <= t1_end
            )
            mid = sum(
                1 for c in commits
                if t1_end < (c.get("timestamp") or "") <= t2_end
            )
            late = len(commits) - early - mid
            parts.append(
                f"Commits: {early} early, {mid} middle, {late} late"
            )

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Pre-analysis: top-level builder + markdown renderer
# ---------------------------------------------------------------------------


def build_session_preanalysis(
    messages: list[dict],
    tool_calls: list[dict],
    commits: list[dict],
    primary_session: dict,
) -> dict:
    """Build pre-analysis of a session for debrief context.

    Extracts patterns, narrative hooks, and descriptive observations
    from the session data.  Returns a dict that can be rendered to markdown
    and passed to other debrief functions.
    """
    opening = _extract_opening_context(messages)
    characteristics = _describe_session_characteristics(
        messages, tool_calls, commits
    )
    ratio, ratio_desc = _compute_autonomy_ratio(messages)
    tools = _analyze_tool_patterns(tool_calls)
    commit_cats = _categorize_commits(commits)
    thinking = _analyze_thinking_blocks(messages)
    moments = _detect_key_moments(messages)
    timeline = _build_timeline_summary(messages, commits)

    return {
        "opening_context": opening,
        "session_characteristics": characteristics,
        "autonomy_ratio": ratio,
        "autonomy_description": ratio_desc,
        "tool_patterns": tools,
        "commit_categories": commit_cats,
        "thinking_blocks": thinking,
        "key_moments": moments,
        "timeline_summary": timeline,
        "total_messages": len(messages),
        "user_messages": sum(
            1 for m in messages if m.get("type") == "user"
        ),
        "total_commits": len(commits),
    }


def _render_preanalysis_md(preanalysis: dict) -> str:
    """Render preanalysis dict as markdown."""
    md = "# Session Pre-Analysis\n\n"

    md += "## Opening Context\n\n"
    md += "The session started with:\n\n"
    for line in preanalysis["opening_context"].split("\n"):
        md += f"> {line}\n" if line.strip() else ">\n"
    md += "\n"

    md += "## Session Characteristics\n\n"
    md += f"{preanalysis['session_characteristics']}\n\n"

    md += "## Autonomy\n\n"
    md += f"{preanalysis['autonomy_description']}\n\n"

    md += "## Tool Patterns\n\n"
    tp = preanalysis["tool_patterns"]
    md += f"{tp['dominant_description']}\n\n"
    if tp["counts"]:
        md += "| Tool | Count |\n|------|-------|\n"
        for tool, count in tp["counts"].items():
            md += f"| {tool} | {count} |\n"
        md += "\n"
    if tp["top_trigrams"]:
        md += "**Common sequences:**\n\n"
        for trigram, count in tp["top_trigrams"]:
            md += f"- {' → '.join(trigram)} (x{count})\n"
        md += "\n"

    md += "## Commits\n\n"
    cc = preanalysis["commit_categories"]
    md += f"{cc['summary']}\n\n"
    if cc["category_counts"]:
        md += "| Category | Count |\n|----------|-------|\n"
        for cat, count in sorted(
            cc["category_counts"].items(), key=lambda x: -x[1]
        ):
            md += f"| {cat} | {count} |\n"
        md += "\n"

    md += "## Thinking Blocks\n\n"
    tb = preanalysis["thinking_blocks"]
    if tb["available"]:
        md += (
            f"{tb['count']} of {tb['total_messages']} messages have thinking "
            "blocks. These may reveal decision points and reasoning.\n\n"
        )
    else:
        md += "No thinking blocks available in this session.\n\n"

    md += "## Key Moments\n\n"
    moments = preanalysis["key_moments"]
    if moments:
        md += (
            f"Detected {len(moments)} potential user corrections/redirections:\n\n"
        )
        for m in moments:
            md += f"- \"{m['content']}\"\n"
        md += "\n"
    else:
        md += "No obvious user corrections detected.\n\n"

    md += "## Timeline\n\n"
    md += f"{preanalysis['timeline_summary']}\n"

    return md


# ---------------------------------------------------------------------------
# Composition helpers — build guide content from preanalysis
# ---------------------------------------------------------------------------


def _compose_what_happened(preanalysis: dict, primary_session: dict) -> str:
    """Compose a concise summary of what happened in the session.

    Uses opening context for the prompt, autonomy for scale, commit
    messages for substance, and timeline for structure.  Avoids restating
    raw numbers that already appear in metrics.
    """
    parts: list[str] = []

    # Opening — what the user asked for
    opening = preanalysis["opening_context"]
    first_line = opening.split("\n")[0][:200]
    if first_line and first_line != "No user messages found.":
        parts.append(f'This session started with: "{first_line}"')

    # Scale and autonomy (one sentence, not repeated)
    total = preanalysis["total_messages"]
    parts.append(
        f"Over {total} messages, {preanalysis['autonomy_description'].lower()}"
    )

    # Commits — use actual commit messages for substance instead of
    # restating category counts (those are already in metrics)
    cc = preanalysis["commit_categories"]
    seen_msgs: set[str] = set()
    non_ci_commits: list[str] = []
    for cat in ("fix", "feature", "refactor"):
        for c in cc["categories"].get(cat, []):
            msg = (c.get("message") or "").strip()
            if msg and msg not in seen_msgs:
                seen_msgs.add(msg)
                non_ci_commits.append(msg)
    if non_ci_commits:
        if len(non_ci_commits) <= 3:
            parts.append(
                "Key commits: " + "; ".join(non_ci_commits[:3])
            )
        else:
            parts.append(
                f"Key commits include: {non_ci_commits[0]}; "
                f"{non_ci_commits[1]} (and {len(non_ci_commits) - 2} more)"
            )

    ci_count = cc["category_counts"].get("ci", 0)
    if ci_count > 0:
        parts.append(
            f"{ci_count} of {preanalysis['total_commits']} commits were "
            "CI/infrastructure work"
        )

    # Timeline — only if it adds information
    timeline = preanalysis["timeline_summary"]
    if "distinct work sessions" in timeline:
        parts.append(timeline.split(".")[0])

    return ". ".join(p.rstrip(".") for p in parts) + "."


def _compose_session_specific_questions(preanalysis: dict) -> str:
    """Generate 3-5 targeted interview questions based on session data."""
    questions: list[str] = []

    # CI-heavy commits
    cc = preanalysis["commit_categories"]
    ci_count = cc["category_counts"].get("ci", 0)
    total_commits = preanalysis["total_commits"]
    if total_commits > 0 and ci_count / total_commits > 0.4:
        questions.append(
            f"- {ci_count} of {total_commits} commits look CI-related. "
            "Was the CI work the real story, a necessary detour, or a yak-shave?"
        )

    # High autonomy
    if preanalysis["autonomy_ratio"] < 0.10:
        questions.append(
            "- The AI had high autonomy in this session. Was that intentional? "
            "Did you step back and let it run, or were you monitoring closely?"
        )

    # Key moments — prefer a real user quote over the synthetic interruption label
    moments = preanalysis["key_moments"]
    if moments:
        # Find the first moment with actual user text, not an interruption label
        real_moment = next(
            (m for m in moments if "interrupted" not in m["content"].lower()),
            None,
        )
        interruption_count = sum(
            1 for m in moments if "interrupted" in m["content"].lower()
        )
        if real_moment:
            quote = real_moment["content"][:100]
            questions.append(
                f'- At one point you said: "{quote}" — '
                "what was going wrong and how did the course correction go?"
            )
        if interruption_count > 0:
            questions.append(
                f"- You interrupted the AI {interruption_count} time(s) during "
                "this session. What prompted those interruptions?"
            )

    # Thinking blocks
    if preanalysis["thinking_blocks"]["available"]:
        questions.append(
            "- There are thinking blocks in this session. "
            "Were there decision points where the AI's reasoning surprised you?"
        )

    # Always include
    questions.append(
        "- What's the one thing about this session that would surprise someone?"
    )

    return "\n".join(questions)


def build_metrics_summary(
    db: Database,
    primary_session: dict,
    related_sessions: list[dict],
    preanalysis: Optional[dict] = None,
    messages: Optional[list[dict]] = None,
    tool_calls: Optional[list[dict]] = None,
    commits: Optional[list[dict]] = None,
) -> str:
    """Compute session stats and return formatted markdown.

    Includes token counts, message counts, tool usage breakdown, and timeline.
    When *preanalysis* is provided, appends commit categorization, autonomy,
    and notable patterns.  When *messages*/*tool_calls*/*commits* are provided,
    skips redundant DB queries.
    """
    session_id = primary_session["id"]
    if messages is None:
        messages = db.get_messages_for_session(session_id)
    if tool_calls is None:
        tool_calls = db.get_tool_calls_for_session(session_id)
    if commits is None:
        commits = db.get_commits_for_session(session_id)

    # Message counts by type
    user_msgs = sum(1 for m in messages if m["type"] == "user")
    assistant_msgs = sum(1 for m in messages if m["type"] == "assistant")
    total_msgs = len(messages)

    # Token counts
    input_tokens = primary_session.get("total_input_tokens") or 0
    output_tokens = primary_session.get("total_output_tokens") or 0
    cache_read_tokens = primary_session.get("total_cache_read_tokens") or 0

    # Tool usage breakdown
    tool_counter: Counter = Counter()
    for tc in tool_calls:
        tool_counter[tc["tool_name"]] += 1

    # Timeline
    started = primary_session.get("started_at") or "unknown"
    ended = primary_session.get("ended_at") or "unknown"

    md = "# Session Metrics\n\n"
    md += "## Primary Session\n\n"
    md += f"- **Session ID**: `{session_id[:12]}...`\n"
    md += f"- **Project**: {primary_session.get('project', 'unknown')}\n"
    md += f"- **Model**: {primary_session.get('model') or 'unknown'}\n"
    md += f"- **Started**: {started}\n"
    md += f"- **Ended**: {ended}\n"
    md += "\n"

    md += "## Message Counts\n\n"
    md += f"- Total messages: {total_msgs}\n"
    md += f"- User messages: {user_msgs}\n"
    md += f"- Assistant messages: {assistant_msgs}\n"
    md += "\n"

    md += "## Token Usage\n\n"
    md += f"- Input tokens: {input_tokens:,}\n"
    md += f"- Output tokens: {output_tokens:,}\n"
    md += f"- Cache read tokens: {cache_read_tokens:,}\n"
    md += f"- Total tokens: {input_tokens + output_tokens + cache_read_tokens:,}\n"
    md += "\n"

    if tool_counter:
        md += "## Tool Usage\n\n"
        md += "| Tool | Count |\n"
        md += "|------|-------|\n"
        for tool, count in tool_counter.most_common():
            md += f"| {tool} | {count} |\n"
        md += "\n"

    md += "## Commits\n\n"
    md += f"- Total commits extracted: {len(commits)}\n"
    if commits:
        md += "\n"
        for c in commits:
            md += f"- `{c['commit_hash']}` {c.get('message', '')}\n"
    md += "\n"

    if related_sessions:
        md += "## Related Sessions\n\n"
        md += f"- {len(related_sessions)} other sessions in the same project\n"
        total_related_input = sum(
            (s.get("total_input_tokens") or 0) for s in related_sessions
        )
        total_related_output = sum(
            (s.get("total_output_tokens") or 0) for s in related_sessions
        )
        md += f"- Combined input tokens: {total_related_input:,}\n"
        md += f"- Combined output tokens: {total_related_output:,}\n"

    # Preanalysis-derived sections
    if preanalysis is not None:
        md += "\n## Commit Categorization\n\n"
        cc = preanalysis["commit_categories"]
        md += f"{cc['summary']}\n\n"
        if cc["category_counts"]:
            md += "| Category | Count |\n|----------|-------|\n"
            for cat, count in sorted(
                cc["category_counts"].items(), key=lambda x: -x[1]
            ):
                md += f"| {cat} | {count} |\n"
            md += "\n"

        md += "## Autonomy\n\n"
        md += f"{preanalysis['autonomy_description']}\n\n"

        md += "## Notable Patterns\n\n"
        md += f"- {preanalysis['session_characteristics']}\n"
        md += f"- {preanalysis['timeline_summary']}\n"
        tp = preanalysis["tool_patterns"]
        md += f"- {tp['dominant_description']}\n"

    return md


def generate_slug(
    primary_session: dict,
    first_user_message: Optional[str] = None,
) -> str:
    """Create a slug from the session's project name and summary/title.

    Falls back to *first_user_message* (when provided), then session ID
    prefix if no summary or title is available.
    """
    # Try summary first, then title, then slug field, then first user message
    text = (
        primary_session.get("summary")
        or primary_session.get("title")
        or primary_session.get("slug")
    )

    if not text and first_user_message:
        text = first_user_message

    if not text:
        return primary_session["id"][:8]

    # Convert to slug: lowercase, replace non-alphanumeric with hyphens, collapse
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    # Truncate to reasonable length
    if len(slug) > 60:
        slug = slug[:60].rstrip("-")
    return slug or primary_session["id"][:8]


def generate_session_guide(
    primary_session: dict,
    related_sessions: list[dict],
    context_dir: Path,
    drafts_dir: Path,
    has_git: bool,
    has_prs: bool,
    pr_files: list[str],
    preanalysis: Optional[dict] = None,
) -> str:
    """Render the session guide markdown from the template.

    Loads the template from the prompts directory and fills in placeholders.
    When *preanalysis* is provided, populates the What Happened section,
    session-specific interview questions, and context inventory entries.
    """
    template_path = Path(__file__).parent / "prompts" / "session_guide_template.md"
    template = template_path.read_text(encoding="utf-8")

    # Build context inventory entries
    related_entry = ""
    if related_sessions:
        related_entry = (
            "| `context/related-sessions.md` "
            f"| {len(related_sessions)} related sessions in the same project |\n"
        )

    git_entry = ""
    if has_git:
        git_entry = "| `context/git-log.md` | Git commit history for the session timeframe |\n"

    pr_entries_str = ""
    if has_prs and pr_files:
        for pr_file in pr_files:
            pr_entries_str += f"| `context/{pr_file}` | Pull request data |\n"

    # Preanalysis-derived placeholders
    if preanalysis is not None:
        what_happened = _compose_what_happened(preanalysis, primary_session)
        session_specific_questions = _compose_session_specific_questions(
            preanalysis
        )
        preanalysis_entry = (
            "| `context/session-preanalysis.md` "
            "| Pre-analysis: opening context, patterns, commit categories, key moments |\n"
        )
        if preanalysis["thinking_blocks"]["available"]:
            tb = preanalysis["thinking_blocks"]
            thinking_block_note = (
                f"\n**Note**: {tb['count']} messages have thinking blocks. "
                "These may reveal decision points and reasoning not visible "
                "in the main transcript.\n"
            )
        else:
            thinking_block_note = ""
    else:
        what_happened = (
            "Pre-analysis not available. Read the primary session transcript "
            "to understand what happened."
        )
        session_specific_questions = (
            "- What's the one thing about this session that would surprise someone?"
        )
        preanalysis_entry = ""
        thinking_block_note = ""

    # Format dates
    started = primary_session.get("started_at") or "unknown"
    ended = primary_session.get("ended_at") or "unknown"
    if started != "unknown" and len(started) >= 10:
        started = started[:10]
    if ended != "unknown" and len(ended) >= 10:
        ended = ended[:10]

    today = datetime.now().strftime("%Y-%m-%d")

    guide = template.format(
        summary=primary_session.get("summary") or primary_session.get("title") or "No summary available",
        project=primary_session.get("project", "unknown"),
        started_at=started,
        ended_at=ended,
        repo=primary_session.get("repo") or "not detected",
        session_id=primary_session["id"][:12] + "...",
        related_sessions_entry=related_entry,
        git_log_entry=git_entry,
        pr_entries=pr_entries_str,
        today=today,
        what_happened=what_happened,
        session_specific_questions=session_specific_questions,
        preanalysis_entry=preanalysis_entry,
        thinking_block_note=thinking_block_note,
    )

    return guide


def _reconstruct_session_from_db(db: Database, session_dict: dict) -> Session:
    """Reconstruct a Session object from a database dict.

    Follows the same pattern as the render command in cli.py.
    """
    session_id = session_dict["id"]

    messages: list[Message] = []
    for msg in db.get_messages_for_session(session_id):
        messages.append(
            Message(
                id=msg["id"],
                session_id=msg["session_id"],
                type=msg["type"],
                timestamp=msg["timestamp"],
                content=msg["content"] or "",
                parent_uuid=msg["parent_uuid"],
                model=msg["model"],
                input_tokens=msg["input_tokens"],
                output_tokens=msg["output_tokens"],
                thinking=msg.get("thinking"),
                stop_reason=msg.get("stop_reason"),
                is_sidechain=bool(msg.get("is_sidechain", False)),
                tool_calls=[],
            )
        )

    tool_calls: list[ToolCall] = []
    for tc in db.get_tool_calls_for_session(session_id):
        tool_call = ToolCall(
            id=tc["id"],
            message_id=tc["message_id"],
            session_id=tc["session_id"],
            tool_name=tc["tool_name"],
            input_json=tc["input_json"],
            timestamp=tc["timestamp"],
        )
        tool_calls.append(tool_call)
        for message in messages:
            if message.id == tc["message_id"]:
                message.tool_calls.append(tool_call)
                break

    tool_results: list[ToolResult] = []
    for tr in db.get_tool_results_for_session(session_id):
        tool_results.append(
            ToolResult(
                id=tr["id"],
                tool_call_id=tr["tool_call_id"],
                session_id=tr["session_id"],
                content=tr["content"] or "",
                is_error=bool(tr["is_error"]),
                timestamp=tr["timestamp"],
            )
        )

    return Session(
        id=session_dict["id"],
        project=session_dict["project"],
        cwd=session_dict["cwd"],
        git_branch=session_dict["git_branch"],
        slug=session_dict.get("slug"),
        summary=session_dict.get("summary"),
        started_at=session_dict["started_at"],
        ended_at=session_dict["ended_at"],
        claude_version=session_dict["claude_version"],
        total_input_tokens=session_dict["total_input_tokens"] or 0,
        total_output_tokens=session_dict["total_output_tokens"] or 0,
        total_cache_read_tokens=session_dict["total_cache_read_tokens"] or 0,
        model=session_dict["model"],
        parent_session_id=session_dict.get("parent_session_id"),
        is_warmup=bool(session_dict.get("is_warmup", False)),
        is_sidechain=bool(session_dict.get("is_sidechain", False)),
        repo=session_dict.get("repo"),
        repo_platform=session_dict.get("repo_platform"),
        messages=messages,
        tool_calls=tool_calls,
        tool_results=tool_results,
    )


def prepare_debrief(
    db: Database,
    cfg: Config,
    session_id_prefix: str,
    archive_dir: Optional[Path] = None,
) -> Path:
    """Top-level orchestrator for debrief preparation.

    Gathers session data, git history, PR context, and generates the
    session guide. Returns the path to the created debrief directory.
    """
    # 1. Look up primary session by prefix
    primary_session = db.get_session_by_id_prefix(session_id_prefix)
    if primary_session is None:
        raise ValueError(f"No session found matching prefix '{session_id_prefix}'")

    # 2. Discover related sessions
    related_sessions = discover_related_sessions(db, primary_session)

    # 3. Fetch messages, tool_calls, commits early (reused by slug,
    #    preanalysis, metrics — avoids duplicate DB queries)
    session_id = primary_session["id"]
    messages = db.get_messages_for_session(session_id)
    tool_calls = db.get_tool_calls_for_session(session_id)
    commits = db.get_commits_for_session(session_id)

    # 4. Get first user message for slug fallback
    first_user_msg = None
    for msg in messages:
        if msg.get("type") == "user" and msg.get("content"):
            first_user_msg = msg["content"].strip()
            break

    # 5. Create output directory
    slug = generate_slug(primary_session, first_user_message=first_user_msg)
    started = primary_session.get("started_at") or ""
    if started and len(started) >= 10:
        date_part = started[:10].replace("-", "_")
    else:
        date_part = datetime.now().strftime("%Y_%m_%d")

    dir_name = f"{date_part}_{slug}"
    base_dir = archive_dir or cfg.archive_dir
    output_dir = base_dir / "debriefs" / dir_name

    # 6. Create subdirectories
    context_dir = output_dir / "context"
    drafts_dir = output_dir / "drafts"
    context_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)

    # 7. Copy primary session TOML to context
    session_obj = _reconstruct_session_from_db(db, primary_session)
    toml_content = render_session_toml(session_obj)
    (context_dir / "primary-session.toml").write_text(toml_content, encoding="utf-8")

    # 8. Build preanalysis
    preanalysis = build_session_preanalysis(
        messages, tool_calls, commits, primary_session
    )
    preanalysis_md = _render_preanalysis_md(preanalysis)
    (context_dir / "session-preanalysis.md").write_text(
        preanalysis_md, encoding="utf-8"
    )

    # 9. Write related sessions summary (with DB for first-user-message excerpts)
    if related_sessions:
        related_md = _build_related_sessions_md(related_sessions, db=db)
        (context_dir / "related-sessions.md").write_text(
            related_md, encoding="utf-8"
        )

    # 10. Write git log
    git_context = gather_git_context(
        cwd=primary_session.get("cwd"),
        start_date=primary_session.get("started_at"),
        end_date=primary_session.get("ended_at"),
    )
    has_git = bool(git_context)
    if has_git:
        (context_dir / "git-log.md").write_text(git_context, encoding="utf-8")

    # 11. Write PR files (reuse pre-fetched commits)
    pr_results = gather_pr_context(
        repo=primary_session.get("repo"),
        repo_platform=primary_session.get("repo_platform"),
        commits=commits,
    )
    has_prs = bool(pr_results)
    pr_files: list[str] = []
    for pr_num, pr_md in pr_results:
        filename = f"pr-{pr_num}.md"
        pr_files.append(filename)
        (context_dir / filename).write_text(pr_md, encoding="utf-8")

    # 12. Write metrics (with preanalysis + pre-fetched data)
    metrics_md = build_metrics_summary(
        db, primary_session, related_sessions,
        preanalysis=preanalysis,
        messages=messages,
        tool_calls=tool_calls,
        commits=commits,
    )
    (context_dir / "metrics.md").write_text(metrics_md, encoding="utf-8")

    # 13. Write session guide (with preanalysis)
    guide = generate_session_guide(
        primary_session=primary_session,
        related_sessions=related_sessions,
        context_dir=context_dir,
        drafts_dir=drafts_dir,
        has_git=has_git,
        has_prs=has_prs,
        pr_files=pr_files,
        preanalysis=preanalysis,
    )
    (output_dir / "session-guide.md").write_text(guide, encoding="utf-8")

    return output_dir


def _build_related_sessions_md(
    related_sessions: list[dict],
    db: Optional[Database] = None,
) -> str:
    """Build a markdown summary of related sessions.

    When *db* is provided, extracts the first user message from each related
    session so the drafter knows what each one was about.
    """
    md = "# Related Sessions\n\n"
    md += f"Found {len(related_sessions)} related sessions in the same project.\n\n"

    for i, s in enumerate(related_sessions, 1):
        session_id = s["id"][:12]
        started = s.get("started_at") or "unknown"
        summary = s.get("summary") or s.get("title") or s.get("slug") or "No summary"
        input_tokens = s.get("total_input_tokens") or 0
        output_tokens = s.get("total_output_tokens") or 0
        model = s.get("model") or "unknown"

        md += f"## Session {i}: `{session_id}...`\n\n"
        md += f"- **Summary**: {summary}\n"
        md += f"- **Started**: {started}\n"
        md += f"- **Model**: {model}\n"
        md += f"- **Input tokens**: {input_tokens:,}\n"
        md += f"- **Output tokens**: {output_tokens:,}\n"

        # Extract first user message when DB is available
        if db is not None:
            try:
                msgs = db.get_messages_for_session(s["id"])
                first_user = next(
                    (m for m in msgs
                     if m.get("type") == "user" and m.get("content")),
                    None,
                )
                if first_user:
                    content = (first_user["content"] or "").strip()
                    if len(content) > 200:
                        content = content[:200] + "..."
                    md += f"- **First prompt**: {content}\n"
            except Exception:
                pass

        md += "\n"

    return md
