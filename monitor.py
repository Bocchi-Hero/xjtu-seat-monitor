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
import logging.handlers
import random
import signal
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
        # 自动轮转：单文件最大 5MB，保留 3 个备份
        handlers.append(
            logging.handlers.RotatingFileHandler(
                ROOT / log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
        )
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
        # 临时故障(如 register.do 空壳)不退出：主循环的保活/恢复逻辑会持续重试，
        # 恢复后自动继续监控；若为永久故障，主循环的掉线通知会兜底提醒
        log.warning("启动时会话校验失败(临时故障?): %s，继续启动，后台自动重试", e)

    if args.login_only:
        log.info("登录完成，session 已保存。可部署到服务器跑 python monitor.py")
        return

    interval = float(cfg.get("poll_interval_sec") or 20)
    jitter = float(cfg.get("poll_jitter_sec") or 5)
    cooldown = float(cfg.get("alert_cooldown_sec") or 600)
    check_every = int(cfg.get("session_check_every") or 50)
    # 登录掉线邮件冷却，避免每 2 分钟刷信（默认 1 小时）
    session_fail_cooldown = float(cfg.get("session_fail_cooldown_sec") or 3600)

    # state: last has_room, last alert time
    last_room: dict[str, bool] = {}
    last_alert_at: dict[str, float] = {}
    last_session_fail_mail_at = 0.0
    session_ok = True
    consecutive_session_fails = 0
    round_i = 0
    shutdown = False

    def _handle_sig(signum: int, _frame: object) -> None:
        nonlocal shutdown
        sig_name = signal.Signals(signum).name
        log.info("收到 %s，优雅退出中…", sig_name)
        shutdown = True

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    def notify_session_dead(detail: str, *, force: bool = False) -> None:
        nonlocal last_session_fail_mail_at, session_ok
        session_ok = False
        now = time.time()
        if not force and now - last_session_fail_mail_at < session_fail_cooldown:
            log.warning("会话仍异常，邮件冷却中，跳过重复通知")
            return
        if _notify_auth_fail(mail_cfg, detail):
            last_session_fail_mail_at = now
            log.info("已发送「登录掉线」邮件")
        else:
            log.error("发送「登录掉线」邮件失败（请检查 SMTP 配置）")

    log.info(
        "开始监控 %d 门课 | 间隔≈%ss±%ss | 空位冷却=%ss | 掉线邮件冷却=%ss | mail=%s",
        len(courses),
        interval,
        jitter,
        cooldown,
        session_fail_cooldown,
        (mail_cfg.get("provider") or "?"),
    )

    while not shutdown:
        round_i += 1
        if round_i % check_every == 1:
            try:
                client.ensure_session(account, password)
                if not session_ok:
                    log.info("会话已恢复")
                session_ok = True
            except (SessionError, MFARequired, CaptchaRequired) as e:
                log.error("保活失败: %s", e)
                notify_session_dead(f"定期保活失败: {e}")
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

        session_error_this_round = False
        for item in courses:
            name = item.get("name") or item.get("teaching_class_id")
            tcid = str(item.get("teaching_class_id") or "").strip()
            if not tcid:
                continue
            try:
                has_room, selected, capacity = client.check_capacity(tcid)
            except SessionError as e:
                log.warning("[%s] 容量查询会话错误: %s", name, e)
                session_error_this_round = True
                consecutive_session_fails += 1
                try:
                    client.ensure_session(account, password)
                    session_ok = True
                    log.info("会话已自动恢复，继续监控")
                    # 已恢复 → 清零计数，不再发「掉线」邮件，避免恢复后误报
                    consecutive_session_fails = 0
                except Exception as e2:  # noqa: BLE001
                    log.error("重登失败: %s", e2)
                    # 连续多轮恢复失败才强制通知；单次抖动走邮件冷却即可
                    if consecutive_session_fails >= 3:
                        log.warning("连续 %d 轮 session 异常，强制发送掉线通知", consecutive_session_fails)
                        notify_session_dead(
                            f"查容量时会话失效，连续 {int(consecutive_session_fails)} 轮自动重登失败: {e2}",
                            force=True,
                        )
                        consecutive_session_fails = 0
                    else:
                        notify_session_dead(f"查容量时会话失效，自动重登失败: {e2}")
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] 查询异常: %s", name, e)
                continue

            # 成功查到容量 → 重置连续失败计数
            consecutive_session_fails = 0

            if not session_ok and not session_error_this_round:
                session_ok = True

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


def _notify_auth_fail(mail_cfg: dict[str, Any], detail: str) -> bool:
    """Send session-dead email. Returns True if send_mail succeeded."""
    if not mail_cfg.get("enabled", True):
        return False
    try:
        send_mail(
            mail_cfg,
            "[选课监控] 登录已掉线 — 请更新 session",
            (
                "服务器上的选课监控检测到登录会话失效，当前无法继续查空位。\n\n"
                f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"详情: {detail}\n\n"
                "请按下面做（有 MFA 必须在本机完成）：\n"
                "1. 本机打开面板或浏览器登录 xkfw，完成验证\n"
                "2. 确认生成/更新了 session.json\n"
                "3. 上传到服务器: /home/ubuntu/xjtu-seat-monitor/session.json\n"
                "4. 执行: sudo systemctl restart xjtu-seat-monitor\n\n"
                "监控进程仍会隔一段时间自动重试；会话恢复后会继续盯课。\n"
                "本类邮件默认约 1 小时最多提醒一次，避免刷屏。\n"
            ),
        )
        return True
    except Exception as e:  # noqa: BLE001
        logging.getLogger("seat-monitor").error("掉线通知发信失败: %s", e)
        return False


if __name__ == "__main__":
    main()
