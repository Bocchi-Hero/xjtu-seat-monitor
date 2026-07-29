# Security Policy

## Do not commit secrets

Never publish:

- `config.yaml` (campus account / password)
- `session.json` (Token / cookies)
- Email SMTP auth codes / app passwords
- Personal course dumps that include student identifiers

Use `config.example.yaml` as a template only.

## Local panel

The web panel binds to `127.0.0.1` by default. Do not expose it to the public internet without authentication and a production WSGI server.

## Reporting issues

If you discover a security-sensitive bug in this repository, open a private report or an issue without attaching credentials or session files.
