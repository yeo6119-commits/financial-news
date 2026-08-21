# =============================================================
# main.py — 파이프라인 조립 (v2.3)
# 순서가 곧 안전장치: HTML 성공 후에만 delivered
# =============================================================
import os
from datetime import datetime, timedelta

import yaml
from dotenv import load_dotenv

import db as dbm
import collector as col
import press_collector as prc
import extractor as ext
import filter as flt
import deduplicator as ddp
import classifier as cls
import summarizer as smr
import reviewer as rvw
import html_generator as htm

load_dotenv()


def calc_window(conn, cfg):
    """검색 구간 결정.

    incremental: true 이면 '직전 성공 실행 이후 ~ 지금'만 본다.
      아침 정기 실행은 window_hours(24h)를 그대로 쓰고,
      낮에 수동 재실행하면 직전 실행 시각부터만 훑는다.
    범위가 지나치게 좁으면(min_hours 미만) 경계 기사 누락을 막기 위해 넓힌다.
    직전 실행 기록이 없으면 기존 방식(24시간)으로 되돌아간다.
    """
    now = dbm.now_kst()
    tcfg = cfg.get("time", {})
    hours = tcfg.get("window_hours", 24)
    full_start = now - timedelta(hours=hours)

    if not tcfg.get("incremental"):
        return full_start, now, None

    row = conn.execute(
        "SELECT requested_at FROM runs WHERE status='success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row or not row[0]:
        return full_start, now, None

    try:
        last = datetime.fromisoformat(row[0])
    except ValueError:
        return full_start, now, None

    # 겹침 여유 — 직전 실행 직전에 올라온 기사가 새지 않도록 조금 앞에서 시작
    lap = tcfg.get("overlap_minutes", 20)
    start = last - timedelta(minutes=lap)
    # 너무 좁은 구간은 의미가 없다 (최소 min_hours 확보)
    min_h = tcfg.get("min_hours", 3)
    if (now - start) < timedelta(hours=min_h):
        start = now - timedelta(hours=min_h)
    # 공백이 길었으면 그만큼 따라잡는다.
    #   예전에는 window_hours(24h)로 잘라내서, 주말처럼 이틀 쉬면
    #   그 사이 기사가 통째로 사라졌다(실측: 36시간 공백 → 12시간치 소실).
    #   자동 스케줄이 늘 도는 게 보장되지 않으므로 상한을 따로 둔다.
    catch_h = max(hours, tcfg.get("max_catchup_hours", 72))
    hard_start = now - timedelta(hours=catch_h)
    if start < hard_start:
        start = hard_start
    span = (now - start).total_seconds() / 3600
    if span > hours + 0.5:
        print(f"  ↺ 공백 따라잡기: 직전 실행 이후 {span:.1f}시간 구간을 훑습니다")
    return start, now, None


def main():
    with open("config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    conn = dbm.connect(cfg["db"]["path"])
    dbm.cleanup(conn, cfg["db"]["retention_days"], cfg["db"].get("excluded_retention_days", 14))

    # 1) 검색 기간
    t0 = dbm.now_kst()
    start, end, truncated_from = calc_window(conn, cfg)
    run_id = dbm.start_run(conn, start, end,
                           truncated=bool(truncated_from), truncated_from=truncated_from)
    WEEK = "월화수목금토일"
    print("=" * 52)
    print(f" 요청 시각   {t0:%Y-%m-%d} ({WEEK[t0.weekday()]}) {t0:%H:%M:%S}")
    print(f" 검색 구간   {start:%m-%d %H:%M} ~ {end:%m-%d %H:%M}"
          + (f"  ⚠ 72h 초과 잘림: {truncated_from:%m-%d %H:%M} 이전 미수집" if truncated_from else ""))
    print(f" 실행 회차   run {run_id}")
    print("=" * 52)

    try:
        # 2) 수집 — 뉴스 + 보도자료
        keywords = col.build_keywords(cfg)
        collector = col.Collector(cfg)
        news_items = collector.collect_all(keywords, start, end)
        press_items, press_health = prc.collect_press(start)
        print(f"뉴스 {len(news_items)}건 / 보도자료 {len(press_items)}건 / "
              f"API {collector.api_calls}콜 / 키워드 {len(keywords)}개")
        for k, v in press_health.items():
            if not v.startswith("ok"):
                print(f"  ⚠ PR 어댑터 {k}: {v}")

        items = news_items + press_items
        # 회차 내 URL 완전중복 제거 (뉴스·PR 소스 간)
        seen, uniq = set(), []
        for it in items:
            if it["url_hash"] in seen:
                continue
            seen.add(it["url_hash"])
            uniq.append(it)
        items = uniq

        # 3) 1차 스크리닝 — 제목만으로 판정 (본문 추출 전, 비용 절감의 핵심)
        companies = flt.company_keywords(cfg)
        relevance = flt.relevance_keywords(cfg)
        for it in items:
            if (it.get("search_keyword") or "").startswith("[PR]"):
                it["excluded"] = 0          # 보도자료는 1차 스크리닝 면제
                continue
            flt.prescreen(it, cfg, companies, relevance)
        survivors = [it for it in items if not it.get("excluded")]
        print(f"1차 스크리닝: {len(items)}건 → {len(survivors)}건 통과")
        if not survivors:
            print("  ⚠ 통과 0건 — 필터가 과하게 걸러냈을 수 있음")

        # 4) 본문 추출 (통과분만, PR 중 본문 동봉 어댑터는 스킵) — 병렬
        need_extract = []
        for it in survivors:
            if it.get("body"):
                it["extract_ok"], it["extract_fail_reason"] = 1, None
            else:
                need_extract.append(it)
        if need_extract:
            ext.extract_many(need_extract, workers=24)
        for it in items:
            it.setdefault("extract_ok", 0)
            it.setdefault("extract_fail_reason", None)

        # 5) 2차 필터 → 중복 → 분류
        for it in survivors:
            flt.apply_filters(it, cfg)
        ddp.dedup(conn, items, cfg)
        live = [it for it in items if not it.get("excluded")]
        print(f"2차 필터·중복제거: {len(survivors)}건 → {len(live)}건 반영")
        if survivors and not live:
            print("  ⚠ 전부 중복/무관 — 직전 회차와 같은 기사만 잡혔을 수 있음")
        cls_idx = cls.build_index(cfg)
        for it in live:
            cls.classify(it, cfg, cls_idx)
        # 검토·요약·중복제거·저장을 청크 단위로 묶어 처리한다.
        #   예전엔 review_many/summarize/dedup_by_summary/insert가 전부
        #   live 전체(수백 건)에 대해 한 번에 실행됐다. 타임아웃으로 중간에
        #   취소되면 맨 끝의 insert에 도달하지 못해 DB에 아무 것도 안 남았다
        #   (if: always()로 커밋 스텝은 살렸지만 커밋할 신규 행 자체가 없었음
        #    — 2026-08-21 실제 운영에서 확인된 문제).
        #   청크가 끝날 때마다 즉시 저장하므로, 다음 청크 처리 중 취소돼도
        #   이전 청크까지는 DB에 남는다.
        CHUNK = cfg.get("pipeline", {}).get("chunk_size", 40)
        total_live = len(live)
        ids = []
        final_live = []
        processed = 0
        excluded_by_review = 0
        cached = 0

        for start in range(0, total_live, CHUNK):
            chunk = live[start:start + CHUNK]

            rvw.review_many(chunk, cfg)
            before = len(chunk)
            chunk = [it for it in chunk if not it.get("excluded")]
            excluded_by_review += before - len(chunk)

            for it in chunk:
                processed += 1
                hit = dbm.get_cached_summary(conn, it["url_hash"])
                if hit and hit["summary"]:
                    it["summary"] = hit["summary"]
                    it["summary_ok"] = 1
                    it["summary_fail_reason"] = None
                    cached += 1
                    print(f"  요약 {processed}/{total_live} CACHE: {it['title'][:40]}")
                    continue
                smr.summarize(it, cfg)
                mark = "OK" if it["summary_ok"] else "FAIL"
                print(f"  요약 {processed}/{total_live} {mark}: {it['title'][:40]}")

            before_sum_dedup = len(chunk)
            ddp.dedup_by_summary(chunk, cfg, conn)
            chunk = [it for it in chunk if not it.get("excluded")]
            if before_sum_dedup != len(chunk):
                print(f"  요약 기반 중복 제거: {before_sum_dedup}건 → {len(chunk)}건 (이 청크)")

            for it in chunk:
                row = {k: it.get(k) for k in (
                    "title", "norm_title", "press", "pub_date", "original_url", "naver_url",
                    "url_hash", "norm_title_hash", "body_hash", "body_fingerprint",
                    "fin_group", "subgroup", "company", "sector", "dig_ai", "matched_keywords",
                    "search_keyword", "summary", "extract_ok", "summary_ok",
                    "extract_fail_reason", "summary_fail_reason", "excluded", "exclude_reason")}
                row["run_id"] = run_id
                row["collected_at"] = dbm.now_kst().isoformat()
                ids.append(dbm.insert_article(conn, row))

            final_live.extend(chunk)
            print(f"  ↳ 청크 저장 완료: {min(start+CHUNK, total_live)}/{total_live} "
                  f"— 누적 반영 {len(ids)}건 (DB 커밋됨, 중단돼도 유지)")

        if excluded_by_review:
            print(f"검토 후: 에이전트가 {excluded_by_review}건 제외")
        if cached:
            print(f"  → 캐시 재사용 {cached}건 (Groq 호출 절약)")
        tok = smr.usage_report()
        if tok:
            print(f"  → 토큰 사용 {tok}")

        live = final_live  # 이후 통계·HTML 코드는 최종 생존 리스트를 그대로 사용 (기존과 동일)

        # 제외 목록은 이번 회차분을 메모리에서 HTML로 바로 전달하므로
        # "조용히 사라지지 않는다"는 원칙은 그대로 유지됨.
        # 제외분은 경량 로그로 남긴다 (본문·요약 제외 → 용량 부담 없음).
        #   회차 하나가 아니라 기간 전체로 추적 가능해야 과도 필터링을 잡아낸다.
        n_ex = dbm.log_excluded(conn, run_id, items)
        if n_ex:
            print(f"  제외 로그 {n_ex}건 기록")

        dbm.update_run_stats(
            conn, run_id,
            api_calls=collector.api_calls, keywords_used=len(keywords),
            raw_collected=len(items),
            cutoff_keywords=", ".join(collector.cutoff_keywords) or None)

        # 9) HTML 생성 (성공해야만 다음 단계)
        # 제외 사유별 집계 — 어느 단계에서 걸렀는지 한눈에 보이도록
        from collections import Counter
        reason_counts = Counter(
            (it.get("exclude_reason") or "기타").split("(")[0]
            for it in items if it.get("excluded"))

        stats = {
            "generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M}",
            "raw": len(items), "final": len(ids),
            "excluded": len(items) - len(ids),
            "api_calls": collector.api_calls,
            "screened": len(survivors),          # 1차 스크리닝 통과
            "deduped": len(live),                # 중복 제거 후 남은 수
            # 추출·요약 실패는 '추출을 시도한 모수' 기준이라야 의미가 있다
            "extract_fail": sum(1 for it in survivors if not it["extract_ok"]),
            "summary_fail": sum(1 for it in live if not it["summary_ok"]),
            "exclude_reasons": dict(reason_counts.most_common(6)),
            "cutoff_keywords": ", ".join(collector.cutoff_keywords),
            "truncated_from": truncated_from.isoformat() if truncated_from else None,
            "press_health": press_health,
        }
        # delivered 예정분을 아카이브에 포함시키기 위해 임시 delivered 마킹 없이
        # 이번 회차분 + 기존 delivered를 함께 렌더링
        conn.execute("UPDATE articles SET delivered=1 WHERE id IN (%s)" %
                     ",".join("?" * len(ids)), ids) if ids else None
        rows = dbm.get_archive_articles(conn, cfg["db"]["retention_days"])
        conn.rollback()  # 임시 마킹 취소 — 실제 delivered는 HTML 성공 후 커밋
        # 제외 목록: 메모리에서 직접 구성 (DB 저장 안 함)
        excluded_rows = [
            {"title": it.get("title"), "press": it.get("press"),
             "pub_date": it.get("pub_date"), "exclude_reason": it.get("exclude_reason")}
            for it in items if it.get("excluded")
        ]
        # 1차 통과분의 최종 행방 — 중복 제거가 타당했는지 검수용
        screened_rows = [
            {"title": it.get("title"), "press": it.get("press"),
             "company": it.get("company"), "pub_date": it.get("pub_date"),
             "naver_url": it.get("naver_url") or it.get("original_url"),
             "excluded": it.get("excluded"),
             "exclude_reason": it.get("exclude_reason"),
             "dup_members": it.get("_dup_members") or [],
             "dup_ref": it.get("_dup_ref"),
             "dup_ref_company": it.get("_dup_ref_company"),
             "dup_ref_date": it.get("_dup_ref_date"),
             "dup_ref_url": it.get("_dup_ref_url")}
            for it in survivors
        ]
        history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
        out = htm.render(rows, stats, excluded_rows, cfg["html"]["output_file"], history,
                         cfg.get("github"), screened_rows)
        print(f"HTML 생성: {out}")

        # 10) delivered 트랜잭션 (HTML rename 성공 후에만)
        dbm.commit_delivered(conn, run_id, ids)
        t1 = dbm.now_kst()
        el = int((t1 - t0).total_seconds())
        ok = sum(1 for it in live if it.get("summary_ok"))
        print("=" * 52)
        print(f" 완료 시각   {t1:%Y-%m-%d %H:%M:%S}   (소요 {el//60}분 {el%60}초)")
        print(f" 반영 {len(ids)}건 / 제외 {len(items) - len(ids)}건"
              f"  ·  요약 성공 {ok}/{len(live)}"
              + (f" (캐시 {cached})" if cached else ""))
        print(f" 결과 보기   open {cfg['html']['output_file']}")
        print("=" * 52)

    except Exception:
        dbm.fail_run(conn, run_id)
        raise


if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    main()
