# Changelog

All notable changes to this project will be documented in this file.

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
