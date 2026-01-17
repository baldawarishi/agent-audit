"""Phase 1: Pattern detection without LLM."""

import json
import re
import shlex
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..database import Database

# Tools that have meaningful subcommands (depth 2 normalization)
SUBCOMMAND_TOOLS = {
    "git", "docker", "kubectl", "npm", "yarn", "pip", "cargo",
    "go", "gh", "aws", "gcloud", "az", "terraform", "make",
    "poetry", "uv", "pnpm", "bun", "deno", "rustup", "conda",
}


@dataclass
class RawPattern:
    """A detected pattern from archive analysis."""
    pattern_type: str  # "tool_sequence", "prompt_prefix", "prompt_phrase", "file_access"
    pattern_key: str  # Normalized pattern identifier
    occurrences: int  # Total count
    sessions: set[str] = field(default_factory=set)  # Session IDs
    projects: set[str] = field(default_factory=set)  # Project names
    first_seen: Optional[str] = None  # ISO timestamp
    last_seen: Optional[str] = None  # ISO timestamp
    examples: list[str] = field(default_factory=list)  # Sample raw values (max 3)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "pattern_type": self.pattern_type,
            "pattern_key": self.pattern_key,
            "occurrences": self.occurrences,
            "sessions": sorted(self.sessions),
            "session_count": len(self.sessions),
            "projects": sorted(self.projects),
            "project_count": len(self.projects),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "examples": self.examples[:3],
        }


def normalize_bash_command(input_json: str) -> str:
    """Extract command signature for pattern matching.

    Uses depth 2 normalization for known tools with subcommands.
    """
    try:
        data = json.loads(input_json)
    except json.JSONDecodeError:
        return "unknown"

    cmd = data.get("command", "")
    if not cmd:
        return "unknown"

    # Try shlex parsing, fall back to simple split
    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = cmd.split()

    if not parts:
        return "unknown"

    base = parts[0]

    # Depth 2 for known tools with subcommands
    if base in SUBCOMMAND_TOOLS and len(parts) > 1:
        subcmd = parts[1]
        # Skip flags and paths as subcommands
        if not subcmd.startswith("-") and not subcmd.startswith("/"):
            return f"{base}-{subcmd}"

    return base


def normalize_tool_name(tool_call: dict) -> str:
    """Normalize a tool call to a pattern-matchable name."""
    tool_name = tool_call.get("tool_name", "")

    if tool_name == "Bash":
        input_json = tool_call.get("input_json", "{}")
        return f"Bash:{normalize_bash_command(input_json)}"

    return tool_name


def extract_tool_sequences(
    tool_calls: list[dict],
    n: int = 3
) -> list[tuple[str, ...]]:
    """Extract n-grams of normalized tool names from a session's tool calls.

    Args:
        tool_calls: List of tool call dicts (must have timestamp for ordering)
        n: Size of n-grams (default 3)

    Returns:
        List of n-gram tuples
    """
    if len(tool_calls) < n:
        return []

    # Sort by timestamp
    sorted_calls = sorted(tool_calls, key=lambda x: x.get("timestamp", ""))

    # Normalize tool names
    tools = [normalize_tool_name(tc) for tc in sorted_calls]

    # Extract n-grams
    return [tuple(tools[i:i + n]) for i in range(len(tools) - n + 1)]


def normalize_prompt(text: str) -> str:
    """Normalize user prompt text for pattern matching."""
    text = text.lower()
    # Remove URLs
    text = re.sub(r'https?://\S+', '<url>', text)
    # Normalize paths
    text = re.sub(r'(/[\w\-./]+)+', '<path>', text)
    # Normalize quoted strings (file names, identifiers)
    text = re.sub(r'["\'][\w\-./]+["\']', '<name>', text)
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text


def extract_prompt_prefix(text: str, n_tokens: int = 5) -> str:
    """Extract first N tokens as pattern key."""
    tokens = normalize_prompt(text).split()[:n_tokens]
    return ' '.join(tokens)


def extract_phrase_ngrams(
    text: str,
    n: int = 5
) -> list[tuple[str, ...]]:
    """Extract n-grams of words from normalized prompt."""
    words = normalize_prompt(text).split()
    if len(words) < n:
        return []
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def normalize_file_path(file_path: str) -> str:
    """Normalize file path by removing user-specific prefixes."""
    # Remove common user-specific prefixes
    patterns = [
        r'^/Users/[^/]+/',
        r'^/home/[^/]+/',
        r'^/mnt/c/Users/[^/]+/',
        r'^C:\\Users\\[^\\]+\\',
    ]
    result = file_path
    for pattern in patterns:
        result = re.sub(pattern, '~/', result)
    return result


def merge_overlapping_sequences(
    sequences: dict[tuple[str, ...], RawPattern],
    min_overlap_ratio: float = 0.5
) -> list[RawPattern]:
    """Merge overlapping sequences into longer patterns when confident.

    Two sequences can be merged if:
    1. They have overlapping elements (like ABC + BCD -> ABCD)
    2. Their occurrence counts are similar (within 50% of each other)
    """
    if not sequences:
        return []

    # Sort by occurrence count descending
    sorted_seqs = sorted(
        sequences.items(),
        key=lambda x: x[1].occurrences,
        reverse=True
    )

    merged: list[RawPattern] = []
    used: set[tuple[str, ...]] = set()

    for seq, pattern in sorted_seqs:
        if seq in used:
            continue

        # Try to find a mergeable sequence
        best_merge = None
        best_merged_seq = None

        for other_seq, other_pattern in sorted_seqs:
            if other_seq == seq or other_seq in used:
                continue

            # Check for overlap at end of seq and start of other_seq
            # e.g., (A,B,C) and (B,C,D) -> (A,B,C,D)
            for overlap_len in range(1, len(seq)):
                if seq[-overlap_len:] == other_seq[:overlap_len]:
                    # Check if counts are similar enough
                    min_count = min(pattern.occurrences, other_pattern.occurrences)
                    max_count = max(pattern.occurrences, other_pattern.occurrences)
                    if min_count / max_count >= min_overlap_ratio:
                        merged_seq = seq + other_seq[overlap_len:]
                        best_merge = other_seq
                        best_merged_seq = merged_seq
                        break

            if best_merge:
                break

        if best_merged_seq and best_merge:
            # Create merged pattern
            other_pattern = sequences[best_merge]
            merged_pattern = RawPattern(
                pattern_type="tool_sequence",
                pattern_key=" → ".join(best_merged_seq),
                occurrences=min(pattern.occurrences, other_pattern.occurrences),
                sessions=pattern.sessions | other_pattern.sessions,
                projects=pattern.projects | other_pattern.projects,
                first_seen=min(filter(None, [pattern.first_seen, other_pattern.first_seen])) if pattern.first_seen or other_pattern.first_seen else None,
                last_seen=max(filter(None, [pattern.last_seen, other_pattern.last_seen])) if pattern.last_seen or other_pattern.last_seen else None,
                examples=pattern.examples + other_pattern.examples,
            )
            merged.append(merged_pattern)
            used.add(seq)
            used.add(best_merge)
        else:
            # No merge possible, keep original
            pattern.pattern_key = " → ".join(seq)
            merged.append(pattern)
            used.add(seq)

    return merged


class PatternDetector:
    """Detects patterns across archived sessions."""

    def __init__(
        self,
        db: Database,
        min_occurrences: int = 3,
        min_sessions: int = 2,
        project_filter: Optional[str] = None,
        since: Optional[str] = None,
    ):
        self.db = db
        self.min_occurrences = min_occurrences
        self.min_sessions = min_sessions
        self.project_filter = project_filter
        self.since = since

    def _get_filtered_sessions(self) -> list[dict]:
        """Get sessions matching filters."""
        if self.project_filter:
            sessions = self.db.get_sessions_by_project(self.project_filter)
        else:
            sessions = self.db.get_all_sessions()

        if self.since:
            sessions = [s for s in sessions if s.get("started_at", "") >= self.since]

        return sessions

    def detect_tool_sequences(self) -> list[RawPattern]:
        """Detect repeated tool call sequences (3-grams)."""
        sessions = self._get_filtered_sessions()
        sequence_counts: dict[tuple[str, ...], RawPattern] = defaultdict(
            lambda: RawPattern(
                pattern_type="tool_sequence",
                pattern_key="",
                occurrences=0,
            )
        )

        for session in sessions:
            tool_calls = self.db.get_tool_calls_for_session(session["id"])
            sequences = extract_tool_sequences(tool_calls)

            for seq in sequences:
                pattern = sequence_counts[seq]
                pattern.occurrences += 1
                pattern.sessions.add(session["id"])
                pattern.projects.add(session["project"])

                # Track timestamps
                timestamp = session.get("started_at")
                if timestamp:
                    if not pattern.first_seen or timestamp < pattern.first_seen:
                        pattern.first_seen = timestamp
                    if not pattern.last_seen or timestamp > pattern.last_seen:
                        pattern.last_seen = timestamp

                # Add example (raw tool names)
                if len(pattern.examples) < 3:
                    pattern.examples.append(" → ".join(seq))

        # Filter by thresholds
        filtered = {
            seq: p for seq, p in sequence_counts.items()
            if p.occurrences >= self.min_occurrences
            and len(p.sessions) >= self.min_sessions
        }

        # Merge overlapping sequences
        return merge_overlapping_sequences(filtered)

    def detect_prompt_prefixes(self) -> list[RawPattern]:
        """Detect repeated prompt prefixes."""
        sessions = self._get_filtered_sessions()
        prefix_patterns: dict[str, RawPattern] = defaultdict(
            lambda: RawPattern(
                pattern_type="prompt_prefix",
                pattern_key="",
                occurrences=0,
            )
        )

        for session in sessions:
            messages = self.db.get_messages_for_session(session["id"])
            user_messages = [m for m in messages if m.get("type") == "user"]

            for msg in user_messages:
                content = msg.get("content", "")
                if not content or len(content) < 10:
                    continue

                prefix = extract_prompt_prefix(content)
                if len(prefix.split()) < 3:  # Skip very short prefixes
                    continue

                pattern = prefix_patterns[prefix]
                pattern.pattern_key = prefix
                pattern.occurrences += 1
                pattern.sessions.add(session["id"])
                pattern.projects.add(session["project"])

                timestamp = msg.get("timestamp")
                if timestamp:
                    if not pattern.first_seen or timestamp < pattern.first_seen:
                        pattern.first_seen = timestamp
                    if not pattern.last_seen or timestamp > pattern.last_seen:
                        pattern.last_seen = timestamp

                if len(pattern.examples) < 3:
                    # Store truncated original
                    pattern.examples.append(content[:100] + ("..." if len(content) > 100 else ""))

        return [
            p for p in prefix_patterns.values()
            if p.occurrences >= self.min_occurrences
            and len(p.sessions) >= self.min_sessions
        ]

    def detect_prompt_phrases(self) -> list[RawPattern]:
        """Detect repeated phrases within prompts (5-grams)."""
        sessions = self._get_filtered_sessions()
        phrase_patterns: dict[tuple[str, ...], RawPattern] = defaultdict(
            lambda: RawPattern(
                pattern_type="prompt_phrase",
                pattern_key="",
                occurrences=0,
            )
        )

        for session in sessions:
            messages = self.db.get_messages_for_session(session["id"])
            user_messages = [m for m in messages if m.get("type") == "user"]

            for msg in user_messages:
                content = msg.get("content", "")
                if not content:
                    continue

                phrases = extract_phrase_ngrams(content)
                seen_in_msg: set[tuple[str, ...]] = set()

                for phrase in phrases:
                    if phrase in seen_in_msg:
                        continue
                    seen_in_msg.add(phrase)

                    pattern = phrase_patterns[phrase]
                    pattern.pattern_key = " ".join(phrase)
                    pattern.occurrences += 1
                    pattern.sessions.add(session["id"])
                    pattern.projects.add(session["project"])

                    timestamp = msg.get("timestamp")
                    if timestamp:
                        if not pattern.first_seen or timestamp < pattern.first_seen:
                            pattern.first_seen = timestamp
                        if not pattern.last_seen or timestamp > pattern.last_seen:
                            pattern.last_seen = timestamp

                    if len(pattern.examples) < 3:
                        pattern.examples.append(content[:100] + ("..." if len(content) > 100 else ""))

        return [
            p for p in phrase_patterns.values()
            if p.occurrences >= self.min_occurrences
            and len(p.sessions) >= self.min_sessions
        ]

    def detect_file_access(self) -> list[RawPattern]:
        """Detect files that are repeatedly accessed."""
        sessions = self._get_filtered_sessions()
        file_patterns: dict[str, RawPattern] = defaultdict(
            lambda: RawPattern(
                pattern_type="file_access",
                pattern_key="",
                occurrences=0,
            )
        )

        for session in sessions:
            tool_calls = self.db.get_tool_calls_for_session(session["id"])
            seen_files: set[str] = set()

            for tc in tool_calls:
                tool_name = tc.get("tool_name", "")
                if tool_name not in ("Read", "Edit", "Write"):
                    continue

                try:
                    input_data = json.loads(tc.get("input_json", "{}"))
                except json.JSONDecodeError:
                    continue

                file_path = input_data.get("file_path", "")
                if not file_path:
                    continue

                normalized = normalize_file_path(file_path)

                # Count each file once per session
                if normalized in seen_files:
                    continue
                seen_files.add(normalized)

                pattern = file_patterns[normalized]
                pattern.pattern_key = normalized
                pattern.occurrences += 1
                pattern.sessions.add(session["id"])
                pattern.projects.add(session["project"])

                timestamp = tc.get("timestamp")
                if timestamp:
                    if not pattern.first_seen or timestamp < pattern.first_seen:
                        pattern.first_seen = timestamp
                    if not pattern.last_seen or timestamp > pattern.last_seen:
                        pattern.last_seen = timestamp

                if len(pattern.examples) < 3:
                    pattern.examples.append(f"{tool_name}: {file_path}")

        return [
            p for p in file_patterns.values()
            if p.occurrences >= self.min_occurrences
            and len(p.sessions) >= self.min_sessions
        ]

    def detect_all(self) -> dict[str, list[RawPattern]]:
        """Detect all pattern types."""
        return {
            "tool_sequences": self.detect_tool_sequences(),
            "prompt_prefixes": self.detect_prompt_prefixes(),
            "prompt_phrases": self.detect_prompt_phrases(),
            "file_access": self.detect_file_access(),
        }


def detect_patterns(
    db: Database,
    min_occurrences: int = 3,
    min_sessions: int = 2,
    project_filter: Optional[str] = None,
    since: Optional[str] = None,
) -> dict:
    """Main entry point for pattern detection.

    Returns a dict with summary and patterns ready for JSON output.
    """
    detector = PatternDetector(
        db=db,
        min_occurrences=min_occurrences,
        min_sessions=min_sessions,
        project_filter=project_filter,
        since=since,
    )

    patterns = detector.detect_all()
    sessions = detector._get_filtered_sessions()
    projects = set(s["project"] for s in sessions)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "total_sessions_analyzed": len(sessions),
            "total_projects": len(projects),
            "patterns_found": {
                "tool_sequences": len(patterns["tool_sequences"]),
                "prompt_prefixes": len(patterns["prompt_prefixes"]),
                "prompt_phrases": len(patterns["prompt_phrases"]),
                "file_access": len(patterns["file_access"]),
            },
        },
        "patterns": {
            "tool_sequences": [p.to_dict() for p in patterns["tool_sequences"]],
            "prompt_prefixes": [p.to_dict() for p in patterns["prompt_prefixes"]],
            "prompt_phrases": [p.to_dict() for p in patterns["prompt_phrases"]],
            "file_access": [p.to_dict() for p in patterns["file_access"]],
        },
    }
