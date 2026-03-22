"""Parse Goose agent sessions from SQLite database or JSONL files."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterator

from .models import (
    Commit,
    COMMIT_PATTERN,
    REPO_PUSH_PATTERN,
    Message,
    Session,
    ToolCall,
    ToolResult,
)
from .parser import project_name_from_cwd


GOOSE_HOME = Path.home() / ".local" / "share" / "goose" / "sessions"


def get_goose_home() -> Path:
    return GOOSE_HOME


def discover_goose_sessions(goose_home: Path | None = None) -> Iterator[tuple[str, str]]:
    """Discover all Goose sessions.

    Goose stores sessions in either:
    1. sessions.db (SQLite) - newer versions
    2. *.jsonl files - older versions

    Yields tuples of (session_identifier, project_name).
    For SQLite: session_identifier is the session id from the DB.
    For JSONL: session_identifier is the file path as a string.
    """
    home = goose_home or get_goose_home()
    if not home.exists():
        return

    db_path = home / "sessions.db"
    if db_path.exists():
        yield from _discover_from_sqlite(db_path)
    else:
        yield from _discover_from_jsonl(home)


def _discover_from_sqlite(db_path: Path) -> Iterator[tuple[str, str]]:
    """Discover sessions from Goose SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT id, name FROM sessions ORDER BY id")
        for row in cursor.fetchall():
            project_name = row["name"] if row["name"] else "goose"
            yield f"sqlite:{row['id']}", project_name
        conn.close()
    except sqlite3.Error:
        return


def _discover_from_jsonl(home: Path) -> Iterator[tuple[str, str]]:
    """Discover sessions from Goose JSONL files."""
    for jsonl_file in home.glob("*.jsonl"):
        project_name = _extract_project_from_jsonl(jsonl_file)
        yield str(jsonl_file), project_name


def _extract_project_from_jsonl(path: Path) -> str:
    """Extract project name from Goose JSONL session header."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    working_dir = obj.get("working_dir")
                    if working_dir:
                        return project_name_from_cwd(working_dir)
                except json.JSONDecodeError:
                    continue
                break
    except OSError:
        pass
    return "goose"


def parse_goose_session(
    session_identifier: str,
    project_name: str,
    goose_home: Path | None = None,
) -> Session:
    """Parse a Goose session into a Session object.

    session_identifier is either:
    - "sqlite:<id>" for SQLite-based sessions
    - A file path string for JSONL-based sessions
    """
    if session_identifier.startswith("sqlite:"):
        session_id = session_identifier[7:]
        home = goose_home or get_goose_home()
        db_path = home / "sessions.db"
        return _parse_sqlite_session(db_path, session_id, project_name)
    else:
        return _parse_jsonl_session(Path(session_identifier), project_name)


def _parse_sqlite_session(
    db_path: Path, session_id: str, project_name: str
) -> Session:
    """Parse a Goose session from SQLite."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    session = Session(
        id=session_id,
        project=project_name,
        agent_type="goose",
    )

    messages: list[Message] = []
    all_tool_calls: list[ToolCall] = []
    all_tool_results: list[ToolResult] = []
    all_commits: list[Commit] = []
    detected_repo: str | None = None

    cursor = conn.execute(
        "SELECT role, content_json, timestamp, created_timestamp "
        "FROM messages WHERE session_id = ? ORDER BY rowid",
        (session_id,),
    )

    for row in cursor.fetchall():
        role = row["role"]
        content_json = row["content_json"]
        timestamp_str = row["timestamp"] or ""
        created_ts = row["created_timestamp"]

        # Use timestamp string or convert epoch
        timestamp = timestamp_str
        if not timestamp and created_ts:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
            timestamp = dt.isoformat()

        if timestamp:
            if not session.started_at or timestamp < session.started_at:
                session.started_at = timestamp
            if not session.ended_at or timestamp > session.ended_at:
                session.ended_at = timestamp

        # Extract text from content_json
        text = _extract_text_from_content_json(content_json)

        msg_type = "assistant" if role == "assistant" else "user"

        msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            type=msg_type,
            timestamp=timestamp,
            content=text,
        )
        messages.append(msg)

        # Extract commits from assistant content
        if role == "assistant" and text:
            for match in COMMIT_PATTERN.finditer(text):
                all_commits.append(
                    Commit(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        commit_hash=match.group(1),
                        message=match.group(2),
                        timestamp=timestamp,
                    )
                )
            if not detected_repo:
                repo_match = REPO_PUSH_PATTERN.search(text)
                if repo_match:
                    detected_repo = repo_match.group(1)

    conn.close()

    session.messages = messages
    session.tool_calls = all_tool_calls
    session.tool_results = all_tool_results
    session.commits = all_commits
    session.claude_version = "goose"

    if not session.repo and detected_repo:
        session.repo = detected_repo
        session.repo_platform = "github"

    session.is_warmup = _is_warmup(session)

    return session


def _parse_jsonl_session(file_path: Path, project_name: str) -> Session:
    """Parse a Goose JSONL session file."""
    session_id = file_path.stem

    session = Session(
        id=session_id,
        project=project_name,
        agent_type="goose",
    )

    messages: list[Message] = []
    all_commits: list[Commit] = []
    detected_repo: str | None = None
    header_parsed = False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # First entry is often the header
                if not header_parsed:
                    if obj.get("working_dir"):
                        session.cwd = obj["working_dir"]
                        session.project = project_name_from_cwd(obj["working_dir"])
                    if obj.get("id"):
                        session.id = obj["id"]
                    if obj.get("description"):
                        session.summary = obj["description"]
                    header_parsed = True
                    # If this is just a header (no role), skip
                    if "role" not in obj:
                        continue

                role = obj.get("role", "")
                if not role:
                    continue

                content = obj.get("content", "")
                text = _extract_text_from_content_json(
                    json.dumps(content) if isinstance(content, (list, dict)) else content
                )

                # Timestamp from 'created' field (epoch seconds)
                timestamp = ""
                created = obj.get("created")
                if created:
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(created, tz=timezone.utc)
                    timestamp = dt.isoformat()

                if timestamp:
                    if not session.started_at or timestamp < session.started_at:
                        session.started_at = timestamp
                    if not session.ended_at or timestamp > session.ended_at:
                        session.ended_at = timestamp

                msg_type = "assistant" if role == "assistant" else "user"

                msg = Message(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    type=msg_type,
                    timestamp=timestamp,
                    content=text,
                )
                messages.append(msg)

                # Extract commits
                if text:
                    for match in COMMIT_PATTERN.finditer(text):
                        all_commits.append(
                            Commit(
                                id=str(uuid.uuid4()),
                                session_id=session.id,
                                commit_hash=match.group(1),
                                message=match.group(2),
                                timestamp=timestamp,
                            )
                        )
                    if not detected_repo:
                        repo_match = REPO_PUSH_PATTERN.search(text)
                        if repo_match:
                            detected_repo = repo_match.group(1)

    except OSError:
        pass

    session.messages = messages
    session.commits = all_commits
    session.claude_version = "goose"

    if not session.repo and detected_repo:
        session.repo = detected_repo
        session.repo_platform = "github"

    session.is_warmup = _is_warmup(session)

    return session


def _extract_text_from_content_json(content_json: str | None) -> str:
    """Extract text from Goose content_json field.

    Can be a JSON array of content blocks, a plain string, or None.
    """
    if not content_json:
        return ""

    # Try parsing as JSON
    try:
        parsed = json.loads(content_json)
    except (json.JSONDecodeError, TypeError):
        return content_json  # Return as-is if not valid JSON

    if isinstance(parsed, str):
        return parsed

    if isinstance(parsed, list):
        texts = []
        for block in parsed:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif "text" in block:
                    texts.append(block["text"])
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts)

    return str(parsed)


def _is_warmup(session: Session) -> bool:
    """Detect if a Goose session is a warmup session."""
    if not session.messages:
        return False
    for msg in session.messages:
        if msg.type == "user":
            content = msg.content.strip() if msg.content else ""
            if content.lower() == "warmup":
                return True
            break
    return False
