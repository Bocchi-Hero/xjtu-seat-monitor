#!/usr/bin/env python3
"""End-to-end check: session → real capacity → simulated drop emails."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yaml

from auth_session import XkfwClient  # noqa: E402
from mailer import send_mail  # noqa: E402

ROOT = _ROOT


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    mail_cfg = cfg.get("mail") or {}
    courses = cfg.get("courses") or []
    if len(courses) < 1:
        print("config.courses 为空")
        return 1

    print("=== 1) 会话 ===")
    client = XkfwClient(str(ROOT / (cfg.get("session_file") or "session.json")))
    account = str(cfg.get("account") or "")
    password = str(cfg.get("password") or "")
    try:
        client.ensure_session(account, password)
    except Exception as e:
        print(f"会话失败: {e}")
        return 2
    print(f"OK student={client.student_code} token={client.token[:12]}…")

    print("\n=== 2) 真实容量查询 ===")
    real = []
    for item in courses:
        name = item.get("name") or item.get("teaching_class_id")
        tcid = str(item.get("teaching_class_id") or "")
        try:
            has_room, selected, capacity = client.check_capacity(tcid)
            real.append((name, tcid, has_room, selected, capacity))
            flag = "有空位" if has_room else "满"
            print(f"  [{flag}] {name}: {selected}/{capacity}  id={tcid}")
        except Exception as e:
            print(f"  [失败] {name}: {e}")
            return 3

    print("\n=== 3) 模拟有人退课 → 发邮件 ===")
    print("（不改学校数据，只走与监控相同的发信路径）")
    for name, tcid, has_room, selected, capacity in real:
        # 模拟：满员时假装少 1 人出现空位
        sim_selected = max(0, selected - 1) if not has_room else selected
        sim_cap = capacity if capacity > 0 else 24
        subject = f"[选课空位·模拟测试] {name} {sim_selected}/{sim_cap}"
        body = (
            f"【这是模拟退课测试，不是真实空位】\n\n"
            f"课程: {name}\n"
            f"教学班: {tcid}\n"
            f"真实容量: {selected}/{capacity}（当前实际仍可能是满的）\n"
            f"模拟空位: {sim_selected}/{sim_cap}\n"
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"若收到此信，说明：会话查询 + QQ 邮件 整条链路正常。\n"
            f"正式监控发现真空位时，主题为 [选课空位] 且无「模拟测试」字样。\n"
        )
        try:
            send_mail(mail_cfg, subject, body)
            print(f"  已发送: {subject}")
        except Exception as e:
            print(f"  发信失败: {e}")
            return 4

    print("\n=== 完成 ===")
    print(f"请查 QQ 邮箱 {mail_cfg.get('to_addr')}（含垃圾箱），应有 {len(real)} 封模拟测试信。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
