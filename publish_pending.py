#!/usr/bin/env python3
"""취소된 실행들이 쌓아둔 미게시(delivered=0) 기사를 강제로 게시한다.
main.py 완주 없이, 이미 검토·요약까지 끝난 기사를 delivered=1로 올리고
HTML을 재생성한다. (재요약·재검토는 하지 않음 — 이미 끝난 데이터 그대로 사용)
"""
import yaml
import db as dbm
import html_generator as htm

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = dbm.connect(cfg["db"]["path"])

pending = conn.execute(
    "SELECT id FROM articles WHERE delivered=0 AND summary_ok=1"
).fetchall()
ids = [r[0] for r in pending]
print(f"미게시 기사 {len(ids)}건 발견")

if ids:
    conn.execute(
        "UPDATE articles SET delivered=1, delivered_at=? WHERE id IN (%s)" %
        ",".join("?" * len(ids)),
        [dbm.now_kst().isoformat()] + ids)
    conn.commit()
    print(f"{len(ids)}건 delivered=1 로 마킹 완료")

rows_all = dbm.get_archive_articles(conn, cfg["db"]["retention_days"])
history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
stats = {"generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M} (미게시분 강제 게시)",
         "raw": 0, "final": len(rows_all), "excluded": 0, "api_calls": 0,
         "extract_fail": 0, "summary_fail": 0, "press_health": {}}

out = htm.render(rows_all, stats, [], cfg["html"]["output_file"], history, cfg.get("github"))
print(f"HTML 갱신: {out}")
print(f"전체 기사(아카이브): {len(rows_all)}건")
