"""기존 DB의 company 값을 앱·브랜드명 → 소속 회사로 일괄 정규화.
classifier.BRAND_TO_COMPANY를 그대로 사용하므로 매핑이 한 곳에서 관리됨."""
import sqlite3
import yaml
from classifier import BRAND_TO_COMPANY, _sector_from_name

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = sqlite3.connect(cfg["db"]["path"])
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, company, sector FROM articles WHERE company IS NOT NULL"
).fetchall()

changed = 0
for r in rows:
    old = r["company"]
    new = BRAND_TO_COMPANY.get(old)
    if not new or new == old:
        continue
    sector = "그룹" if new == "신한금융" else _sector_from_name(new)
    conn.execute("UPDATE articles SET company=?, sector=? WHERE id=?",
                 (new, sector, r["id"]))
    changed += 1
    print(f"  {old} → {new} ({sector})")

conn.commit()
print(f"\n총 {changed}건 정규화 완료")

# 결과 확인
print("\n[탭별 회사 분포]")
for row in conn.execute(
    "SELECT fin_group, company, COUNT(*) c FROM articles "
    "WHERE delivered=1 GROUP BY 1,2 ORDER BY 1, c DESC"
):
    print(f"  {row[0]:<12} {row[1]:<18} {row[2]}건")
