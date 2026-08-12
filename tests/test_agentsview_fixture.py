"""The committed AgentsView fixture is the offline stand-in for the mirror.

Every later step tests against ``tests/fixtures/agentsview/mirror.json`` — no
daemon, no network, no live archive. These assertions pin the mirror facts
Step 1 measured, so a re-dump that loses one fails here instead of in Step 4.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agent_audit.mining.bash import _command_text, first_token

FIXTURE = Path(__file__).parent / "fixtures" / "agentsview" / "mirror.json"
DUMPER = Path(__file__).parents[1] / "scripts" / "dump_agentsview_fixtures.py"


@pytest.fixture(scope="module")
def mirror() -> dict:
    return json.loads(FIXTURE.read_text())


def _calls(mirror: dict, tool: str) -> list[dict]:
    return [c for c in mirror["rows"]["tool_calls"] if c["tool_name"] == tool]


def test_fixture_covers_three_agent_shapes(mirror):
    assert {s["agent"] for s in mirror["rows"]["sessions"]} == {
        "claude", "codex", "antigravity-cli",
    }


def test_tool_calls_carry_no_id_so_the_key_is_tool_use_id(mirror):
    """The mirror leaves ``tool_calls.id`` NULL; Step 2 must key on something else."""
    calls = mirror["rows"]["tool_calls"]
    assert calls and not any(c["id"] for c in calls)
    assert all(c["tool_use_id"] for c in calls)
    keys = {(c["session_id"], c["message_id"], c["call_index"]) for c in calls}
    assert len(keys) == len(calls)


def test_every_call_resolves_to_a_message_timestamp(mirror):
    stamps = {m["id"]: m["timestamp"] for m in mirror["rows"]["messages"]}
    assert all(stamps.get(c["message_id"]) for c in mirror["rows"]["tool_calls"])


def test_bash_family_commands_survive_first_token(mirror):
    shells = _calls(mirror, "Bash") + _calls(mirror, "exec_command")
    assert len(shells) >= 15
    assert all(first_token(_command_text(c["input_json"])) for c in shells)


def test_codex_exec_is_not_a_shell_tool(mirror):
    """``exec`` runs JavaScript, so it must stay out of ``_BASH_TOOL_NAMES``."""
    js = _calls(mirror, "exec")
    assert js and not any(_command_text(c["input_json"]) for c in js)


def test_antigravity_calls_carry_no_result_content(mirror):
    calls = [c for c in mirror["rows"]["tool_calls"]
             if c["session_id"].startswith("antigravity-cli:")]
    assert calls and not any(c["result_content"] for c in calls)


def test_failures_are_visible_only_as_result_text(mirror):
    """No is_error column exists, so a failure is text or nothing (Q2)."""
    assert "is_error" not in dict(mirror["schema"]["tool_calls"])
    failed = [c for c in mirror["rows"]["tool_calls"]
              if (c["result_content"] or "").startswith("Exit code 1")]
    assert failed


def test_fixture_is_scrubbed_of_the_dumping_user(mirror):
    blob = FIXTURE.read_text()
    assert str(Path.home()) not in blob
    assert Path.home().name not in blob


def test_duckdb_build_round_trips_the_json(tmp_path, mirror):
    duckdb = pytest.importorskip("duckdb")
    spec = importlib.util.spec_from_file_location("dumper", DUMPER)
    dumper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dumper)
    built = tmp_path / "mirror.duckdb"
    dumper.build_duckdb(mirror, built)
    conn = duckdb.connect(str(built), read_only=True)
    counts = {
        table: conn.execute(f"select count(*) from {table}").fetchone()[0]
        for table in mirror["rows"]
    }
    assert counts == {t: len(rows) for t, rows in mirror["rows"].items()}
