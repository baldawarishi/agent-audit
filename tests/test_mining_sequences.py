"""Tests for the mining tool-sequence query (agent_audit.mining.sequences)."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.mining import format_sequences_table, get_query, list_queries
from agent_audit.mining.sequences import tool_sequences_query, trigrams
from agent_audit.models import Message, Session, ToolCall


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([], []),
        (["A"], []),
        (["A", "B"], []),
        (["A", "B", "C"], [("A", "B", "C")]),
        (["A", "B", "C", "D"], [("A", "B", "C"), ("B", "C", "D")]),
        (["A", "A", "A"], [("A", "A", "A")]),  # repeats kept
        (["A", "A", "A", "A"], [("A", "A", "A"), ("A", "A", "A")]),  # dup kept
    ],
)
def test_trigrams(names, expected):
    assert trigrams(names) == expected


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    database = Database(db_path)
    database.connect()
    yield database
    database.close()
    db_path.unlink()


def _insert(db, sid, tool_names):
    """One tool call per name, strictly increasing ts -> deterministic order."""
    base = "2026-01-01T10:00:00Z"
    db.insert_session(Session(
        id=sid,
        project=f"p-{sid}",
        started_at=base,
        messages=[Message(id=f"m-{sid}", session_id=sid, type="assistant",
                          timestamp=base, content="")],
        tool_calls=[
            ToolCall(
                id=f"{sid}c{i}", message_id=f"m-{sid}", session_id=sid,
                tool_name=name, input_json="{}",
                timestamp=f"2026-01-01T10:00:{i:02d}Z",
            )
            for i, name in enumerate(tool_names)
        ],
        tool_results=[],
    ))


def test_sequences_envelope_and_ordering(db):
    # s1: 3 distinct trigrams; s2 repeats (Read,Edit,Bash); s3 < 3 calls.
    _insert(db, "s1", ["Read", "Edit", "Bash", "Read", "Edit"])
    _insert(db, "s2", ["Read", "Edit", "Bash"])
    _insert(db, "s3", ["Read", "Edit"])

    result = tool_sequences_query(db)

    assert result["name"] == "04_tool_sequences"
    assert result["meta"] == {
        "sessions_scanned": 3,
        "sessions_with_3plus_calls": 2,  # s3 has only 2 calls
        "distinct_trigrams": 3,
    }
    assert result["rows"] == [
        {"trigram": "Read→Edit→Bash", "count": 2, "sessions": 2},
        {"trigram": "Bash→Read→Edit", "count": 1, "sessions": 1},
        {"trigram": "Edit→Bash→Read", "count": 1, "sessions": 1},
    ]


def test_per_session_distinct_session_tally(db):
    # (A,A,A) occurs twice in ONE session: count +2 but sessions +1.
    _insert(db, "s1", ["A", "A", "A", "A"])
    result = tool_sequences_query(db)
    assert result["rows"] == [{"trigram": "A→A→A", "count": 2, "sessions": 1}]
    assert result["meta"]["distinct_trigrams"] == 1


def test_sequences_no_3plus_calls(db):
    _insert(db, "s1", ["Read", "Edit"])
    result = tool_sequences_query(db)
    assert result["rows"] == []
    assert result["meta"] == {
        "sessions_scanned": 1,
        "sessions_with_3plus_calls": 0,
        "distinct_trigrams": 0,
    }


def test_registry_includes_sequences():
    assert "sequences" in list_queries()
    assert get_query("sequences") is tool_sequences_query


def test_format_sequences_table_empty_rows():
    result = {
        "name": "04_tool_sequences",
        "meta": {"sessions_scanned": 9, "sessions_with_3plus_calls": 0,
                 "distinct_trigrams": 0},
        "rows": [],
    }
    assert (
        format_sequences_table(result, 20)
        == "Scanned 9 sessions; no 3+-call sequences found."
    )


def test_format_sequences_table_known_envelope():
    result = {
        "name": "04_tool_sequences",
        "meta": {"sessions_scanned": 3, "sessions_with_3plus_calls": 2,
                 "distinct_trigrams": 3},
        "rows": [
            {"trigram": "Read→Edit→Bash", "count": 2, "sessions": 2},
            {"trigram": "Bash→Read→Edit", "count": 1, "sessions": 1},
        ],
    }
    out = format_sequences_table(result, top=20)
    lines = out.splitlines()
    assert lines[0].startswith("trigram")
    assert "count" in lines[0]
    assert "Read→Edit→Bash" in out
    # footer "trigrams:" is total occurrences (2 + 1), not distinct.
    assert lines[-1] == (
        "trigrams: 3  |  distinct: 3  |  sessions scanned: 3"
    )


def test_format_sequences_table_top_truncates():
    rows = [
        {"trigram": f"T{i}→x→y", "count": 10 - i, "sessions": 1}
        for i in range(5)
    ]
    result = {
        "name": "04_tool_sequences",
        "meta": {"sessions_scanned": 1, "sessions_with_3plus_calls": 1,
                 "distinct_trigrams": 5},
        "rows": rows,
    }
    out = format_sequences_table(result, top=2)
    assert "T0→x→y" in out and "T1→x→y" in out
    assert "T2→x→y" not in out  # truncated by top
    assert "trigrams: 40" in out  # footer counts ALL rows, not just top


def test_mine_cli_list_and_sequences(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    db_path = tmp_path / "sessions.db"
    database = Database(db_path)
    database.connect()
    _insert(database, "s1", ["Read", "Edit", "Bash", "Read", "Edit", "Bash"])
    database.close()

    runner = CliRunner()

    res = runner.invoke(main, ["mine", "list"])
    assert res.exit_code == 0, res.output
    assert res.output.split() == ["bash", "churn", "failures", "sequences"]

    json_out = tmp_path / "out" / "04_tool_sequences.json"
    res = runner.invoke(
        main,
        ["mine", "sequences", "--db", str(db_path), "--top", "20",
         "--write-json", str(json_out)],
    )
    assert res.exit_code == 0, res.output
    assert "Read→Edit→Bash" in res.output
    assert f"Wrote {json_out}" in res.output

    data = json.loads(json_out.read_text())
    assert data["name"] == "04_tool_sequences"
    assert data["rows"][0]["trigram"] == "Read→Edit→Bash"
    assert data["rows"][0]["count"] == 2  # two overlapping windows


def test_mine_sequences_missing_db(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    res = CliRunner().invoke(
        main, ["mine", "sequences", "--db", str(tmp_path / "nope.db")]
    )
    assert res.exit_code == 0
    assert "No archive database found" in res.output
