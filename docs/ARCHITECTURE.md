# Architecture

```
┌─────────────────────┐     HTTP JSON      ┌──────────────────────┐
│  Browser (panel)    │ ◄────────────────► │  panel_app.py        │
│  panel_static/*     │   127.0.0.1:18730   │  panel_service.py    │
└─────────────────────┘                    └──────────┬───────────┘
                                                      │ spawns / stops
                                                      ▼
                                           ┌──────────────────────┐
                                           │  monitor.py          │
                                           │  (background loop)   │
                                           └──────────┬───────────┘
                                                      │
                         ┌────────────────────────────┼────────────┐
                         ▼                            ▼            ▼
                  auth_session.py                 mailer.py    config.yaml
                  xkfw capacity.do                SMTP         session.json
```

## Components

| Module | Responsibility |
|--------|----------------|
| `monitor.py` | Poll capacity; edge-trigger email; session keep-alive |
| `auth_session.py` | Cookie/token load-save; CAS best-effort; `capacity.do` |
| `mailer.py` | QQ / Gmail / custom SMTP |
| `panel_app.py` | Flask routes, static UI |
| `panel_service.py` | Config I/O, process mgmt, checklist, catalog search |

## Design choices

1. **Notify only** — no `volunteer.do` submit from the monitor.
2. **Local panel** — localhost bind; secrets never returned unmasked to the UI.
3. **Process detect** — PID file + live check (no dependency on deprecated `wmic`).
4. **UI IA** — Overview for status; Settings for credentials; Courses for IDs.
5. **Session recovery — always refresh, never trust probe.** `ensure_session`
   unconditionally calls `register.do` to obtain a fresh token on every check,
   rather than relying on `is_alive()` probing `dictionary.do` (which accepts
   expired tokens). Combined with a consecutive-failure counter in
   `monitor.py`, this prevents silent dead-loop failures.
