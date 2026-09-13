# Changelog

All notable changes to this project will be documented in this file.

## [0.3.1] - 2026-09-13

### Fixed

- **False session recovery — the monitor could sit in a silent dead loop.**
  `ensure_session()` accepted "recovered" as soon as `register.do` (token refresh) and
  `dictionary.do` (liveness probe) both succeeded. But xkfw keeps a separate
  server-side login state (app session, `JSESSIONID`/`GS_SESSIONID`): once that is
  gone, `register.do` still hands out a token that `capacity.do` rejects with
  `未查询到登录信息` ("no login info found"). Observed live: the monitor logged
  "会话已自动恢复" every ~15s while every capacity query kept failing — no alerts sent,
  no courses actually monitored. Only a full CAS login (fresh app-session cookies)
  restores it.
  - `ensure_session(account, password, verify_tcid="")` now verifies against the
    **operational** API: it makes one real `capacity.do` call for a configured course
    and escalates to a full CAS login when the token is rejected.
  - New `TokenRejected(SessionError)` separates "token not accepted" from transient API
    noise (empty shell / network glitches), so a peak-time empty shell cannot trigger a
    login storm.
  - `monitor.py` and `panel_service.py` pass the verification course (`verify_tcid`) at
    every `ensure_session()` call site.

- **`_try_register()` had no retry.** `register.do` intermittently returns the empty
  shell `{"data":null,"code":null}` for minutes at a time; because each candidate was
  tried only once, one flaky window made `full_login()` give up with
  "无法解析 CAS execution，页面可能已变" instead of recovering. It now retries the same
  way `refresh_token()` does (3 rounds × 3 candidates, 1.5s apart).

### Added

- Regression tests for the false-recovery path (`tests/test_auth_session.py`): a
  rejected token must force a full login, an empty shell must not, and a healthy
  session must not trigger one either.

## [0.3.0] - 2026-09-13

### Added

- **Session renewal tool `scripts/mfa_login.py` (two-factor auth / trusted client).**
  XJTU CAS uses a *dynamic* MFA strategy: a new device or a long-idle account is asked
  for a second factor (secure-phone SMS / secure-email code). On a headless server
  nobody can read that code, so re-login always failed — this is the real root cause
  behind "expired token needs manual fixing". The tool covers the whole chain:
  - `probe` — read-only: whether MFA is required, which methods are available, and the
    masked phone/email the code would be sent to;
  - `start` / `start --type securephone|secureemail` — trigger the verification and
    persist the pending session state (`.mfa_state.json`, mode 0600);
  - `verify --code` — finish the login and write `session.json`;
  - `start --wait-mail` — send the code to the secure email, read it back over IMAP and
    log in fully unattended;
  - `auto` — log in without a code; exit code 3 means a human is needed.
  The login form now carries `trustAgent=true` ("trust this client"), after which the
  dynamic strategy skips the second factor and `ensure_session()` can re-login on its
  own again.

- **Secure-email code reading (`mail_mfa` config).**
  `auth_session.read_mfa_code_from_mailbox()` polls the secure mailbox over IMAP and
  extracts the 6-digit code sent by `xjtulogin@xjtu.edu.cn`. `full_login()` now runs the
  "send code → read code → validate" chain automatically when MFA is demanded, and only
  falls back to `MFARequired` when that fails. `user`/`password` default to
  `mail.from_addr`/`mail.password` (a QQ auth code works for both SMTP and IMAP).

- `XkfwClient(session_file, mail_mfa_cfg)` gained its second parameter; the panel's
  "login" button and the monitor now share `make_client()` and both take the automatic
  path.

### Fixed

- **Startup MFA failure caused a systemd crash loop.** `MFARequired` / `CaptchaRequired`
  used to `sys.exit(2)`, so systemd restarted the unit every 10s, spamming "session
  dead" emails until it gave up and the service stayed dead. Both are now logged,
  alerted once and retried while the process keeps running, so a restored session
  resumes without restarting the service.
- `full_login()` now sends the browser's `loginType=passwordLogin` parameter to `mfa/detect`.
- `session.json` is tightened to mode 0600 after every write (it holds a token and CAS cookies).

### Changed

- Docs: README gained a "session renewal / two-factor auth" section;
  `config.example.yaml` documents the new `mail_mfa` block (disabled by default).
- `.gitignore` now covers `.mfa_state.json` and `.backups/`.

## [0.2.4] - 2026-07-31

### Fixed

- **`scripts/healthcheck.py` process check was Windows-only.** It invoked
  `wmic` (a Windows command), so on Linux/macOS the process check always
  failed with "进程检查失败" and the healthcheck reported errors even when the
  monitor was fine. Rewritten to be cross-platform: Linux scans `ps aux` with a
  `/proc/<pid>/cmdline` fallback for the pid file, Windows keeps wmic.

## [0.2.3] - 2026-07-31

### Added

- **Webhook notifications (`notifier.py`).** POST JSON to any URL (QQ bot /
  Server酱 / Bark / 飞书 / custom), configurable via `webhook: {enabled, url}`.
  Fires alongside email for: free-seat alerts, sustained-seat reminders and
  session-dead notifications. `--test-mail` also tests the webhook.
- **Sustained-seat reminders (`respot_remind_min`).** If a seat stays free and
  nobody grabs it, a follow-up alert is sent every N minutes (default 0 =
  disabled). Previously a free seat was only announced once, ever.

### Fixed

- **`--login-only` blocked by the single-instance lock.** Login/session refresh
  now happens before the lock is acquired, so you can re-export a session while
  the systemd monitor is running. The lock now only guards the polling loop.

### Changed

- Panel config API exposes `respot_remind_min` and `webhook` (masked-safe URL,
  enabled flag); `config.example.yaml` documents both.

## [0.2.2] - 2026-07-31

### Fixed

- **capacity.do empty-shell misread as "full" (P1, could miss seats).** When xkfw
  returns `{"data":null,"code":null}` during peak hours, `check_capacity` now
  raises `SessionError` instead of reporting "已满 0/0" — the caller retries and
  the failure is no longer treated as a normal "no room" state.
- **`is_alive()` empty-shell guard now actually catches the shell.** The previous
  `bool(j) and ("code" in j or ...)` check returned True for
  `{"data":null,"code":null}` because the keys existed. Now `data is None and
  code is None` is treated as not-alive (transient).
- **Panel `/api/logs` unbounded `n`.** Clamped to 1..500 so a bad parameter can't
  dump the entire log.

### Changed

- **Single-instance lock (`monitor.lock`).** `monitor.py` takes a non-blocking
  file lock (fcntl on POSIX, msvcrt on Windows) at startup; a second instance
  (e.g. panel start while systemd is running) exits immediately instead of
  duplicating alerts.
- **`_pid_alive` checks `/proc/<pid>/cmdline`** on Linux to avoid a recycled PID
  being mistaken for a running monitor.
- **Passwords can now be cleared** from the panel (`"password": ""`), both for
  the campus account and the SMTP auth code.
- **Version pins** added upper bounds in `requirements.txt`; new
  `requirements-dev.txt` with pytest.
- **Docker**: compose runs as `user: "1000:1000"` so the container doesn't chown
  `session.json` to root; scripts normalized to LF line endings.

### Added

- **First test suite** (`tests/`, 37 tests): empty-shell handling, edge-trigger
  alerting, single-instance lock, SMTP config resolution, panel config
  masking/clearing and course filtering. Run with:
  `pip install -r requirements-dev.txt && python -m pytest tests/ -q`

## [0.2.1] - 2026-07-31

### Fixed

- **Startup hard-exit on transient session failure.** `ensure_session()` at
  startup no longer calls `sys.exit(2)` when the session check fails — xkfw
  occasionally returns an empty shell (`{"data":null,"code":null}`) that
  self-heals within minutes. The monitor now logs a warning and keeps running;
  the main loop's recovery/notification logic acts as the safety net.
- **False-positive "session dead" emails after recovery.** `consecutive_session_fails`
  is now reset to 0 once the session recovers, so a transient outage no longer
  triggers a spurious disconnect alert after a successful re-login.
- **`auth_session.py` `is_alive()` empty-shell guard.** Now treats
  `{"data":null,"code":null}` as not-alive instead of a healthy probe.
- **`refresh_token()` 3×2 retry.** Retries `register.do` up to 3 rounds
  (trying both the cached student number and `"null"`) with a 1.5s pause,
  tolerating the empty-shell flakiness instead of failing on the first miss.

### Changed

- Simplified `.gitignore`; `start_panel.bat`/`start_panel.sh` marked executable.

## [0.2.0] - 2026-07-30

### Fixed

- **Session dead-loop without notification (critical).** `is_alive()` used
  `dictionary.do` to probe token validity, but that endpoint returns 200 + valid
  JSON even after the token expires on `capacity.do`. This meant `ensure_session`
  always thought the session was healthy and never triggered the "session dead"
  email, creating an infinite loop of failed queries with no alert.
- **`auth_session.py`:** `ensure_session` now always calls `refresh_token()`
  (via lightweight `register.do`) before checking `is_alive()`, guaranteeing a
  fresh token for every capacity query.
- **`monitor.py`:** Added `consecutive_session_fails` counter. If 3 consecutive
  rounds of session errors occur (even if the code claims recovery), a
  forced notification is sent. Unified session-dead email logic into
  `notify_session_dead()` with proper cooldown control.

### Changed

- **`monitor.py`:** Replaced `FileHandler` with `RotatingFileHandler`
  (5 MB max, 3 backups) to prevent log files from growing unbounded.
- **`monitor.py`:** Added `SIGTERM`/`SIGINT` handlers for graceful shutdown
  — the main loop exits cleanly instead of being killed mid-iteration.
- **`config.example.yaml`:** Added `session_fail_cooldown_sec` to document
  the session-dead email throttling setting.
- **`scripts/healthcheck.py`:** Removed hardcoded `!= 2` course count check;
  now only warns when no courses are configured.
- **`Dockerfile`:** Copy `config.example.yaml` into the image as a reference
  for users mounting their own config.

## [0.1.0] - 2026-07-29

### Added

- Background monitor: poll teaching-class capacity, email on free seats (QQ / Gmail).
- Local web panel (`panel_app.py`): sidebar pages — Overview / Courses / Settings / Logs.
- CAS best-effort login + `session.json` persistence; register.do token refresh.
- CLI utilities under `scripts/` (list courses, PE conflict helper, healthcheck, simulate drop).
- Docker image for headless monitor process.
- Open-source scaffolding: MIT license, security notes, example config.

### Notes

- Panel is a development server bound to localhost; for personal use only.
- Course listing depends on a valid elective batch and campus network access.
