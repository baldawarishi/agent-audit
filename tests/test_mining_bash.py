"""Tests for the mining bash-subcommand query (agent_audit.mining.bash)."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.mining import format_bash_table, get_query, list_queries
from agent_audit.mining.bash import (
    NO_FAIL_SIGNAL,
    _command_text,
    bash_subcommands_query,
    first_token,
)
from agent_audit.models import Message, Session, ToolCall, ToolResult


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git status", "git"),
        ("FOO=1 BAR=2 npm test", "npm"),
        ("sudo apt-get install -y curl", "apt-get"),
        ("cat file | grep x", "cat"),
        ("cd src && pytest -q", "cd"),  # verbatim: cd is a finding, not rewritten
        ('"git" log --oneline', "git"),  # surrounding quotes stripped
        ("", ""),
        (None, ""),
    ],
)
def test_first_token(command, expected):
    assert first_token(command) == expected


@pytest.mark.parametrize(
    ("input_json", "expected"),
    [
        ('{"command": "git status", "description": "x"}', "git status"),
        ('{"cmd": "ls -la"}', "ls -la"),
        ('{"arguments": {"command": "make build"}}', "make build"),
        ('{"arguments": "raw text"}', "raw text"),
        ("{}", ""),
        ("not json", ""),
        (None, ""),
    ],
)
def test_command_text(input_json, expected):
    assert _command_text(input_json) == expected


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    database = Database(db_path)
    database.connect()
    yield database
    database.close()
    db_path.unlink()


def _insert(db, sid, calls, fail_ids=()):
    """calls: list of (call_id, tool_name, command_or_None)."""
    ts = "2026-01-01T10:00:00Z"
    db.insert_session(Session(
        id=sid,
        project=f"p-{sid}",
        started_at=ts,
        messages=[Message(id=f"m-{sid}", session_id=sid, type="assistant",
                          timestamp=ts, content="")],
        tool_calls=[
            ToolCall(
                id=cid, message_id=f"m-{sid}", session_id=sid,
                tool_name=tname,
                input_json=(
                    json.dumps({"command": cmd}) if cmd is not None else "{}"
                ),
                timestamp=ts,
            )
            for cid, tname, cmd in calls
        ],
        tool_results=[
            ToolResult(id=f"r-{cid}", tool_call_id=cid, session_id=sid,
                       content="Exit code 1", is_error=True, timestamp=ts)
            for cid in fail_ids
        ],
    ))


def test_bash_query_envelope_and_ordering(db):
    # s1: git status, git diff (fails), npm test, + a non-bash Read (excluded)
    _insert(db, "s1", [
        ("s1c1", "Bash", "git status"),
        ("s1c2", "bash", "git diff HEAD"),
        ("s1c3", "run_shell_command", "npm test"),
        ("s1c4", "Read", "ignored"),
    ], fail_ids=("s1c2",))
    # s2: another git -> git spans 2 sessions
    _insert(db, "s2", [("s2c1", "Bash", "git log --oneline")])

    result = bash_subcommands_query(db)

    assert result["name"] == "03_bash_subcommands"
    meta = result["meta"]
    assert meta == {
        "sessions_scanned": 2,
        "bash_calls": 4,           # Read excluded
        "distinct_subcommands": 2,  # git, npm
        "fail_rate_known": True,    # the archive carries is_error
        "fail_rate_note": None,
    }

    rows = result["rows"]
    assert [r["subcommand"] for r in rows] == ["git", "npm"]  # count desc
    git = rows[0]
    assert git["count"] == 3
    assert git["sessions"] == 2
    assert git["calls_per_session"] == pytest.approx(1.5)
    assert git["fail_rate"] == pytest.approx(1 / 3)
    npm = rows[1]
    assert npm["count"] == 1
    assert npm["fail_rate"] == 0.0


def test_exec_command_is_bash_family_but_exec_is_not(db):
    """codex's ``exec_command`` carries ``cmd``; its ``exec`` is JavaScript."""
    ts = "2026-01-01T10:00:00Z"
    db.insert_session(Session(
        id="s3", project="petri", started_at=ts,
        messages=[Message(id="m3", session_id="s3", type="assistant",
                          timestamp=ts, content="")],
        tool_calls=[
            ToolCall(id="c1", message_id="m3", session_id="s3",
                     tool_name="exec_command",
                     input_json=json.dumps({"cmd": "uv run pytest -q"}),
                     timestamp=ts),
            ToolCall(id="c2", message_id="m3", session_id="s3",
                     tool_name="exec",
                     input_json='const r = await tools.exec_command({cmd:"ls"});',
                     timestamp=ts),
        ],
        tool_results=[ToolResult(id="r1", tool_call_id="c1", session_id="s3",
                                 content="Exit code 1", is_error=True,
                                 timestamp=ts)],
    ))

    result = bash_subcommands_query(db)

    assert [r["subcommand"] for r in result["rows"]] == ["uv"]
    assert result["meta"]["bash_calls"] == 1  # the JavaScript exec is excluded
    # The archive still measures fail_rate -- only the mirror leaves it unknown.
    assert result["rows"][0]["fail_rate"] == 1.0
    assert result["meta"]["fail_rate_known"] is True


def test_bash_query_no_bash_calls(db):
    _insert(db, "s1", [("s1c1", "Read", "x")])
    result = bash_subcommands_query(db)
    assert result["rows"] == []
    assert result["meta"]["bash_calls"] == 0


def test_registry_includes_bash():
    assert "bash" in list_queries()
    assert get_query("bash") is bash_subcommands_query


def test_format_bash_table_empty_rows():
    result = {
        "name": "03_bash_subcommands",
        "meta": {"sessions_scanned": 7, "bash_calls": 0,
                 "distinct_subcommands": 0},
        "rows": [],
    }
    assert (
        format_bash_table(result, 20)
        == "Scanned 7 sessions; no bash tool calls found."
    )


def test_format_bash_table_known_envelope():
    result = {
        "name": "03_bash_subcommands",
        "meta": {"sessions_scanned": 3, "bash_calls": 4,
                 "distinct_subcommands": 1},
        "rows": [{
            "subcommand": "git", "count": 3, "sessions": 2,
            "calls_per_session": 1.5, "fail_rate": 1 / 3,
        }],
    }
    out = format_bash_table(result, top=20)
    lines = out.splitlines()
    assert lines[0].startswith("subcommand")
    assert "fail%" in lines[0]
    assert "git" in out
    assert " 33.3%" in out
    assert "1.50" in out
    assert lines[-1] == (
        "bash calls: 4  |  distinct subcommands: 1  |  sessions scanned: 3"
    )


def test_format_bash_table_unknown_fail_rate():
    """An unmeasurable fail_rate prints ``?`` + a reason, never ``0.0%``."""
    result = {
        "name": "03_bash_subcommands",
        "meta": {"sessions_scanned": 3, "bash_calls": 4,
                 "distinct_subcommands": 1, "fail_rate_known": False,
                 "fail_rate_note": NO_FAIL_SIGNAL},
        "rows": [{
            "subcommand": "git", "count": 3, "sessions": 2,
            "calls_per_session": 1.5, "fail_rate": None,
        }],
    }
    out = format_bash_table(result, top=20)
    assert "0.0%" not in out and "%" not in out.splitlines()[2]
    assert out.splitlines()[2].endswith("?")
    assert out.splitlines()[-1] == NO_FAIL_SIGNAL


def test_mine_cli_list_and_bash(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    db_path = tmp_path / "sessions.db"
    database = Database(db_path)
    database.connect()
    _insert(database, "s1", [
        ("s1c1", "Bash", "git status"),
        ("s1c2", "Bash", "git diff"),
        ("s1c3", "Bash", "pytest -q"),
    ], fail_ids=("s1c3",))
    database.close()

    runner = CliRunner()

    res = runner.invoke(main, ["mine", "list"])
    assert res.exit_code == 0, res.output
    assert res.output.split() == ["bash", "bash-sequences", "churn", "failures", "sequences"]

    json_out = tmp_path / "out" / "03_bash_subcommands.json"
    res = runner.invoke(
        main,
        ["mine", "bash", "--db", str(db_path), "--top", "20",
         "--write-json", str(json_out)],
    )
    assert res.exit_code == 0, res.output
    assert "bash calls: 3" in res.output
    assert "git" in res.output
    assert f"Wrote {json_out}" in res.output

    data = json.loads(json_out.read_text())
    assert data["name"] == "03_bash_subcommands"
    assert [r["subcommand"] for r in data["rows"]] == ["git", "pytest"]
    assert data["rows"][0]["count"] == 2  # git status + git diff


def test_mine_bash_missing_db(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    res = CliRunner().invoke(
        main, ["mine", "bash", "--db", str(tmp_path / "nope.db")]
    )
    assert res.exit_code == 0
    assert "No archive database found" in res.output
