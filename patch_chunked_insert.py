#!/usr/bin/env python3
"""main.py를 배치 통삽입 -> 청크 단위 즉시삽입 구조로 변경 (일회성 패치)

문제: review_many + summarize + dedup_by_summary + insert가 전부 batch 끝에
      한꺼번에 실행돼서, 타임아웃으로 중간에 취소되면 DB에 아무것도 안 남는다.
      (if: always()로 DB 커밋 스텝은 살렸지만, 커밋할 신규 행 자체가 없었음
       — 2026-08-21 실제 운영에서 확인)

해결: live를 CHUNK(기본 40)건씩 나눠 review->summarize->dedup_by_summary->insert를
      청크 단위로 완결시킨다. 청크가 끝날 때마다 db.py의 즉시 commit()으로
      실제 디스크에 반영되므로, 다음 청크 처리 중 취소되어도 이전 청크는 남는다.
      이후 통계/HTML 생성 코드는 최종 live를 그대로 참조하므로 변경 불필요.
"""
import sys

path = "main.py"
src = open(path, encoding="utf-8").read()

OLD = '''        # 검토 에이전트 — 필터가 놓친 오탐을 LLM으로 최종 차단
        rvw.review_many(live, cfg)
        before_review = len(live)
        live = [it for it in live if not it.get("excluded")]
        if before_review != len(live):
            print(f"검토 후: {before_review}건 → {len(live)}건 (에이전트가 {before_review-len(live)}건 제외)")

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

        # 7-b) 요약 기반 2차 중복 판정 — 제목만으론 못 잡는 '같은 사건, 다른 제목'
        #      (예: "JP모건 키넥시스 활용 송금" vs "블록체인 국제결제망 기업결제")
        before_sum_dedup = len([it for it in live if not it.get("excluded")])
        ddp.dedup_by_summary(live, cfg, conn)
        live = [it for it in live if not it.get("excluded")]
        if before_sum_dedup != len(live):
            print(f"  요약 기반 중복 제거: {before_sum_dedup}건 → {len(live)}건")

        # 8) DB 저장 — 반영 기사만. 제외 기사는 저장하지 않음(DB 비대화 방지).
        #    제외 목록은 이번 회차분을 메모리에서 HTML로 바로 전달하므로
        #    "조용히 사라지지 않는다"는 원칙은 그대로 유지됨.
        # 제외분은 경량 로그로 남긴다 (본문·요약 제외 → 용량 부담 없음).
        #   회차 하나가 아니라 기간 전체로 추적 가능해야 과도 필터링을 잡아낸다.
        n_ex = dbm.log_excluded(conn, run_id, items)
        if n_ex:
            print(f"  제외 로그 {n_ex}건 기록")

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

        dbm.update_run_stats('''

NEW = '''        # 검토·요약·중복제거·저장을 청크 단위로 묶어 처리한다.
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

        dbm.update_run_stats('''

if OLD not in src:
    print("실패 — 원본 텍스트를 찾지 못함 (main.py가 예상과 다름)")
    sys.exit(1)

n = src.count(OLD)
if n != 1:
    print(f"실패 — 매칭이 {n}번 발생 (정확히 1번이어야 함)")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
open(path, "w", encoding="utf-8").write(src)
print("완료 — main.py 패치 적용됨")
