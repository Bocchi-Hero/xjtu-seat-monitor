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


# ── 假恢复识别（2026-09-13 线上实测）──────────────────────────────────
#
# 现象：register.do 换 token 成功、dictionary.do 探活也通过，但 capacity.do
# 一直回「未查询到登录信息」—— xkfw 的登录态（app 会话）已经失效。
# 旧逻辑判定「已自动恢复」，于是监控无限循环：恢复 → 查容量失败 → 再恢复，
# 既不报警也不真正监控。修法：ensure_session 用一门真实课程做业务级验收，
# token 被业务接口拒绝时必须升级为完整 CAS 登录。

from auth_session import TokenRejected  # noqa: E402  (测试文件顶部未导入)


def _rejecting_capacity(msg="未查询到登录信息"):
    def _raise(tcid):
        raise TokenRejected(msg)
    return _raise


def test_check_capacity_token_rejected_is_token_rejected():
    c = _client_with_http()
    c.http.get = lambda *a, **k: FakeResp({"code": "302", "msg": "未查询到登录信息"})
    with pytest.raises(TokenRejected):
        c.check_capacity("20262027XXXX01")
    # 仍是 SessionError 子类：调用方原有的 except SessionError 不受影响
    assert issubclass(TokenRejected, SessionError)


def test_operational_ok_false_only_for_token_rejection():
    c = _client_with_http()
    # token 被业务接口拒绝 → 不算恢复
    c.check_capacity = _rejecting_capacity()
    assert c._operational_ok("tcid1") is False
    # 空壳（高峰抖动）不是会话问题，不能触发完整登录，避免登录风暴
    c.check_capacity = lambda tcid: (_ for _ in ()).throw(
        SessionError("容量接口返回空壳/无效数据: {'data': None, 'code': None}")
    )
    assert c._operational_ok("tcid1") is True
    # 没给验收课程 → 视为通过（保持旧行为）
    assert c._operational_ok("") is True


def test_ensure_session_forces_full_login_when_token_rejected():
    c = _client_with_http()
    calls = {"full_login": 0}
    c.refresh_token = lambda: True          # 轻量刷新"成功"
    c.is_alive = lambda: True               # 探活也"健康"
    c.check_capacity = _rejecting_capacity()

    def fake_full_login(account, password, captcha=""):
        calls["full_login"] += 1
        c.check_capacity = lambda tcid: (False, 24, 24)   # 登录后业务接口正常

    c.full_login = fake_full_login
    c.ensure_session("u", "p", verify_tcid="tcid1")
    assert calls["full_login"] == 1


def test_ensure_session_raises_when_capacity_still_rejects_after_login():
    c = _client_with_http()
    c.refresh_token = lambda: True
    c.is_alive = lambda: True
    c.full_login = lambda account, password, captcha="": None
    c.check_capacity = _rejecting_capacity()
    with pytest.raises(SessionError):
        c.ensure_session("u", "p", verify_tcid="tcid1")


def test_ensure_session_no_full_login_when_healthy():
    c = _client_with_http()
    calls = {"full_login": 0}
    c.refresh_token = lambda: True
    c.is_alive = lambda: True
    c.check_capacity = lambda tcid: (False, 24, 24)
    c.full_login = lambda account, password, captcha="": calls.__setitem__("full_login", calls["full_login"] + 1)
    c.ensure_session("u", "p", verify_tcid="tcid1")
    assert calls["full_login"] == 0
