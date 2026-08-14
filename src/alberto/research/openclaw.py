from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class OpenClawInvocationError(RuntimeError):
    pass


def parse_openclaw_final_json(stdout: str) -> dict[str, Any]:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OpenClawInvocationError("OpenClaw did not return a valid JSON envelope") from exc
    if not isinstance(envelope, dict):
        raise OpenClawInvocationError("OpenClaw JSON envelope must be an object")
    if envelope.get("status") != "ok":
        error = envelope.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        raise OpenClawInvocationError(message or f"OpenClaw invocation failed: {envelope.get('status')}")
    final = extract_assistant_text(envelope)
    try:
        payload = json.loads(final)
    except json.JSONDecodeError as exc:
        raise OpenClawInvocationError("OpenClaw assistant text was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpenClawInvocationError("OpenClaw assistant JSON must be an object")
    return payload


def extract_assistant_text(envelope: dict[str, Any]) -> str:
    result = envelope.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list) and payloads:
            first = payloads[0]
            if isinstance(first, dict):
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        meta = result.get("meta")
        if isinstance(meta, dict):
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                text = meta.get(key)
                if isinstance(text, str) and text.strip():
                    return text
    raise OpenClawInvocationError("OpenClaw JSON envelope did not include assistant text")


def invoke_openclaw_json(command: list[str], prompt: str, *, timeout_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(prompt)
        message_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [*command, "--message-file", str(message_path), "--json"],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenClawInvocationError(f"OpenClaw invocation timed out after {timeout_seconds}s") from exc
    finally:
        message_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise OpenClawInvocationError(stderr or f"OpenClaw exited with status {completed.returncode}")
    return parse_openclaw_final_json(completed.stdout)
