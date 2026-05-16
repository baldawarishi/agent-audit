"""Tests for the Step 1 churn-score spike (scripts/01_churn_spike.py)."""

import importlib.util
import tempfile
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.models import Message, Session, ToolCall, ToolResult

SPIKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "01_churn_spike.py"
_spec = importlib.util.spec_from_file_location("churn_spike", SPIKE_PATH)
churn_spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(churn_spike)


def _call(idx: int, ts: str | None) -> dict:
    return {"id": f"c{idx}", "timestamp": ts}


def test_count_sequences_splits_on_gap():
    calls = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:01:00Z"),  # +60s  -> same run
        _call(3, "2026-01-01T10:05:00Z"),  # +240s -> new run
        _call(4, "2026-01-01T10:05:30Z"),  # +30s  -> same run
    ]
    assert churn_spike.count_sequences(calls, 120.0) == 2


def test_count_sequences_gap_boundary_is_inclusive():
    # Exactly 120s apart must NOT split (split is strictly > gap).
    at_boundary = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:02:00Z"),  # +120s
    ]
    assert churn_spike.count_sequences(at_boundary, 120.0) == 1

    just_over = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, "2026-01-01T10:02:01Z"),  # +121s
    ]
    assert churn_spike.count_sequences(just_over, 120.0) == 2


def test_count_sequences_single_and_empty():
    assert churn_spike.count_sequences([], 120.0) == 0
    assert churn_spike.count_sequences([_call(1, "2026-01-01T10:00:00Z")], 120.0) == 1


def test_count_sequences_bad_timestamp_is_gap_break():
    calls = [
        _call(1, "2026-01-01T10:00:00Z"),
        _call(2, None),
        _call(3, "2026-01-01T10:00:10Z"),
    ]
    # c1->c2 breaks (c2 None), c2->c3 breaks (prev None): 3 sequences.
    assert churn_spike.count_sequences(calls, 120.0) == 3


def test_fail_count_ignores_calls_without_results():
    calls = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    results = [
        {"tool_call_id": "c1", "is_error": True},
        {"tool_call_id": "c2", "is_error": False},
        {"tool_call_id": "c3", "is_error": None},
        {"tool_call_id": "unknown", "is_error": True},  # not a call here
    ]
    assert churn_spike.fail_count(calls, results) == 1


def test_fail_count_zero_when_no_results():
    assert churn_spike.fail_count([{"id": "c1"}, {"id": "c2"}], []) == 0


def test_median():
    assert churn_spike.median([]) == 0.0
    assert churn_spike.median([5]) == 5
    assert churn_spike.median([3, 1, 2]) == 2
    assert churn_spike.median([4, 1, 3, 2]) == 2.5


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

    row = churn_spike.score_session({"id": sid, "project": "demo-project"}, db, 120.0)
    assert row is not None
    assert row["total"] == 4
    assert row["sequences"] == 2
    assert row["fail_count"] == 1
    assert row["fail_ratio"] == 0.25
    assert row["churn"] == pytest.approx(2.5)


def test_score_session_none_when_no_tool_calls(db):
    sid = "empty-sess"
    db.insert_session(Session(id=sid, project="p", started_at="2026-01-01T10:00:00Z"))
    assert churn_spike.score_session({"id": sid, "project": "p"}, db, 120.0) is None
