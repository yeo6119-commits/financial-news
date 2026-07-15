"""요약 실패 기사 재시도 (재수집 없음)

DB에 delivered=1 이지만 summary_ok=0 인 기사만 골라
본문을 다시 추출하고 Groq 요약을 재시도한다.

- 레이트리밋으로 실패했던 건들이 쿼터 회복 후 채워짐
- '본문 없음' 건도 본문 재추출로 복구 시도
- 429가 연속으로 나면 즉시 중단 (쿼터 소진 → 다음 날 다시)

사용:  python retry_summary.py           (전체 재시도)
       python retry_summary.py 30        (30건만 — 쿼터 아껴 쓰기)
"""
import sys
import sqlite3
import yaml
from dotenv import load_dotenv

import extractor as ext
import summarizer as smr
import db as dbm
import html_generator as htm

load_dotenv(".env")
cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

conn = dbm.connect(cfg["db"]["path"])
q = """SELECT id, title, naver_url, original_url, summary_fail_reason
       FROM articles WHERE delivered=1 AND summary_ok=0
       ORDER BY pub_date DESC"""
rows = [dict(r) for r in conn.execute(q).fetchall()]
if limit:
    rows = rows[:limit]

if not rows:
    print("재시도할 요약 실패 기사가 없습니다.")
    sys.exit(0)

print(f"요약 실패 {len(rows)}건 재시도 (모델: {cfg['summarizer']['model']})")
print("=" * 52)

ok = fail = 0
rate_limited = 0
for i, r in enumerate(rows, 1):
    art = {"title": r["title"], "naver_url": r["naver_url"] or "",
           "original_url": r["original_url"] or ""}
    ext.extract(art, delay=0.2)
    if not art.get("body"):
        print(f"  {i}/{len(rows)} 본문 실패: {r['title'][:38]}")
        fail += 1
        continue

    smr.summarize(art, cfg)
    if art.get("summary_ok"):
        conn.execute(
            "UPDATE articles SET summary=?, summary_ok=1, summary_fail_reason=NULL WHERE id=?",
            (art["summary"], r["id"]))
        conn.commit()
        ok += 1
        rate_limited = 0
        print(f"  {i}/{len(rows)} OK: {r['title'][:38]}")
    else:
        reason = art.get("summary_fail_reason") or "알 수 없음"
        conn.execute("UPDATE articles SET summary_fail_reason=? WHERE id=?", (reason, r["id"]))
        conn.commit()
        fail += 1
        print(f"  {i}/{len(rows)} FAIL({reason[:14]}): {r['title'][:30]}")
        if "레이트리밋" in reason or "429" in reason:
            rate_limited += 1
            if rate_limited >= 3:
                print("\n  ⚠ 레이트리밋 연속 3회 — 쿼터 소진으로 판단, 중단합니다.")
                print("    (Groq 무료 한도는 한국시간 오전 9시에 리셋됩니다)")
                break
        else:
            rate_limited = 0

print("=" * 52)
print(f" 재시도 결과: 성공 {ok} / 실패 {fail}")

if ok:
    rows_all = dbm.get_archive_articles(conn, cfg["db"]["retention_days"])
    history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
    stats = {"generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M} (요약 재시도)",
             "raw": 0, "final": len(rows_all), "excluded": 0, "api_calls": 0,
             "extract_fail": 0, "summary_fail": 0, "press_health": {}}
    out = htm.render(rows_all, stats, [], cfg["html"]["output_file"], history, cfg.get("github"))
    print(f" HTML 갱신: {out}")
    print(f" 남은 요약 실패: "
          f"{conn.execute('SELECT COUNT(*) FROM articles WHERE delivered=1 AND summary_ok=0').fetchone()[0]}건")
