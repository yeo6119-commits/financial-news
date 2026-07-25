# export_csv.py — 누적 DB를 구글 시트/엑셀에서 볼 수 있는 CSV로 내보낸다.
#
# 산출물 2개:
#   news_archive.csv        저장소 루트 — 구글 시트 IMPORTDATA 용 (raw URL로 직접 읽힘)
#   output/news_archive.csv GitHub Pages 용 (브라우저에서 다운로드)
#
# 왜 CSV인가:
#   구글 시트 API를 쓰려면 서비스 계정 키를 secrets에 넣고 권한을 관리해야 한다.
#   저장소가 public이므로 CSV 한 장을 커밋하면 시트가 IMPORTDATA로 매번 읽어간다.
#   운영비 0원 원칙을 지키면서 자동 갱신이 된다.
import csv
import os
import sqlite3
import sys

import yaml

COLUMNS = [
    ("pub_date", "날짜"),
    ("company", "회사"),
    ("fin_group", "그룹"),
    ("title", "제목"),
    ("summary", "요약"),
    ("press", "매체"),
    ("url", "링크"),
    ("run_id", "회차"),
]

# 그룹 코드 → 화면 표기 (HTML 탭과 맞춘다)
GROUP_LABEL = {
    "kb": "KB", "shinhan": "신한", "hana": "하나", "woori": "우리",
    "nh": "NH", "internet": "핀테크", "overseas": "해외",
    "securities": "증권", "cardins": "카드·보험", "regional": "지방",
    "policy": "정책", "nonholding": "비지주", "etc": "기타",
}


def rows(conn, limit_days: int | None = None):
    sql = """
        SELECT pub_date, company, fin_group, title, summary, press,
               COALESCE(NULLIF(naver_url, ''), original_url) AS url, run_id
        FROM articles
        WHERE excluded = 0
    """
    if limit_days:
        sql += " AND collected_at >= datetime('now', ?)"
    sql += " ORDER BY pub_date DESC, id DESC"
    cur = conn.execute(sql, (f"-{limit_days} days",) if limit_days else ())
    return cur.fetchall()


def clean(value, key: str) -> str:
    """셀 하나를 시트에서 읽기 좋게 다듬는다."""
    if value is None:
        return ""
    s = str(value)
    if key == "pub_date":
        # 2026-07-23T14:41:00+09:00 → 2026-07-23 14:41 (시트가 날짜로 인식)
        s = s.replace("T", " ")[:16]
    elif key == "summary":
        # 개조식 여러 줄 → 한 셀. 줄바꿈은 셀 안에서 깨지므로 ' / '로 잇는다.
        s = " / ".join(l.lstrip("- ").strip() for l in s.splitlines() if l.strip())
    elif key == "fin_group":
        s = GROUP_LABEL.get(s, s or "")
    return s


def write_csv(path: str, data: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        # utf-8-sig: 엑셀에서 한글이 깨지지 않도록 BOM을 붙인다.
        w = csv.writer(fh)
        w.writerow([label for _, label in COLUMNS])
        for r in data:
            w.writerow([clean(r[i], key) for i, (key, _) in enumerate(COLUMNS)])


def main() -> int:
    with open("config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    db_path = cfg["db"]["path"]
    if not os.path.exists(db_path):
        print(f"⚠ DB 없음: {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    data = rows(conn)
    if not data:
        print("⚠ 내보낼 기사 없음")
        return 0

    write_csv("news_archive.csv", data)
    write_csv(os.path.join("output", "news_archive.csv"), data)
    print(f"CSV 내보내기 완료: {len(data)}건 → news_archive.csv, output/news_archive.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
