"""``AgentsViewSource`` over the committed mirror fixture (no daemon, no live archive).

The ``.duckdb`` is git-ignored, so every test rebuilds it from
``mirror.json`` with the Step-1 dumper — the JSON stays the reviewable
source of truth.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agent_audit.database import Database
from agent_audit.mining.sequences import tool_sequences_query
from agent_audit.mining.source import (
    DEFAULT_MIRROR_PATH,
    AgentsViewSource,
    SessionSource,
)

FIXTURE = Path(__file__).parent / "fixtures" / "agentsview" / "mirror.json"
DUMPER = Path(__file__).parents[1] / "scripts" / "dump_agentsview_fixtures.py"
CLAUDE = "6a5843f9-4c08-40b9-9810-37ab161c0556"
ANTIGRAVITY = "antigravity-cli:83ff1828-0266-4df9-b3ce-2c99e6438619"
CODEX = "codex:019f920d-851a-7fa0-857f-a89931b98a2f"


@pytest.fixture(scope="module")
def mirror_path(tmp_path_factory) -> Path:
    spec = importlib.util.spec_from_file_location("dumper", DUMPER)
    dumper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dumper)
    built = tmp_path_factory.mktemp("mirror") / "mirror.duckdb"
    dumper.build_duckdb(json.loads(FIXTURE.read_text()), built)
    return built


@pytest.fixture(scope="module")
def source(mirror_path) -> AgentsViewSource:
    return AgentsViewSource(mirror_path)


def test_both_stores_satisfy_the_seam(source, tmp_path):
    """The adapter and ``Database`` are interchangeable to a mining query."""
    assert isinstance(source, SessionSource)
    assert isinstance(Database(tmp_path / "sessions.db"), SessionSource)


def test_sessions_carry_the_join_fields(source):
    sessions = source.get_all_sessions()
    assert [s["id"] for s in sessions] == sorted([CLAUDE, ANTIGRAVITY, CODEX])
    assert {s["agent"] for s in sessions} == {"claude", "codex", "antigravity-cli"}
    # antigravity ships an empty project; the id is the only reliable key.
    assert {s["id"]: s["project"] for s in sessions} == {
        CLAUDE: "quamina_rs", CODEX: "petri", ANTIGRAVITY: "",
    }


def test_calls_are_ordered_by_the_message_clock(source):
    calls = source.get_tool_calls_for_session(CLAUDE)
    assert [c["tool_name"] for c in calls] == [
        "Bash", "Bash", "Bash", "Bash", "Bash", "Bash", "Bash", "Bash", "Bash",
        "Bash", "Bash", "Edit", "Bash", "Bash", "Read", "Edit", "Edit", "Agent",
    ]
    stamps = [c["timestamp"] for c in calls]
    assert stamps == sorted(stamps) and all(stamps)
    shared = [c["call_index"] for c in calls if c["timestamp"] == stamps[0]]
    assert shared == [0, 1]  # two calls on one message keep call_index order


def test_call_ids_are_synthesized_because_the_mirror_leaves_them_null(source):
    calls = [c for sid in (CLAUDE, CODEX, ANTIGRAVITY)
             for c in source.get_tool_calls_for_session(sid)]
    assert len({c["id"] for c in calls}) == len(calls)
    first = source.get_tool_calls_for_session(CLAUDE)[0]
    assert first["id"] == f"{CLAUDE}:{first['message_id']}:0"
    assert all(c["tool_use_id"] for c in calls)  # carried for Step 4/5


def test_results_leave_is_error_unknown(source):
    results = source.get_tool_results_for_session(CLAUDE)
    calls = source.get_tool_calls_for_session(CLAUDE)
    assert [r["tool_call_id"] for r in results] == [c["id"] for c in calls]
    assert all(r["is_error"] is None for r in results)
    assert any((r["content"] or "").startswith("Exit code 1") for r in results)
    assert not any(
        r["content"] for r in source.get_tool_results_for_session(ANTIGRAVITY)
    )


def test_tool_sequences_over_the_mirror(source):
    result = tool_sequences_query(source)

    assert result["name"] == "04_tool_sequences"
    assert result["meta"] == {
        "sessions_scanned": 3,
        "sessions_with_3plus_calls": 3,
        "distinct_trigrams": 31,
    }
    assert result["rows"][:4] == [
        {"trigram": "Bash→Bash→Bash", "count": 9, "sessions": 1},
        {"trigram": "view_file→view_file→view_file", "count": 8, "sessions": 1},
        {"trigram": "run→run→run", "count": 6, "sessions": 1},
        {"trigram": "send_message→send_message→send_message",
         "count": 4, "sessions": 1},
    ]
    trigrams = {r["trigram"] for r in result["rows"]}
    # Names stay verbatim: exec (JavaScript) never merges into exec_command,
    # and antigravity still yields trigrams with no result text at all.
    assert "exec→exec→exec" in trigrams and "exec_command→exec→exec" in trigrams
    assert "view_file→view_file→view_file" in trigrams


def test_mine_sequences_cli_reads_the_mirror(mirror_path, tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    json_out = tmp_path / "out" / "04_tool_sequences.json"
    res = CliRunner().invoke(
        main,
        ["mine", "sequences", "--source", "agentsview", "--db", str(mirror_path),
         "--top", "2", "--write-json", str(json_out)],
    )
    assert res.exit_code == 0, res.output
    assert "Bash→Bash→Bash" in res.output
    assert "run→run→run" not in res.output  # --top 2 truncates the print

    data = json.loads(json_out.read_text())
    assert data["meta"]["distinct_trigrams"] == 31
    assert data["rows"][0] == {
        "trigram": "Bash→Bash→Bash", "count": 9, "sessions": 1
    }


def test_mine_sequences_missing_mirror(tmp_path):
    from click.testing import CliRunner

    from agent_audit.cli import main

    res = CliRunner().invoke(
        main,
        ["mine", "sequences", "--source", "agentsview",
         "--db", str(tmp_path / "nope.duckdb")],
    )
    assert res.exit_code == 0
    assert "No AgentsView mirror found" in res.output


def test_source_resolves_its_own_default_path():
    from agent_audit.cli import resolve_source_path
    from agent_audit.config import Config

    cfg = Config()
    assert resolve_source_path("agentsview", None, cfg) == DEFAULT_MIRROR_PATH
    assert resolve_source_path("archive", None, cfg) == cfg.db_path
    explicit = Path("/tmp/other.duckdb")
    assert resolve_source_path("agentsview", explicit, cfg) == explicit
