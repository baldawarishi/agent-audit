#!/usr/bin/env python3
"""Dump five real AgentsView sessions into offline test fixtures.

Writes ``tests/fixtures/agentsview/mirror.json`` (the reviewable source of
truth) and rebuilds ``mirror.duckdb`` from it, so every later step can test
against the mirror's real schema with no daemon and no live archive.

One session per shape worth protecting: Claude (Bash + head-anchored errors),
Codex (``exec_command`` vs the non-shell ``exec``), antigravity (no
``result_content`` at all), and -- added in Step 5 -- gemini and pi, whose
failures are a *trailing* exit-code line the head anchor cannot see.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
MIRROR = Path.home() / ".agentsview" / "sessions.duckdb"
OUT_DIR = REPO / "tests" / "fixtures" / "agentsview"
TABLES = ("sessions", "messages", "tool_calls", "tool_result_events")
CAP = 1200

SESSIONS = (
    "6a5843f9-4c08-40b9-9810-37ab161c0556",
    "codex:019f920d-851a-7fa0-857f-a89931b98a2f",
    "antigravity-cli:83ff1828-0266-4df9-b3ce-2c99e6438619",
    "gemini:cd1db565-ca0c-400d-aad0-0faaed74369b",
    "pi:7261bd39-9f0d-45ca-84ee-1e27cd89b833",
)
DROPPED = {"messages": ("content", "thinking_text")}

# The user name also shows up encoded (Claude's ``-Users-name-workspaces``
# project slugs, ``/T/pytest-of-name``), so scrub the bare token too.
_SCRUBS = (
    (re.compile(re.escape(str(Path.home()))), "/Users/agent"),
    (re.compile(re.escape(Path.home().name)), "agent"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "dev@example.com"),
    (re.compile(r"\b(?:sk-|ghp_|gho_|github_pat_|xox[bap]-|AKIA)[A-Za-z0-9_-]{8,}"),
     "<redacted>"),
)


def redact(value: object) -> object:
    """Replace home paths, emails and token-shaped strings; stamps to ISO text."""
    if not isinstance(value, str):
        return value.isoformat() if hasattr(value, "isoformat") else value
    for pattern, replacement in _SCRUBS:
        value = pattern.sub(replacement, value)
    return value


def clean(name: str, value: object) -> object:
    """Redact and cap one value; ``input_json`` is edited inside the object.

    Editing the encoded text would corrupt escapes (``\\u003c`` reads as an
    email to the redactor), so JSON inputs are parsed, cleaned and re-dumped.
    """
    if not isinstance(value, str):
        return value.isoformat() if hasattr(value, "isoformat") else value
    parsed = None
    if name == "input_json":
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
    if not isinstance(parsed, dict):
        return redact(value)[:CAP]
    return json.dumps({
        key: redact(item)[:CAP] if isinstance(item, str) else item
        for key, item in parsed.items()
    })


def collect(conn) -> dict:
    schema, rows = {}, {}
    for table in TABLES:
        columns = [(r[0], r[1]) for r in conn.execute(f"describe {table}").fetchall()]
        schema[table] = columns
        key = "id" if table == "sessions" else "session_id"
        raw = conn.execute(
            f"select * from {table} where {key} = any(?)", [list(SESSIONS)]
        ).fetchall()
        dropped = DROPPED.get(table, ())
        rows[table] = [
            {
                name: None if name in dropped else clean(name, value)
                for (name, _), value in zip(columns, row)
            }
            for row in raw
        ]
    return {"schema": schema, "rows": rows}


def build_duckdb(payload: dict, path: Path) -> None:
    """Rebuild the binary from the JSON; a small block size keeps it ~200 KB."""
    path.unlink(missing_ok=True)
    conn = duckdb.connect(":memory:")
    conn.execute(f"attach '{path}' as fixture (block_size 16384)")
    for table, columns in payload["schema"].items():
        names = [f'"{name}" {kind}' for name, kind in columns]
        conn.execute(f"create table fixture.{table} ({', '.join(names)})")
        rows = payload["rows"][table]
        if not rows:
            continue
        placeholders = ", ".join("?" * len(columns))
        conn.executemany(
            f"insert into fixture.{table} values ({placeholders})",
            [[row[name] for name, _ in columns] for row in rows],
        )
    conn.close()


def main() -> None:
    conn = duckdb.connect(str(MIRROR), read_only=True)
    payload = collect(conn)
    payload["meta"] = {
        "source": "agentsview duckdb push (v0.40.1)",
        "sessions": list(SESSIONS),
        "scrubbed": "home paths, emails, token-shaped strings",
        "text_cap_chars": CAP,
        "dropped_columns": {t: list(c) for t, c in DROPPED.items()},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "mirror.json"
    json_path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    build_duckdb(payload, OUT_DIR / "mirror.duckdb")
    counts = {t: len(rows) for t, rows in payload["rows"].items()}
    print(f"wrote {json_path} ({json_path.stat().st_size // 1024} KB) rows={counts}")


if __name__ == "__main__":
    main()
