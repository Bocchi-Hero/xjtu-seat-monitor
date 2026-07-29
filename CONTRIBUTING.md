# Contributing

Thanks for helping improve this project.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # fill locally, never commit
python panel_app.py                  # http://127.0.0.1:18730/
```

## Guidelines

1. **No secrets** in commits, screenshots, or sample configs.
2. Keep the **overview page simple** (monitor on/off + seat status). Put config in **Settings**.
3. Prefer small, focused PRs with a short description of *why*.
4. Test on Windows if you change `start_panel.bat` or process detection; test on Linux if you change Docker paths.

## Code layout

| Path | Role |
|------|------|
| `monitor.py` | Background seat watcher |
| `panel_app.py` / `panel_service.py` | Local control panel API |
| `panel_static/` | Panel UI |
| `auth_session.py` / `mailer.py` | XKfw session & email |
| `scripts/` | Optional CLI utilities |

## License

By contributing, you agree your contributions are licensed under the MIT License.
