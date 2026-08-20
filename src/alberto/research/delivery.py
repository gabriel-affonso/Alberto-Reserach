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
            "body{margin:0;padding:0;background:#d8c49a;color:#2f2417;font-family:Georgia,'Times New Roman',serif;line-height:1.55}",
            ".page{max-width:780px;margin:0 auto;padding:28px 18px}",
            ".newsletter{background:#f6edd5;border:1px solid #9d7a45;border-radius:8px;box-shadow:0 8px 26px rgba(61,42,20,.18);overflow:hidden}",
            ".masthead{background:#5c2f1b;color:#f7ead0;padding:18px 24px;border-bottom:4px solid #b98d45;font-family:Georgia,'Times New Roman',serif;font-size:13px;letter-spacing:.08em;text-transform:uppercase}",
            ".content{padding:24px 28px 30px;background:linear-gradient(90deg,rgba(255,255,255,.18),rgba(255,255,255,0) 18%,rgba(126,82,35,.08) 100%)}",
            "h1{font-size:28px;line-height:1.18;margin:0 0 20px;color:#3b2114;font-weight:700}",
            "h2{font-size:18px;margin:30px 0 12px;color:#5c2f1b;border-top:1px solid #c6a66c;border-bottom:1px solid #d8bd84;padding:9px 0 7px;text-transform:uppercase;letter-spacing:.05em}",
            "h3{font-size:18px;margin:22px 0 8px;color:#2f2417;font-weight:700}",
            "p{margin:8px 0 14px}",
            "ul{margin:8px 0 16px 20px;padding:0}",
            "li{margin:6px 0}",
            "code{background:#ead9b5;border:1px solid #c9a96f;border-radius:4px;padding:1px 5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:90%;color:#4a2515}",
            ".local-copy{margin-top:30px;padding-top:14px;border-top:1px solid #d4b678;color:#6b5636;font-size:13px}",
            "</style>",
            "</head>",
            "<body>",
            '<div class="page">',
            '<div class="newsletter">',
            '<div class="masthead">Alberto Research Dispatch</div>',
            '<div class="content">',
            *body_parts,
            "</div>",
            "</div>",
            "</div>",
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
