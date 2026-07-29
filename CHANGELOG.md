# Changelog

All notable changes to this project will be documented in this file.

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
