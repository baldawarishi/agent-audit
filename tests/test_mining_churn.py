"""Tests for the mining churn query (agent_audit.mining.churn)."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.mining import churn, format_churn_table, get_query, list_queries
from agent_audit.mining.churn import churn_query
from agent_audit.models import Message, Session, ToolCall, ToolResult


def _call(idx: int, ts: str | None) -> dict:
    return {"id": f"c{idx}", "timestamp": ts}


def test_count_sequences_splits_on_gap():
    calls = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:01:00Z"),  # +60s  -> same run
        _call(3, "2026-01-01T10:05:00Z"),  # +240s -> new run
        _call(4, "2026-01-01T10:05:30Z"),  # +30s  -> same run
    ]
    assert churn.count_sequences(calls, 120.0) == 2


def test_count_sequences_gap_boundary_is_inclusive():
    # Exactly 120s apart must NOT split (split is strictly > gap).
    at_boundary = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:02:00Z"),  # +120s
    ]
    assert churn.count_sequences(at_boundary, 120.0) == 1

    just_over = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:02:01Z"),  # +121s
    ]
    assert churn.count_sequences(just_over, 120.0) == 2


def test_count_sequences_single_and_empty():
    assert churn.count_sequences([], 120.0) == 0
    assert churn.count_sequences([_call(1, "2026-01-01T10:00:00Z")], 120.0) == 1


def test_count_sequences_bad_timestamp_is_gap_break():
    calls = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, None),
        _call(3, "2026-01-01T10:00:10Z"),
    ]
    # c1->c2 breaks (c2 None), c2->c3 breaks (prev None): 3 sequences.
    assert churn.count_sequences(calls, 120.0) == 3


def test_fail_count_ignores_calls_without_results():
    calls = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    results = [
        {"tool_call_id": "c1", "is_error": True},
        {"tool_call_id": "c2", "is_error": False},
        {"tool_call_id": "c3", "is_error": None},
        {"tool_call_id": "unknown", "is_error": True},  # not a call here
    ]
    assert churn.fail_count(calls, results) == 1


def test_fail_count_zero_when_no_results():
    assert churn.fail_count([{"id": "c1"}, {"id": "c2"}], []) == 0


def test_median():
    assert churn.median([]) == 0.0
    assert churn.median([5]) == 5
    assert churn.median([3, 1, 2]) == 2
    assert churn.median([4, 1, 3, 2]) == 2.5


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    database = Database(db_path)
    database.connect()
    yield database
    database.close()
    db_path.unlink()


def test_score_session_hand_computed(db):
    """4 calls -> 2 sequences, 1 failure -> churn = 2 * (1 + 1/4) = 2.5."""
    sid = "sess-1"
    ts = [
        "2026-01-01T10:00:00Z",
        "2026-01-01T10:01:00Z",  # +60s  same run
        "2026-01-01T10:05:00Z",  # +240s new run
        "2026-01-01T10:05:30Z",  # +30s  same run
    ]
    calls = [
        ToolCall(id=f"c{i}", message_id="m1", session_id=sid,
                 tool_name="Bash", input_json="{}", timestamp=t)
        for i, t in enumerate(ts, 1)
    ]
    results = [
        ToolResult(id="r2", tool_call_id="c2", session_id=sid,
                   content="boom", is_error=True, timestamp=ts[1]),
        ToolResult(id="r3", tool_call_id="c3", session_id=sid,
                   content="ok", is_error=False, timestamp=ts[2]),
        # c1 and c4 have no result -> not failures.
    ]
    session = Session(
        id=sid,
        project="demo-project",
        started_at=ts[0],
        messages=[Message(id="m1", session_id=sid, type="assistant",
                          timestamp=ts[0], content="")],
        tool_calls=calls,
        tool_results=results,
    )
    db.insert_session(session)

    row = churn.score_session({"id": sid, "project": "demo-project"}, db, 120.0)
    assert row is not None
    assert row["total"] == 4
    assert row["sequences"] == 2
    assert row["fail_count"] == 1
    assert row["fail_ratio"] == 0.25
    assert row["churn"] == pytest.approx(2.5)


def test_score_session_none_when_no_tool_calls(db):
    sid = "empty-sess"
    db.insert_session(Session(id=sid, project="p", started_at="2026-01-01T10:00:00Z"))
    assert churn.score_session({"id": sid, "project": "p"}, db, 120.0) is None


def _insert_session(db, sid, project, ts_list, fail_ids=()):
    db.insert_session(Session(
        id=sid,
        project=project,
        started_at=ts_list[0],
        messages=[Message(id=f"m-{sid}", session_id=sid, type="assistant",
                          timestamp=ts_list[0], content="")],
        tool_calls=[ToolCall(id=f"{sid}-c{i}", message_id=f"m-{sid}",
                             session_id=sid, tool_name="Bash",
                             input_json="{}", timestamp=t)
                    for i, t in enumerate(ts_list, 1)],
        tool_results=[ToolResult(id=f"{sid}-r{i}", tool_call_id=f"{sid}-c{i}",
                                 session_id=sid, content="boom",
                                 is_error=True, timestamp=ts_list[i - 1])
                      for i in fail_ids],
    ))


def test_churn_query_envelope_and_ordering(db):
    """churn_query returns {name, meta, rows}; rows churn-desc, all sessions."""
    # high churn: 4 calls, 2 sequences, 1 failure -> 2 * (1 + 1/4) = 2.5
    _insert_session(db, "hi", "p-hi", [
        "2026-01-01T10:00:00Z",
        "2026-01-01T10:01:00Z",  # +60s  same run
        "2026-01-01T10:05:00Z",  # +240s new run
        "2026-01-01T10:05:30Z",  # +30s  same run
    ], fail_ids=(2,))
    # low churn: 1 call, 1 sequence, 0 failures -> 1.0
    _insert_session(db, "lo", "p-lo", ["2026-01-01T10:00:00Z"])

    result = churn_query(db, gap=120.0)

    assert result["name"] == "01_churn"
    meta = result["meta"]
    assert set(meta) == {
        "gap", "sessions_scanned", "sessions_with_calls", "median_churn",
    }
    assert meta["gap"] == 120.0
    assert meta["sessions_scanned"] == 2
    assert meta["sessions_with_calls"] == 2

    rows = result["rows"]
    churns = [r["churn"] for r in rows]
    assert churns == sorted(churns, reverse=True)
    assert rows[0]["session_id"] == "hi"
    assert rows[0]["churn"] == pytest.approx(2.5)
    assert rows[-1]["churn"] == pytest.approx(1.0)
    assert meta["median_churn"] == pytest.approx(churn.median(churns))


def test_registry():
    assert "churn" in list_queries()
    assert get_query("churn") is churn_query
    with pytest.raises(KeyError):
        get_query("nope")


def test_format_churn_table_known_envelope():
    """Pinned regression contract for the Step-1 table (shim is gone)."""
    result = {
        "name": "01_churn",
        "meta": {
            "gap": 120.0,
            "sessions_scanned": 3,
            "sessions_with_calls": 1,
            "median_churn": 2.5,
        },
        "rows": [
            {
                "session_id": "abcd1234ef",
                "project": "demo-project",
                "total": 4,
                "sequences": 2,
                "fail_count": 1,
                "fail_ratio": 0.25,
                "churn": 2.5,
            }
        ],
    }
    out = format_churn_table(result, top=20)
    lines = out.splitlines()
    assert lines[0].startswith("session")
    assert "churn" in lines[0]
    # session id truncated to 8 chars; churn right-aligned to 2dp.
    assert "abcd1234" in out
    assert " 25.0%" in out
    assert "    2.50" in out
    assert (
        lines[-1]
        == "sessions scanned: 3  |  with tool calls: 1  |  median churn: 2.50"
    )


def test_format_churn_table_empty_rows():
    result = {
        "name": "01_churn",
        "meta": {
            "gap": 120.0,
            "sessions_scanned": 5,
            "sessions_with_calls": 0,
            "median_churn": 0.0,
        },
        "rows": [],
    }
    assert (
        format_churn_table(result, 20)
        == "Scanned 5 sessions; none had tool calls."
    )


def test_mine_cli_list_and_churn(tmp_path):
    """`mine list` + `mine churn --db <tmp> --json <tmp>` end to end."""
    from click.testing import CliRunner

    from agent_audit.cli import main

    db_path = tmp_path / "sessions.db"
    database = Database(db_path)
    database.connect()
    # high churn: 4 calls, 2 sequences, 1 failure -> 2 * (1 + 1/4) = 2.5
    _insert_session(database, "hi", "p-hi", [
        "2026-01-01T10:00:00Z",
        "2026-01-01T10:01:00Z",
        "2026-01-01T10:05:00Z",
        "2026-01-01T10:05:30Z",
    ], fail_ids=(2,))
    # low churn: 1 call, 1 sequence, 0 failures -> 1.0
    _insert_session(database, "lo", "p-lo", ["2026-01-01T10:00:00Z"])
    database.close()

    runner = CliRunner()

    res = runner.invoke(main, ["mine", "list"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "churn"

    json_out = tmp_path / "out" / "01_churn.json"
    res = runner.invoke(
        main,
        ["mine", "churn", "--db", str(db_path), "--top", "20",
         "--write-json", str(json_out)],
    )
    assert res.exit_code == 0, res.output
    assert "median churn:" in res.output
    assert "hi" in res.output
    assert f"Wrote {json_out}" in res.output

    data = json.loads(json_out.read_text())
    assert data["name"] == "01_churn"
    churns = [r["churn"] for r in data["rows"]]
    assert churns == sorted(churns, reverse=True)
    assert data["rows"][0]["session_id"] == "hi"
    assert data["rows"][0]["churn"] == pytest.approx(2.5)


def test_mine_churn_missing_db(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    res = CliRunner().invoke(
        main, ["mine", "churn", "--db", str(tmp_path / "nope.db")]
    )
    assert res.exit_code == 0
    assert "No archive database found" in res.output
