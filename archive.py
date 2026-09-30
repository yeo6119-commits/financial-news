# archive.py — 무제한 누적 아카이브 (월별 CSV, 삭제 없음)
#
# news.db는 60일 보관(retention_days)이라 오래된 기사가 지워진다.
# 이 스크립트는 반영 기사를 archive/YYYY-MM.csv 에 URL 기준으로 "추가만" 한다.
# 기존 행은 지우지 않는다 (요약이 갱신된 경우에만 덮어쓴다).
#
# 사용:
#   python archive.py              현재 news.db → archive/ 병합 (Actions가 매 실행 후 호출)
#   python archive.py --from-git   git 이력의 과거 news.db 전부에서 60일 밖 기사까지 복구
import csv
import os
import sqlite3
import subprocess
import sys
import tempfile

ARCHIVE_DIR = "archive"
COLUMNS = ["pub_date", "company", "fin_group", "title", "summary", "press", "url", "run_id"]
HEADER = ["날짜", "회사", "그룹", "제목", "요약", "매체", "링크", "회차"]
SQL = """
    SELECT pub_date, company, fin_group, title, summary, press,
           COALESCE(NULLIF(naver_url, ''), original_url) AS url, run_id
    FROM articles WHERE excluded = 0
"""


def _clean(key, v):
    s = "" if v is None else str(v)
    if key == "pub_date":
        s = s.replace("T", " ")[:16]
    elif key == "summary":
        s = " / ".join(l.lstrip("- ").strip() for l in s.splitlines() if l.strip())
    return s


def _month_path(pub_date: str) -> str:
    return os.path.join(ARCHIVE_DIR, f"{(pub_date or 'unknown')[:7] or 'unknown'}.csv")


def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        next(r, None)
        return {row[6]: row for row in r if len(row) >= 8}


def merge(rows) -> int:
    """rows(DB 튜플들)를 월별 CSV에 병합. 새로 추가된 건수 반환."""
    by_month = {}
    for r in rows:
        clean = [_clean(k, v) for k, v in zip(COLUMNS, r)]
        if clean[6]:
            by_month.setdefault(_month_path(clean[0]), []).append(clean)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    added = 0
    for path, new in by_month.items():
        cur = _load(path)
        for row in new:
            if row[6] not in cur:
                added += 1
                cur[row[6]] = row
            elif not cur[row[6]][4] and row[4]:      # 빈 요약만 채운다
                cur[row[6]] = row
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for row in sorted(cur.values(), key=lambda x: x[0], reverse=True):
                w.writerow(row)
    return added


def from_db(path) -> list:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(SQL).fetchall()
    finally:
        conn.close()


def from_git() -> int:
    commits = subprocess.run(["git", "log", "--format=%H", "--", "news.db"],
                             capture_output=True, text=True, check=True).stdout.split()
    total = 0
    with tempfile.TemporaryDirectory() as td:
        for i, c in enumerate(reversed(commits), 1):
            p = os.path.join(td, "old.db")
            blob = subprocess.run(["git", "show", f"{c}:news.db"], capture_output=True)
            if blob.returncode != 0 or not blob.stdout:
                continue
            with open(p, "wb") as fh:
                fh.write(blob.stdout)
            try:
                total += merge(from_db(p))
            except sqlite3.DatabaseError:
                continue
            if i % 50 == 0:
                print(f"  {i}/{len(commits)} 커밋 처리, 누적 추가 {total}건")
    return total


def main() -> int:
    if "--from-git" in sys.argv:
        print(f"git 이력 복구: +{from_git()}건")
    if os.path.exists("news.db"):
        print(f"현재 DB 병합: +{merge(from_db('news.db'))}건")
    n = sum(len(_load(os.path.join(ARCHIVE_DIR, f))) for f in os.listdir(ARCHIVE_DIR)) \
        if os.path.isdir(ARCHIVE_DIR) else 0
    print(f"아카이브 총 {n}건 ({ARCHIVE_DIR}/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
