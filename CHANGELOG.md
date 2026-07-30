# Changelog

All notable changes to this project will be documented in this file.

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
