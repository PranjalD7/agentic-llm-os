"""
LLMPlanner unit tests — all Ollama calls are mocked via unittest.mock.
No real Ollama instance required.
"""
import json
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from llmos.planner.heuristic import HeuristicPlanner
from llmos.planner.llm import LLMPlanner, STEP_LIST_SCHEMA


def _make_planner(max_retries: int = 3) -> LLMPlanner:
    return LLMPlanner(
        host="http://localhost:11434",
        model="llama3.2",
        max_retries=max_retries,
        fallback=HeuristicPlanner(),
    )


def _ollama_response(steps: list) -> MagicMock:
    """Build a mock httpx.Response that looks like a valid Ollama reply."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "message": {
            "role": "assistant",
            "content": json.dumps({"steps": steps}),
        }
    }
    return mock_resp


# ── Successful path ───────────────────────────────────────────────────────────

def test_successful_plan():
    steps_data = [
        {"order": 0, "description": "List files", "command": "ls -la"},
    ]
    with patch("httpx.post", return_value=_ollama_response(steps_data)):
        planner = _make_planner()
        steps = planner.plan("list files")

    assert len(steps) == 1
    assert steps[0].order == 0
    assert steps[0].command == "ls -la"
    assert steps[0].description == "List files"


def test_multi_step_plan():
    steps_data = [
        {"order": 0, "description": "Create venv",    "command": "python3 -m venv .venv"},
        {"order": 1, "description": "Install deps",   "command": "python3 -m pip install -r requirements.txt"},
        {"order": 2, "description": "Run tests",      "command": "python3 -m pytest"},
    ]
    with patch("httpx.post", return_value=_ollama_response(steps_data)):
        planner = _make_planner()
        steps = planner.plan("create venv and run tests")

    assert len(steps) == 3
    assert steps[2].command == "python3 -m pytest"


# ── Repair loop ───────────────────────────────────────────────────────────────

def test_repair_loop_success_on_second_attempt():
    """First response is invalid JSON; second is valid. Should succeed."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock()
    bad_resp.json.return_value = {"message": {"role": "assistant", "content": "not json at all"}}

    good_resp = _ollama_response([{"order": 0, "description": "Echo", "command": "echo hi"}])

    with patch("httpx.post", side_effect=[bad_resp, good_resp]):
        planner = _make_planner(max_retries=3)
        steps = planner.plan("say hello")

    assert len(steps) == 1
    assert steps[0].command == "echo hi"


def test_repair_loop_sends_error_context():
    """On a bad response, the correction message must be included in the retry."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock()
    bad_resp.json.return_value = {"message": {"role": "assistant", "content": "oops"}}

    good_resp = _ollama_response([{"order": 0, "description": "pwd", "command": "pwd"}])

    with patch("httpx.post", side_effect=[bad_resp, good_resp]) as mock_post:
        planner = _make_planner(max_retries=3)
        planner.plan("where am i")

    # Second call's messages should contain the bad output + error instruction
    second_call_body = mock_post.call_args_list[1].kwargs["json"]
    messages = second_call_body["messages"]
    roles = [m["role"] for m in messages]
    assert "assistant" in roles   # bad output appended
    assert roles.count("user") >= 2  # original + correction


# ── Fallback on connectivity errors ───────────────────────────────────────────

def test_fallback_on_connect_error():
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        planner = _make_planner()
        steps = planner.plan("list files")

    # Should return heuristic result — ls -la
    assert len(steps) >= 1
    assert "ls" in steps[0].command


def test_fallback_on_timeout():
    with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
        planner = _make_planner()
        steps = planner.plan("list files")

    assert len(steps) >= 1


def test_fallback_after_max_retries():
    """All attempts return bad JSON — should fall back after exhausting retries."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock()
    bad_resp.json.return_value = {"message": {"role": "assistant", "content": "!!invalid!!"}}

    with patch("httpx.post", return_value=bad_resp) as mock_post:
        planner = _make_planner(max_retries=3)
        steps = planner.plan("list files")

    assert mock_post.call_count == 3   # exhausted all retries
    assert len(steps) >= 1             # fell back to heuristic


# ── Request body correctness ──────────────────────────────────────────────────

def test_temperature_zero_in_request():
    with patch("httpx.post", return_value=_ollama_response(
        [{"order": 0, "description": "x", "command": "echo x"}]
    )) as mock_post:
        _make_planner().plan("echo x")

    body = mock_post.call_args.kwargs["json"]
    assert body["options"]["temperature"] == 0


def test_format_schema_in_request():
    with patch("httpx.post", return_value=_ollama_response(
        [{"order": 0, "description": "x", "command": "echo x"}]
    )) as mock_post:
        _make_planner().plan("echo x")

    body = mock_post.call_args.kwargs["json"]
    assert body["format"] == STEP_LIST_SCHEMA


def test_stream_false_in_request():
    with patch("httpx.post", return_value=_ollama_response(
        [{"order": 0, "description": "x", "command": "echo x"}]
    )) as mock_post:
        _make_planner().plan("echo x")

    body = mock_post.call_args.kwargs["json"]
    assert body["stream"] is False


def test_correct_model_sent():
    with patch("httpx.post", return_value=_ollama_response(
        [{"order": 0, "description": "x", "command": "echo x"}]
    )) as mock_post:
        planner = LLMPlanner(
            host="http://localhost:11434",
            model="mistral",
            max_retries=1,
            fallback=HeuristicPlanner(),
        )
        planner.plan("echo x")

    body = mock_post.call_args.kwargs["json"]
    assert body["model"] == "mistral"
