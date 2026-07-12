"""재수집 없이 DB의 delivered 기사만으로 HTML 재생성 (구조 확인용)"""
import yaml
import db as dbm
import html_generator as htm

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = dbm.connect(cfg["db"]["path"])
rows = dbm.get_archive_articles(conn, cfg["db"]["retention_days"])
history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
stats = {"generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M} (재렌더링)",
         "raw": 0, "final": len(rows), "excluded": 0, "api_calls": 0,
         "extract_fail": 0, "summary_fail": 0, "press_health": {}}
out = htm.render(rows, stats, [], cfg["html"]["output_file"], history)
print(f"HTML 재생성 완료: {out}")
print(f"  기사 {len(rows)}건 / 회차 {len(history)}회")
