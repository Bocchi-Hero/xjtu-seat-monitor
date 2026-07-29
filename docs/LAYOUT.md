# 目录与文件分类

本仓库按用途分为五类。本地密钥与运行时文件**不入库**。

## 1. 文档与开源元数据（仓库根）

| 文件 | 说明 |
|------|------|
| `README.md` | 项目说明、安装、使用 |
| `LICENSE` | MIT |
| `SECURITY.md` | 密钥与安全约定 |
| `CONTRIBUTING.md` | 贡献指南 |
| `CHANGELOG.md` | 版本记录 |
| `.gitignore` | 忽略规则 |
| `docs/ARCHITECTURE.md` | 架构说明 |
| `docs/LAYOUT.md` | 本文件：目录分类 |

## 2. 核心程序（仓库根，便于直接运行）

| 文件 | 说明 |
|------|------|
| `monitor.py` | 后台空位监控进程 |
| `auth_session.py` | 选课会话 / 容量查询 |
| `mailer.py` | QQ / Gmail 发信 |
| `panel_app.py` | Web 面板入口（`127.0.0.1:18730`） |
| `panel_service.py` | 面板后端逻辑 |
| `requirements.txt` | Python 依赖 |
| `config.example.yaml` | 配置模板（可提交） |

## 3. 前端静态资源

| 路径 | 说明 |
|------|------|
| `panel_static/index.html` | 面板页面 |
| `panel_static/panel.css` | 样式 |
| `panel_static/panel.js` | 前端逻辑 |

## 4. 启动与部署

| 文件 | 说明 |
|------|------|
| `start_panel.bat` | Windows 启动面板 |
| `start_panel.sh` | Linux / macOS 启动面板 |
| `Dockerfile` | 仅监控进程镜像 |
| `docker-compose.yml` | 容器编排 |

## 5. 可选脚本（`scripts/`）

| 文件 | 说明 |
|------|------|
| `list_courses.py` | 拉取可选课列表 |
| `pe_conflict_check.py` | 体育课时间冲突粗检 |
| `healthcheck.py` | 本机链路自检 |
| `simulate_drop.py` | 模拟空位发信测试 |

在仓库根目录执行，例如：

```bash
python scripts/list_courses.py --batch <code>
```

## 6. 仅本地存在（勿提交）

| 文件 / 目录 | 说明 |
|-------------|------|
| `config.yaml` | 真实账号、邮箱授权码、盯课列表 |
| `session.json` | 登录 Token / Cookie |
| `data/` | 预留运行时输出目录 |
| `*.log` / `*.pid` | 日志与进程号 |
| `.venv/` | 虚拟环境 |
| `__pycache__/` | 字节码缓存 |

## 清理命令（本机）

```powershell
# Windows PowerShell（在仓库根）
Remove-Item -Recurse -Force __pycache__, .venv -ErrorAction SilentlyContinue
Remove-Item -Force *.log, *.pid, _deploy*, _upload* -ErrorAction SilentlyContinue
# 不要误删 config.yaml / session.json（除非你要注销会话）
```
