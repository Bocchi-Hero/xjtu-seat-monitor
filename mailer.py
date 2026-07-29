"""SMTP mail helpers — Gmail / QQ / custom."""

from __future__ import annotations

import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from typing import Any


PROVIDERS: dict[str, dict[str, Any]] = {
    "gmail": {
        "host": "smtp.gmail.com",
        "port": 465,
        "use_ssl": True,
    },
    "qq": {
        "host": "smtp.qq.com",
        "port": 465,
        "use_ssl": True,
    },
    # 备用：QQ 也可用 STARTTLS 587
    "qq_starttls": {
        "host": "smtp.qq.com",
        "port": 587,
        "use_ssl": False,
        "starttls": True,
    },
}


def resolve_smtp(mail_cfg: dict[str, Any]) -> dict[str, Any]:
    provider = (mail_cfg.get("provider") or "qq").lower().strip()
    base = dict(PROVIDERS.get(provider, {}))
    if provider == "custom" or not base:
        base = {
            "host": mail_cfg.get("host", "smtp.qq.com"),
            "port": int(mail_cfg.get("port", 465)),
            "use_ssl": bool(mail_cfg.get("use_ssl", True)),
            "starttls": bool(mail_cfg.get("starttls", False)),
        }
    # allow overrides
    for k in ("host", "port", "use_ssl", "starttls"):
        if k in mail_cfg and mail_cfg[k] is not None:
            base[k] = mail_cfg[k]
    base["port"] = int(base["port"])
    return base


def send_mail(mail_cfg: dict[str, Any], subject: str, body: str) -> None:
    if not mail_cfg.get("enabled", True):
        return

    from_addr = mail_cfg["from_addr"]
    to_addr = mail_cfg.get("to_addr") or from_addr
    password = mail_cfg["password"]
    smtp = resolve_smtp(mail_cfg)

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((str(Header("XJTU选课空位监控", "utf-8")), from_addr))
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8")

    host = smtp["host"]
    port = smtp["port"]
    context = ssl.create_default_context()

    if smtp.get("use_ssl", True):
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if smtp.get("starttls"):
                server.starttls(context=context)
            server.login(from_addr, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
