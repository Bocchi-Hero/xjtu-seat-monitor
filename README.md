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
- **会话保活**：自动刷新 token；CAS 会话过期时可用「可信客户端 + 安全邮箱自动读码」续期，
  掉线重连 + 连续失败强制通知
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
│   ├── mfa_login.py            # 会话续期（二次认证 / 可信客户端 / 安全邮箱自动读码）
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
| `mail_mfa.enabled` | 二次认证时自动读安全邮箱验证码续期 | `false` |
| `mail_mfa.trust_agent` | 登录后登记为「可信客户端」以跳过二次认证 | `true` |

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

# 会话续期（token 掉线 / 需要二次认证时用；详见下文「会话续期」）
python scripts/mfa_login.py probe                       # 只读诊断：是否需要二次认证
python scripts/mfa_login.py start --wait-mail           # 发码到安全邮箱并自动读码登录
python scripts/mfa_login.py start                       # 发码到安全手机，再 verify --code
python scripts/mfa_login.py auto                        # 无人值守续期（免二次认证时）

# 模拟退课（仅测邮件通路，不实际操作）
python scripts/simulate_drop.py

# 体育课冲突检查
python scripts/pe_conflict_check.py
```

---

## 会话续期 / 二次认证（MFA）

选课系统（xkfw）的会话由统一认证 CAS 签发，分三层：

| 层 | 有效期 | 失效后的后果 |
|:---|:---|:---|
| xkfw token（`session.json`） | 较短，几小时~ | `register.do` 用 CAS 会话直接换新 token，**自动续期，无感** |
| xkfw 登录态（app 会话 cookie） | 较短 | 登录态没了以后 `register.do` 仍会发 token，但 `capacity.do` 回「未查询到登录信息」——**必须重新完整登录一次**才能恢复 |
| CAS 会话（cookie / TGC） | 较长 | 必须重新走一次统一认证；**新设备或长期未登录时会被要求二次认证** |

> ⚠️ 第二层最坑：**只换 token 属于"假恢复"**。`ensure_session(verify_tcid=...)` 会拿一门
> 真实课程做业务级验收（`capacity.do` 真的通过才算恢复），否则会陷入
> 「已恢复 → 查容量失败 → 再恢复」的静默死循环，既不报警也不监控。

问题出在第三层：CAS 对「新设备 / 长期未登录」启用动态 MFA 策略，要求安全手机短信或
安全邮箱验证码。服务器上没人能收码，于是登录失败 → 监控退出 → systemd 反复重启刷邮件。
**token 会失效一次，根因几乎都是 CAS 会话过期 + 二次认证。**

本项目的处理方式（`mail_mfa` 配置 + `scripts/mfa_login.py`）：

1. **登记「可信客户端」**：登录表单带 `trustAgent=true` 时，CAS 会把本机记为可信设备，
   之后动态策略默认跳过二次认证 —— 监控的 `ensure_session()` 就能像往常一样自动重登。
2. **安全邮箱自动读码**：即使仍被要求二次认证，只要安全邮箱就是 `mail` 里配置的邮箱，
   程序会自动发码 → 通过 IMAP 读码 → 完成验证（`mail_mfa.enabled: true`）。
3. **不再崩溃循环**：启动时遇到 MFA / 验证码失败只是记录并继续重试（发一封掉线提醒），
   会话恢复后自动接着监控，不需要重启服务。

手动续期（一次性）：

```bash
python scripts/mfa_login.py probe              # 看看是否真的需要二次认证
python scripts/mfa_login.py start --wait-mail  # 安全邮箱自动读码并完成登录
# 或走短信：start 后把收到的 6 位验证码交给 verify
python scripts/mfa_login.py start --type securephone
python scripts/mfa_login.py verify --code 123456
```

> 安全手机 / 安全邮箱的绑定关系在统一认证网关里维护；若两者都未绑定，
> 只能在本机浏览器登录一次并导出 `session.json`。
> `mail_mfa` 只读取认证中心（`xjtulogin@xjtu.edu.cn`）发来的验证码邮件。

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
