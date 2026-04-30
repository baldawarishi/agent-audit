"""Tests for Gemini CLI parser."""

import json
from pathlib import Path

from agent_audit.gemini_parser import (
    discover_gemini_sessions,
    parse_gemini_session,
)


def _make_project_dir(home: Path, slug: str, cwd: str) -> Path:
    """Create a fake ~/.gemini/tmp/<slug> directory with .project_root + chats/."""
    project_dir = home / "tmp" / slug
    (project_dir / "chats").mkdir(parents=True)
    (project_dir / ".project_root").write_text(cwd)
    return project_dir


def _write_session(
    path: Path,
    messages: list[dict],
    session_id: str = "ac1faa48",
    **extra,
) -> None:
    payload = {
        "sessionId": session_id,
        "projectHash": "deadbeef",
        "startTime": "2026-04-29T14:32:16.791Z",
        "lastUpdated": "2026-04-29T22:43:15.679Z",
        "messages": messages,
    }
    payload.update(extra)
    path.write_text(json.dumps(payload))


def test_discover_finds_top_level_sessions(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    _write_session(project_dir / "chats" / "session-2026-04-29T14-32-aaaa.json", [])
    _write_session(project_dir / "chats" / "session-2026-04-29T14-33-bbbb.json", [])

    found = list(discover_gemini_sessions(home=tmp_path))
    assert len(found) == 2
    # Project name is derived from cwd, matching Claude Code convention
    assert all(name == "workspaces-my-proj" for _, name in found)
    names = sorted(p.name for p, _ in found)
    assert names == [
        "session-2026-04-29T14-32-aaaa.json",
        "session-2026-04-29T14-33-bbbb.json",
    ]


def test_parse_basic_user_and_assistant(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {
                "id": "u1",
                "timestamp": "2026-04-29T14:33:14.899Z",
                "type": "user",
                "content": [{"text": "hello there"}],
            },
            {
                "id": "g1",
                "timestamp": "2026-04-29T14:33:24.296Z",
                "type": "gemini",
                "content": "hi back",
                "model": "gemini-3.1-pro-preview",
                "tokens": {"input": 100, "output": 25, "cached": 0, "total": 125},
            },
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")

    assert session.id == "ac1faa48"
    assert session.agent_type == "gemini-cli"
    assert session.claude_version == "gemini-cli"
    assert session.cwd == "/Users/dev/workspaces/my-proj"
    assert session.started_at == "2026-04-29T14:32:16.791Z"
    assert session.ended_at == "2026-04-29T22:43:15.679Z"

    assert len(session.messages) == 2
    user_msg, asst_msg = session.messages
    assert user_msg.type == "user"
    assert user_msg.content == "hello there"
    assert asst_msg.type == "assistant"
    assert asst_msg.content == "hi back"
    assert asst_msg.model == "gemini-3.1-pro-preview"
    assert asst_msg.input_tokens == 100
    assert asst_msg.output_tokens == 25

    assert session.model == "gemini-3.1-pro-preview"
    assert session.total_input_tokens == 100
    assert session.total_output_tokens == 25


def test_drops_noise_message_types(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "ok"}]},
            {"id": "i1", "timestamp": "t", "type": "info", "content": "update available"},
            {"id": "e1", "timestamp": "t", "type": "error", "content": "boom"},
            {"id": "w1", "timestamp": "t", "type": "warning", "content": "be careful"},
            {"id": "g1", "timestamp": "t", "type": "gemini", "content": "fine"},
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")

    types = [m.type for m in session.messages]
    assert types == ["user", "assistant"]


def test_tool_calls_and_results(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "search"}]},
            {
                "id": "g1",
                "timestamp": "t",
                "type": "gemini",
                "content": "ok",
                "toolCalls": [
                    {
                        "id": "tc_ok",
                        "name": "google_web_search",
                        "args": {"query": "x"},
                        "status": "success",
                        "result": [
                            {
                                "functionResponse": {
                                    "id": "tc_ok",
                                    "name": "google_web_search",
                                    "response": {"output": "result body"},
                                }
                            }
                        ],
                    },
                    {
                        "id": "tc_err",
                        "name": "run_shell_command",
                        "args": {"cmd": "false"},
                        "status": "error",
                        "result": [
                            {
                                "functionResponse": {
                                    "id": "tc_err",
                                    "name": "run_shell_command",
                                    "response": {"output": "boom"},
                                }
                            }
                        ],
                    },
                ],
            },
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")

    assert len(session.tool_calls) == 2
    tc_ok, tc_err = session.tool_calls
    assert tc_ok.tool_name == "google_web_search"
    assert json.loads(tc_ok.input_json) == {"query": "x"}
    assert tc_ok.message_id == "g1"
    assert tc_err.tool_name == "run_shell_command"

    # ToolCalls also attached to the assistant message
    asst = next(m for m in session.messages if m.type == "assistant")
    assert [tc.id for tc in asst.tool_calls] == ["tc_ok", "tc_err"]

    assert len(session.tool_results) == 2
    tr_ok, tr_err = session.tool_results
    assert tr_ok.tool_call_id == "tc_ok"
    assert tr_ok.content == "result body"
    assert tr_ok.is_error is False
    assert tr_err.tool_call_id == "tc_err"
    assert tr_err.content == "boom"
    assert tr_err.is_error is True


def test_thoughts_become_thinking(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "hi"}]},
            {
                "id": "g1",
                "timestamp": "t",
                "type": "gemini",
                "content": "answer",
                "thoughts": [
                    {"subject": "Plan", "description": "First, search.", "timestamp": "t"},
                    {"subject": "Execute", "description": "Then summarize.", "timestamp": "t"},
                ],
            },
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")
    asst = next(m for m in session.messages if m.type == "assistant")
    assert asst.thinking == "Plan: First, search.\nExecute: Then summarize."


def test_sidecar_rehydration(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    sidecar_dir = project_dir / "tool-outputs" / "session-ac1faa48"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "tc_big.txt").write_text("FULL OUTPUT CONTENTS")

    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "go"}]},
            {
                "id": "g1",
                "timestamp": "t",
                "type": "gemini",
                "content": "ok",
                "toolCalls": [
                    {
                        "id": "tc_big",
                        "name": "run_shell_command",
                        "args": {"cmd": "ls"},
                        "status": "success",
                        "result": [
                            {
                                "functionResponse": {
                                    "id": "tc_big",
                                    "name": "run_shell_command",
                                    "response": {
                                        "output": "Output too large. Showing first 8,000...\nOutput: trimmed"
                                    },
                                }
                            }
                        ],
                    },
                    {
                        "id": "tc_missing",
                        "name": "run_shell_command",
                        "args": {"cmd": "ls"},
                        "status": "success",
                        "result": [
                            {
                                "functionResponse": {
                                    "id": "tc_missing",
                                    "name": "run_shell_command",
                                    "response": {
                                        "output": "Output too large. no sidecar exists."
                                    },
                                }
                            }
                        ],
                    },
                ],
            },
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")
    by_id = {tr.tool_call_id: tr for tr in session.tool_results}
    assert by_id["tc_big"].content == "FULL OUTPUT CONTENTS"
    # Missing sidecar: keep original
    assert by_id["tc_missing"].content.startswith("Output too large.")


def test_discovery_recursive_subagent(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    parent = project_dir / "chats" / "session-2026-04-29T14-32-aaaa.json"
    _write_session(parent, [], session_id="aaaa")

    sub_dir = project_dir / "chats" / "session-2026-04-29T14-32-aaaa"
    sub_dir.mkdir()
    sub = sub_dir / "session-2026-04-29T14-33-bbbb.json"
    _write_session(sub, [], session_id="bbbb", kind="subagent")

    found = list(discover_gemini_sessions(home=tmp_path))
    paths = sorted(p.name for p, _ in found)
    assert paths == [
        "session-2026-04-29T14-32-aaaa.json",
        "session-2026-04-29T14-33-bbbb.json",
    ]


def test_subagent_session_marked(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    sub_dir = project_dir / "chats" / "session-2026-04-29T14-32-aaaa"
    sub_dir.mkdir()
    sub_file = sub_dir / "session-2026-04-29T14-33-bbbb.json"
    _write_session(sub_file, [], session_id="bbbb", kind="subagent")

    session = parse_gemini_session(sub_file, "workspaces-my-proj")
    assert session.is_sidechain is True
    assert session.parent_session_id == "2026-04-29T14-32-aaaa"


def test_user_multimodal_flag(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {
                "id": "u1",
                "timestamp": "t",
                "type": "user",
                "content": [
                    {"text": "see image"},
                    {"inlineData": {"mimeType": "image/png", "data": "..."}},
                ],
            },
            {
                "id": "u2",
                "timestamp": "t",
                "type": "user",
                "content": [{"text": "no media"}],
            },
            {
                "id": "u3",
                "timestamp": "t",
                "type": "user",
                "content": [
                    {"text": "see file"},
                    {"fileData": {"fileUri": "gs://x"}},
                ],
            },
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")
    flags = {m.id: m.has_images for m in session.messages}
    assert flags == {"u1": True, "u2": False, "u3": True}


def test_rewind_and_set_replay(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "first"}]},
            {"id": "g1", "timestamp": "t", "type": "gemini", "content": "first reply"},
            {"id": "u2", "timestamp": "t", "type": "user", "content": [{"text": "second"}]},
            {"id": "g2", "timestamp": "t", "type": "gemini", "content": "second reply"},
            {"type": "$rewindTo", "id": "g1"},
            {"type": "$set", "id": "g1", "patch": {"content": "patched reply"}},
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")
    ids = [m.id for m in session.messages]
    assert ids == ["u1", "g1"]
    g1 = next(m for m in session.messages if m.id == "g1")
    assert g1.content == "patched reply"


def test_warmup_detection(tmp_path):
    project_dir = _make_project_dir(tmp_path, "my-proj", "/Users/dev/workspaces/my-proj")
    session_file = project_dir / "chats" / "session-x.json"
    _write_session(
        session_file,
        [
            {"id": "u1", "timestamp": "t", "type": "user", "content": [{"text": "Warmup"}]},
            {"id": "g1", "timestamp": "t", "type": "gemini", "content": "ok"},
        ],
    )

    session = parse_gemini_session(session_file, "workspaces-my-proj")
    assert session.is_warmup is True
