# XJTU Seat Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/downloads/)

西安交通大学选课系统 **空位邮件提醒** 工具：后台轮询教学班容量，有人退课出现空位时发邮件。
提供本机 **Web 控制面板**（总览 / 盯课 / 设置 / 日志），无需手改配置文件即可使用。

> **Only notifies — does not auto-select courses.**
> 仅提醒，不自动提交选课。

---

## Features

- **本地面板**：打开浏览器即可操作，无需手写配置
- **自动盯课**：后台轮询，有人退课即刻邮件通知
- **邮件提醒**：QQ / Gmail SMTP，空位出现时秒级告警
- **会话保活**：自动刷新 token，掉线重连 + 连续失败强制通知
- **日志轮转**：日志自动切割（5MB / 份，保留 3 份），不占磁盘
- **优雅退出**：收到停止信号时正常结束，不丢数据
- **可选脚本**：列课、体育冲突检查、自检、模拟发信
- **Docker**：无界面服务器挂机监控

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
- 用 systemd 或 Docker 运行 `monitor.py`（见下面 Linux / Docker 章节）

---

## Quick start (Linux / macOS)

```bash
# 1. 克隆项目
git clone https://github.com/Bocchi-Hero/xjtu-seat-monitor.git
cd xjtu-seat-monitor

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 复制配置文件
cp config.example.yaml config.yaml
```

### 方式 A：使用面板（推荐）

```bash
chmod +x start_panel.sh
./start_panel.sh
```

打开 **http://127.0.0.1:18730/**，按面板指引操作。

### 方式 B：命令行（无头模式）

编辑 `config.yaml` 填入账号、课程、邮箱信息，然后：

```bash
# 首次登录（需要本机 CAS 验证）
python monitor.py --login-only

# 测试邮件配置
python monitor.py --test-mail

# 开始监控
python monitor.py
```

### 方式 C：systemd 服务（服务器 24h）

```bash
# 编辑 config.yaml 并完成登录后，使用 systemd 管理
sudo cp xjtu-seat-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xjtu-seat-monitor
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
├── config.example.yaml         # 配置模板（不要直接改）
├── start_panel.bat / .sh       # 本地面板启动脚本
├── panel_app.py                # Flask 面板入口 (127.0.0.1:18730)
├── panel_service.py            # 面板后端服务
├── panel_static/               # 面板前端页面
├── monitor.py                  # 后台监控主进程
├── auth_session.py             # 选课系统会话 / 容量查询
├── mailer.py                   # 邮件发送
├── Dockerfile
├── docker-compose.yml
├── scripts/
│   ├── list_courses.py         # 列出可选课程
│   ├── pe_conflict_check.py    # 体育课冲突检查
│   ├── healthcheck.py          # 全流程自检
│   ├── simulate_drop.py        # 模拟退课（仅测试邮件）
│   └── build_release.py        # 打包发布
└── docs/
    └── ARCHITECTURE.md
```

**⚠️ 切勿提交到 Git：** `config.yaml`、`session.json`、`*.log`、`courses_list.json`

---

## Configuration

完整字段见 [`config.example.yaml`](config.example.yaml)。

| 键 | 说明 | 默认值 |
|:---|:---|:---:|
| `account` / `password` | 统一认证账号密码 | — |
| `courses[].name` | 课程显示名（仅日志用） | — |
| `courses[].teaching_class_id` | 教学班编号 | — |
| `mail.provider` | 邮件服务商：`qq` / `gmail` / `qq_starttls` / `custom` | `qq` |
| `mail.from_addr` | 发件邮箱 | — |
| `mail.to_addr` | 收件邮箱（默认同发件） | `from_addr` |
| `mail.password` | SMTP 授权码（**不是登录密码**） | — |
| `poll_interval_sec` | 轮询间隔（秒） | `20` |
| `poll_jitter_sec` | 随机抖动（秒，防封） | `5` |
| `alert_cooldown_sec` | 空位提醒邮件冷却（秒） | `600` |
| `session_check_every` | 每 N 轮做一次会话保活检查 | `50` |
| `session_fail_cooldown_sec` | 断线通知邮件冷却（秒） | `3600` |

> QQ 邮箱授权码获取：登录 QQ邮箱 → 设置 → 帐户 → 生成授权码

---

## Docker（服务器无头监控）

```bash
# 1. 在本机完成登录并生成 session.json
# 2. 将 config.yaml + session.json 传到服务器项目目录
# 3. 启动容器
docker compose up -d --build
```

容器运行 `monitor.py`，挂载 `config.yaml`（只读）和 `session.json`（可写）。宿主机需要能访问 `xkfw.xjtu.edu.cn`。

如需代理 / VPN 访问校园网，取消 `docker-compose.yml` 中 `network_mode: host` 的注释。

---

## CLI utilities

所有脚本从项目根目录运行（脚本会自动添加父目录到 `sys.path`）：

```bash
# 列出可选课程（需要先登录）
python scripts/list_courses.py --batch <batch_code>

# 全流程自检：配置、会话、容量接口、进程
python scripts/healthcheck.py

# 模拟退课（仅测邮件通路，不实际操作）
python scripts/simulate_drop.py

# 体育课冲突检查
python scripts/pe_conflict_check.py
```

---

## Privacy

- 账号密码、邮箱授权码仅保存在本机 `config.yaml` 中。
- 面板服务仅监听 **localhost（127.0.0.1）**，不对外暴露。
- 如曾在聊天或截图中泄露过授权码，请及时在邮箱设置中**重新生成**。

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
