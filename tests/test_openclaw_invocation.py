from __future__ import annotations

import json
import subprocess

import pytest

from alberto.research.openclaw import (
    OpenClawInvocationError,
    invoke_openclaw_json,
    parse_openclaw_final_json,
)


def test_outer_envelope_and_inner_final_json_parse() -> None:
    payload = parse_openclaw_final_json(
        json.dumps(
            {
                "ok": True,
                "status": "ok",
                "final": json.dumps({"score": 0.75, "decision": "QUEUE", "rationale": "Relevant."}),
            }
        )
    )
    assert payload == {"score": 0.75, "decision": "QUEUE", "rationale": "Relevant."}


def test_invalid_inner_final_json_fails() -> None:
    with pytest.raises(OpenClawInvocationError):
        parse_openclaw_final_json(json.dumps({"ok": True, "status": "ok", "final": "not json"}))


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
            stdout=json.dumps({"ok": True, "status": "ok", "final": json.dumps({"ok": True})}),
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
