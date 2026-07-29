#!/usr/bin/env python3
"""List PE classes that do not conflict with current selected timetable."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DAY = {
    "星期一": 1,
    "星期二": 2,
    "星期三": 3,
    "星期四": 4,
    "星期五": 5,
    "星期六": 6,
    "星期日": 7,
    "周一": 1,
    "周二": 2,
    "周三": 3,
    "周四": 4,
    "周五": 5,
    "周六": 6,
    "周日": 7,
}
DAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def parse_weeks(s: str) -> set[int]:
    s = (s or "").strip()
    if not s:
        return set(range(1, 17))
    m = re.match(r"(\d+)\s*-\s*(\d+)\s*周", s)
    if m:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    # 4周,8周,12周,16周
    if "周" in s and "-" not in s:
        nums = [int(x) for x in re.findall(r"(\d+)周", s)]
        if nums:
            return set(nums)
    m = re.match(r"^(\d+)周$", s)
    if m:
        return {int(m.group(1))}
    return set(range(1, 17))


def parse_sections(s: str) -> set[int]:
    s = s.replace("第", "").replace("节", "")
    m = re.search(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    return {int(x) for x in re.findall(r"\d+", s)}


def expand_week_blob(s: str) -> set[int]:
    """Parse '1周,3-4周,6-7周,9-10周' or '1-16周' into week set."""
    s = (s or "").strip()
    if not s:
        return set(range(1, 17))
    weeks: set[int] = set()
    for part in re.split(r"[,，]", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(\d+)\s*-\s*(\d+)\s*周?", part)
        if m:
            weeks.update(range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        m = re.match(r"(\d+)\s*周?", part)
        if m:
            weeks.add(int(m.group(1)))
    return weeks or set(range(1, 17))


def parse_place(place: str | None) -> list[tuple[set[int], int, set[int]]]:
    if not place:
        return []
    # Normalize: keep week lists with day as one block.
    # e.g. "1周,3-4周,6-7周 星期一 第3节-第4节 场地"
    text = place.strip()
    slots: list[tuple[set[int], int, set[int]]] = []

    # Find each day occurrence and take week info before it (may contain commas)
    for name, d in DAY.items():
        for m in re.finditer(re.escape(name), text):
            # walk left for week blob: from previous day/end or start
            start = 0
            # previous comma-separated teaching block often starts after a place name;
            # take from last "节" + place end is hard — use nearest prior "，" that
            # is NOT inside week list: split by pattern 节<place> then comma
            left = text[: m.start()]
            # week blob: trailing chunk after last 节... roughly last segment
            # Better: match weeks immediately before day name
            left_stripped = left.rstrip(" ,，")
            # take from last Chinese place-ish break: after previous 节+spaces+non-week
            wm = re.search(
                r"((?:\d+\s*-\s*\d+\s*周|\d+\s*周)(?:\s*[,，]\s*(?:\d+\s*-\s*\d+\s*周|\d+\s*周))*)\s*$",
                left_stripped,
            )
            if wm:
                weeks = expand_week_blob(wm.group(1))
            else:
                weeks = set(range(1, 17))
            after = text[m.end() :]
            sec_m = re.search(
                r"((?:第)?\d+\s*-\s*(?:第)?\d+\s*节|(?:第)?\d+\s*节\s*-\s*(?:第)?\d+\s*节|"
                r"(?:第)?\d+\s*-\s*\d+节?|(?:第)?\d+节)",
                after,
            )
            if not sec_m:
                sec_m = re.search(r"\d+\s*-\s*\d+", after)
            if not sec_m:
                continue
            sections = parse_sections(sec_m.group(0))
            slots.append((weeks, d, sections))
    return slots


def conflicts(a, b) -> bool:
    for wa, da, sa in a:
        for wb, db, sb in b:
            if da != db:
                continue
            if sa & sb and wa & wb:
                return True
    return False


def main() -> None:
    sel_path = _ROOT / "selected_raw.json"
    if not sel_path.exists():
        print(f"缺少 {sel_path}：请先用已登录会话拉取已选课并保存为 selected_raw.json")
        return
    sel = json.loads(sel_path.read_text(encoding="utf-8")).get("dataList") or []
    my_slots = []
    print("=== 已选课表 ===")
    pe_selected = []
    for d in sel:
        name = d.get("courseName") or ""
        place = d.get("teachingPlace") or d.get("teachingPlaceHide") or ""
        teacher = d.get("teacherName") or ""
        tid = d.get("teachingClassID") or ""
        slots = parse_place(place)
        my_slots.extend(slots)
        mark = ""
        if "篮球" in place or "篮球" in name:
            mark = "  ← 已选篮球"
            pe_selected.append(d)
        print(f"- {name} | {teacher} | {place}{mark}")

    print("\n=== 占用节次（按星期，合并周次）===")
    occ: dict[int, set[int]] = defaultdict(set)
    for _w, day, secs in my_slots:
        occ[day] |= secs
    for day in range(1, 8):
        if occ[day]:
            print(f"  {DAY_CN[day]}: {sorted(occ[day])} 节")

    courses_path = _ROOT / "courses_list.json"
    if not courses_path.exists():
        print(f"缺少 {courses_path}：请先运行 python scripts/list_courses.py")
        return
    rows = json.loads(courses_path.read_text(encoding="utf-8"))
    pe = [r for r in rows if r.get("class_type") == "TYKC" or r.get("type_name") == "体育"]

    free = []
    conflict_n = 0
    no_time = 0
    skipped_ball = 0
    for r in pe:
        name = r.get("course_name") or ""
        place = r.get("place") or ""
        if "篮球" in name or "篮球" in place:
            skipped_ball += 1
            continue
        slots = parse_place(place)
        if not slots:
            no_time += 1
            continue
        if conflicts(my_slots, slots):
            conflict_n += 1
            continue
        free.append(r)

    print(
        f"\n体育总班 {len(pe)} | 排除篮球 {skipped_ball} | 时间冲突 {conflict_n} | "
        f"无时间信息 {no_time} | **不冲突 {len(free)}**"
    )

    groups: dict[str, list] = defaultdict(list)
    for r in free:
        groups[r["course_name"]].append(r)

    lines = [
        "# 与当前课表不冲突的体育课（已排除篮球）",
        "",
        "已选体育：体育-3 篮球｜张宇琨｜周五 7-8 节｜西南运动场-篮球场（3）",
        "",
        f"不冲突教学班：**{len(free)}**｜项目约 **{len(groups)}** 种",
        "",
        "| 项目 | 教师 | 时间地点 | 教学班号 |",
        "|------|------|----------|----------|",
    ]
    for r in sorted(free, key=lambda x: (x.get("place") or "", x.get("course_name") or "")):
        lines.append(
            f"| {r['course_name']} | {r.get('teacher','')} | {r.get('place','')} | "
            f"`{r.get('teaching_class_id','')}` |"
        )

    (_ROOT / "pe_no_conflict.md").write_text("\n".join(lines), encoding="utf-8")
    (_ROOT / "pe_no_conflict.json").write_text(
        json.dumps(free, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== 不冲突体育课（按时间）===")
    for r in sorted(free, key=lambda x: (x.get("place") or "", x.get("course_name") or "")):
        print(f"{r['course_name']} | {r['teacher']} | {r['place']} | {r['teaching_class_id']}")

    print(f"\n已写入 pe_no_conflict.md / pe_no_conflict.json")


if __name__ == "__main__":
    main()
