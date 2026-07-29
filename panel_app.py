#!/usr/bin/env python3
"""
选课空位监控 — 本机可视化控制面板
仅监听 127.0.0.1，双击 start_panel.bat 或: python panel_app.py
"""

from __future__ import annotations

import webbrowser
from threading import Timer

from flask import Flask, jsonify, request, send_from_directory

import panel_service as svc

app = Flask(__name__, static_folder="panel_static", static_url_path="/static")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def api_status():
    with_cap = request.args.get("with_capacity", "0") in ("1", "true", "yes")
    return jsonify(svc.full_status(with_capacity=with_cap))


@app.get("/api/config")
def api_config_get():
    return jsonify(svc.public_config(svc.load_cfg()))


@app.post("/api/config")
def api_config_save():
    body = request.get_json(force=True, silent=True) or {}
    cfg = svc.merge_config_update(body)
    return jsonify({"ok": True, "config": svc.public_config(cfg)})


@app.post("/api/login")
def api_login():
    return jsonify(svc.do_login())


@app.post("/api/capacity")
def api_capacity():
    return jsonify(svc.check_capacities())


@app.post("/api/mail/test")
def api_mail_test():
    return jsonify(svc.test_mail())


@app.post("/api/monitor/start")
def api_mon_start():
    return jsonify(svc.start_monitor())


@app.post("/api/monitor/stop")
def api_mon_stop():
    return jsonify(svc.stop_monitor())


@app.get("/api/logs")
def api_logs():
    n = request.args.get("n", 100, type=int)
    return jsonify({"lines": svc.read_logs(n)})


@app.get("/api/catalog")
def api_catalog():
    q = request.args.get("q", "")
    limit = request.args.get("limit", 40, type=int)
    return jsonify({"items": svc.search_catalog(q, limit), "ready": svc.full_status()["catalog_ready"]})


def main():
    host = "127.0.0.1"
    port = 18730
    url = f"http://{host}:{port}/"
    print(f"XJTU Seat Monitor panel: {url}")
    print("Keep this process running. Closing it stops the panel API.")
    print("A started monitor.py process can keep running independently.")
    try:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    # threaded=True：前端轮询 + 登录/容量请求可并行
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
