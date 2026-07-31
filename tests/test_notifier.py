"""notifier (webhook) 测试：mock requests，不触网"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import notifier


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


def test_no_url_returns_false(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: pytest.fail("不应发起请求"))
    assert notifier.send_webhook({}, "s", "b") is False
    assert notifier.send_webhook({"enabled": True, "url": ""}, "s", "b") is False


def test_disabled_returns_false(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: pytest.fail("不应发起请求"))
    assert notifier.send_webhook({"enabled": False, "url": "http://x"}, "s", "b") is False


def test_success(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResp(200)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    ok = notifier.send_webhook({"url": "https://example.com/hook"}, "主题", "内容", {"k": "v"})
    assert ok is True
    assert captured["url"] == "https://example.com/hook"
    assert captured["json"]["subject"] == "主题"
    assert captured["json"]["body"] == "内容"
    assert captured["json"]["msg_type"] == "seat_monitor"
    assert captured["json"]["extra"] == {"k": "v"}
    assert captured["timeout"] == 10


def test_http_error_returns_false(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: FakeResp(500, "boom"))
    assert notifier.send_webhook({"url": "https://example.com/hook"}, "s", "b") is False


def test_network_error_returns_false(monkeypatch):
    import requests as real_requests

    def boom(*a, **k):
        raise real_requests.ConnectionError("refused")

    monkeypatch.setattr(notifier.requests, "post", boom)
    assert notifier.send_webhook({"url": "https://example.com/hook"}, "s", "b") is False
