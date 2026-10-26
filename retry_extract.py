# =============================================================
# retry_extract.py — 본문 '접속 실패'로 요약이 비었던 기사를 다시 가져온다
#
# 배경: 로컬에선 1초 안에 열리는 매체가 Actions(해외 서버)에서만 간헐적으로 접속에 실패해
#   '본문 추출 실패 → 요약 없음'으로 남았고, 다시 시도하는 경로가 없었다
#   (최근 21일 반영 986건 중 25건). 대부분 일시적이라 다음 실행에서 다시 하면 풀린다.
#
# 규칙
#   - 대상은 사유에 '접속 실패'가 든 건만 — 유료·구조 문제('원문 추출 실패')는 다시 해도 같다
#   - 같은 기사는 extract_max_tries회까지만 (사유에 '(재시도 N회)'를 남겨 센다)
#   - Groq 쿼터가 남아 있을 때만 (본문을 가져와도 요약을 못 하면 시도 횟수만 소모되므로 건너뜀)
#   - 기사 1건 = 요약 호출 1회 (배치 금지)
# =============================================================
import re
from datetime import timedelta

import db as dbm
import extractor as ext
import summarizer as smr

LIMIT_REASONS = ("레이트리밋", "분당한도")
_TRY = re.compile(r"\s*\(재시도 (\d+)회\)")


def _tries(reason) -> int:
    m = _TRY.search(reason or "")
    return int(m.group(1)) if m else 0


def _mark(reason: str, n: int) -> str:
    return "%s (재시도 %d회)" % (_TRY.sub("", reason or "").strip(), n)


def run(conn, cfg) -> tuple[int, int]:
    """(채운 건수, 시도 건수) 반환. 기사마다 DB에 즉시 커밋한다."""
    bc = (cfg.get("summarizer") or {}).get("backfill") or {}
    per_run = bc.get("extract_retry_per_run", 0)
    max_tries = bc.get("extract_max_tries", 3)
    if not bc.get("enabled", False) or per_run <= 0:
        return 0, 0
    if smr.all_quota_out(cfg):
        print("  본문 재추출: 이번 실행에서 요약 쿼터가 소진돼 건너뜀")
        return 0, 0

    cutoff = (dbm.now_kst() - timedelta(days=bc.get("max_age_days", 14))).isoformat()
    rows = conn.execute(
        """SELECT id, title, naver_url, original_url, extract_fail_reason FROM articles
           WHERE delivered=1 AND extract_ok=0 AND summary_ok=0 AND pub_date >= ?
             AND extract_fail_reason LIKE '%접속 실패%'
           ORDER BY pub_date DESC LIMIT 200""", (cutoff,)).fetchall()
    rows = [r for r in rows if _tries(r["extract_fail_reason"]) < max_tries][:per_run]
    if not rows:
        return 0, 0

    print(f"본문 재추출: 접속 실패했던 {len(rows)}건 다시 시도")
    ok = tried = 0
    for r in rows:
        if smr.all_quota_out(cfg):
            break
        tried += 1
        art = {"title": r["title"], "naver_url": r["naver_url"] or "",
               "original_url": r["original_url"] or ""}
        ext.extract(art, delay=0.2)
        if not art.get("body"):
            reason = art.get("extract_fail_reason") or "원문 접속 실패"
            n = _tries(r["extract_fail_reason"]) + 1
            # 이번엔 접속이 됐는데 본문이 없다면('원문 추출 실패') 사유가 바뀌어 다음부턴 대상에서 빠진다
            conn.execute("UPDATE articles SET extract_fail_reason=? WHERE id=?",
                         (_mark(reason, n), r["id"]))
            conn.commit()
            print(f"  재추출 실패({n}/{max_tries}): {r['title'][:36]}")
            continue

        smr.summarize(art, cfg)
        reason = None if art.get("summary_ok") else (art.get("summary_fail_reason") or "알 수 없음")
        conn.execute(
            """UPDATE articles SET extract_ok=1, extract_fail_reason=NULL,
                   press=COALESCE(NULLIF(press, ''), ?), summary=?, summary_ok=?, summary_fail_reason=?
               WHERE id=?""",
            (art.get("press") or "", art.get("summary") if art.get("summary_ok") else None,
             1 if art.get("summary_ok") else 0, reason, r["id"]))
        conn.commit()
        if art.get("summary_ok"):
            ok += 1
            print(f"  재추출 OK: {r['title'][:40]}")
        else:
            print(f"  재추출 본문 확보·요약 실패({reason[:14]}): {r['title'][:30]}")
            if reason.startswith(LIMIT_REASONS):
                print("  본문 재추출: 요약 쿼터 소진 — 중단 (다음 실행에서 이어서)")
                break
    print(f"  본문 재추출 결과: {ok}/{tried}건 채움")
    return ok, tried
