"""auth_session 纯逻辑与空壳处理测试（不依赖网络）"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth_session import SessionError, XkfwClient, _code_ok, _to_int


class FakeResp:
    def __init__(self, payload, url="https://xkfw.xjtu.edu.cn/x"):
        self._payload = payload
        self.url = url
        self.status_code = 200
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("bad json")
        return self._payload


def _client_with_http():
    c = XkfwClient(session_file=str(Path(__file__).parent / "no_such_session.json"))
    c.token = "test-token"
    c.student_code = "12345"
    c.http.headers["Token"] = c.token
    return c


# ── 纯函数 ──

@pytest.mark.parametrize("v,ok", [(0, True), (1, True), ("0", True), ("1", True), (None, False), ("-1", False), ("x", False)])
def test_code_ok(v, ok):
    assert _code_ok(v) is ok


@pytest.mark.parametrize("v,out", [("24", 24), (24, 24), (" 12 ", 12), (None, 0), ("abc", 0), ("", 0)])
def test_to_int(v, out):
    assert _to_int(v) == out


# ── 空壳识别（P1 核心）──

def test_check_capacity_empty_shell_raises():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp({"data": None, "code": None})
    with pytest.raises(SessionError):
        c.check_capacity("20262027XXXX01")


def test_check_capacity_valid():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp(
        {"code": "0", "data": {"numberOfSelected": "22", "classCapacity": "24"}}
    )
    has_room, selected, capacity = c.check_capacity("20262027XXXX01")
    assert (has_room, selected, capacity) == (True, 22, 24)


def test_check_capacity_full():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp(
        {"code": "0", "data": {"numberOfSelected": "24", "classCapacity": "24"}}
    )
    has_room, selected, capacity = c.check_capacity("x")
    assert (has_room, selected, capacity) == (False, 24, 24)


def test_is_alive_empty_shell_false():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp({"data": None, "code": None})
    assert c.is_alive() is False


def test_is_alive_redirect_to_cas_false():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp({}, url="https://login.xjtu.edu.cn/cas/login")
    assert c.is_alive() is False


def test_is_alive_valid_true():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp({"code": "0", "data": [{"key": "v"}]})
    assert c.is_alive() is True


def test_check_capacity_no_token_raises():
    c = _client_with_http()
    c.token = ""
    with pytest.raises(SessionError):
        c.check_capacity("x")
