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
import html_generator as htm

load_dotenv()


def calc_window(conn, cfg):
    """요청 시각 기준 최근 24시간 고정.
    (직전 실행 시각과 무관 — 기열람 제외로 중복 수록은 방지됨)"""
    now = dbm.now_kst()
    hours = cfg["time"].get("window_hours", 24)
    start = now - timedelta(hours=hours)
    return start, now, None    # truncated_from 없음


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

        # 4) 본문 추출 (통과분만, PR 중 본문 동봉 어댑터는 스킵) — 병렬
        need_extract = []
        for it in survivors:
            if it.get("body"):
                it["extract_ok"], it["extract_fail_reason"] = 1, None
            else:
                need_extract.append(it)
        if need_extract:
            ext.extract_many(need_extract, workers=10)
        for it in items:
            it.setdefault("extract_ok", 0)
            it.setdefault("extract_fail_reason", None)

        # 5) 2차 필터 → 중복 → 분류
        for it in survivors:
            flt.apply_filters(it, cfg)
        ddp.dedup(conn, items, cfg)
        live = [it for it in items if not it.get("excluded")]
        cls_idx = cls.build_index(cfg)
        for it in live:
            cls.classify(it, cfg, cls_idx)

        # 7) 요약 — 캐시 우선 (C안: 이미 요약된 URL이면 Groq 호출 0회)
        cached = 0
        for i, it in enumerate(live, 1):
            hit = dbm.get_cached_summary(conn, it["url_hash"])
            if hit and hit["summary"]:
                it["summary"] = hit["summary"]
                it["summary_ok"] = 1
                it["summary_fail_reason"] = None
                cached += 1
                print(f"  요약 {i}/{len(live)} CACHE: {it['title'][:40]}")
                continue
            smr.summarize(it, cfg)
            mark = "OK" if it["summary_ok"] else "FAIL"
            print(f"  요약 {i}/{len(live)} {mark}: {it['title'][:40]}")
        if cached:
            print(f"  → 캐시 재사용 {cached}건 (Groq 호출 절약)")
        tok = smr.usage_report()
        if tok:
            print(f"  → 토큰 사용 {tok}")

        # 8) DB 저장 — 반영 기사만. 제외 기사는 저장하지 않음(DB 비대화 방지).
        #    제외 목록은 이번 회차분을 메모리에서 HTML로 바로 전달하므로
        #    "조용히 사라지지 않는다"는 원칙은 그대로 유지됨.
        ids = []
        for it in items:
            if it.get("excluded"):
                continue
            row = {k: it.get(k) for k in (
                "title", "norm_title", "press", "pub_date", "original_url", "naver_url",
                "url_hash", "norm_title_hash", "body_hash", "body_fingerprint",
                "fin_group", "subgroup", "company", "sector", "dig_ai", "matched_keywords",
                "search_keyword", "summary", "extract_ok", "summary_ok",
                "extract_fail_reason", "summary_fail_reason", "excluded", "exclude_reason")}
            row["run_id"] = run_id
            row["collected_at"] = dbm.now_kst().isoformat()
            ids.append(dbm.insert_article(conn, row))

        dbm.update_run_stats(
            conn, run_id,
            api_calls=collector.api_calls, keywords_used=len(keywords),
            raw_collected=len(items),
            cutoff_keywords=", ".join(collector.cutoff_keywords) or None)

        # 9) HTML 생성 (성공해야만 다음 단계)
        stats = {
            "generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M}",
            "raw": len(items), "final": len(ids),
            "excluded": len(items) - len(ids),
            "api_calls": collector.api_calls,
            "extract_fail": sum(1 for it in live if not it["extract_ok"]),
            "summary_fail": sum(1 for it in live if not it["summary_ok"]),
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
        history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
        out = htm.render(rows, stats, excluded_rows, cfg["html"]["output_file"], history,
                         cfg.get("github"))
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
