#!/usr/bin/env python3
"""XJTU xkfw 会话续期工具（含 MFA / 安全验证）。

背景：xkfw 的 `register.do` 只有在 CAS 会话仍有效时才能换到新 token。
CAS 会话过期后必须重新走一次统一认证（`full_login`）；而统一认证在
「新设备 / 长时间未登录」时会要求二次认证（安全手机短信 / 安全邮箱验证码），
服务器上无法自动完成 —— 这正是服务崩溃循环、邮件提醒「登录已掉线」的根因。

本工具把这条链路补全：

  probe    只读诊断：本次是否需要二次认证、可用哪些验证方式、验证码会发到哪个
           号码（打码显示）。不发送任何验证码。
  start    触发安全验证（把验证码发到安全手机或安全邮箱），会话状态落盘到
           .mfa_state.json（cookie / mfaState / gid），等待验证码。
           加 --wait-mail：验证码发到安全邮箱后由本工具自动通过 IMAP 读码并
           完成登录，全程无需人工。
  verify   用验证码完成二次认证 → CAS 登录 → register.do 取 token → 写入 session.json
  auto     无人值守：不需要二次认证时直接登录写 session.json；需要时以退出码 3 结束
  status   查看待验证状态

关键点：默认勾选「设为可信客户端」（登录表单 trustAgent=true）。登记成功后
CAS 的动态 MFA 策略会跳过二次认证，监控进程的 `ensure_session()` 就能继续自动
重登，不再需要人工介入 —— 这是让 token 失效不再需要手动处理的关键。

用法（在服务器项目根目录）：
    .venv/bin/python scripts/mfa_login.py probe
    .venv/bin/python scripts/mfa_login.py start              # 默认发安全手机
    .venv/bin/python scripts/mfa_login.py start --type secureemail
    .venv/bin/python scripts/mfa_login.py verify --code 123456
    .venv/bin/python scripts/mfa_login.py auto                # 适合定时任务

安全说明：验证码、密码、token 都不写日志；.mfa_state.json 含临时 cookie，
verify 成功后自动删除。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path
from urllib.parse import quote

import _bootstrap  # noqa: F401  (adds repo root to sys.path)

import yaml  # noqa: E402

from auth_session import (  # noqa: E402
    CAS,
    XkfwClient,
    _encrypt_password,
    _extract_execution,
    _fingerprint,
    _new_http,
    read_mfa_code_from_mailbox,
)

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".mfa_state.json"
DEFAULT_SERVICE = "https://xkfw.xjtu.edu.cn/xsxkapp/sys/xsxkapp/*default/index.do"
MFA_TTL_SEC = 600  # 验证码 / mfaState 大致有效期，仅用于提示

# CAS initByType 名称 → (attest 接口路径, 目标字段, 中文名, detect 里的开关)
MFA_TYPES: dict[str, tuple[str, str, str, str]] = {
    "securephone": ("securephone", "securePhone", "安全手机短信", "mfaTypeSecurePhone"),
    "secureemail": ("secureemail", "secureEmail", "安全邮箱验证码", "mfaTypeSecureEmail"),
    "apppush": ("apppush", "appPush", "超级APP推送", "mfaTypeAppPush"),
    "otp": ("otp", "otpSecret", "OTP 令牌", "mfaTypeOtp"),
}


# ── 基础辅助 ────────────────────────────────────────────────────────────


def _die(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def _load_cfg() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        _die(f"缺少配置文件: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _login_url(service: str) -> str:
    # 与浏览器一致：'/' → %2F，'*' 保留
    return f"{CAS}/cas/login?service={quote(service, safe='*')}"


def _resolve_mail_mfa(cfg: dict) -> dict:
    """安全邮箱读码参数：mail_mfa 优先，缺省复用 mail 里的邮箱与授权码。"""
    m = dict(cfg.get("mail_mfa") or {})
    mail = cfg.get("mail") or {}
    m.setdefault("user", mail.get("from_addr"))
    m.setdefault("password", mail.get("password"))
    m.setdefault("provider", mail.get("provider") or "qq")
    return m


def _mask(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return "（未返回）"
    if "@" in v:
        name, _, dom = v.partition("@")
        return f"{name[:2]}{'*' * max(0, len(name) - 2)}@{dom}"
    if "*" in v:
        return v
    if len(v) > 6:
        return f"{v[:3]}{'*' * (len(v) - 6)}{v[-3:]}"
    return v


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


def _load_state() -> dict:
    if not STATE_FILE.exists():
        _die("没有待验证的会话，请先执行: mfa_login.py start")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _restore_http(state: dict):
    s = _new_http()
    for c in state.get("cookies") or []:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    return s


def _dump_cookies(s) -> list[dict]:
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in s.cookies]


# ── CAS 流程 ────────────────────────────────────────────────────────────


def _open_login(cfg: dict):
    """打开登录页 → 取 execution / 公钥 / 提交 mfa/detect。"""
    account = str(cfg.get("account") or "").strip()
    password = str(cfg.get("password") or "")
    if not account or not password:
        _die("config.yaml 缺少 account / password")

    s = _new_http()
    fp = _fingerprint()
    url = _login_url(cfg.get("service") or DEFAULT_SERVICE)

    r = s.get(url, timeout=25)
    execution = _extract_execution(r.text)
    if not execution:
        _die("无法解析 CAS execution，登录页可能已改版")

    pem = ""
    try:
        pr = s.get(f"{CAS}/cas/jwt/publicKey", timeout=15)
        pem = pr.text if pr.ok else ""
    except Exception:  # noqa: BLE001
        pass
    enc_pwd = _encrypt_password(password, pem)

    dr = s.post(
        f"{CAS}/cas/mfa/detect",
        data={"loginType": "passwordLogin", "username": account,
              "password": enc_pwd, "fpVisitorId": fp},
        timeout=25,
    )
    try:
        dj = dr.json()
    except ValueError:
        _die(f"mfa/detect 返回非 JSON: {(dr.text or '')[:160]}")
    if (dj or {}).get("code") != 0:
        _die(f"mfa/detect 失败（账号/密码或风控）: {json.dumps(dj, ensure_ascii=False)[:200]}")

    return s, fp, execution, enc_pwd, account, (dj.get("data") or {})


def _init_type(s, mfa_state: str, api_path: str) -> dict:
    ir = s.get(f"{CAS}/cas/mfa/initByType/{api_path}", params={"state": mfa_state}, timeout=25)
    try:
        ij = ir.json()
    except ValueError:
        _die(f"initByType 返回非 JSON: {(ir.text or '')[:160]}")
    if (ij or {}).get("code") != 0:
        return {}
    return (ij.get("data") or {})


def _finish_login(s, cfg: dict, fp: str, execution: str, enc_pwd: str,
                  mfa_state: str, trust: bool, account: str) -> XkfwClient:
    """提交 CAS 登录表单 → 跟随跳转拿 xkfw cookie → register.do 换 token。"""
    form = {
        "username": account,
        "password": enc_pwd,
        "captcha": "",
        "currentMenu": "1",
        "failN": "-1",
        "mfaState": mfa_state,
        "execution": execution,
        "_eventId": "submit",
        "geolocation": "",
        "fpVisitorId": fp,
        "trustAgent": "true" if trust else "",
        "submit1": "Login1",
    }
    r = s.post(_login_url(cfg.get("service") or DEFAULT_SERVICE),
               data=form, timeout=30, allow_redirects=True)

    body = r.text or ""
    if "login.xjtu.edu.cn" in r.url and ("fm1" in body or "请重新登录" in body):
        _die("CAS 登录未通过（仍停在登录页），可能需要验证码或密码已变更: "
             + body[:160].replace("\n", " "))
    if "account-wrap" in body:
        _die("需要选择本科/研究生身份：请用浏览器登录一次后再跑监控")

    client = XkfwClient(session_file=str(ROOT / (cfg.get("session_file") or "session.json")))
    client.http = s          # 换成已认证的会话
    client.fp = fp

    if not client._try_register(account):
        _die("登录成功但 register.do 未拿到 token（可能 xkfw 端空壳抖动，稍后重试 verify）")

    print(f"✅ 登录成功，学号 {client.student_code}，session.json 已更新")
    return client


# ── 子命令 ──────────────────────────────────────────────────────────────


def cmd_probe(args: argparse.Namespace) -> int:
    cfg = _load_cfg()
    s, fp, _execution, _enc, _account, data = _open_login(cfg)

    need = data.get("need")
    print(f"本次是否需要二次认证: {'是' if need else '否'}")
    if not need:
        print("→ 不需要验证码：直接运行 `mfa_login.py auto` 即可完成续期。")
        return 0

    enabled = [t for t, (_, _, _, flag) in MFA_TYPES.items() if data.get(flag)]
    print(f"账号可用的验证方式: {', '.join(MFA_TYPES[t][2] for t in enabled) or '（无）'}")
    state = data.get("state") or ""
    for t in enabled:
        api_path, target_key, label, _ = MFA_TYPES[t]
        d = _init_type(s, state, api_path)
        if not d:
            print(f"  - {label}: 初始化失败（可能未绑定）")
            continue
        print(f"  - {label}: 目标 {_mask(d.get(target_key) or '')}"
              f"{'（有 gid）' if d.get('gid') else ''}")
    print("\n选一个可用方式执行: mfa_login.py start --type securephone|secureemail")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    cfg = _load_cfg()
    if args.type not in MFA_TYPES:
        _die(f"不支持的验证方式: {args.type}（可选: {', '.join(MFA_TYPES)}）")
    api_path, target_key, label, flag = MFA_TYPES[args.type]

    s, fp, execution, enc_pwd, account, data = _open_login(cfg)
    mfa_state = data.get("state") or ""

    if not data.get("need"):
        print("ℹ️  本次不需要二次认证（可信客户端 / 近期已登录），直接完成登录…")
        client = _finish_login(s, cfg, fp, execution, enc_pwd, mfa_state,
                               not args.no_trust, account)
        _verify_result(client, cfg)
        return 0

    if not data.get(flag):
        _die(f"账号未启用「{label}」，请换 --type（可先运行 probe 查看可用方式）")

    idata = _init_type(s, mfa_state, api_path)
    if not idata:
        _die(f"无法初始化「{label}」（可能未绑定）")
    gid = idata.get("gid")
    attest = idata.get("attestServerUrl")
    target = idata.get(target_key)
    if not gid or not attest:
        _die(f"initByType 缺少 gid/attestServerUrl: {json.dumps(idata, ensure_ascii=False)[:200]}")

    sr = s.post(f"{attest}/api/guard/{api_path}/send", json={"gid": gid}, timeout=25)
    try:
        sj = sr.json()
    except ValueError:
        sj = {}
    if (sj or {}).get("code") != 0:
        hint = ((sj or {}).get("data") or {}).get("result", "")
        _die(f"发送验证码失败{('（' + str(hint) + '）') if hint else ''}: "
             f"{json.dumps(sj, ensure_ascii=False)[:200]}")

    sent_at = time.time()
    state = {
        "created_at": sent_at, "type": args.type, "api_path": api_path,
        "gid": gid, "attest": attest, "mfa_state": mfa_state,
        "execution": execution, "fp": fp, "enc_pwd": enc_pwd,
        "account": account, "trust": not args.no_trust, "cookies": _dump_cookies(s),
    }
    _save_state(state)

    print(f"✅ 验证码已发送到 {label}: {_mask(target or '')}")

    if not args.wait_mail:
        print(f"   请在约 {MFA_TTL_SEC // 60} 分钟内执行："
              f" .venv/bin/python scripts/mfa_login.py verify --code 验证码")
        return 0

    # 自动从安全邮箱读码（需要邮箱与 mail_mfa/mail 配置一致且开启 IMAP）
    mail_cfg = _resolve_mail_mfa(cfg)
    if not mail_cfg.get("user") or not mail_cfg.get("password"):
        print("⚠️  mail_mfa / mail 里没有邮箱与授权码，无法自动读码，请手动 verify --code")
        return 3
    timeout = float(args.mail_timeout or mail_cfg.get("timeout_sec") or 180)
    print(f"   ⏳ 正在从 {_mask(str(mail_cfg['user']))} 读取验证码（最多 {int(timeout)}s）…")
    code = read_mfa_code_from_mailbox(mail_cfg, since_ts=sent_at, timeout_sec=timeout)
    if not code:
        print("⚠️  未能自动读到验证码：请手动执行 verify --code 六位验证码")
        return 3
    if not _validate_code(s, state, code):
        print("❌ 自动读到的验证码校验未通过，请手动 verify --code")
        return 1
    return _complete(state, s)


def _validate_code(s, state: dict, code: str) -> bool:
    """把验证码交给 CAS 校验；返回是否通过（通过后表单提交才算登录）。"""
    vr = s.post(f"{state['attest']}/api/guard/{state['api_path']}/valid",
                json={"gid": state["gid"], "code": code}, timeout=25)
    try:
        vj = vr.json()
    except ValueError:
        _die(f"校验返回非 JSON: {(vr.text or '')[:160]}")

    vdata = (vj or {}).get("data") or {}
    if (vj or {}).get("code") != 0 or str(vdata.get("status")) != "2":
        print(f"❌ 验证码校验未通过: {json.dumps(vj, ensure_ascii=False)[:200]}", file=sys.stderr)
        print("   状态文件已保留，可直接重试；或用 start 重新获取验证码。", file=sys.stderr)
        print("   注意：连续失败会触发账号锁定（约 10 分钟），请勿反复试错。", file=sys.stderr)
        return False
    print("✅ 二次认证通过")
    return True


def _complete(state: dict, s) -> int:
    """验证通过之后：提交 CAS 登录 → register.do 取 token → 清理状态文件。"""
    cfg = _load_cfg()
    client = _finish_login(s, cfg, state["fp"], state["execution"], state["enc_pwd"],
                          state["mfa_state"], bool(state.get("trust", True)), state["account"])
    _verify_result(client, cfg)

    if state.get("trust"):
        print("🔐 已登记为「可信客户端」：后续动态策略默认跳过二次认证，监控可自动重登。")
    try:
        STATE_FILE.unlink()
    except OSError:
        pass
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    state = _load_state()
    code = (args.code or "").strip()
    if not code and not sys.stdin.isatty():
        code = sys.stdin.read().strip()
    if not code:
        _die("缺少验证码：--code 123456")

    age = time.time() - float(state.get("created_at") or 0)
    if age > MFA_TTL_SEC:
        print(f"⚠️  待验证状态已 {int(age)}s，验证码可能已过期（必要时重新 start）")

    s = _restore_http(state)
    if not _validate_code(s, state, code):
        return 1
    return _complete(state, s)


def cmd_auto(args: argparse.Namespace) -> int:
    """无人值守：仅在不需要二次认证时完成登录，否则退出码 3。"""
    cfg = _load_cfg()
    s, fp, execution, enc_pwd, account, data = _open_login(cfg)

    if data.get("need"):
        print("mfa-required: 需要二次认证，请人工执行 start + verify")
        return 3

    client = _finish_login(s, cfg, fp, execution, enc_pwd, data.get("state") or "",
                          not args.no_trust, account)
    _verify_result(client, cfg)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if not STATE_FILE.exists():
        print("没有待验证状态（.mfa_state.json 不存在）")
        return 0
    st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    age = time.time() - float(st.get("created_at") or 0)
    label = MFA_TYPES.get(st.get("type", ""), ("", "", st.get("type", "?"), ""))[2]
    print(f"待验证方式: {label}  已等待: {int(age)}s  "
          f"可能过期: {'是' if age > MFA_TTL_SEC else '否'}")
    return 0


def _verify_result(client: XkfwClient, cfg: dict) -> None:
    """登录后自检：探活 + 查一轮容量，确认监控真的能跑。"""
    print(f"   会话探活: {'正常' if client.is_alive() else '异常'}")
    for item in cfg.get("courses") or []:
        tcid = str(item.get("teaching_class_id") or "").strip()
        if not tcid:
            continue
        name = item.get("name") or tcid
        try:
            has_room, selected, capacity = client.check_capacity(tcid)
            print(f"   [{name}] {'有空位' if has_room else '仍满'} {selected}/{capacity}")
        except Exception as e:  # noqa: BLE001
            print(f"   [{name}] 容量查询失败: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="XJTU xkfw 会话续期（含二次认证 / 可信客户端）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="只读诊断：是否需要二次认证、可用方式与目标号码")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("start", help="触发安全验证并保存会话状态")
    p.add_argument("--type", default="securephone", choices=sorted(MFA_TYPES),
                   help="验证方式（默认 securephone 安全手机）")
    p.add_argument("--no-trust", action="store_true", help="不登记为可信客户端")
    p.add_argument("--wait-mail", action="store_true",
                   help="发码后自动从安全邮箱读码并完成登录（需 --type secureemail）")
    p.add_argument("--mail-timeout", type=float, default=0.0,
                   help="等待邮件的秒数（默认 180）")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("verify", help="用验证码完成登录并写入 session.json")
    p.add_argument("--code", default="", help="验证码（也可从 stdin 传入）")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("auto", help="无人值守续期（需要二次认证时退出码 3）")
    p.add_argument("--no-trust", action="store_true", help="不登记为可信客户端")
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("status", help="查看待验证状态")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
