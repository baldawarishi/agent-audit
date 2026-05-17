"""Tests for the mining failure-classification query."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.mining import format_failures_table, get_query, list_queries
from agent_audit.mining.failures import (
    _example,
    classify_error,
    failures_query,
)
from agent_audit.models import Message, Session, ToolCall, ToolResult


@pytest.mark.parametrize(
    "content,bucket",
    [
        ("401 Unauthorized: token expired", "auth"),
        ("403 Forbidden", "auth"),
        ("Permission denied", "auth"),
        ("404 page missing", "not_found"),
        ("No such file or directory", "not_found"),
        ("400 Bad Request", "http_client"),
        ("operation timed out after 30s", "timeout"),
        ("context deadline exceeded", "timeout"),
        ("xelatex failed to compile", "pdf"),
        ("pandoc conversion failed", "pdf"),
        ("error: something broke", "runtime"),
        ("Traceback (most recent call last):\n  File ...", "runtime"),
        ("something weird happened", "other"),
        ("UNAUTHORIZED", "auth"),  # case-insensitive
        (None, "other"),
        ("", "other"),
    ],
)
def test_classify_error_buckets(content, bucket):
    assert classify_error(content) == bucket


def test_classify_error_precedence_auth_beats_http_client():
    # Contains both 401 and 400 -> auth wins (rule order is load-bearing).
    assert classify_error("HTTP 401 then later a 400") == "auth"


@pytest.mark.parametrize(
    "content,bucket",
    [
        # Status codes need word boundaries: these must NOT classify.
        ("internal/poll.(*pollDesc).wait(0xdd68d8d4000?, 0x0)", "other"),
        ("read 4040 bytes then 40123 more", "other"),
        ("contributing to her 401k plan failed", "other"),
        # Decimal fractions must not trip the status-code rule.
        ("SmallTables 10 (avg size 3.400, max 6)", "other"),
        ("schema v2.401 deploy failed", "other"),
        # But genuine codes still match, incl. trailing-period prose.
        ("HTTP 400 Bad Request", "http_client"),
        ("server returned status code 403", "auth"),
        ("Error 404.", "not_found"),
    ],
)
def test_classify_error_numeric_word_boundary(content, bucket):
    assert classify_error(content) == bucket


@pytest.mark.parametrize(
    "content,bucket,expected",
    [
        # Generic bash header is skipped for the line that proves the bucket.
        (
            "Exit code 1\ncurl: (28) Operation timed out after 30000 ms",
            "timeout",
            "curl: (28) Operation timed out after 30000 ms",
        ),
        (
            "Exit code 1\nTraceback (most recent call last):\n  File x",
            "runtime",
            "Traceback (most recent call last):",
        ),
        # other has no needle -> first non-empty line.
        ("Exit code 1\nsomething odd", "other", "Exit code 1"),
        # blank lines stripped; cap at 120 chars.
        ("\n  \n401 " + "x" * 200, "auth", ("401 " + "x" * 200)[:120]),
        (None, "other", ""),
    ],
)
def test_example_picks_classifying_line(content, bucket, expected):
    assert _example(content, bucket) == expected


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    database = Database(db_path)
    database.connect()
    yield database
    database.close()
    db_path.unlink()


def _insert_with_errors(db, sid, project, results, started_at="2026-01-01T10:00:00Z"):
    """results: list of (content, is_error) tuples -> one call/result each.

    ``started_at`` matters: get_all_sessions() scans started_at DESC, and
    the first error encountered per bucket is the kept example.
    """
    ts = started_at
    db.insert_session(Session(
        id=sid,
        project=project,
        started_at=ts,
        messages=[Message(id=f"m-{sid}", session_id=sid, type="assistant",
                          timestamp=ts, content="")],
        tool_calls=[ToolCall(id=f"{sid}-c{i}", message_id=f"m-{sid}",
                             session_id=sid, tool_name="Bash",
                             input_json="{}", timestamp=ts)
                    for i in range(len(results))],
        tool_results=[ToolResult(id=f"{sid}-r{i}", tool_call_id=f"{sid}-c{i}",
                                 session_id=sid, content=content,
                                 is_error=is_err, timestamp=ts)
                      for i, (content, is_err) in enumerate(results)],
    ))


def test_failures_query_envelope_and_ordering(db):
    # s1 is the newest -> scanned first -> its 401 is the kept auth example.
    _insert_with_errors(db, "s1", "p1", [
        ("401 Unauthorized", True),
        ("404 not found", True),
        ("ok", False),
    ], started_at="2026-01-03T10:00:00Z")
    _insert_with_errors(db, "s2", "p2", [
        ("permission denied here", True),
        ("plain weird", True),
    ], started_at="2026-01-02T10:00:00Z")
    _insert_with_errors(db, "s3", "p3", [("ok", False)],
                        started_at="2026-01-01T10:00:00Z")

    result = failures_query(db, examples=1)

    assert result["name"] == "02_failure_classification"
    meta = result["meta"]
    assert set(meta) == {
        "sessions_scanned", "sessions_with_errors", "total_failures",
    }
    assert meta["sessions_scanned"] == 3
    assert meta["sessions_with_errors"] == 2
    assert meta["total_failures"] == 4

    rows = result["rows"]
    # count desc, ties broken by bucket asc -> auth(2), not_found(1), other(1)
    assert [(r["bucket"], r["count"]) for r in rows] == [
        ("auth", 2), ("not_found", 1), ("other", 1),
    ]
    auth = rows[0]
    assert auth["pct_of_failures"] == pytest.approx(50.0)
    assert auth["sessions_affected"] == 2
    assert auth["examples"] == ["401 Unauthorized"]
    assert sum(r["pct_of_failures"] for r in rows) == pytest.approx(100.0)


def test_failures_query_no_errors_is_empty(db):
    _insert_with_errors(db, "s1", "p1", [("ok", False)])
    result = failures_query(db)
    assert result["rows"] == []
    assert result["meta"]["total_failures"] == 0
    assert result["meta"]["sessions_with_errors"] == 0


def test_registry_has_failures():
    assert list_queries() == ["bash", "bash-sequences", "churn", "failures", "sequences"]
    assert get_query("failures") is failures_query


def test_format_failures_table_known_envelope():
    result = {
        "name": "02_failure_classification",
        "meta": {
            "sessions_scanned": 10,
            "sessions_with_errors": 4,
            "total_failures": 7,
        },
        "rows": [
            {"bucket": "auth", "count": 5, "pct_of_failures": 71.4,
             "sessions_affected": 3, "examples": ["401 Unauthorized"]},
            {"bucket": "other", "count": 2, "pct_of_failures": 28.6,
             "sessions_affected": 1, "examples": []},
        ],
    }
    out = format_failures_table(result)
    lines = out.splitlines()
    assert lines[0].startswith("bucket")
    assert "401 Unauthorized" in out
    assert " 71.4%" in out
    assert (
        lines[-1]
        == "sessions scanned: 10  |  with errors: 4  |  total failures: 7"
    )


def test_format_failures_table_empty_rows():
    result = {
        "name": "02_failure_classification",
        "meta": {
            "sessions_scanned": 5,
            "sessions_with_errors": 0,
            "total_failures": 0,
        },
        "rows": [],
    }
    assert (
        format_failures_table(result)
        == "Scanned 5 sessions; no error results found."
    )


def test_mine_cli_list_and_failures(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    db_path = tmp_path / "sessions.db"
    database = Database(db_path)
    database.connect()
    _insert_with_errors(database, "s1", "p1", [
        ("401 Unauthorized: token expired", True),
        ("something weird", True),
    ])
    database.close()

    runner = CliRunner()

    res = runner.invoke(main, ["mine", "list"])
    assert res.exit_code == 0, res.output
    assert res.output.split() == ["bash", "bash-sequences", "churn", "failures", "sequences"]

    json_out = tmp_path / "out" / "02_failure_classification.json"
    res = runner.invoke(
        main,
        ["mine", "failures", "--db", str(db_path),
         "--write-json", str(json_out)],
    )
    assert res.exit_code == 0, res.output
    assert "total failures:" in res.output
    assert "auth" in res.output
    assert f"Wrote {json_out}" in res.output

    data = json.loads(json_out.read_text())
    assert data["name"] == "02_failure_classification"
    assert data["meta"]["total_failures"] == 2
    counts = [r["count"] for r in data["rows"]]
    assert counts == sorted(counts, reverse=True)


def test_mine_failures_missing_db(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    res = CliRunner().invoke(
        main, ["mine", "failures", "--db", str(tmp_path / "nope.db")]
    )
    assert res.exit_code == 0
    assert "No archive database found" in res.output
