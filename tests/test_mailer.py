"""mailer 配置解析测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mailer import resolve_smtp


def test_qq_default():
    cfg = resolve_smtp({"provider": "qq", "from_addr": "a@qq.com"})
    assert cfg["host"] == "smtp.qq.com"
    assert cfg["port"] == 465
    assert cfg["use_ssl"] is True


def test_gmail():
    cfg = resolve_smtp({"provider": "gmail"})
    assert cfg["host"] == "smtp.gmail.com"


def test_custom():
    cfg = resolve_smtp({"provider": "custom", "host": "smtp.example.com", "port": 587, "use_ssl": False})
    assert cfg["host"] == "smtp.example.com"
    assert cfg["port"] == 587
    assert cfg["use_ssl"] is False


def test_override_builtin():
    cfg = resolve_smtp({"provider": "qq", "host": "smtp.mail.qq.com"})
    assert cfg["host"] == "smtp.mail.qq.com"


def test_port_int_coercion():
    cfg = resolve_smtp({"provider": "qq", "port": "465"})
    assert cfg["port"] == 465
    assert isinstance(cfg["port"], int)
