"""
XJTU xkfw session: load/save, capacity check, lightweight re-login.

Full CAS (MFA/captcha) is interactive — on a server, prefer:
  1) run once interactively to create session.json
  2) overnight: refresh via register.do; if dead, email + exit or wait

二次认证（安全手机 / 安全邮箱）：CAS 用「动态 MFA 策略」，新设备或长期未登录时
会要求验证码。两条免人工的路子：
  * 首次登录时带 trustAgent=true（见 scripts/mfa_login.py），把本机登记为
    「可信客户端」，之后动态策略默认跳过二次认证；
  * 万一仍被要求验证码，且安全邮箱就是项目里已配置的那个邮箱，
    可用 read_mfa_code_from_mailbox() 走 IMAP 读码自动完成（mail_mfa 配置）。
"""

from __future__ import annotations

import base64
import email
import imaplib
import json
import logging
import os
import re
import stat
import time
from email.utils import parsedate_to_datetime
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


class TokenRejected(SessionError):
    """业务接口（capacity.do）拒绝当前 token：token 已不被承认。

    区别于「空壳/网络抖动」：这类错误说明 xkfw 端的登录态（app 会话）已经没了，
    仅靠 register.do 换 token 是**假恢复** —— 必须重新走一次 CAS 登录把 app 会话
    建回来。见 XkfwClient.ensure_session()。
    """

    def __init__(self, message: str = ""):
        super().__init__(message or "token 未被接受（登录态已失效）")


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


# ── 安全邮箱验证码（IMAP 读码）────────────────────────────────────────────

# provider → (imap host, port)
IMAP_HOSTS: dict[str, tuple[str, int]] = {
    "qq": ("imap.qq.com", 993),
    "qq_starttls": ("imap.qq.com", 993),
    "gmail": ("imap.gmail.com", 993),
}


def _message_text(msg: "email.message.Message") -> str:
    """取邮件所有 text/plain + text/html 正文（解码后拼接）。"""
    chunks: list[str] = []
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            chunks.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
        except (LookupError, ValueError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def _extract_code(text: str) -> str:
    """从邮件正文里抽 6 位验证码。样例：「验证码990610(有效期5分钟)」。

    只认 6 位数字，避免把「验证码…2026 年」这类年份当成验证码。
    """
    if not text:
        return ""
    for pattern in (
        r"验证码[^0-9]{0,8}(\d{6})",
        r"(?:验证|校验|动态)码[^0-9]{0,8}(\d{6})",
        r"(?:code|Code|CODE)[^0-9]{0,8}(\d{6})",
    ):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def _is_auth_mail(msg: "email.message.Message") -> bool:
    """粗判是否是统一身份认证发来的邮件（发件人/主题）。"""
    sender = str(msg.get("From") or "").lower()
    subject = str(msg.get("Subject") or "")
    return "xjtu.edu.cn" in sender or any(k in subject for k in ("认证", "验证", "安全", "登录"))


def _fetch_mfa_code_once(host: str, port: int, user: str, password: str,
                         since_ts: float, scan: int = 15) -> str:
    """连一次 IMAP，从最新的邮件往前找验证码；找不到返回 ""。

    先只看认证中心发来的邮件，都没有再放宽到任意邮件。
    """
    box = imaplib.IMAP4_SSL(host, port, timeout=20)
    try:
        box.login(user, password)
        box.select("INBOX", readonly=True)
        typ, dat = box.search(None, "ALL")
        if typ != "OK":
            return ""

        candidates: list[tuple[bool, str]] = []   # (是否认证邮件, 正文)
        for num in reversed((dat[0] or b"").split()[-scan:]):
            try:
                typ, d = box.fetch(num, "(RFC822)")
            except imaplib.IMAP4.error:
                continue
            if typ != "OK" or not d or not d[0]:
                continue
            msg = email.message_from_bytes(d[0][1])
            try:
                ts = parsedate_to_datetime(msg.get("Date")).timestamp()
            except (TypeError, ValueError):
                ts = 0.0
            # 只认本次请求前后到达的邮件，避免拿到上一次的旧验证码
            if since_ts and ts and ts < since_ts - 120:
                continue
            candidates.append((_is_auth_mail(msg), _message_text(msg)))

        for auth_mail_only in (True, False):
            for is_auth, text in candidates:
                if auth_mail_only and not is_auth:
                    continue
                code = _extract_code(text)
                if code:
                    log.info("已从安全邮箱读到验证码（%d 位）", len(code))
                    return code
        return ""
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def read_mfa_code_from_mailbox(cfg: dict[str, Any], *, since_ts: float = 0.0,
                               timeout_sec: float = 180.0, poll_sec: float = 6.0) -> str:
    """轮询安全邮箱，读取统一身份认证发来的验证码；超时/不可用返回 ""。

    cfg 可用字段（host/port 缺失时按 provider 推断，默认 QQ 邮箱）::

        enabled: true            # 是否启用（False 时调用方不应调用）
        provider: qq             # qq / gmail
        host: imap.qq.com        # 可覆盖
        port: 993
        user: xxx@qq.com         # 缺省用 mail.from_addr
        password: <IMAP 授权码>   # QQ 的 SMTP 授权码同时可用于 IMAP
        timeout_sec: 180

    注意：QQ 邮箱需要在「设置 → 账户」里开启 IMAP/SMTP 服务（生成授权码时一并开启）。
    """
    cfg = cfg or {}
    user = str(cfg.get("user") or cfg.get("from_addr") or "").strip()
    password = str(cfg.get("password") or "")
    if not user or not password:
        log.warning("mail_mfa 缺少 user/password，无法自动读码")
        return ""

    host = str(cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 0)
    if not host:
        provider = str(cfg.get("provider") or "qq").lower()
        host, default_port = IMAP_HOSTS.get(provider, ("imap.qq.com", 993))
        port = port or default_port
    if not port:
        port = 993

    timeout_sec = float(cfg.get("timeout_sec") or timeout_sec)
    deadline = time.time() + timeout_sec
    attempt = 0
    while True:
        attempt += 1
        try:
            code = _fetch_mfa_code_once(host, port, user, password, since_ts)
            if code:
                return code
        except (imaplib.IMAP4.error, OSError, UnicodeDecodeError) as e:
            log.warning("读安全邮箱失败(第 %d 次): %s", attempt, e)
        if time.time() >= deadline:
            log.warning("等待安全邮箱验证码超时（%.0fs）", timeout_sec)
            return ""
        time.sleep(poll_sec)


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
    def __init__(self, session_file: str = "session.json",
                 mail_mfa_cfg: dict[str, Any] | None = None):
        self.session_file = Path(session_file)
        self.http = _new_http()
        self.token = ""
        self.student_code = ""
        self.fp = _fingerprint()
        # 安全邮箱自动读码（可选）：启用后 full_login 在遇到二次认证时会
        # 自动发码到安全邮箱 → IMAP 读码 → 完成验证，无需人工。
        self.mail_mfa: dict[str, Any] = dict(mail_mfa_cfg or {})
        self.mail_mfa_enabled = bool(self.mail_mfa.get("enabled"))
        # 登录时是否登记为「可信客户端」（让后续登录免二次认证）
        self.trust_agent = bool(self.mail_mfa.get("trust_agent", True)) and self.mail_mfa_enabled
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
        # session.json 含 token 与 CAS cookie，收紧权限（0600），避免同机其它用户可读
        try:
            os.chmod(self.session_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
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
        if not isinstance(j, dict):
            return False
        # 空壳 {"data":null,"code":null}（高峰偶发、几分钟自愈）不能算健康探活结果
        if j.get("data") is None and j.get("code") is None:
            return False
        return "code" in j or "data" in j or "dataList" in j

    def refresh_token(self) -> bool:
        """Try register.do without full CAS."""
        num = self.student_code or "null"
        # xkfw 端偶发返回空壳({"data":null,"code":null}，通常几分钟内自愈)，
        # 多试几轮提高命中率；空壳/异常一律视为失败，绝不抛异常
        for attempt in range(3):
            for candidate in (num, "null"):
                url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/register.do"
                try:
                    r = self.http.get(url, params={"number": candidate}, timeout=15)
                    j = r.json()
                except (requests.RequestException, ValueError):
                    continue
                data = (j or {}).get("data") or {}
                if _code_ok((j or {}).get("code")) and data.get("token"):
                    self.token = data["token"]
                    if data.get("number"):
                        self.student_code = data["number"]
                    self.http.headers["Token"] = self.token
                    self.save()
                    log.info("Token 刷新成功")
                    return True
            time.sleep(1.5)
        return False

    def ensure_session(self, account: str, password: str, verify_tcid: str = "") -> None:
        """确保会话真正可用（不只是"看起来活着"）。

        历史坑（2026-09-13 实测）：
          1) dictionary.do / register.do 可能都成功，但 capacity.do 仍回
             「未查询到登录信息」—— xkfw 的**登录态（app 会话）**已经没了，
             register.do 只会发一个不被承认的新 token，属于**假恢复**：
             监控于是无限循环"已恢复→查容量失败"，既不报警也不监控。
          2) 只有重新走一次完整 CAS 登录（GET xkfw → CAS 自动发票 → 新的
             JSESSIONID/GS_SESSIONID）才能把登录态建回来。

        因此这里用 verify_tcid（一门真实课程）做**业务级**验收：
        凡是"探活通过但容量接口拒绝 token"，一律视为未恢复并升级到完整登录。
        """
        if self.refresh_token() and self.is_alive() and self._operational_ok(verify_tcid):
            return
        log.info("会话失效（或 token 不被业务接口接受），尝试完整 CAS 登录…")
        self.full_login(account, password)
        if not self.is_alive():
            raise SessionError("登录后会话仍无效")
        if not self._operational_ok(verify_tcid):
            raise SessionError("登录后容量接口仍拒绝该 token（登录态未建立）")

    def _operational_ok(self, tcid: str) -> bool:
        """业务级验收：用一门真实课程调 capacity.do。

        只有明确"token 不被承认"（TokenRejected）才算会话问题；
        空壳/网络抖动等其它 SessionError 不算（避免高峰抖动触发登录风暴）。
        """
        if not tcid:
            return True
        try:
            self.check_capacity(tcid)
            return True
        except TokenRejected:
            return False
        except SessionError:
            return True

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
        if isinstance((j or {}).get("code"), str) and j.get("code") not in ("0", "1", ""):
            msg = j.get("msg") or str(j.get("code"))
            if "登录" in msg or "token" in msg.lower():
                # 明确"token 不被承认"：app 登录态已失效，换 token 无用，
                # 需要完整 CAS 登录重建会话（见 ensure_session / _operational_ok）
                raise TokenRejected(msg)

        # 高峰期间 xkfw 偶发返回空壳 {"data":null,"code":null}（几分钟自愈）。
        # 空壳绝不能当成"已满 0/0"——那会静默错过空位；视为会话级异常，
        # 上层会重试，且不会清零连续失败计数。
        data = (j or {}).get("data")
        if not isinstance(data, dict):
            raise SessionError(f"容量接口返回空壳/无效数据: {str(j or {})[:120]}")

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
                    "loginType": "passwordLogin",
                    "username": account,
                    "password": enc_pwd,
                    "fpVisitorId": self.fp,
                },
                timeout=15,
            )
            dj = dr.json()
            data = (dj or {}).get("data") or {}
            need = data.get("need")
            mfa_state = data.get("state") or ""
            if need:
                # 能用安全邮箱自动读码就自动完成；否则交给上层（人工/浏览器）
                if not self._mfa_via_mail(mfa_state):
                    raise MFARequired(state=mfa_state)
                log.info("已通过安全邮箱自动完成二次认证")
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
            "trustAgent": "true" if self.trust_agent else "",
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

    def _mfa_via_mail(self, mfa_state: str) -> bool:
        """安全邮箱自动验证：initByType → 发码 → IMAP 读码 → valid。

        成功返回 True（后续表单提交带上 mfaState 即可完成登录）。
        任何一步失败都返回 False，由调用方回退到「需要人工 MFA」。
        绝不抛异常、绝不改 session.json。
        """
        if not self.mail_mfa_enabled or not mfa_state:
            return False
        try:
            ir = self.http.get(
                f"{CAS}/cas/mfa/initByType/secureemail",
                params={"state": mfa_state},
                timeout=20,
            )
            idata = (ir.json() or {}).get("data") or {}
            gid = idata.get("gid")
            attest = idata.get("attestServerUrl")
            if not gid or not attest:
                log.warning("安全邮箱验证未初始化（可能未绑定）: %s", str(idata)[:120])
                return False

            sent_at = time.time()
            sr = self.http.post(
                f"{attest}/api/guard/secureemail/send", json={"gid": gid}, timeout=20
            )
            if (sr.json() or {}).get("code") != 0:
                log.warning("安全邮箱验证码发送失败: %s", (sr.text or "")[:120])
                return False

            code = read_mfa_code_from_mailbox(
                self.mail_mfa,
                since_ts=sent_at,
                timeout_sec=float(self.mail_mfa.get("timeout_sec") or 180),
            )
            if not code:
                return False

            vr = self.http.post(
                f"{attest}/api/guard/secureemail/valid",
                json={"gid": gid, "code": code},
                timeout=20,
            )
            vj = vr.json() or {}
            vdata = vj.get("data") or {}
            return _code_ok(vj.get("code")) and str(vdata.get("status")) == "2"
        except (requests.RequestException, ValueError, TypeError, KeyError) as e:
            log.warning("安全邮箱自动验证失败: %s", e)
            return False

    def _try_register(self, account: str = "", attempts: int = 3) -> bool:
        """GET register.do 换 token。

        register.do 会偶发返回空壳 {"data":null,"code":null}（几分钟自愈）。
        原先这里每个候选只试一次，抖动期间会让 full_login 直接抛
        「无法解析 CAS execution」而放弃恢复（2026-09-13 实测踩到）；
        改成和 refresh_token() 一样的多轮重试。
        """
        for attempt in range(max(1, attempts)):
            for num in ("null", self.student_code or "", account):
                if num is None or num == "":
                    continue
                url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/register.do"
                try:
                    r = self.http.get(url, params={"number": num}, timeout=15)
                    j = r.json()
                except (requests.RequestException, ValueError):
                    continue
                if _code_ok((j or {}).get("code")) and ((j or {}).get("data") or {}).get("token"):
                    self.token = j["data"]["token"]
                    if j["data"].get("number"):
                        self.student_code = j["data"]["number"]
                    self.http.headers["Token"] = self.token
                    self.save()
                    log.info("register 成功 student=%s", self.student_code)
                    return True
            if attempt < attempts - 1:
                time.sleep(1.5)
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
