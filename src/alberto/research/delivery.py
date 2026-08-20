from __future__ import annotations

import os
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from html import escape
from pathlib import Path


class Delivery(ABC):
    @abstractmethod
    def deliver(self, *, subject: str, body: str, local_path: Path) -> str:
        raise NotImplementedError


class LocalDelivery(Delivery):
    def deliver(self, *, subject: str, body: str, local_path: Path) -> str:
        return f"saved:{local_path}"


class SmtpDelivery(Delivery):
    def deliver(self, *, subject: str, body: str, local_path: Path) -> str:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ["SMTP_FROM"]
        msg["To"] = os.environ["SMTP_TO"]
        msg.set_content(f"{plain_text_digest(body)}\n\nLocal copy: {local_path}")
        msg.add_alternative(html_digest(body, local_path=local_path), subtype="html")
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if os.environ.get("SMTP_USERNAME"):
                smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
        return f"email:{msg['To']}"


def configured_delivery() -> Delivery:
    if os.environ.get("ALBERTO_EMAIL_PROVIDER") == "smtp":
        return SmtpDelivery()
    return LocalDelivery()


def plain_text_digest(markdown: str) -> str:
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("# "):
            lines.append(line[2:].strip())
        elif line.startswith("## "):
            lines.extend(["", line[3:].strip().upper()])
        elif line.startswith("### "):
            lines.extend(["", line[4:].strip()])
        elif line.startswith("- "):
            lines.append(f"* {line[2:].strip()}")
        elif line.startswith("  - "):
            lines.append(f"  - {line[4:].strip()}")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def html_digest(markdown: str, *, local_path: Path) -> str:
    body_parts: list[str] = []
    in_list = False
    in_nested_list = False
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            in_list, in_nested_list = close_lists(body_parts, in_list, in_nested_list)
            continue
        if line.startswith("# "):
            in_list, in_nested_list = close_lists(body_parts, in_list, in_nested_list)
            body_parts.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            in_list, in_nested_list = close_lists(body_parts, in_list, in_nested_list)
            body_parts.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            in_list, in_nested_list = close_lists(body_parts, in_list, in_nested_list)
            body_parts.append(f"<h3>{escape(line[4:].strip())}</h3>")
        elif line.startswith("  - "):
            if not in_list:
                body_parts.append("<ul>")
                in_list = True
            if not in_nested_list:
                body_parts.append("<ul>")
                in_nested_list = True
            body_parts.append(f"<li>{inline_markup(line[4:].strip())}</li>")
        elif line.startswith("- "):
            if in_nested_list:
                body_parts.append("</ul>")
                in_nested_list = False
            if not in_list:
                body_parts.append("<ul>")
                in_list = True
            body_parts.append(f"<li>{inline_markup(line[2:].strip())}</li>")
        else:
            in_list, in_nested_list = close_lists(body_parts, in_list, in_nested_list)
            body_parts.append(f"<p>{inline_markup(line)}</p>")
    close_lists(body_parts, in_list, in_nested_list)
    body_parts.append(f'<p class="local-copy">Local copy: {escape(str(local_path))}</p>')
    return "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<style>",
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.45;color:#1f2933;max-width:760px;margin:0 auto;padding:24px;background:#ffffff}",
            "h1{font-size:24px;line-height:1.2;margin:0 0 18px;color:#111827}",
            "h2{font-size:18px;margin:28px 0 10px;border-bottom:1px solid #e5e7eb;padding-bottom:6px;color:#111827}",
            "h3{font-size:16px;margin:18px 0 6px;color:#172554}",
            "ul{margin:6px 0 12px 22px;padding:0}",
            "li{margin:4px 0}",
            "code{background:#f3f4f6;border:1px solid #e5e7eb;border-radius:4px;padding:1px 4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:90%}",
            ".local-copy{margin-top:28px;color:#6b7280;font-size:13px}",
            "</style>",
            "</head>",
            "<body>",
            *body_parts,
            "</body>",
            "</html>",
        ]
    )


def close_lists(parts: list[str], in_list: bool, in_nested_list: bool) -> tuple[bool, bool]:
    if in_nested_list:
        parts.append("</ul>")
        in_nested_list = False
    if in_list:
        parts.append("</ul>")
        in_list = False
    return in_list, in_nested_list


def inline_markup(value: str) -> str:
    escaped = escape(value)
    parts = escaped.split("`")
    for index in range(1, len(parts), 2):
        parts[index] = f"<code>{parts[index]}</code>"
    return "".join(parts)
