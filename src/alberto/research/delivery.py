from __future__ import annotations

import os
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
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
        msg.set_content(f"{body}\n\nLocal copy: {local_path}")
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
