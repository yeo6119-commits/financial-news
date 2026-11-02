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
import re
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


_EN_TAG = "(영문 재시도)"


def retry_english(conn, cfg, limit: int = 5) -> tuple[int, int]:
    """영문 기사가 예전 근거 검사에 '환각'으로 폐기된 건을 새 검사(영문 전용)로 한 번만 다시 요약한다.

    한글 기사의 환각 폐기는 건드리지 않는다(같은 프롬프트로 다시 해도 같은 결과).
    사유에 '(영문 재시도)'를 남겨 기사당 1회만 시도한다.
    """
    if not (cfg.get("summarizer") or {}).get("backfill", {}).get("enabled", False):
        return 0, 0
    if smr.all_quota_out(cfg):
        return 0, 0
    cutoff = (dbm.now_kst() - timedelta(days=(cfg["summarizer"]["backfill"]).get("max_age_days", 14))).isoformat()
    rows = conn.execute(
        """SELECT id, title, company, naver_url, original_url, summary_fail_reason FROM articles
           WHERE delivered=1 AND summary_ok=0 AND extract_ok=1 AND pub_date >= ?
             AND summary_fail_reason LIKE '환각%' AND summary_fail_reason NOT LIKE ?
             AND title NOT GLOB '*[가-힣]*'
           ORDER BY pub_date DESC LIMIT ?""", (cutoff, "%" + _EN_TAG + "%", limit)).fetchall()
    if not rows:
        return 0, 0
    print(f"영문 기사 재요약: {len(rows)}건 다시 시도")
    ok = 0
    for r in rows:
        art = {"title": r["title"], "company": r["company"],
               "naver_url": r["naver_url"] or "", "original_url": r["original_url"] or ""}
        ext.extract(art, delay=0.2)
        if art.get("body"):
            smr.summarize(art, cfg)
        if art.get("summary_ok"):
            conn.execute("UPDATE articles SET summary=?, summary_ok=1, summary_fail_reason=NULL WHERE id=?",
                         (art["summary"], r["id"]))
            ok += 1
            print(f"  영문 재요약 OK: {r['title'][:50]}")
        else:
            why = art.get("summary_fail_reason") or r["summary_fail_reason"]
            if why.startswith(LIMIT_REASONS):      # 쿼터 문제면 시도 기록을 남기지 않고 중단
                break
            conn.execute("UPDATE articles SET summary_fail_reason=? WHERE id=?", (why + " " + _EN_TAG, r["id"]))
            print(f"  영문 재요약 실패({why[:12]}): {r['title'][:40]}")
        conn.commit()
    return ok, len(rows)


# -------------------------------------------------------------
# 본문 오추출로 잘못 저장된 요약 복구 (2026-11)
#   날씨 위젯·'다른 기사' 소개문이 본문으로 잡혀 제목과 다른 요약이 저장되거나, 잡음 본문 탓에
#   요약이 '환각'으로 폐기되어 비었던 기사들이다. 추출기는 고쳤지만 이미 저장된 카드는 그대로라서,
#   config의 summarizer.repair.article_ids에 적은 기사만 새 추출기로 다시 처리한다.
#   - 본문을 다시 받아 기존 요약이 새 본문에 근거하면(근거율 ≥ keep_ratio) 그대로 둔다(LLM 호출 없음)
#   - 아니면 다시 요약한다. 다시 요약해도 안 되면 틀린 요약은 지운다 — 오요약은 빈칸보다 나쁘다
#   - 처리 표지는 extract_fail_reason에 남긴다(본문 추출에 성공한 기사에서는 쓰지 않는 칸).
#     완료·시도 횟수가 표지로 남아 같은 기사를 다시 집지 않으므로, 목록을 config에 남겨 둬도 안전하다
#   - 신규 요약이 끝난 뒤 남는 쿼터로만, 회차당 max_per_run건까지 (기사 1건 = 요약 호출 1회, 배치 금지)
# -------------------------------------------------------------
_REPAIR_DONE = "(요약 복구 완료)"
_REPAIR_TRY = re.compile(r"\(요약 복구 시도 (\d+)회\)")
_REPAIR_MAX_TRIES = 2           # 본문을 못 받은 건은 이 횟수까지만 (계속 막히는 매체 반복 방지)


def _repair_tries(note) -> int:
    m = _REPAIR_TRY.search(note or "")
    return int(m.group(1)) if m else 0


def repair_wrong_body(conn, cfg) -> tuple[int, int]:
    """(복구 건수, 처리 건수) 반환. 기사마다 DB에 즉시 커밋한다."""
    rc = (cfg.get("summarizer") or {}).get("repair") or {}
    ids = list(rc.get("article_ids") or [])
    per_run = rc.get("max_per_run", 0)
    keep_ratio = rc.get("keep_ratio", 0.40)
    if not ids or per_run <= 0:
        return 0, 0
    if smr.all_quota_out(cfg):
        print("  요약 복구: 이번 실행에서 쿼터가 소진돼 건너뜀")
        return 0, 0

    rows = conn.execute(
        "SELECT id, title, summary, naver_url, original_url, extract_fail_reason FROM articles "
        "WHERE delivered=1 AND id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
    order = {i: n for n, i in enumerate(ids)}          # config에 적은 순서 = 우선순위
    rows = [r for r in sorted(rows, key=lambda r: order[r["id"]])
            if _REPAIR_DONE not in (r["extract_fail_reason"] or "")
            and _repair_tries(r["extract_fail_reason"]) < _REPAIR_MAX_TRIES][:per_run]
    if not rows:
        return 0, 0

    print(f"요약 복구: 본문 오추출 의심 {len(rows)}건 다시 처리")
    fixed = 0
    for r in rows:
        if smr.all_quota_out(cfg):
            break
        art = {"title": r["title"], "naver_url": r["naver_url"] or "",
               "original_url": r["original_url"] or ""}
        ext.extract(art, delay=0.2)
        if not art.get("body"):
            n = _repair_tries(r["extract_fail_reason"]) + 1
            conn.execute("UPDATE articles SET extract_fail_reason=? WHERE id=?",
                         ("(요약 복구 시도 %d회)" % n, r["id"]))
            conn.commit()
            print(f"  복구 보류(본문 못 받음 {n}회): {r['title'][:36]}")
            continue

        old = (r["summary"] or "").strip()
        if old:
            smr._grounded(old, r["title"], smr.compact_body(art["body"], cfg["summarizer"].get("body_chars", 1100)))
            if smr.is_english(art["body"]) or smr.LAST_GROUND_RATIO >= keep_ratio:
                conn.execute("UPDATE articles SET extract_fail_reason=? WHERE id=?", (_REPAIR_DONE, r["id"]))
                conn.commit()
                print(f"  복구 불필요(요약이 본문에 근거): {r['title'][:36]}")
                continue

        smr.summarize(art, cfg)
        if art.get("summary_ok"):
            conn.execute("UPDATE articles SET summary=?, summary_ok=1, summary_fail_reason=NULL, "
                         "extract_fail_reason=? WHERE id=?", (art["summary"], _REPAIR_DONE, r["id"]))
            conn.commit()
            fixed += 1
            print(f"  복구 OK: {r['title'][:40]}")
            continue
        why = art.get("summary_fail_reason") or "알 수 없음"
        if why.startswith(LIMIT_REASONS):
            print("  요약 복구: 쿼터 소진 — 중단 (다음 실행에서 이어서)")
            break
        # 다시 요약해도 안 되는 기사: 틀린 요약이 남아 있으면 지우고 사유를 보인다
        conn.execute("UPDATE articles SET summary=NULL, summary_ok=0, summary_fail_reason=?, "
                     "extract_fail_reason=? WHERE id=?", (why, _REPAIR_DONE, r["id"]))
        conn.commit()
        print(f"  복구 FAIL({why[:14]}){' — 틀린 요약 삭제' if old else ''}: {r['title'][:34]}")
    print(f"  요약 복구 결과: {fixed}/{len(rows)}건")
    return fixed, len(rows)
