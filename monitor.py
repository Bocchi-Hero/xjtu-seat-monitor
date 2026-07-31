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
from notifier import send_webhook

ROOT = Path(__file__).resolve().parent


def _edge_trigger(has_room: bool, prev: bool | None) -> bool:
    """边沿触发：从「无空位/未知」→「有空位」才返回 True（首次即有空位也提醒）。"""
    return bool(has_room and (prev is False or prev is None))


def _remind_due(since: float, last_remind: float, now: float, remind_min: float) -> bool:
    """空位持续提醒判定：空位已保持 remind_min 分钟，且距上次补发也超过 remind_min。

    remind_min<=0 表示关闭该功能。
    """
    if remind_min <= 0 or since <= 0:
        return False
    interval = remind_min * 60
    return (now - since) >= interval and (now - last_remind) >= interval


def _acquire_singleton() -> Any:
    """单实例互斥：防止 panel 与 systemd 同时跑两个 monitor 重复发信。

    返回持有文件锁的文件句柄；锁随进程退出自动释放。
    拿不到锁说明已有实例在跑，直接退出。
    """
    lock_path = ROOT / "monitor.lock"
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        import fcntl  # POSIX

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:  # Windows
        try:
            import msvcrt

            fh.seek(0)
            if fh.tell() == 0:
                fh.write("lock")
                fh.flush()
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            raise SystemExit("已有 monitor 实例在运行（monitor.lock 被占用），退出避免重复发信")
    except OSError:
        fh.close()
        raise SystemExit("已有 monitor 实例在运行（monitor.lock 被占用），退出避免重复发信")
    return fh


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
    webhook_cfg = cfg.get("webhook") or {}
    if args.test_mail:
        send_mail(
            mail_cfg,
            "[选课监控] 测试邮件",
            "若你收到这封信，说明 Gmail/QQ SMTP 配置正确。\n",
        )
        log.info("测试邮件已发送 → %s", mail_cfg.get("to_addr") or mail_cfg.get("from_addr"))
        wb = cfg.get("webhook") or {}
        if (wb.get("url") or "").strip():
            ok = send_webhook(wb, "[选课监控] 测试推送", "若你收到这条推送，说明 webhook 配置正确。")
            log.info("测试 webhook 推送: %s", "成功" if ok else "失败")
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
        _notify_auth_fail(mail_cfg, str(e), webhook_cfg)
        sys.exit(2)
    except CaptchaRequired as e:
        log.error("%s", e)
        _notify_auth_fail(mail_cfg, str(e), webhook_cfg)
        sys.exit(2)
    except SessionError as e:
        # 临时故障(如 register.do 空壳)不退出：主循环的保活/恢复逻辑会持续重试，
        # 恢复后自动继续监控；若为永久故障，主循环的掉线通知会兜底提醒
        log.warning("启动时会话校验失败(临时故障?): %s，继续启动，后台自动重试", e)

    if args.login_only:
        log.info("登录完成，session 已保存。可部署到服务器跑 python monitor.py")
        return

    # 单实例互斥：systemd / panel 双跑时后启动者直接退出，避免重复发信
    # （--login-only 豁免：它只写 session.json，与监控实例并发无害）
    _lock_handle = _acquire_singleton()

    interval = float(cfg.get("poll_interval_sec") or 20)
    jitter = float(cfg.get("poll_jitter_sec") or 5)
    cooldown = float(cfg.get("alert_cooldown_sec") or 600)
    check_every = int(cfg.get("session_check_every") or 50)
    # 登录掉线邮件冷却，避免每 2 分钟刷信（默认 1 小时）
    session_fail_cooldown = float(cfg.get("session_fail_cooldown_sec") or 3600)
    # 空位持续提醒：0=关闭；>0 时空位保持 N 分钟补发一封（可配）
    remind_min = float(cfg.get("respot_remind_min") or 0)

    # state: last has_room, last alert time
    last_room: dict[str, bool] = {}
    last_alert_at: dict[str, float] = {}
    room_since: dict[str, float] = {}      # 空位开始时间（持续提醒用）
    last_remind_at: dict[str, float] = {}  # 上次「持续提醒」时间
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
        if _notify_auth_fail(mail_cfg, detail, webhook_cfg):
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
            now = time.time()

            # 空位持续提醒：空位保持 remind_min 分钟没人抢时周期补发（可配）
            if has_room:
                if prev is not True:
                    room_since[tcid] = now
                if _remind_due(room_since.get(tcid, 0), last_remind_at.get(tcid, 0), now, remind_min):
                    last_remind_at[tcid] = now
                    r_subject = f"[选课空位-持续] {name} {status}"
                    r_body = (
                        f"课程: {name}\n"
                        f"教学班: {tcid}\n"
                        f"容量: {selected} / {capacity}\n"
                        f"空位已持续 {remind_min} 分钟，仍未满。\n"
                        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"可能没人注意到，请尽快处理。\n"
                    )
                    try:
                        send_mail(mail_cfg, r_subject, r_body)
                        send_webhook(webhook_cfg, r_subject, r_body)
                        log.info("已发持续提醒: %s", r_subject)
                    except Exception as e:  # noqa: BLE001
                        log.error("持续提醒发信失败: %s", e)
            else:
                room_since.pop(tcid, None)
                last_remind_at.pop(tcid, None)

            if has_room:
                log.info("[%s] 有空位 %s  id=%s", name, status, tcid)
            else:
                # log full status every 5 rounds (~100s) to prove polling works
                if round_i == 1 or round_i % 5 == 0:
                    log.info("[%s] 仍满 %s", name, status)
                else:
                    log.debug("[%s] 满 %s", name, status)

            # 边沿触发：从无空位/未知 → 有空位；或首次即有空位也提醒一次
            edge = _edge_trigger(has_room, prev)
            if not edge:
                continue

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
                send_webhook(webhook_cfg, subject, body)
                last_alert_at[tcid] = now
                log.info("已发邮件: %s", subject)
            except Exception as e:  # noqa: BLE001
                log.error("发信失败: %s", e)

        if args.once:
            break

        sleep_s = max(3.0, interval + random.uniform(-jitter, jitter))
        time.sleep(sleep_s)


def _notify_auth_fail(mail_cfg: dict[str, Any], detail: str, webhook_cfg: dict[str, Any] | None = None) -> bool:
    """Send session-dead email (+webhook). Returns True if send_mail succeeded."""
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
        send_webhook(webhook_cfg or {}, "[选课监控] 登录已掉线", f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n详情: {detail}")
        return True
    except Exception as e:  # noqa: BLE001
        logging.getLogger("seat-monitor").error("掉线通知发信失败: %s", e)
        return False


if __name__ == "__main__":
    main()
