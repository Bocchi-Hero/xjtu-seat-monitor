#!/usr/bin/env python3
"""Full pipeline self-check for seat monitor."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yaml

from auth_session import XkfwClient  # noqa: E402
from mailer import send_mail, resolve_smtp  # noqa: E402

ROOT = _ROOT


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    errors: list[str] = []
    lines: list[str] = []
    print("======== XJTU 选课监控 全流程自检 ========\n")

    # 1 config
    print("1) 配置文件")
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.exists():
        fail("缺少 config.yaml")
        return 1
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    courses = cfg.get("courses") or []
    mail_cfg = cfg.get("mail") or {}
    if len(courses) == 0:
        fail("课程数为 0，请先添加课程")
        errors.append("courses count")
    else:
        ok(f"盯课 {len(courses)} 门")
    for c in courses:
        tid = c.get("teaching_class_id") or ""
        if not tid or "XXXX" in tid:
            fail(f"无效班号: {c}")
            errors.append("bad class id")
        else:
            ok(f"{c.get('name')} → {tid}")
    if not mail_cfg.get("from_addr") or not mail_cfg.get("password"):
        fail("邮件账号/授权码缺失")
        errors.append("mail creds")
    else:
        smtp = resolve_smtp(mail_cfg)
        ok(f"邮件 {mail_cfg.get('provider')} → {mail_cfg.get('to_addr')} via {smtp['host']}:{smtp['port']}")

    # 2 session
    print("\n2) 登录会话")
    client = XkfwClient(str(ROOT / (cfg.get("session_file") or "session.json")))
    if not client.token:
        fail("无 token")
        errors.append("no token")
    else:
        ok(f"token 已加载 len={len(client.token)}")
    try:
        client.ensure_session(str(cfg.get("account") or ""), str(cfg.get("password") or ""))
        if client.is_alive():
            ok(f"会话存活 student={client.student_code}")
        else:
            fail("ensure 后仍不存活")
            errors.append("session dead")
    except Exception as e:
        fail(f"会话异常: {e}")
        errors.append(f"session: {e}")

    # 3 capacity
    print("\n3) 容量接口（真实）")
    cap_rows = []
    for c in courses:
        name = c.get("name")
        tid = str(c.get("teaching_class_id"))
        try:
            has_room, sel, cap = client.check_capacity(tid)
            cap_rows.append((name, tid, has_room, sel, cap))
            ok(f"{name}: {sel}/{cap} ({'有空位' if has_room else '满'})")
        except Exception as e:
            fail(f"{name}: {e}")
            errors.append(f"capacity {tid}")

    # 4 monitor process
    print("\n4) 后台监控进程")
    mon_ok = False
    pid_file = ROOT / "monitor.pid"
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
    # find by command line
    try:
        import subprocess

        out = subprocess.check_output(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            text=True,
            errors="ignore",
        )
        running_pids = []
        for line in out.splitlines():
            if "monitor.py" in line and "-u" in line or ( "monitor.py" in line):
                parts = line.strip().split()
                for p in parts[::-1]:
                    if p.isdigit():
                        running_pids.append(int(p))
                        break
        # simpler: tasklist style via PowerShell not available — parse wmic
        for line in out.splitlines():
            if "monitor.py" in line.lower():
                mon_ok = True
                # extract last number-like token
                nums = [t for t in line.replace('"', " ").split() if t.isdigit()]
                if nums:
                    pid = int(nums[-1])
                ok(f"monitor.py 在运行 pid≈{pid or nums}")
                break
        if not mon_ok:
            fail("未发现 monitor.py 进程")
            errors.append("monitor not running")
    except Exception as e:
        # fallback: try OpenProcess
        if pid:
            try:
                os.kill(pid, 0)  # may fail on Windows
            except OSError:
                pass
            try:
                import ctypes

                k = ctypes.windll.kernel32
                h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    k.CloseHandle(h)
                    mon_ok = True
                    ok(f"PID {pid} 进程存在")
                else:
                    fail(f"PID {pid} 不存在")
                    errors.append("monitor dead")
            except Exception as e2:
                fail(f"无法确认进程: {e} / {e2}")
                errors.append("monitor check fail")
        else:
            fail(f"进程检查失败: {e}")
            errors.append("monitor check fail")

    log_path = ROOT / (cfg.get("log_file") or "monitor.log")
    if log_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-8:]
        ok(f"日志 {log_path.name} 末行:")
        for t in tail:
            print(f"      {t}")
    else:
        fail("无 monitor.log")
        errors.append("no log")

    # 5 mail
    print("\n5) 邮件自检")
    status = "全部通过" if not errors else f"有问题: {', '.join(errors)}"
    body = (
        f"选课空位监控 — 全流程自检报告\n"
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"结果: {status}\n\n"
        f"学号: {client.student_code}\n"
        f"会话: {'存活' if client.is_alive() else '异常'}\n"
        f"监控进程: {'运行中' if mon_ok else '未运行'} pid={pid}\n\n"
        f"盯课容量:\n"
    )
    for name, tid, has_room, sel, cap in cap_rows:
        body += f"  - {name}\n    {tid}\n    {sel}/{cap} ({'有空' if has_room else '满'})\n"
    body += (
        f"\n说明: 此信仅自检。真空位通知主题为 [选课空位]，无「自检」字样。\n"
    )
    try:
        send_mail(
            mail_cfg,
            f"[选课监控·自检] {status}",
            body,
        )
        ok(f"自检邮件已发送 → {mail_cfg.get('to_addr')}")
    except Exception as e:
        fail(f"发信失败: {e}")
        errors.append(f"mail: {e}")

    print("\n======== 汇总 ========")
    if errors:
        print("未完全通过:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("全部通过：配置 / 会话 / 容量 / 监控进程 / 邮件")
    print("真空位时将自动发 [选课空位] 邮件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
