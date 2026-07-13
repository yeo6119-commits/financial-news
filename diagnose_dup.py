"""중복으로 의심되는 기사들의 본문 simhash 해밍거리를 측정.
현재 DB의 최근 회차에서 같은 그룹 기사끼리 거리를 출력 → 임계값 조정 근거."""
import sqlite3, yaml
import deduplicator as d

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = sqlite3.connect(cfg["db"]["path"])
conn.row_factory = sqlite3.Row

# 최근 회차의 delivered 기사
rows = conn.execute(
    """SELECT title, company, fin_group, body_fingerprint, pub_date
       FROM articles WHERE delivered=1 AND body_fingerprint IS NOT NULL
         AND body_fingerprint != '0'
       ORDER BY fin_group, pub_date DESC"""
).fetchall()

print(f"본문 지문 보유 기사 {len(rows)}건\n")
print("=== 같은 그룹 내 본문 해밍거리 ≤10 쌍 (중복 후보) ===\n")

found = 0
for i in range(len(rows)):
    for j in range(i+1, len(rows)):
        a, b = rows[i], rows[j]
        if a["fin_group"] != b["fin_group"]:
            continue
        try:
            dist = d.hamming(int(a["body_fingerprint"],16), int(b["body_fingerprint"],16))
        except (ValueError, TypeError):
            continue
        if dist <= 10:
            found += 1
            print(f"  거리 {dist:2d} | {a['company']} vs {b['company']}")
            print(f"         A: {a['title'][:40]}")
            print(f"         B: {b['title'][:40]}")
            print()

print(f"\n총 {found}쌍. 이 중 실제 중복인 것의 최대 거리를 보고 임계값을 정하면 됨.")
print("(현재 배치 내 임계값=6, 과거분 재탕 임계값=3)")
