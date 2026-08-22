#!/usr/bin/env python3
"""검수 패널(제외/중복 상세) 사후 재구성 — 강제 게시로 비어버린 audit 섹션 복구.

한계: 중복(dup_members)·기열람(seen) 묶음의 '누구와 중복이었는지' 세부 정보는
      원래 실행 중 메모리에만 있고 DB에 저장되지 않아 완전 복구가 불가능하다.
      excluded_log의 제목·매체·사유(reason)만 살아있으므로, 모든 제외 항목을
      '본문 확인 후 제외' 섹션 하나로 모으되 원래 사유 텍스트는 그대로 보존한다.
      (원래 '중복'·'기열람'으로 시작하는 사유는 접두어를 바꿔 표시 —
       그대로 두면 _audit()이 dup_members 없이 그 항목을 조용히 숨겨버림)
"""
import sqlite3
import yaml

import db as dbm
import html_generator as htm

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = dbm.connect(cfg["db"]["path"])
conn.row_factory = sqlite3.Row

SINCE = "2026-08-18T08:46:00"   # 마지막 정상 완주(요청 이력 168회) 이후 전체

def neutralize(reason: str) -> str:
    """'중복'/'기열람'으로 시작하면 _audit()이 dup_members 없이 항목을 숨기므로
    접두어를 바꿔 irr(본문무관) 버킷으로 보내되 원래 사유는 보존한다."""
    r = reason or "사유 미상"
    if r.startswith("중복") or r.startswith("기열람"):
        return f"[재구성] 원사유: {r}"
    return r

screened = []
for r in conn.execute(
        "SELECT title, url, press, reason FROM excluded_log WHERE collected_at >= ?", (SINCE,)):
    screened.append({
        "title": r["title"], "naver_url": r["url"], "press": r["press"],
        "excluded": 1, "exclude_reason": neutralize(r["reason"]),
        "dup_members": None,
    })

for r in conn.execute(
        "SELECT title, naver_url, press FROM articles WHERE delivered=1 AND collected_at >= ?", (SINCE,)):
    screened.append({
        "title": r["title"], "naver_url": r["naver_url"], "press": r["press"],
        "excluded": 0, "exclude_reason": None, "dup_members": None,
    })

print(f"재구성된 검수 대상: {len(screened)}건 "
      f"(제외 {sum(1 for s in screened if s['excluded'])} / "
      f"반영 {sum(1 for s in screened if not s['excluded'])})")

rows_all = dbm.get_archive_articles(conn, cfg["db"]["retention_days"])
history = dbm.get_run_history(conn, cfg["db"]["retention_days"])
stats = {"generated_at": f"{dbm.now_kst():%Y-%m-%d %H:%M} (검수 패널 사후 재구성)",
         "raw": 0, "final": len(rows_all), "excluded": 0, "api_calls": 0,
         "extract_fail": 0, "summary_fail": 0, "press_health": {}}

out = htm.render(rows_all, stats, [], cfg["html"]["output_file"], history, cfg.get("github"),
                  screened_rows=screened)
print(f"HTML 갱신: {out}")
