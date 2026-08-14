from __future__ import annotations

import json
import subprocess

import pytest

from alberto.research.openclaw import (
    OpenClawInvocationError,
    extract_assistant_text,
    invoke_openclaw_json,
    parse_openclaw_final_json,
)


def production_envelope(text: str, *, status: str = "ok") -> dict:
    return {
        "runId": "run_test",
        "status": status,
        "summary": "completed",
        "result": {
            "payloads": [{"text": text}],
            "meta": {
                "finalAssistantVisibleText": text,
                "finalAssistantRawText": text,
            },
        },
    }


def test_result_payload_text_and_inner_json_parse() -> None:
    payload = parse_openclaw_final_json(
        json.dumps(production_envelope(json.dumps({"score": 0.75, "decision": "QUEUE", "rationale": "Relevant."})))
    )
    assert payload == {"score": 0.75, "decision": "QUEUE", "rationale": "Relevant."}


def test_fallback_visible_text_parse() -> None:
    text = json.dumps({"score": 0.8, "decision": "DEEP_READ", "rationale": "Visible fallback."})
    envelope = production_envelope("")
    envelope["result"]["payloads"] = []
    envelope["result"]["meta"]["finalAssistantVisibleText"] = text
    assert parse_openclaw_final_json(json.dumps(envelope))["rationale"] == "Visible fallback."


def test_fallback_raw_text_parse() -> None:
    text = json.dumps({"score": 0.6, "decision": "QUEUE", "rationale": "Raw fallback."})
    envelope = production_envelope("")
    envelope["result"]["payloads"] = []
    envelope["result"]["meta"]["finalAssistantVisibleText"] = ""
    envelope["result"]["meta"]["finalAssistantRawText"] = text
    assert parse_openclaw_final_json(json.dumps(envelope))["rationale"] == "Raw fallback."


def test_invalid_inner_final_json_fails() -> None:
    with pytest.raises(OpenClawInvocationError):
        parse_openclaw_final_json(json.dumps(production_envelope("not json")))


def test_non_ok_status_fails() -> None:
    with pytest.raises(OpenClawInvocationError):
        parse_openclaw_final_json(json.dumps(production_envelope("{}", status="error")))


def test_missing_assistant_text_fails() -> None:
    with pytest.raises(OpenClawInvocationError):
        extract_assistant_text({"status": "ok", "result": {"payloads": [], "meta": {}}})


def test_invoke_openclaw_json_uses_message_file_and_json(monkeypatch) -> None:
    calls = []

    def fake_run(command, *, text, capture_output, timeout, check):
        calls.append((command, text, capture_output, timeout, check))
        message_path = command[command.index("--message-file") + 1]
        with open(message_path, encoding="utf-8") as handle:
            assert handle.read() == "prompt com acento"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(production_envelope(json.dumps({"ok": True}))),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert invoke_openclaw_json(["openclaw", "agent", "exec"], "prompt com acento", timeout_seconds=7) == {"ok": True}
    command, text, capture_output, timeout, check = calls[0]
    assert command[:3] == ["openclaw", "agent", "exec"]
    assert command[-1] == "--json"
    assert "--message-file" in command
    assert text is True
    assert capture_output is True
    assert timeout == 7
    assert check is False
