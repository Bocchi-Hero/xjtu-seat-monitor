#!/usr/bin/env python3
"""List batches and teaching classes using saved session.json."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from auth_session import XKFW, XkfwClient, _ts  # noqa: E402

QUERY = {
    "TJKC": ("recommendedCourse.do", True),
    "FANKC": ("programCourse.do", True),
    "FAWKC": ("programCourse.do", True),
    "TYKC": ("programCourse.do", True),
    "XGXK": ("publicCourse.do", False),
}

TYPE_NAME = {
    "TJKC": "主修推荐",
    "FANKC": "方案内",
    "FAWKC": "方案外",
    "XGXK": "通识",
    "TYKC": "体育",
}


def fetch_batches(client: XkfwClient) -> list[dict]:
    url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/{client.student_code}.do"
    r = client.http.get(url, params={"timestamp": _ts()}, timeout=20)
    r.raise_for_status()
    j = r.json()
    return ((j.get("data") or {}).get("electiveBatchList")) or []


def enter_round(client: XkfwClient, batch_code: str) -> str:
    url = f"{XKFW}/xsxkapp/sys/xsxkapp/student/xkxf.do"
    r = client.http.post(
        url,
        data={"xh": client.student_code, "xklcdm": batch_code, "xklclx": "01"},
        timeout=20,
    )
    campus = ""
    try:
        campus = ((r.json().get("data") or {}).get("campus")) or ""
    except Exception:
        pass
    return campus or "1"


def parse_rows(raw_list, class_type: str, has_tc: bool, is_xgxk: bool) -> list[dict]:
    rows: list[dict] = []
    if not raw_list:
        return rows
    if is_xgxk:
        for item in raw_list:
            rows.append(
                {
                    "class_type": class_type,
                    "type_name": TYPE_NAME.get(class_type, class_type),
                    "course_name": item.get("courseName") or "",
                    "teacher": item.get("teacherName") or "",
                    "teaching_class_id": item.get("teachingClassID") or "",
                    "place": item.get("teachingPlace") or "",
                    "campus": item.get("campus") or "",
                    "subtype": item.get("publicCourseTypeName")
                    or item.get("courseTypeName")
                    or "",
                }
            )
    elif has_tc:
        for a in raw_list:
            cname = a.get("courseName") or ""
            for tc in a.get("tcList") or []:
                name = cname
                if class_type == "TYKC" and tc.get("sportName"):
                    name = f"{cname}-{tc.get('sportName')}"
                rows.append(
                    {
                        "class_type": class_type,
                        "type_name": TYPE_NAME.get(class_type, class_type),
                        "course_name": name,
                        "teacher": tc.get("teacherName") or "",
                        "teaching_class_id": tc.get("teachingClassID") or "",
                        "place": tc.get("teachingPlace") or "",
                        "campus": tc.get("campus") or "",
                        "subtype": a.get("typeName") or "",
                    }
                )
    return rows


def fetch_type(
    client: XkfwClient,
    class_type: str,
    batch_code: str,
    campus: str,
    keyword: str = "",
) -> list[dict]:
    endpoint, has_tc = QUERY[class_type]
    is_xgxk = class_type == "XGXK"
    all_rows: list[dict] = []
    page = 0
    total_pages = 1
    while page < total_pages:
        setting = {
            "data": {
                "studentCode": client.student_code,
                "campus": campus,
                "electiveBatchCode": batch_code,
                "isMajor": "1",
                "teachingClassType": class_type,
                "checkConflict": "2",
                "checkCapacity": "2",
                "queryContent": keyword,
            },
            "pageSize": "50",
            "pageNumber": str(page),
            "order": "",
        }
        url = f"{XKFW}/xsxkapp/sys/xsxkapp/elective/{endpoint}"
        r = client.http.post(
            url, data={"querySetting": json.dumps(setting, ensure_ascii=False)}, timeout=30
        )
        try:
            j = r.json()
        except Exception:
            print(f"  [{class_type}] page {page} non-json: {r.text[:200]}", file=sys.stderr)
            break
        raw = j.get("dataList") or []
        all_rows.extend(parse_rows(raw, class_type, has_tc, is_xgxk))
        total = j.get("totalCount") or 0
        try:
            total = int(total)
        except Exception:
            total = len(raw)
        total_pages = max(1, int(math.ceil(total / 50.0))) if total else 1
        if not raw:
            break
        page += 1
        if page > 40:
            break
    return all_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="", help="按课名/教师过滤（服务端+本地）")
    ap.add_argument("--types", default="TJKC,FANKC,FAWKC,XGXK,TYKC")
    ap.add_argument("--batch", default="", help="指定轮次 code；默认选第一个 canSelect=1")
    ap.add_argument("--campus", default="", help="校区代码，默认进入轮次返回值")
    ap.add_argument("--out", default="courses_list")
    args = ap.parse_args()

    client = XkfwClient(str(_ROOT / "session.json"))
    if not client.token:
        print("无 session，请先 python monitor.py --login-only")
        sys.exit(1)
    if not client.is_alive():
        if not client.refresh_token() or not client.is_alive():
            print("会话失效，请重新 login-only")
            sys.exit(1)

    batches = fetch_batches(client)
    print(f"学号 {client.student_code} | 轮次 {len(batches)} 个\n")
    if not batches:
        print("当前没有可选轮次（可能未到开放时间，或账号无批次）。")
        print("开放后再跑本脚本。")
        Path("batches.json").write_text("[]", encoding="utf-8")
        sys.exit(0)

    for b in batches:
        flag = "可选" if str(b.get("canSelect")) == "1" else "不可选"
        print(
            f"  [{flag}] code={b.get('code')} type={b.get('typeCode')}  {b.get('name')}"
        )

    batch = args.batch
    if not batch:
        for b in batches:
            if str(b.get("canSelect")) == "1":
                batch = b.get("code")
                break
        if not batch:
            batch = batches[0].get("code")
            print("\n没有 canSelect=1 的轮次，尝试第一个（可能仍能浏览）…")

    campus = args.campus or enter_round(client, batch)
    print(f"\n使用轮次 code={batch} campus={campus}\n")

    types = [t.strip().upper() for t in args.types.split(",") if t.strip()]
    all_rows: list[dict] = []
    for t in types:
        if t not in QUERY:
            print(f"跳过未知类型 {t}")
            continue
        print(f"拉取 {TYPE_NAME.get(t, t)} ({t}) …")
        rows = fetch_type(client, t, batch, campus, args.keyword)
        print(f"  → {len(rows)} 个教学班")
        all_rows.extend(rows)

    if args.keyword:
        kw = args.keyword.lower()
        all_rows = [
            r
            for r in all_rows
            if kw in (r["course_name"] or "").lower()
            or kw in (r["teacher"] or "").lower()
            or kw in (r["teaching_class_id"] or "").lower()
        ]

    # de-dup by teaching_class_id
    seen = set()
    uniq = []
    for r in all_rows:
        tid = r["teaching_class_id"]
        if not tid or tid in seen:
            continue
        seen.add(tid)
        uniq.append(r)
    all_rows = uniq

    out = Path(args.out)
    if not out.is_absolute():
        out = _ROOT / out
    json_path = out.with_suffix(".json")
    csv_path = out.with_suffix(".csv")
    md_path = out.with_suffix(".md")

    json_path.write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "type_name",
                "class_type",
                "course_name",
                "teacher",
                "teaching_class_id",
                "place",
                "campus",
                "subtype",
            ],
        )
        w.writeheader()
        w.writerows(all_rows)

    lines = [
        f"# 可选教学班列表",
        f"",
        f"- 学号: {client.student_code}",
        f"- 轮次: `{batch}`",
        f"- 校区: `{campus}`",
        f"- 合计: **{len(all_rows)}** 个教学班",
        f"",
        f"| 类型 | 课程 | 教师 | 教学班号 | 地点/时间 | 校区 |",
        f"|------|------|------|----------|-----------|------|",
    ]
    for r in all_rows:
        place = (r.get("place") or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {r['type_name']} | {r['course_name']} | {r['teacher']} | "
            f"`{r['teaching_class_id']}` | {place} | {r.get('campus','')} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n共 {len(all_rows)} 个教学班")
    print(f"  JSON: {json_path.resolve()}")
    print(f"  CSV:  {csv_path.resolve()}")
    print(f"  MD:   {md_path.resolve()}")
    print("\n前 30 条预览:")
    for r in all_rows[:30]:
        print(
            f"  [{r['type_name']}] {r['course_name']} | {r['teacher']} | {r['teaching_class_id']}"
        )
    if len(all_rows) > 30:
        print(f"  … 其余 {len(all_rows)-30} 条见文件")


if __name__ == "__main__":
    main()
