# XJTU Seat Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/downloads/)

西安交通大学选课系统 **空位邮件提醒** 工具：后台轮询教学班容量，有人退课出现空位时发邮件。  
提供本机 **Web 控制面板**（总览 / 盯课 / 设置 / 日志），无需手改配置文件即可使用。

> **Only notifies — does not auto-select courses.**  
> 仅提醒，不自动提交选课。

---

## Features

- 本地面板：一眼查看监控开关与课容量；侧栏多页布局（桌面 + 手机）
- 邮件：QQ / Gmail SMTP
- 会话：`session.json` 持久化；Token 刷新；CAS 尽力登录（MFA 需本机处理）
- 可选脚本：列课、体育冲突粗检、自检、模拟发信
- Docker：无界面挂机监控

---

## Disclaimer

- 仅供 **学习与个人账号** 使用，请遵守学校选课规则与网络使用规定。
- 高频请求可能影响服务或触发限制；请使用合理轮询间隔。
- 作者不对选课结果、账号异常或数据丢失负责。
- 使用即表示你理解并自行承担风险。

---

## Quick start (Windows)

```bat
git clone <this-repo> xjtu-seat-monitor
cd xjtu-seat-monitor
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

Double-click **`start_panel.bat`** (keep the window open), then open:

**http://127.0.0.1:18730/**

| Page | Purpose |
|------|---------|
| **总览** | Monitor on/off + seat full/free |
| **盯课** | Add teaching class IDs / search catalog |
| **设置** | Account, email, login, test mail |
| **日志** | Recent monitor logs |

Flow: **Settings (save + login)** → **Courses** → **Overview → Start monitor**.

---

## Quick start (Linux / macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
# edit config.yaml
chmod +x start_panel.sh
./start_panel.sh
```

Or headless monitor only:

```bash
python -u monitor.py
```

---

## Project layout

```
xjtu-seat-monitor/
├── README.md / LICENSE / SECURITY.md / CONTRIBUTING.md / CHANGELOG.md
├── requirements.txt
├── config.example.yaml          # template only (copy → config.yaml)
│
├── monitor.py                   # background watcher
├── auth_session.py / mailer.py
├── panel_app.py / panel_service.py
├── panel_static/                # web UI
├── start_panel.bat / start_panel.sh
├── Dockerfile / docker-compose.yml
│
├── scripts/                     # optional CLI tools
├── docs/                        # ARCHITECTURE.md, LAYOUT.md
└── data/                        # local runtime (gitignored except .gitkeep)
```

分类说明见 [`docs/LAYOUT.md`](docs/LAYOUT.md)。

**Never commit:** `config.yaml`, `session.json`, `*.log`, personal course dumps.

---

## Configuration

See [`config.example.yaml`](config.example.yaml).

| Key | Meaning |
|-----|---------|
| `account` / `password` | Campus SSO |
| `courses[].teaching_class_id` | Teaching class ID to watch |
| `mail.provider` | `qq` or `gmail` |
| `mail.password` | SMTP auth code / app password |
| `poll_interval_sec` | Check interval (default 20) |

---

## Docker (monitor only)

```bash
cp config.example.yaml config.yaml
# fill config + produce session.json via local panel login first
docker compose up -d --build
```

The container runs `monitor.py`. Mount `config.yaml` and `session.json`. Host must reach `xkfw.xjtu.edu.cn`.

---

## CLI utilities

Run from repo root (scripts add parent to `sys.path`):

```bash
python scripts/list_courses.py --batch <batch_code>
python scripts/healthcheck.py
python scripts/simulate_drop.py   # test email path only
python scripts/pe_conflict_check.py
```

---

## Privacy

- Credentials stay on your machine.
- Panel listens on **localhost only**.
- Rotate email auth codes if they were ever pasted into chat or screenshots.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
