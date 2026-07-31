"""panel_service 配置处理测试（monkeypatch 路径，绝不触碰真实 config.yaml）"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel_service as svc


def _write_cfg(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


def test_public_config_masks_password(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = {"account": "stu", "password": "secret123", "mail": {"from_addr": "a@qq.com", "password": "authcode"}}
    pub = svc.public_config(cfg)
    assert pub["password"] == ""
    assert pub["password_set"] is True
    assert pub["mail"]["password"] == ""
    assert pub["mail"]["password_set"] is True


def test_merge_config_clears_password(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(svc, "CONFIG_PATH", cfg_path)
    _write_cfg(cfg_path, {"account": "stu", "password": "secret123"})

    svc.merge_config_update({"password": ""})  # 传空串 → 清空
    cfg = svc.load_cfg()
    assert cfg["password"] == ""

    svc.merge_config_update({"password": "newpass"})
    assert svc.load_cfg()["password"] == "newpass"


def test_merge_config_filters_bad_courses(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(svc, "CONFIG_PATH", cfg_path)
    _write_cfg(cfg_path, {"courses": []})

    svc.merge_config_update(
        {"courses": [{"name": "ok", "teaching_class_id": "20262027ABC01"}, {"name": "bad", "teaching_class_id": ""}, "not-a-dict"]}
    )
    courses = svc.load_cfg()["courses"]
    assert len(courses) == 1
    assert courses[0]["teaching_class_id"] == "20262027ABC01"


def test_search_catalog_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "ROOT", tmp_path)
    (tmp_path / "courses_list.json").write_text(
        json_dumps([{"course_name": "健美", "teacher": "张三"}, {"course_name": "游泳", "teacher": "李四"}]),
        encoding="utf-8",
    )
    hits = svc.search_catalog("健")
    assert len(hits) == 1
    assert hits[0]["course_name"] == "健美"
    assert svc.search_catalog("")  # 无关键字返回全部


def json_dumps(obj):
    import json

    return json.dumps(obj, ensure_ascii=False)
