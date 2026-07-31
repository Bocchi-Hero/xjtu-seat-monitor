"""monitor 纯逻辑测试：边沿触发、单实例锁"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import monitor


# ── 边沿触发 ──

@pytest.mark.parametrize(
    "has_room,prev,expected",
    [
        (True, None, True),    # 首次查询即有空位 → 提醒
        (True, False, True),   # 无空位 → 有空位 → 提醒
        (True, True, False),   # 一直有空位 → 不重复提醒
        (False, None, False),  # 无空位 → 不提醒
        (False, False, False),  # 仍满 → 不提醒
        (False, True, False),  # 有空位 → 变满 → 不提醒（边沿只在出现空位时触发）
    ],
)
def test_edge_trigger(has_room, prev, expected):
    assert monitor._edge_trigger(has_room, prev) is expected


# ── 单实例锁 ──

def test_singleton_lock_excludes_second_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    fh1 = monitor._acquire_singleton()
    try:
        with pytest.raises(SystemExit):
            monitor._acquire_singleton()
    finally:
        fh1.close()


def test_singleton_lock_released_after_close(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    fh1 = monitor._acquire_singleton()
    fh1.close()
    # 释放后第二个实例应能拿到锁
    fh2 = monitor._acquire_singleton()
    fh2.close()
    assert (tmp_path / "monitor.lock").exists()
