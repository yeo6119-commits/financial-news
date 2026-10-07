# =============================================================
# backfill.py — 한도로 실패한 요약을 다음 실행에서 채운다
#
# 배경: Groq 일일한도가 소진되면 그 회차 기사는 '요약 미제공'으로 저장되는데,
#   예전엔 이걸 다시 시도하는 경로가 없어(retry_summary.py는 로컬 전용이라
#   news.db 충돌 위험) 한도가 풀려도 영영 비어 있었다.
#
# 규칙
#   - 신규 기사 요약이 끝난 뒤에만, 남은 쿼터로 돌린다 (신규가 우선)
#   - 대상은 사유가 레이트리밋/분당한도인 건뿐 — 환각·형식·본문없음은 다시 해도 같다
#   - 쿼터가 다시 막히면 즉시 중단 (한도 실패를 반복 호출하지 않는다)
#   - 기사 1건 = 요약 호출 1회 (배치 금지)
# =============================================================
from datetime import timedelta

import db as dbm
import extractor as ext
import summarizer as smr

LIMIT_REASONS = ("레이트리밋", "분당한도")


def run(conn, cfg) -> tuple[int, int]:
    """(성공 건수, 시도 건수) 반환. 요약이 채워지면 DB에 즉시 커밋한다."""
    bc = (cfg.get("summarizer") or {}).get("backfill") or {}
    if not bc.get("enabled", False):
        return 0, 0
    if smr.all_quota_out(cfg):
        print("  요약 보충: 이번 실행에서 쿼터가 이미 소진돼 건너뜀")
        return 0, 0

    cutoff = (dbm.now_kst() - timedelta(days=bc.get("max_age_days", 14))).isoformat()
    rows = conn.execute(
        """SELECT id, title, naver_url, original_url FROM articles
           WHERE delivered=1 AND summary_ok=0 AND pub_date >= ?
             AND (summary_fail_reason LIKE '레이트리밋%' OR summary_fail_reason LIKE '분당한도%')
           ORDER BY pub_date DESC LIMIT ?""",
        (cutoff, bc.get("max_per_run", 20))).fetchall()
    if not rows:
        return 0, 0

    print(f"요약 보충: 한도로 실패한 {len(rows)}건 재시도")
    ok = tried = 0
    for r in rows:
        if smr.all_quota_out(cfg):
            break
        tried += 1
        art = {"title": r["title"], "naver_url": r["naver_url"] or "",
               "original_url": r["original_url"] or ""}
        ext.extract(art, delay=0.2)
        if not art.get("body"):
            reason = "본문 없음"
        else:
            smr.summarize(art, cfg)
            if art.get("summary_ok"):
                conn.execute(
                    "UPDATE articles SET summary=?, summary_ok=1, summary_fail_reason=NULL "
                    "WHERE id=?", (art["summary"], r["id"]))
                conn.commit()
                ok += 1
                print(f"  보충 OK: {r['title'][:40]}")
                continue
            reason = art.get("summary_fail_reason") or "알 수 없음"
        if reason.startswith(LIMIT_REASONS):
            print("  요약 보충: 쿼터 소진 — 중단 (다음 실행에서 이어서)")
            break
        # 한도가 아닌 사유로 실패 → 사유를 갱신해 같은 건을 다시 집지 않게 한다
        conn.execute("UPDATE articles SET summary_fail_reason=? WHERE id=?", (reason, r["id"]))
        conn.commit()
        print(f"  보충 FAIL({reason[:14]}): {r['title'][:36]}")
    print(f"  요약 보충 결과: {ok}/{tried}건 채움")
    return ok, tried
