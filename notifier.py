"""Webhook 通知：POST JSON 到任意 URL（可接 QQ 机器人 / Server酱 / Bark / 飞书等）。"""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger("seat-monitor")


def send_webhook(cfg: dict[str, Any], subject: str, body: str, extra: dict[str, Any] | None = None) -> bool:
    """发送一条 webhook 推送。cfg 为 config 里的 webhook 段：{enabled, url}。

    成功返回 True；未配置 / 失败返回 False（绝不抛异常）。
    """
    if not cfg or not cfg.get("enabled", True):
        return False
    url = str(cfg.get("url") or "").strip()
    if not url:
        return False
    payload = {
        "msg_type": "seat_monitor",
        "subject": subject,
        "body": body,
        "extra": extra or {},
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 400:
            log.error("webhook 返回 %s: %s", r.status_code, r.text[:120])
            return False
        return True
    except requests.RequestException as e:
        log.error("webhook 发送失败: %s", e)
        return False
