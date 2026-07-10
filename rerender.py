import yaml, db as dbm, html_generator as htm
cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = dbm.connect(cfg["db"]["path"])
rows = dbm.get_archive_articles(conn, 60)
stats = {"generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M} (구조 확인용 재렌더링)",
         "raw": 0, "final": len(rows), "excluded": 0, "api_calls": 0,
         "extract_fail": 0, "summary_fail": 0, "press_health": {}}
out = htm.render(rows, stats, [], cfg["html"]["output_file"])
print(f"HTML 재생성 완료: {out} (기사 {len(rows)}건)")
