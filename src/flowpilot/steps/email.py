"""``email`` — send an email over SMTP (STARTTLS or implicit TLS).

Defaults come from ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``,
``SMTP_PASSWORD`` and ``SMTP_FROM``.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StepError
from flowpilot.registry import step


@step("email")
def email(
    ctx: StepContext,
    to: str | list[str],
    subject: str,
    body: str = "",
    html: str | None = None,
    sender: str | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    security: str = "starttls",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send an email. ``security`` is ``starttls`` (default), ``ssl`` or ``none``."""
    host = host or os.environ.get("SMTP_HOST")
    if not host:
        raise StepConfigError("email: no SMTP host (set SMTP_HOST or pass host)")
    security = security.lower()
    if security not in {"starttls", "ssl", "none"}:
        raise StepConfigError("email: security must be starttls, ssl or none")
    port = int(port or os.environ.get("SMTP_PORT") or (465 if security == "ssl" else 587))
    username = username or os.environ.get("SMTP_USER")
    password = password or os.environ.get("SMTP_PASSWORD")
    sender = sender or os.environ.get("SMTP_FROM") or username
    if not sender:
        raise StepConfigError("email: no sender (set SMTP_FROM or pass sender)")
    recipients = [to] if isinstance(to, str) else list(to)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body or "")
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        smtp: smtplib.SMTP
        if security == "ssl":
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
        with smtp:
            if security == "starttls":
                smtp.starttls(context=context)
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise StepError(f"email: {type(exc).__name__}: {exc}") from exc
    ctx.log.info(f"email sent to {', '.join(recipients)}")
    return {"to": recipients, "subject": subject}
