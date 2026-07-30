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

### 1️⃣ 安装 Python

从 [python.org](https://www.python.org/downloads/) 下载 **Python 3.10+**（推荐 3.12）。  
安装时 **务必勾选** ✅ **Add Python to PATH**，否则命令行找不到 `python`。

验证是否装好：打开 cmd 或 PowerShell，输入：
```bat
python --version
```

### 2️⃣ 下载本项目

点 GitHub 仓库绿色的 **Code** → **Download ZIP**，解压到某个文件夹（路径不要有中文）。  
或者装了 Git 的话：
```bat
git clone https://github.com/Bocchi-Hero/xjtu-seat-monitor.git
cd xjtu-seat-monitor
```

### 3️⃣ 启动面板（图形界面）

**双击 `start_panel.bat`**，会弹出命令行窗口并自动：
- 安装依赖（首次会慢一点，耐心等）
- 启动本地面板
- 自动打开浏览器 → **http://127.0.0.1:18730/**

**⚠️ 这个命令行窗口不能关**，关了面板就停了。

> 如果浏览器没自动打开，手动访问 `http://127.0.0.1:18730/` 即可。

### 4️⃣ 按顺序完成面板设置

面板打开后是一个网页，左侧有 4 个页面：

| 页面 | 做什么 |
|:---|:---|
| **总览** | 看监控状态、检查步骤进度条 |
| **盯课** | 搜索要监控的课程并添加 |
| **设置** | 填写账号、邮箱、登录选课系统 |
| **日志** | 看监控运行日志 |

推荐操作顺序：

**① 设置 → 填写信息**
- **学号 / 密码**：你的统一认证账号
- **邮箱**：选 `qq`，填 QQ 号 + SMTP 授权码（**不是 QQ 密码**）
  > QQ 邮箱授权码获取：登录 QQ邮箱 → 设置 → 帐户 → 生成授权码
- 点 **保存配置**

**② 设置 → 登录选课系统**
- 点 **登录选课** 按钮
- 如果弹出验证码/MFA，说明需要本机交互，按提示完成即可
- 登录成功后左上角会显示学号

**③ 盯课 → 搜索课程**
- 输入关键词（如 `健美`、`羽毛球`），点搜索
- 找到你要盯的课，点 **添加** 加入监控列表
- 也可以直接填教学班号手动添加

**④ 总览 → 启动监控**
- 确认 5 步检查项全部 ✅
- 点 **开始后台监控**
- 几秒后就能看到课程容量状态（如 `24/24 满`）

### 5️⃣ 收邮件提醒

有人退课出现空位时，你会收到邮件：
- 标题：`[选课空位] 课程名 23/24`
- 正文包含课程名称、教学班号、时间

收到提醒后尽快登录选课系统操作，空位很快会被抢。

### 6️⃣ 进阶：部署到服务器

本机监控需要一直开着电脑。想 24h 挂机的话，可以把 `config.yaml` 和 `session.json` 传到服务器：
- 本机先完成登录（确保 session.json 有效）
- 把整个文件夹传到服务器
- 用 systemd 或 Docker 运行 `monitor.py`（见下面 Linux/Docker 章节）

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
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── requirements.txt
├── config.example.yaml      # template only
├── start_panel.bat / .sh    # local web panel
├── panel_app.py             # Flask entry (127.0.0.1:18730)
├── panel_service.py
├── panel_static/            # UI
├── monitor.py               # watcher process
├── auth_session.py          # xkfw session / capacity
├── mailer.py
├── Dockerfile
├── docker-compose.yml
├── scripts/                 # optional CLI tools
│   ├── list_courses.py
│   ├── pe_conflict_check.py
│   ├── healthcheck.py
│   └── simulate_drop.py
└── docs/
    └── ARCHITECTURE.md
```

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
