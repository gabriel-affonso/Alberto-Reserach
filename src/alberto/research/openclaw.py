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
    if envelope.get("ok") is False or envelope.get("status") in {"error", "timeout"}:
        error = envelope.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        raise OpenClawInvocationError(message or f"OpenClaw invocation failed: {envelope.get('status')}")
    final = envelope.get("final")
    if not isinstance(final, str) or not final.strip():
        raise OpenClawInvocationError("OpenClaw JSON envelope did not include a non-empty final field")
    try:
        payload = json.loads(final)
    except json.JSONDecodeError as exc:
        raise OpenClawInvocationError("OpenClaw final field was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpenClawInvocationError("OpenClaw final JSON must be an object")
    return payload


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
