"""
XJTU xkfw session: load/save, capacity check, lightweight re-login.

Full CAS (MFA/captcha) is interactive — on a server, prefer:
  1) run once interactively to create session.json
  2) overnight: refresh via register.do; if dead, email + exit or wait
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
except ImportError:  # pragma: no cover
    RSA = None  # type: ignore
    PKCS1_v1_5 = None  # type: ignore

log = logging.getLogger("seat-monitor")

XKFW = "https://xkfw.xjtu.edu.cn"
CAS = "https://login.xjtu.edu.cn"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class SessionError(Exception):
    pass


class MFARequired(SessionError):
    def __init__(self, state: str = "", safety: bool = False):
        super().__init__("需要 MFA / 二次认证，请本机交互登录后写入 session.json")
        self.state = state
        self.safety = safety


class CaptchaRequired(SessionError):
    def __init__(self, message: str = ""):
        super().__init__(message or "需要验证码，请本机浏览器/GUI 登录后导出 session")


def _new_http() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


def _ts() -> str:
    return str(int(time.time() * 1000))


def _extract_execution(html: str) -> str:
    m = re.search(r'name="execution"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="execution"', html)
    return m.group(1) if m else ""


def _extract_alert(html: str) -> str:
    m = re.search(r'el-alert[^>]*title="([^"]+)"', html)
    return m.group(1) if m else ""


def _code_ok(code: Any) -> bool:
    return code in (0, 1, "0", "1")


def _fingerprint() -> str:
    """Stable-ish device id without browser (SHA-ish via hash)."""
    import hashlib
    import platform
    import uuid

    raw = "|".join(
        [
            platform.system(),
            platform.machine(),
            platform.node(),
            str(os.cpu_count() or 0),
            hex(uuid.getnode()),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _encrypt_password(plaintext: str, pem: str) -> str:
    if not pem or RSA is None:
        # fallback: send plain only if school allows (usually not)
        return plaintext
    key = RSA.import_key(pem.encode() if isinstance(pem, str) else pem)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plaintext.encode("utf-8"))
    return "__RSA__" + base64.b64encode(encrypted).decode("ascii")


class XkfwClient:
    def __init__(self, session_file: str = "session.json"):
        self.session_file = Path(session_file)
        self.http = _new_http()
        self.token = ""
        self.student_code = ""
        self.fp = _fingerprint()
        self._load()

    # ── persistence ──

    def _load(self) -> None:
        if not self.session_file.exists():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.token = data.get("token") or ""
        self.student_code = data.get("student_code") or ""
        for c in data.get("cookies") or []:
            self.http.cookies.set(
                c.get("name", ""),
                c.get("value", ""),
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )
        if self.token:
            self.http.headers["Token"] = self.token
        log.info("已加载 session: student=%s token=%s…", self.student_code, self.token[:12] if self.token else "")

    def save(self) -> None:
        cookies = []
        for c in self.http.cookies:
            cookies.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                }
            )
        payload = {
            "token": self.token,
            "student_code": self.student_code,
            "cookies": cookies,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.session_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("session 已写入 %s", self.session_file)

    # ── health ──

    def is_alive(self) -> bool:
        if not self.token:
            return False
        url = f"{XKFW}/xsxkapp/sys/xsxkapp/publicinfo/dictionary.do"
        try:
            r = self.http.get(url, params={"timestamp": _ts()}, timeout=15)
        except requests.RequestException as e:
            log.warning("探活网络错误: %s", e)
            return False
        if "login.xjtu.edu.cn" in r.url or "cas" in r.url.lower():
            return False
        if r.status_code != 200:
            return False
        try:
            j = r.json()
        except ValueError:
            return False
        return "code" in j or "data" in j or "dataList" in j

    def refresh_token(self) -> bool:
        """Try register.do without full CAS."""
        num = self.student_code or "null"
        for candidate in (num, "null"):
            url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/register.do"
            try:
                r = self.http.get(url, params={"number": candidate}, timeout=15)
                j = r.json()
            except (requests.RequestException, ValueError):
                continue
            if _code_ok(j.get("code")) and j.get("data", {}).get("token"):
                self.token = j["data"]["token"]
                if j["data"].get("number"):
                    self.student_code = j["data"]["number"]
                self.http.headers["Token"] = self.token
                self.save()
                log.info("Token 刷新成功")
                return True
        return False

    def ensure_session(self, account: str, password: str) -> None:
        if self.is_alive():
            return
        if self.refresh_token() and self.is_alive():
            return
        log.info("会话失效，尝试完整 CAS 登录…")
        self.full_login(account, password)
        if not self.is_alive():
            raise SessionError("登录后会话仍无效")

    # ── capacity ──

    def check_capacity(self, teaching_class_id: str) -> tuple[bool, int, int]:
        """
        Returns (has_room, selected, capacity).
        On auth failure raises SessionError.
        """
        if not self.token:
            raise SessionError("无 Token")
        url = f"{XKFW}/xsxkapp/sys/xsxkapp/elective/teachingclass/capacity.do"
        params = {
            "teachingClassId": teaching_class_id,
            "capacitySuffix": "",
            "xh": self.student_code,
            "timestamp": _ts(),
        }
        r = self.http.get(url, params=params, timeout=15)
        if "login.xjtu.edu.cn" in r.url:
            raise SessionError("会话跳转 CAS")
        try:
            j = r.json()
        except ValueError as e:
            raise SessionError(f"容量接口非 JSON: {r.text[:120]}") from e

        # some error payloads
        if isinstance(j.get("code"), str) and j.get("code") not in ("0", "1", ""):
            msg = j.get("msg") or str(j.get("code"))
            if "登录" in msg or "token" in msg.lower():
                raise SessionError(msg)

        data = j.get("data") or {}
        selected = _to_int(data.get("numberOfSelected"))
        capacity = _to_int(data.get("classCapacity"))
        has_room = selected < capacity if capacity > 0 else False
        return has_room, selected, capacity

    # ── CAS login (best-effort; MFA/captcha may require interactive) ──

    def full_login(self, account: str, password: str, captcha: str = "") -> None:
        # 1) hit xkfw → CAS
        r = self.http.get(XKFW, timeout=20, allow_redirects=True)
        cas_url = r.url
        html = r.text
        execution = _extract_execution(html)
        if not execution:
            # already have app cookies?
            if self._try_register(account):
                return
            raise SessionError("无法解析 CAS execution，页面可能已变")

        # 2) public key
        pem = ""
        try:
            pr = self.http.get(f"{CAS}/cas/jwt/publicKey", timeout=15)
            if pr.ok:
                pem = pr.text
        except requests.RequestException:
            pass

        enc_pwd = _encrypt_password(password, pem)

        # 3) MFA detect
        mfa_state = ""
        try:
            dr = self.http.post(
                f"{CAS}/cas/mfa/detect",
                data={
                    "username": account,
                    "password": enc_pwd,
                    "fpVisitorId": self.fp,
                },
                timeout=15,
            )
            dj = dr.json()
            need = (dj.get("data") or {}).get("need")
            mfa_state = (dj.get("data") or {}).get("state") or ""
            if need:
                raise MFARequired(state=mfa_state)
        except MFARequired:
            raise
        except (requests.RequestException, ValueError, TypeError):
            log.warning("MFA detect 失败，继续尝试登录")

        # 4) POST login
        form = {
            "username": account,
            "password": enc_pwd,
            "captcha": captcha,
            "currentMenu": "1",
            "failN": "0",
            "mfaState": mfa_state,
            "execution": execution,
            "_eventId": "submit",
            "geolocation": "",
            "fpVisitorId": self.fp,
            "trustAgent": "",
            "submit1": "Login1",
        }
        r2 = self.http.post(cas_url, data=form, timeout=20, allow_redirects=True)
        body = r2.text

        if "secState" in body and ("Safety Verify" in body or "二次认证" in body):
            raise MFARequired(safety=True)

        if "account-wrap" in body:
            raise SessionError("需要选择本科/研究生身份：请用浏览器登录一次后再跑监控")

        alert = _extract_alert(body)
        if "captcha" in body.lower() and ("execution" in body) and (
            "fm1" in body or alert
        ):
            # still on login page
            if "captcha.jpg" in body and "display:none" not in body[max(0, body.find("captcha.jpg") - 400) : body.find("captcha.jpg")]:
                raise CaptchaRequired(alert or "需要验证码")
            if alert:
                raise SessionError(f"登录失败: {alert}")

        if not self._try_register(account):
            raise SessionError("登录后 register.do 未拿到 token")

    def _try_register(self, account: str = "") -> bool:
        for num in ("null", self.student_code or "", account):
            if num is None or num == "":
                continue
            url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/register.do"
            try:
                r = self.http.get(url, params={"number": num}, timeout=15)
                j = r.json()
            except (requests.RequestException, ValueError):
                continue
            if _code_ok(j.get("code")) and (j.get("data") or {}).get("token"):
                self.token = j["data"]["token"]
                if j["data"].get("number"):
                    self.student_code = j["data"]["number"]
                self.http.headers["Token"] = self.token
                self.save()
                log.info("register 成功 student=%s", self.student_code)
                return True
        return False


def _to_int(v: Any) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def import_session_from_browser_export(path: str, client: XkfwClient) -> None:
    """
    Optional: load a JSON like:
      {"token": "...", "student_code": "...", "cookies":[{"name","value","domain"}]}
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    client.token = data.get("token") or client.token
    client.student_code = data.get("student_code") or client.student_code
    for c in data.get("cookies") or []:
        client.http.cookies.set(
            c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/")
        )
    if client.token:
        client.http.headers["Token"] = client.token
    client.save()
