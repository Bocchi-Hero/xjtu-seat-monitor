"""Shared helpers for the web control panel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from auth_session import (
    CaptchaRequired,
    MFARequired,
    SessionError,
    XkfwClient,
)
from mailer import send_mail

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
PID_PATH = ROOT / "monitor.pid"


def load_cfg() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        example = ROOT / "config.example.yaml"
        if example.exists():
            CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("courses", [])
    data.setdefault("mail", {})
    data.setdefault("poll_interval_sec", 20)
    data.setdefault("poll_jitter_sec", 5)
    data.setdefault("alert_cooldown_sec", 600)
    data.setdefault("respot_remind_min", 0)
    data.setdefault("webhook", {"enabled": True, "url": ""})
    data.setdefault("session_file", "session.json")
    data.setdefault("log_file", "monitor.log")
    return data


def save_cfg(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Config for UI — secrets masked."""
    mail = dict(cfg.get("mail") or {})
    mail_pw = mail.get("password") or ""
    mail["password"] = ""
    mail["password_set"] = bool(mail_pw)
    return {
        "account": cfg.get("account") or "",
        "password": "",
        "password_set": bool(cfg.get("password")),
        "student_code": cfg.get("student_code") or "",
        "courses": cfg.get("courses") or [],
        "poll_interval_sec": cfg.get("poll_interval_sec", 20),
        "poll_jitter_sec": cfg.get("poll_jitter_sec", 5),
        "alert_cooldown_sec": cfg.get("alert_cooldown_sec", 600),
        "respot_remind_min": cfg.get("respot_remind_min", 0),
        "webhook": {"enabled": bool((cfg.get("webhook") or {}).get("enabled", True)), "url": (cfg.get("webhook") or {}).get("url", "")},
        "mail": mail,
    }


def merge_config_update(body: dict[str, Any]) -> dict[str, Any]:
    cfg = load_cfg()
    if "account" in body:
        cfg["account"] = str(body.get("account") or "").strip()
    if "password" in body and body["password"] is not None:
        # 允许传空串清空已存密码（UI 未填时不应误清，前端不传该字段即可）
        cfg["password"] = str(body["password"])
    if "student_code" in body:
        cfg["student_code"] = str(body.get("student_code") or "").strip()
    if "courses" in body and isinstance(body["courses"], list):
        courses = []
        for c in body["courses"]:
            if not isinstance(c, dict):
                continue
            tid = str(c.get("teaching_class_id") or "").strip()
            if not tid:
                continue
            courses.append(
                {
                    "name": str(c.get("name") or tid).strip(),
                    "teaching_class_id": tid,
                }
            )
        cfg["courses"] = courses
    for k in ("poll_interval_sec", "poll_jitter_sec", "alert_cooldown_sec", "respot_remind_min"):
        if k in body and body[k] is not None:
            try:
                cfg[k] = int(body[k])
            except (TypeError, ValueError):
                pass
    if "webhook" in body and isinstance(body["webhook"], dict):
        wh = dict(cfg.get("webhook") or {})
        w = body["webhook"]
        if "url" in w:
            wh["url"] = str(w["url"] or "").strip()
        if "enabled" in w:
            wh["enabled"] = bool(w["enabled"])
        cfg["webhook"] = wh
    if "mail" in body and isinstance(body["mail"], dict):
        mail = dict(cfg.get("mail") or {})
        m = body["mail"]
        for key in ("enabled", "provider", "from_addr", "to_addr", "host", "port", "use_ssl"):
            if key in m:
                mail[key] = m[key]
        if "password" in m and m["password"] is not None:
            mail["password"] = str(m["password"])
        if "enabled" in m:
            mail["enabled"] = bool(m["enabled"])
        cfg["mail"] = mail
    save_cfg(cfg)
    return cfg


def session_info(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_cfg()
    client = XkfwClient(str(ROOT / (cfg.get("session_file") or "session.json")))
    alive = False
    try:
        alive = client.is_alive()
    except Exception:
        alive = False
    return {
        "alive": alive,
        "student_code": client.student_code or cfg.get("student_code") or "",
        "token_preview": (client.token[:12] + "…") if client.token else "",
        "has_token": bool(client.token),
        "session_file": cfg.get("session_file") or "session.json",
    }


def do_login(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_cfg()
    client = XkfwClient(str(ROOT / (cfg.get("session_file") or "session.json")))
    account = str(cfg.get("account") or "")
    password = str(cfg.get("password") or "")
    if not account or not password:
        return {"ok": False, "error": "请先在面板填写学号/账号和密码并保存"}
    try:
        client.ensure_session(account, password)
        return {
            "ok": True,
            "student_code": client.student_code,
            "alive": client.is_alive(),
        }
    except MFARequired as e:
        return {"ok": False, "error": f"需要 MFA：{e}。请浏览器登录后导出 session，或本机完成二次验证。"}
    except CaptchaRequired as e:
        return {"ok": False, "error": f"需要验证码：{e}"}
    except SessionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def check_capacities(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_cfg()
    client = XkfwClient(str(ROOT / (cfg.get("session_file") or "session.json")))
    try:
        if not client.is_alive():
            client.ensure_session(str(cfg.get("account") or ""), str(cfg.get("password") or ""))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"会话无效: {e}", "courses": []}

    rows = []
    for c in cfg.get("courses") or []:
        name = c.get("name") or c.get("teaching_class_id")
        tid = str(c.get("teaching_class_id") or "")
        try:
            has_room, selected, capacity = client.check_capacity(tid)
            rows.append(
                {
                    "name": name,
                    "teaching_class_id": tid,
                    "has_room": has_room,
                    "selected": selected,
                    "capacity": capacity,
                    "status": "有空位" if has_room else "已满",
                    "error": None,
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "name": name,
                    "teaching_class_id": tid,
                    "has_room": False,
                    "selected": None,
                    "capacity": None,
                    "status": "查询失败",
                    "error": str(e),
                }
            )
    return {"ok": True, "courses": rows, "checked_at": time.strftime("%H:%M:%S")}


def _pid_alive(pid: int) -> bool:
    """Return True if process id exists (any process)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
            )
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            # tasklist fallback
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    text=True,
                    errors="ignore",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return str(pid) in out and "No tasks" not in out and "没有" not in out
            except Exception:
                return False
    try:
        # Linux: 校验 cmdline 里确为 monitor.py，防 PID 被系统回收复用后误判"在运行"
        if sys.platform != "win32":
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "ignore")
                if "monitor.py" not in cmd:
                    return False
            except OSError:
                return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_monitor_pids() -> list[int]:
    """Find running monitor.py PIDs without relying on deprecated wmic."""
    pids: list[int] = []

    # 1) pid file (most reliable after we start it)
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            if _pid_alive(pid):
                pids.append(pid)
        except ValueError:
            pass

    # 2) PowerShell / CIM (Windows) — wmic is removed on many Win11 installs
    if sys.platform == "win32":
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
                "| Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    ps,
                ],
                text=True,
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).strip()
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for row in data or []:
                    cmd = str(row.get("CommandLine") or "")
                    if "monitor.py" in cmd and "panel_app" not in cmd:
                        try:
                            pids.append(int(row["ProcessId"]))
                        except (KeyError, TypeError, ValueError):
                            pass
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["ps", "aux"], text=True, errors="ignore")
            for line in out.splitlines():
                if "monitor.py" in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) > 1 and parts[1].isdigit():
                        pids.append(int(parts[1]))
        except Exception:
            pass

    return sorted(set(pids))


def monitor_running() -> dict[str, Any]:
    pids = find_monitor_pids()
    pid_file = None
    if PID_PATH.exists():
        try:
            pid_file = int(PID_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            pid_file = None
    # If pid file points to a live process, count as running even if CIM scan failed
    if pid_file and _pid_alive(pid_file) and pid_file not in pids:
        pids.append(pid_file)
        pids = sorted(set(pids))
    return {
        "running": len(pids) > 0,
        "pids": pids,
        "pid_file": pid_file,
    }


def start_monitor() -> dict[str, Any]:
    st = monitor_running()
    if st["running"]:
        return {"ok": True, "message": f"监控已在运行（PID {','.join(map(str, st['pids']))}）", **st}

    cfg = load_cfg()
    issues = []
    if not (cfg.get("account") and cfg.get("password")):
        issues.append("未保存选课账号密码")
    if not (cfg.get("courses")):
        issues.append("盯课列表为空")
    mail = cfg.get("mail") or {}
    if not (mail.get("from_addr") and mail.get("password")):
        issues.append("未配置邮箱授权码")
    sess = session_info(cfg)
    if not sess.get("alive"):
        issues.append("选课会话未登录或已过期（请先点「登录选课」）")
    if issues:
        return {
            "ok": False,
            "message": "还不能开始监控：" + "；".join(issues),
            "running": False,
            "pids": [],
            "pid_file": st.get("pid_file"),
            "blockers": issues,
        }

    stdout_path = ROOT / "monitor_stdout.log"
    stderr_path = ROOT / "monitor_stderr.log"
    log_out = open(stdout_path, "a", encoding="utf-8")
    log_err = open(stderr_path, "a", encoding="utf-8")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "monitor.py")],
            cwd=str(ROOT),
            stdout=log_out,
            stderr=log_err,
            creationflags=creationflags,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"无法启动监控进程：{e}", "running": False, "pids": [], "pid_file": None}

    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(1.0)

    # Primary check: child still alive (do not depend on wmic)
    alive = proc.poll() is None and _pid_alive(proc.pid)
    if alive:
        return {
            "ok": True,
            "message": f"监控已启动（PID {proc.pid}），有空位将发邮件提醒",
            "running": True,
            "pids": [proc.pid],
            "pid_file": proc.pid,
        }

    # Process exited immediately — read stderr tail
    err_tail = ""
    try:
        err_tail = stderr_path.read_text(encoding="utf-8", errors="ignore")[-500:]
    except OSError:
        pass
    msg = f"监控进程启动后立刻退出（PID {proc.pid}）"
    if err_tail.strip():
        msg += f"。详情：{err_tail.strip()[-200:]}"
    return {
        "ok": False,
        "message": msg,
        "running": False,
        "pids": [],
        "pid_file": proc.pid,
    }


def stop_monitor() -> dict[str, Any]:
    pids = find_monitor_pids()
    if PID_PATH.exists():
        try:
            pf = int(PID_PATH.read_text(encoding="utf-8").strip())
            if pf not in pids:
                pids.append(pf)
        except ValueError:
            pass
    pids = sorted(set(pids))
    killed = []
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.kill(pid, 15)
            killed.append(pid)
        except Exception:
            pass
    if PID_PATH.exists():
        try:
            PID_PATH.unlink()
        except OSError:
            pass
    time.sleep(0.3)
    st = monitor_running()
    if st["running"]:
        msg = f"仍有监控在运行：{st['pids']}"
    elif killed:
        msg = f"已停止监控（结束 PID {', '.join(map(str, killed))}）"
    else:
        msg = "当前没有正在运行的监控"
    return {"ok": not st["running"], "killed": killed, "message": msg, **st}


def read_logs(n: int = 80) -> list[str]:
    path = ROOT / (load_cfg().get("log_file") or "monitor.log")
    if not path.exists():
        path = ROOT / "monitor_stdout.log"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return lines[-n:]


def test_mail(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_cfg()
    mail = cfg.get("mail") or {}
    try:
        send_mail(
            mail,
            "[选课监控] 面板测试邮件",
            f"面板发信测试成功。\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        )
        return {"ok": True, "to": mail.get("to_addr") or mail.get("from_addr")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def search_catalog(keyword: str = "", limit: int = 50) -> list[dict[str, Any]]:
    path = ROOT / "courses_list.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    kw = (keyword or "").strip().lower()
    out = []
    for r in rows:
        if kw:
            blob = " ".join(
                [
                    str(r.get("course_name") or ""),
                    str(r.get("teacher") or ""),
                    str(r.get("teaching_class_id") or ""),
                    str(r.get("place") or ""),
                    str(r.get("type_name") or ""),
                ]
            ).lower()
            if kw not in blob:
                continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def build_checklist(cfg: dict[str, Any], sess: dict[str, Any], mon: dict[str, Any]) -> dict[str, Any]:
    """Step checklist for ordinary users — what is done / what to do next."""
    mail = cfg.get("mail") or {}
    courses = cfg.get("courses") or []
    has_account = bool(str(cfg.get("account") or "").strip() and str(cfg.get("password") or "").strip())
    has_mail = bool(
        str(mail.get("from_addr") or "").strip()
        and str(mail.get("password") or "").strip()
        and str(mail.get("to_addr") or mail.get("from_addr") or "").strip()
    )
    has_courses = len(courses) > 0
    session_ok = bool(sess.get("alive"))
    monitor_ok = bool(mon.get("running"))

    steps = [
        {
            "id": "account",
            "no": 1,
            "title": "填写并保存账号",
            "ok": has_account,
            "detail": "已保存选课账号" if has_account else "填写学号/统一认证账号和密码，点「保存配置」",
        },
        {
            "id": "mail",
            "no": 2,
            "title": "配置邮箱通知",
            "ok": has_mail,
            "detail": (
                f"将发到 {mail.get('to_addr') or mail.get('from_addr')}"
                if has_mail
                else "选 QQ/Gmail，填邮箱和「授权码」（不是登录密码），再保存"
            ),
        },
        {
            "id": "courses",
            "no": 3,
            "title": "添加要盯的课",
            "ok": has_courses,
            "detail": (
                f"已盯 {len(courses)} 门"
                if has_courses
                else "搜索课名加入，或手动填写教学班号后保存"
            ),
        },
        {
            "id": "login",
            "no": 4,
            "title": "登录选课系统",
            "ok": session_ok,
            "detail": (
                f"已登录，学号 {sess.get('student_code') or '—'}"
                if session_ok
                else ("会话可能过期，请重新登录" if sess.get("has_token") else "点「登录选课」完成登录")
            ),
        },
        {
            "id": "monitor",
            "no": 5,
            "title": "开始后台监控",
            "ok": monitor_ok,
            "detail": (
                f"监控运行中 PID {', '.join(map(str, mon.get('pids') or []))}"
                if monitor_ok
                else "前面都完成后，点「开始监控」；有空位会发邮件"
            ),
        },
    ]

    next_step = next((s for s in steps if not s["ok"]), None)
    all_ready = next_step is None
    if all_ready:
        next_action = {
            "code": "watching",
            "label": "一切就绪，正在盯课",
            "hint": "保持电脑不休眠；有空位时邮箱会收到「选课空位」主题邮件。可用「刷新容量」查看是否仍满。",
        }
    else:
        action_map = {
            "account": ("save", "去保存账号配置"),
            "mail": ("save", "去保存邮箱配置"),
            "courses": ("courses", "去添加盯课"),
            "login": ("login", "去登录选课"),
            "monitor": ("start", "去开始监控"),
        }
        code, label = action_map.get(next_step["id"], ("save", "继续设置"))
        next_action = {
            "code": code,
            "label": label,
            "hint": next_step["detail"],
            "step": next_step["no"],
            "step_title": next_step["title"],
        }

    return {
        "steps": steps,
        "done": sum(1 for s in steps if s["ok"]),
        "total": len(steps),
        "all_ready": all_ready,
        "next_action": next_action,
    }


def full_status(with_capacity: bool = False) -> dict[str, Any]:
    cfg = load_cfg()
    mon = monitor_running()
    sess = session_info(cfg)
    checklist = build_checklist(cfg, sess, mon)
    capacity = None
    if with_capacity and sess.get("alive") and (cfg.get("courses") or []):
        capacity = check_capacities(cfg)
    return {
        "config": public_config(cfg),
        "session": sess,
        "monitor": mon,
        "checklist": checklist,
        "capacity": capacity,
        "log_tail": read_logs(40),
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "catalog_ready": (ROOT / "courses_list.json").exists(),
        "catalog_count": _catalog_count(),
    }


def _catalog_count() -> int:
    path = ROOT / "courses_list.json"
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0
