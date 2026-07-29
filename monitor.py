#!/usr/bin/env python3
"""
XJTU 选课空位监控：轮询 capacity.do，有人退课出现空位时发邮件（Gmail / QQ）。

用法:
  1. pip install -r requirements.txt
  2. copy config.example.yaml → config.yaml 并填写
  3. 本机先登录一次（或填好账号让脚本尝试 CAS）:
       python monitor.py --login-only
  4. 通宵 / 服务器:
       python monitor.py
  5. 测邮件:
       python monitor.py --test-mail
"""

from __future__ import annotations

import argparse
import logging
import random
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


def setup_log(log_file: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(ROOT / log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"缺少配置文件: {path}\n请复制 config.example.yaml 为 config.yaml")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    ap = argparse.ArgumentParser(description="XJTU 选课空位邮件监控")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--login-only", action="store_true", help="只登录并保存 session")
    ap.add_argument("--test-mail", action="store_true", help="发送一封测试邮件后退出")
    ap.add_argument("--once", action="store_true", help="只查一轮容量后退出")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    setup_log(cfg.get("log_file") or "monitor.log")
    log = logging.getLogger("seat-monitor")

    mail_cfg = cfg.get("mail") or {}
    if args.test_mail:
        send_mail(
            mail_cfg,
            "[选课监控] 测试邮件",
            "若你收到这封信，说明 Gmail/QQ SMTP 配置正确。\n",
        )
        log.info("测试邮件已发送 → %s", mail_cfg.get("to_addr") or mail_cfg.get("from_addr"))
        return

    account = str(cfg.get("account") or "")
    password = str(cfg.get("password") or "")
    courses = cfg.get("courses") or []
    if not courses:
        log.error("config 里 courses 为空")
        sys.exit(1)

    client = XkfwClient(session_file=str(ROOT / (cfg.get("session_file") or "session.json")))
    if cfg.get("student_code") and not client.student_code:
        client.student_code = str(cfg["student_code"])

    try:
        client.ensure_session(account, password)
    except MFARequired as e:
        log.error("%s", e)
        log.error("服务器无交互 MFA 时：请在本机浏览器登录 xkfw，导出 token 到 session.json，再上传服务器。")
        _notify_auth_fail(mail_cfg, str(e))
        sys.exit(2)
    except CaptchaRequired as e:
        log.error("%s", e)
        _notify_auth_fail(mail_cfg, str(e))
        sys.exit(2)
    except SessionError as e:
        log.error("会话失败: %s", e)
        _notify_auth_fail(mail_cfg, str(e))
        sys.exit(2)

    if args.login_only:
        log.info("登录完成，session 已保存。可部署到服务器跑 python monitor.py")
        return

    interval = float(cfg.get("poll_interval_sec") or 20)
    jitter = float(cfg.get("poll_jitter_sec") or 5)
    cooldown = float(cfg.get("alert_cooldown_sec") or 600)
    check_every = int(cfg.get("session_check_every") or 50)

    # state: last has_room, last alert time
    last_room: dict[str, bool] = {}
    last_alert_at: dict[str, float] = {}
    round_i = 0

    log.info(
        "开始监控 %d 门课 | 间隔≈%ss±%ss | 冷却=%ss | mail=%s",
        len(courses),
        interval,
        jitter,
        cooldown,
        (mail_cfg.get("provider") or "?"),
    )

    while True:
        round_i += 1
        if round_i % check_every == 1:
            try:
                client.ensure_session(account, password)
            except (SessionError, MFARequired, CaptchaRequired) as e:
                log.error("保活失败: %s", e)
                _notify_auth_fail(mail_cfg, f"监控中会话失效: {e}")
                # 通宵场景：等一会儿再试，避免 MFA 死循环狂登
                time.sleep(120)
                continue

        # heartbeat every round so we can confirm the loop is alive
        if round_i == 1 or round_i % 5 == 0:
            log.info("心跳 round=%d 监控中…", round_i)
            for h in logging.getLogger().handlers:
                try:
                    h.flush()
                except Exception:  # noqa: BLE001
                    pass

        for item in courses:
            name = item.get("name") or item.get("teaching_class_id")
            tcid = str(item.get("teaching_class_id") or "").strip()
            if not tcid:
                continue
            try:
                has_room, selected, capacity = client.check_capacity(tcid)
            except SessionError as e:
                log.warning("[%s] 容量查询会话错误: %s", name, e)
                try:
                    client.ensure_session(account, password)
                except Exception as e2:  # noqa: BLE001
                    log.error("重登失败: %s", e2)
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] 查询异常: %s", name, e)
                continue

            prev = last_room.get(tcid)
            last_room[tcid] = has_room
            status = f"{selected}/{capacity}"
            if has_room:
                log.info("[%s] 有空位 %s  id=%s", name, status, tcid)
            else:
                # log full status every 5 rounds (~100s) to prove polling works
                if round_i == 1 or round_i % 5 == 0:
                    log.info("[%s] 仍满 %s", name, status)
                else:
                    log.debug("[%s] 满 %s", name, status)

            # 边沿触发：从无空位/未知 → 有空位；或首次即有空位也提醒一次
            edge = has_room and (prev is False or prev is None)
            if not edge:
                continue

            now = time.time()
            if now - last_alert_at.get(tcid, 0) < cooldown:
                log.info("[%s] 空位中，但仍在冷却期内，跳过邮件", name)
                continue

            subject = f"[选课空位] {name} {status}"
            body = (
                f"课程: {name}\n"
                f"教学班: {tcid}\n"
                f"容量: {selected} / {capacity}\n"
                f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"有人退课或出现空位。请尽快登录选课系统或打开 Course Genius 抢课。\n"
                f"空位可能很快被占满，本邮件仅作提醒。\n"
            )
            try:
                send_mail(mail_cfg, subject, body)
                last_alert_at[tcid] = now
                log.info("已发邮件: %s", subject)
            except Exception as e:  # noqa: BLE001
                log.error("发信失败: %s", e)

        if args.once:
            break

        sleep_s = max(3.0, interval + random.uniform(-jitter, jitter))
        time.sleep(sleep_s)


def _notify_auth_fail(mail_cfg: dict[str, Any], detail: str) -> None:
    if not mail_cfg.get("enabled", True):
        return
    try:
        send_mail(
            mail_cfg,
            "[选课监控] 会话/登录失败",
            f"监控脚本无法维持选课会话，已暂停有效查询。\n\n详情:\n{detail}\n\n"
            "请本机重新 login 或更新 session.json 后重启。\n",
        )
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
